"""Tests for the Phase C probe machinery (P2/P3/P5/P8/P9/P10).

All outbound HTTP is mocked; no live credentials are touched. These tests
verify request construction, authentication injection, sanitized evidence
capture, error classification, quota capture, pagination, normalization
provenance, deterministic matching, and the value matrix.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from defend_integrations.http import FetchResult
from defend_integrations.matching import (
    MatchLevel,
    MatchResult,
    match_event,
    matching_rates,
    normalize_name,
)
from defend_integrations.phase_c_adapters import (
    OddspapiPhaseCAdapter,
    RapidApiPhaseCAdapter,
    RapidEndpoint,
    SportradarTTPhaseCAdapter,
    TheOddsApiPhaseCAdapter,
    parse_oddspapi_historical,
    rapid_adapters,
)
from defend_integrations.probing import (
    CanonicalObservation,
    ProbeBudget,
    RawEvidence,
    capture_quota,
    classify_error,
    probe_get,
    sha256_text,
)
from defend_integrations.value_matrix import (
    EvidenceLevel,
    ProviderRole,
    ProviderValueRow,
    write_matrix,
)


def _fake_fetch(bodies: dict[int, str], headers=None):
    """Return a fetch stand-in mapping status -> (body, headers)."""

    def fetch(url, **kwargs):
        status_code, body = next(iter(bodies.items()))
        return FetchResult(
            ok=200 <= status_code < 300,
            status_code=status_code,
            latency_ms=5,
            error_type=None,
            body=body,
            headers=headers or {},
        )

    return fetch


# ------------------------------------------------------------------ errors


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (429, "", "rate_limited"),
        (401, "", "auth_failed"),
        (403, "subscribe to a paid plan", "plan_required"),
        (400, '{"error":{"message":"Too many bookmakers specified.","code":"TOO_MANY_BOOKMAKERS"}}', "validation"),
        (404, '{"error":{"message":"No historical odds found.","code":"NOT_FOUND"}}', "not_found"),
        (404, "", "not_found"),
        (500, "", "unavailable"),
        (None, "", "unavailable"),
        (200, "", "unavailable"),  # only called for non-2xx in practice
    ],
)
def test_classify_error(status, body, expected):
    assert classify_error(status, body) == expected


# --------------------------------------------------------- evidence capture


def test_probe_get_captures_sanitized_evidence(monkeypatch):
    secret = "super-secret-key-1234"
    monkeypatch.setattr(
        "defend_integrations.probing.fetch",
        _fake_fetch({200: json.dumps({"ok": True, "echo": secret})}),
    )
    result, evidence, parsed = probe_get(
        "test_provider",
        "sports",
        f"https://api.example.com/sports?apiKey={secret}",
        known_secrets=(secret,),
    )
    assert evidence.body is not None
    assert secret not in evidence.body
    assert secret not in evidence.url_sanitized
    assert evidence.body_sha256 == sha256_text(evidence.body)
    assert secret not in json.dumps(parsed)


def test_probe_get_captures_error_body(monkeypatch):
    body = '{"error":{"code":"NOT_FOUND"}}'
    monkeypatch.setattr(
        "defend_integrations.probing.fetch",
        _fake_fetch({404: body}),
    )
    result, evidence, parsed = probe_get("p", "historical-odds", "https://x.dev/e")
    assert result.ok is False
    assert evidence.body == body
    assert parsed == {"error": {"code": "NOT_FOUND"}}


def test_raw_evidence_save_is_immutable(tmp_path):
    evidence = RawEvidence(
        provider_id="p",
        endpoint="e",
        status_code=200,
        latency_ms=1,
        retrieved_at="2026-08-20T00:00:00Z",
        url_sanitized="https://x.dev/e",
        body="{}",
        body_sha256=sha256_text("{}"),
    )
    first = evidence.save(tmp_path)
    second = evidence.save(tmp_path)
    assert first == second
    assert first.read_text(encoding="utf-8").startswith("{")


def test_capture_quota_headers_and_body():
    remaining, reset = capture_quota(
        {"x-ratelimit-remaining": "37", "x-ratelimit-reset": "2026-08-21T00:00:00Z"},
        ("x-ratelimit-remaining",),
    )
    assert remaining == 37
    assert reset == "2026-08-21T00:00:00Z"
    remaining, _ = capture_quota(
        None, (), {"data": {"remaining_quota": 12}}, "data"
    )
    assert remaining == 12


def test_probe_budget_enforcement():
    budget = ProbeBudget("oddspapi", cap=3)
    assert budget.take() and budget.take(2)
    assert not budget.take()
    assert budget.remaining == 0


# ------------------------------------------------- OddsPapi normalization


def test_parse_oddspapi_historical_provenance():
    payload = {
        "fixtureId": "id2503634973488400",
        "bookmakers": {
            "1xbet": {
                "markets": {
                    "251": {
                        "outcomes": {
                            "251": {
                                "players": {
                                    "0": [
                                        {
                                            "createdAt": "2026-08-06T13:55:38.328Z",
                                            "price": 2.06,
                                            "limit": None,
                                            "active": True,
                                            "exchangeMeta": None,
                                        },
                                        {
                                            "createdAt": "2026-08-06T16:03:40.503Z",
                                            "price": 2.075,
                                            "limit": None,
                                            "active": True,
                                        },
                                    ]
                                }
                            }
                        }
                    }
                }
            }
        },
    }
    observations = parse_oddspapi_historical(
        payload,
        provider="oddspapi",
        fixture_id="id2503634973488400",
        raw_evidence_ref="evidence/1.json",
        commence_at="2026-08-08T00:00:00+00:00",
        ingested_at="2026-08-20T00:00:00Z",
    )
    assert len(observations) == 2
    first = observations[0]
    assert first.provider == "oddspapi"
    assert first.provider_event_id == "id2503634973488400"
    assert first.provider_bookmaker == "1xbet"
    assert first.provider_market_id == "251"
    assert first.provider_outcome_id == "251"
    assert first.raw_evidence_ref == "evidence/1.json"
    assert first.observed_at == "2026-08-06T13:55:38.328Z"
    assert first.commence_at == "2026-08-08T00:00:00+00:00"
    assert first.price == 2.06
    assert first.active is True
    assert first.participant_key == "0"
    assert first.to_dict()["provider"] == "oddspapi"


def test_oddspapi_historical_requires_bookmakers():
    adapter = OddspapiPhaseCAdapter()
    budget = ProbeBudget("oddspapi", cap=10)
    result, observations = adapter.probe_historical(
        budget, Path("."), fixture_id="id1", bookmakers=[]
    )
    assert observations == []
    assert "bookmakers param required" in result.notes[0]
    assert budget.used == 0


def test_oddspapi_historical_budget_cap():
    adapter = OddspapiPhaseCAdapter()
    budget = ProbeBudget("oddspapi", cap=0)
    result, observations = adapter.probe_historical(
        budget, Path("."), fixture_id="id1", bookmakers=["1xbet"]
    )
    assert observations == []
    assert "budget exhausted" in result.notes[0]


# ----------------------------------------------------------- Sportradar URL


def test_sportradar_url_construction():
    adapter = SportradarTTPhaseCAdapter()
    assert adapter._url("SECRET", "competitions") == (
        "https://api.sportradar.com/tabletennis/trial/v2/competitions.json"
        "?api_key=SECRET"
    )
    assert adapter._url("SECRET", "seasons/sr:season:1/probabilities") == (
        "https://api.sportradar.com/tabletennis/trial/v2/seasons/"
        "sr:season:1/probabilities.json?api_key=SECRET"
    )


# --------------------------------------------------------- RapidAPI family


def test_rapidapi_headers_and_no_quota_without_catalog(monkeypatch):
    adapter = RapidApiPhaseCAdapter("rapidapi_tt_live", "tt-host.p.rapidapi.com", [])
    captured = {}

    def fake_fetch(url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        return FetchResult(True, 200, 1, None, body="{}")

    monkeypatch.setattr("defend_integrations.probing.fetch", fake_fetch)
    budget = ProbeBudget("rapidapi_tt_live", cap=40)
    result = adapter.run({"RAPIDAPI_KEY": "K"}, budget, Path("."))
    assert result.evidence == []
    assert budget.used == 0
    assert any("UNVERIFIED" in note for note in result.notes)


def test_rapidapi_micro_endpoint_loop(monkeypatch):
    adapter = RapidApiPhaseCAdapter(
        "rapidapi_tt_micro",
        "table-tennis-micro.p.rapidapi.com",
        [RapidEndpoint("matches-live", "/matches-live")],
    )
    captured = {}

    def fake_fetch(url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        return FetchResult(True, 200, 1, None, body=json.dumps({"data": []}))

    monkeypatch.setattr("defend_integrations.probing.fetch", fake_fetch)
    budget = ProbeBudget("rapidapi_tt_micro", cap=40)
    result = adapter.run({"RAPIDAPI_KEY": "K"}, budget, Path("."))
    assert captured["url"] == "https://table-tennis-micro.p.rapidapi.com/matches-live"
    assert captured["headers"]["X-RapidAPI-Key"] == "K"
    assert captured["headers"]["X-RapidAPI-Host"] == "table-tennis-micro.p.rapidapi.com"
    assert budget.used == 1
    assert result.capabilities.get("matches-live") == "yes"


def test_rapid_adapters_registry():
    adapters = rapid_adapters()
    assert set(adapters) == {
        "rapidapi_tt_micro",
        "rapidapi_tabletennis",
        "rapidapi_allscores",
        "rapidapi_allsportsapi2",
        "rapidapi_tt_live",
    }
    assert adapters["rapidapi_tt_micro"].endpoints


# ------------------------------------------------------------ matching (P5)


def _canonical(events):
    return [
        {
            "event_key": event["event_key"],
            "provider_event_id": event.get("provider_event_id"),
            "participant_keys": [normalize_name(p) for p in event.get("participants", [])],
            "participant_ids": event.get("participant_ids"),
            "competition": event.get("competition"),
            "commence_at": event.get("commence_at"),
        }
        for event in events
    ]


def test_match_exact_id():
    events = _canonical(
        [
            {
                "event_key": "oaio:id2503634973488400",
                "provider_event_id": "id2503634973488400",
                "participants": ["A", "B"],
            }
        ]
    )
    result = match_event(
        provider_event_id="id2503634973488400",
        provider_prefix="oaio",
        participants=["A", "B"],
        competition=None,
        commence_at=None,
        canonical_events=events,
    )
    assert result.level is MatchLevel.EXACT_ID
    assert result.matched_event_key == "oaio:id2503634973488400"


def test_match_normalized_deterministic():
    events = _canonical(
        [
            {
                "event_key": "oaio:1",
                "participants": ["Jan Sobíšek", "Petr Chlebeček"],
                "competition": "Czech Liga Pro",
                "commence_at": "2026-08-08T00:00:00+00:00",
            },
            {
                "event_key": "oaio:2",
                "participants": ["Jan Sobíšek", "Petr Chlebeček"],
                "competition": "TT Cup",
                "commence_at": "2026-08-08T00:00:00+00:00",
            },
        ]
    )
    result = match_event(
        provider_event_id="id2503634973488400",
        provider_prefix="oaio",
        participants=["Jan Sobisek", "Petr Chlebecek"],
        competition="Czech Liga Pro",
        commence_at="2026-08-08T00:10:00+00:00",
        canonical_events=events,
    )
    assert result.level is MatchLevel.NORMALIZED
    assert result.matched_event_key == "oaio:1"


def test_match_ambiguous_fails_closed():
    events = _canonical(
        [
            {
                "event_key": "oaio:1",
                "participants": ["Jan Sobisek", "Petr Chlebecek"],
                "competition": "Czech Liga Pro",
                "commence_at": "2026-08-08T00:00:00+00:00",
            },
            {
                "event_key": "oaio:2",
                "participants": ["Jan Sobisek", "Petr Chlebecek"],
                "competition": "Czech Liga Pro",
                "commence_at": "2026-08-08T00:30:00+00:00",
            },
        ]
    )
    result = match_event(
        provider_event_id="x",
        provider_prefix="oaio",
        participants=["Jan Sobisek", "Petr Chlebecek"],
        competition="Czech Liga Pro",
        commence_at="2026-08-08T00:10:00+00:00",
        canonical_events=events,
    )
    assert result.level is MatchLevel.AMBIGUOUS
    assert result.matched_event_key is None
    assert len(result.candidate_keys) == 2


def test_match_identity_map():
    events = _canonical(
        [{"event_key": "oaio:9", "participants": ["A", "B"]}]
    )
    result = match_event(
        provider_event_id="sgo:77",
        provider_prefix="oaio",
        participants=["A", "B"],
        competition=None,
        commence_at=None,
        canonical_events=events,
        identity_map={"sgo:77": "oaio:9"},
    )
    assert result.level is MatchLevel.IDENTITY_MAP
    assert result.matched_event_key == "oaio:9"


def test_match_unmatched():
    events = _canonical([{"event_key": "oaio:1", "participants": ["X", "Y"]}])
    result = match_event(
        provider_event_id="z",
        provider_prefix="oaio",
        participants=["Nobody", "Knows"],
        competition="None",
        commence_at=None,
        canonical_events=events,
    )
    assert result.level is MatchLevel.UNMATCHED


def test_matching_rates():
    events = _canonical(
        [{"event_key": "oaio:1", "provider_event_id": "1", "participants": ["A", "B"]}]
    )
    results = [
        match_event(
            provider_event_id="1",
            provider_prefix="oaio",
            participants=["A", "B"],
            competition="C",
            commence_at=None,
            canonical_events=events,
        ),
        MatchResult(MatchLevel.UNMATCHED, None, (), "no deterministic candidate"),
    ]
    rates = matching_rates(results)
    assert rates["TOTAL"] == 2
    assert rates["EXACT_ID_MATCH_RATE"] == 0.5
    assert rates["UNMATCHED_RATE"] == 0.5
    assert rates["MATCHED_RATE"] == 0.5


# ------------------------------------------------------------ value matrix


def test_value_matrix_roundtrip(tmp_path):
    row = ProviderValueRow(
        provider="oddspapi",
        auth="query api_key",
        tt_results="yes",
        tt_historical_odds="yes",
        multi_snapshot="yes",
        bookmaker_depth="yes",
        evidence_level=EvidenceLevel.EMPIRICALLY_VERIFIED,
        roles=(ProviderRole.HISTORICAL_ODDS_RESEARCH_GRADE,),
        notes="line-move history confirmed",
    )
    path = write_matrix(tmp_path / "matrix.json", [row])
    document = json.loads(path.read_text(encoding="utf-8"))
    providers = document["providers"]
    assert providers[0]["PROVIDER"] == "oddspapi"
    assert providers[0]["EVIDENCE_LEVEL"] == "EMPIRICALLY_VERIFIED"
    assert providers[0]["ROLES"] == ["HISTORICAL_ODDS_RESEARCH_GRADE"]


def test_the_odds_api_adapter_classifies_unsupported(monkeypatch, tmp_path):
    body = json.dumps(
        [{"key": "soccer_epl", "title": "Soccer EPL"}, {"key": "tennis", "title": "Tennis"}]
    )
    monkeypatch.setattr(
        "defend_integrations.probing.fetch",
        _fake_fetch({200: body}, headers={"x-requests-remaining": "499"}),
    )
    adapter = TheOddsApiPhaseCAdapter()
    result = adapter.run(
        {"THE_ODDS_API_KEY": "K"}, ProbeBudget("the_odds_api", cap=40), tmp_path
    )
    assert result.capabilities["tt_results"] == "no"
    assert any("UNSUPPORTED_FOR_TT" in note for note in result.notes)
    assert result.endpoints["sports"]["remaining_quota"] == 499
    assert len(result.evidence) == 1