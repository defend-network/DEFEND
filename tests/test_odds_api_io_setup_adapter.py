"""Setup coverage diagnostics for the real Odds-API.io adapter."""

from __future__ import annotations

import json

import defend_integrations.adapters as adapters_module
from defend_integrations.adapters import OddsApiIoAdapter
from defend_integrations.http import FetchResult
from defend_integrations.registry import find_provider


KEY = "synthetic-odds-api-io-key"


def _success(body: object) -> FetchResult:
    return FetchResult(
        ok=True,
        status_code=200,
        latency_ms=20,
        error_type=None,
        body=json.dumps(body),
        retries=0,
        headers={},
    )


def test_authenticated_empty_tt_coverage_is_distinct(monkeypatch):
    def fake_fetch(url, **kwargs):
        if "/sports" in url:
            return _success([{"name": "Table Tennis", "slug": "table-tennis"}])
        if "/bookmakers/selected" in url:
            return _success({"bookmakers": ["Sbobet", "SingBet"]})
        if "/events?" in url:
            return _success([{"id": 73859912}])
        if "/odds?" in url:
            return _success({"bookmakers": {}})
        raise AssertionError(url)

    monkeypatch.setattr(adapters_module, "fetch", fake_fetch)
    definition = find_provider("odds_api_io")
    probe = OddsApiIoAdapter().probe(
        definition,
        {"ODDS_API_IO_API_KEY": KEY},
        {},
    )

    assert probe.ok is True
    assert probe.authenticated is True
    assert probe.coverage_state == "EMPTY"
    assert "bookmaker_keys=none" in (probe.coverage_detail or "")
    assert KEY not in json.dumps(probe.to_dict())


def test_available_tt_coverage_is_reported_when_payload_has_markets(monkeypatch):
    def fake_fetch(url, **kwargs):
        if "/sports" in url:
            return _success([{"name": "Table Tennis", "slug": "table-tennis"}])
        if "/bookmakers/selected" in url:
            return _success({"bookmakers": ["Sbobet", "SingBet"]})
        if "/events?" in url:
            return _success([{"id": 73859912}])
        if "/odds?" in url:
            return _success({"bookmakers": {"Sbobet": [{"name": "ML"}]}})
        raise AssertionError(url)

    monkeypatch.setattr(adapters_module, "fetch", fake_fetch)
    definition = find_provider("odds_api_io")
    probe = OddsApiIoAdapter().probe(
        definition,
        {"ODDS_API_IO_API_KEY": KEY},
        {},
    )

    assert probe.coverage_state == "AVAILABLE"
    assert "Sbobet" in (probe.coverage_detail or "")


def test_truncated_events_sweep_recovers_and_reports_empty(monkeypatch):
    def fake_fetch(url, **kwargs):
        if "/sports" in url:
            return _success([{"name": "Table Tennis", "slug": "table-tennis"}])
        if "/bookmakers/selected" in url:
            return _success({"bookmakers": ["Sbobet", "SingBet"]})
        if "/events?" in url:
            body = '[{"id": 73859912}, {"id": 73859914}, {"id": "cut'
            return FetchResult(
                ok=True, status_code=200, latency_ms=20, error_type=None,
                body=body, retries=0, headers={},
            )
        if "/odds?" in url:
            return _success({"bookmakers": {}})
        raise AssertionError(url)

    monkeypatch.setattr(adapters_module, "fetch", fake_fetch)
    definition = find_provider("odds_api_io")
    probe = OddsApiIoAdapter().probe(
        definition,
        {"ODDS_API_IO_API_KEY": KEY},
        {},
    )

    assert probe.ok is True
    assert probe.coverage_state == "EMPTY"
    assert "events=2" in (probe.coverage_detail or "")
