"""Unit tests for the Odds-API.io provider adapter (no network)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import urllib.parse

import pytest

from defend_sports.providers.odds_api_io import (
    OddsApiIoProviderError,
    OddsApiIoSportsProvider,
    _is_legal_final_game,
    _parse_scores,
    parse_scores,
    parse_tt_final_result,
    slugify,
)


class FakeHttpGet:
    def __init__(self) -> None:
        self.urls: list[str] = []
        self.payloads: dict[str, object] = {}

    def set(self, payload: object) -> None:
        self.payloads["__default__"] = payload

    def set_for(self, marker: str, payload: object) -> None:
        self.payloads[marker] = payload

    def __call__(self, url: str) -> tuple[object, int]:
        self.urls.append(url)
        path = urllib.parse.urlparse(url).path
        for marker, payload in self.payloads.items():
            if marker != "__default__" and marker in path:
                return payload, 200
        return self.payloads.get("__default__", []), 200


def _provider(http: FakeHttpGet, **overrides) -> OddsApiIoSportsProvider:
    kwargs: dict[str, object] = {
        "api_key": "test-key",
        "http_get": http,
        "sleep": lambda _seconds: None,
    }
    kwargs.update(overrides)
    return OddsApiIoSportsProvider(**kwargs)


def _sports_payload() -> list[dict[str, object]]:
    return [{"id": 1, "name": "Table Tennis", "sportKey": "table-tennis"}]


def test_missing_key_raises_before_any_request():
    http = FakeHttpGet()
    provider = _provider(http, api_key="")
    with pytest.raises(OddsApiIoProviderError, match="missing ODDS_API_IO_API_KEY"):
        provider.poll()
    with pytest.raises(OddsApiIoProviderError, match="missing ODDS_API_IO_API_KEY"):
        provider.historical_events(
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 8, tzinfo=timezone.utc),
        )
    assert http.urls == []


def test_resolve_sport_slug_discovers_table_tennis():
    http = FakeHttpGet()
    http.set([{"id": 1, "name": "Table Tennis", "sportKey": "table-tennis"}])
    provider = _provider(http)
    assert provider.resolve_sport_slug() == "table-tennis"
    assert provider.resolve_sport_slug() == "table-tennis"  # cached
    assert len(http.urls) == 1


def test_resolve_sport_slug_falls_back_to_default():
    http = FakeHttpGet()
    http.set([{"id": 2, "name": "Soccer", "sportKey": "soccer"}])
    provider = _provider(http)
    assert provider.resolve_sport_slug() == "table-tennis"


def test_poll_maps_events_odds_and_live():
    http = FakeHttpGet()
    http.set_for("sports", _sports_payload())
    http.set_for("events/live", [])
    http.set(
        [
            {
                "id": "evt-1",
                "home": "Alice",
                "away": "Bob",
                "league": "TT Pro",
                "date": "2026-08-18T12:00:00Z",
                "status": "pending",
            },
        ]
    )
    http.set_for(
        "odds",
        {
            "id": "evt-1",
            "date": "2026-08-18T12:00:00Z",
            "updatedAt": "2026-08-18T11:59:00Z",
            "bookmakers": [
                {
                    "bookmaker": "BookCo",
                    "markets": [
                        {
                            "market": "ML",
                            "home": "1.85",
                            "away": "2.05",
                        },
                    ],
                },
            ],
        },
    )
    provider = _provider(http)
    batch = provider.poll()

    assert len(batch.events) == 1
    event = batch.events[0]
    assert event.event_external_id == "oaio:evt-1"
    assert event.sport_key == "table_tennis"
    assert event.league_key == "tt-pro"
    assert event.display_name == "Alice vs Bob"
    assert event.scheduled_at is not None

    assert len(batch.raw_events) == 1
    raw = batch.raw_events[0]
    assert raw.source.provider == "odds_api_io"
    assert raw.provider_event_id.startswith("oaio:evt-1@live:")
    assert raw.payload["home"] == "Alice"

    assert len(batch.odds) == 2
    odds = {item.selection_key: item for item in batch.odds}
    assert odds["home"].decimal_odds == Decimal("1.85")
    assert odds["away"].decimal_odds == Decimal("2.05")
    assert odds["home"].market_key == "match_winner"
    assert odds["home"].source.external_id == "bookco"
    assert odds["home"].raw_event_ref == raw.provider_event_id
    assert odds["home"].observed_at == datetime(2026, 8, 18, 11, 59, tzinfo=timezone.utc)


def test_poll_skips_non_ml_markets():
    http = FakeHttpGet()
    http.set_for("sports", _sports_payload())
    http.set_for("events/live", [])
    http.set(
        [
            {
                "id": "evt-2",
                "home": "Alice",
                "away": "Bob",
                "league": "TT Pro",
                "date": "2026-08-18T12:00:00Z",
            },
        ]
    )
    http.set_for(
        "odds",
        {
            "id": "evt-2",
            "bookmakers": [
                {
                    "bookmaker": "BookCo",
                    "markets": [
                        {"market": "handicap", "home": "1.5", "away": "2.4"},
                        {"market": "ML", "home": "1.8", "away": "2.1"},
                    ],
                },
            ],
        },
    )
    provider = _provider(http)
    batch = provider.poll()
    assert len(batch.odds) == 2
    assert all(item.market_key == "match_winner" for item in batch.odds)


def test_poll_live_observation_uses_event_ref():
    http = FakeHttpGet()
    http.set_for("sports", _sports_payload())
    http.set(
        [
            {
                "id": "evt-3",
                "home": "Alice",
                "away": "Bob",
                "league": "TT Pro",
                "date": "2026-08-18T12:00:00Z",
            },
        ]
    )
    http.set_for(
        "events/live",
        [
            {
                "id": "evt-3",
                "scores": {"home": 2, "away": 1},
            },
        ],
    )
    http.set_for("odds", {"id": "evt-3", "bookmakers": []})
    provider = _provider(http)
    batch = provider.poll()
    assert len(batch.live) == 1
    observation = batch.live[0]
    assert observation.event_external_id == "oaio:evt-3"
    assert observation.state["scores"] == (2, 1)
    assert observation.raw_event_ref == batch.raw_events[0].provider_event_id


def test_poll_unexpected_events_payload_raises():
    http = FakeHttpGet()
    http.set_for("sports", _sports_payload())
    http.set({"not": "a list"})
    provider = _provider(http)
    with pytest.raises(OddsApiIoProviderError, match="unexpected /events payload"):
        provider.poll()


def test_historical_events_builds_window_query():
    http = FakeHttpGet()
    http.set_for("sports", _sports_payload())
    http.set([])
    provider = _provider(http, league_slug="tt-pro-league")
    rows, status = provider.historical_events(
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 8, tzinfo=timezone.utc),
        skip=200,
        limit=200,
    )
    assert rows == []
    assert status == 200
    historical_url = next(
        url for url in http.urls if "historical/events" in url
    )
    assert "sport=table-tennis" in historical_url
    assert "league=tt-pro-league" in historical_url
    assert "from=2026-01-01T00%3A00%3A00Z" in historical_url
    assert "to=2026-01-08T00%3A00%3A00Z" in historical_url
    assert "skip=200" in historical_url
    assert "limit=200" in historical_url


def test_historical_events_filters_non_dict_rows():
    http = FakeHttpGet()
    http.set([{"id": "a"}, "junk", None, {"id": "b"}])
    provider = _provider(http)
    rows, _status = provider.historical_events(
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 8, tzinfo=timezone.utc),
    )
    assert rows == [{"id": "a"}, {"id": "b"}]


def test_historical_events_requires_league_param_in_url():
    http = FakeHttpGet()
    http.set_for("sports", _sports_payload())
    http.set_for(
        "leagues",
        [{"name": "Czech Liga Pro", "slug": "czech-republic-czech-liga-pro", "eventsCount": 267}],
    )
    http.set([])
    provider = _provider(http)
    provider.historical_events(
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 8, tzinfo=timezone.utc),
    )
    historical_url = next(url for url in http.urls if "historical/events" in url)
    assert "league=czech-republic-czech-liga-pro" in historical_url


def test_resolve_league_slug_picks_biggest_and_caches():
    http = FakeHttpGet()
    http.set_for(
        "leagues",
        [
            {"name": "TT Cup", "slug": "international-tt-cup", "eventsCount": 91},
            {"name": "Czech Liga Pro", "slug": "czech-republic-czech-liga-pro", "eventsCount": 267},
        ],
    )
    provider = _provider(http, sport_slug="table-tennis")
    assert provider.resolve_league_slug() == "czech-republic-czech-liga-pro"
    assert provider.resolve_league_slug() == "czech-republic-czech-liga-pro"  # cached
    assert len(http.urls) == 1


def test_resolve_league_slug_pin_overrides_discovery():
    http = FakeHttpGet()
    provider = _provider(http, league_slug="international-tt-cup")
    assert provider.resolve_league_slug() == "international-tt-cup"
    assert http.urls == []  # no discovery request when pinned


def test_parse_event_payload_dict_league():
    from defend_sports.providers.odds_api_io import parse_event_payload

    raw, event = parse_event_payload(
        {
            "id": "evt-d1",
            "home": "Alice",
            "away": "Bob",
            "league": {"name": "Czech Republic - Czech Liga Pro", "slug": "czech-republic-czech-liga-pro"},
            "date": "2026-08-01T00:00:00Z",
        },
        observed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        suffix="hist:20260801",
    )
    assert event.league_key == "czech-republic-czech-liga-pro"
    assert event.event_external_id == "oaio:evt-d1"
    assert raw.provider_event_id == "oaio:evt-d1@hist:20260801"


def test_historical_odds_sends_bookmakers_param():
    http = FakeHttpGet()
    http.set({"id": "evt-9", "bookmakers": {}})
    provider = _provider(http, bookmakers=("22Bet", "888Sport"))
    payload = provider.historical_odds("evt-9")
    assert payload["id"] == "evt-9"
    url = http.urls[0]
    assert "bookmakers=22Bet%2C888Sport" in url


def test_historical_odds_unexpected_payload_raises():
    http = FakeHttpGet()
    http.set([])
    provider = _provider(http)
    with pytest.raises(OddsApiIoProviderError, match="unexpected /historical/odds payload"):
        provider.historical_odds("evt-9")


def test_parse_odds_payload_shapes():
    from defend_sports.providers.odds_api_io import parse_odds_payload

    observed_at = datetime(2026, 8, 1, tzinfo=timezone.utc)
    dict_rows = parse_odds_payload(
        {"bookmakers": {"22Bet": {"markets": {"ML": {"home": 1.85, "away": 2.05}}}}},
        event_external_id="oaio:evt-x",
        raw_event_ref="oaio:evt-x@hist:20260801",
        default_observed_at=observed_at,
    )
    assert len(dict_rows) == 2
    assert dict_rows[0].selection_key == "home"
    assert dict_rows[0].decimal_odds == Decimal("1.85")

    list_rows = parse_odds_payload(
        {
            "bookmakers": [
                {
                    "bookmaker": "22Bet",
                    "markets": [
                        {"market": "ML", "home": 2.0, "away": 1.8},
                        {"market": "handicap", "home": 1.5, "away": 2.4},
                    ],
                }
            ]
        },
        event_external_id="oaio:evt-x",
        raw_event_ref="oaio:evt-x@hist:20260801",
        default_observed_at=observed_at,
    )
    assert len(list_rows) == 2  # ML only; handicap skipped

    empty = parse_odds_payload(
        {"bookmakers": {}},
        event_external_id="oaio:evt-x",
        raw_event_ref="oaio:evt-x@hist:20260801",
        default_observed_at=observed_at,
    )
    assert empty == ()


def test_parse_scores_variants():
    assert parse_scores({"home": 3, "away": 1}) == (3, 1)
    assert parse_scores({"homeScore": 2, "awayScore": 0}) == (2, 0)
    assert parse_scores([{"home": 4, "away": 2}]) == (4, 2)
    assert parse_scores([{"homeScore": 1, "awayScore": 1}]) == (1, 1)
    assert parse_scores("3:1") == (3, 1)
    assert parse_scores({"home": -1, "away": 1}) is None
    assert parse_scores({"home": "x", "away": 1}) is None
    assert parse_scores(None) is None
    assert parse_scores({"home": True, "away": 1}) is None


def test_slugify_helpers():
    assert slugify("TT Pro League") == "tt-pro-league"
    assert slugify("  Premier Ping Pong  ") == "premier-ping-pong"
    assert slugify("") is None
    assert slugify(None) is None


def test_poll_paces_requests():
    slept: list[float] = []

    def sleeper(seconds: float) -> None:
        slept.append(seconds)

    http = FakeHttpGet()
    http.set_for("sports", _sports_payload())
    http.set_for("events/live", [])
    http.set([])
    provider = _provider(http, sleep=sleeper)
    batch = provider.poll()
    assert batch.events == ()
    assert len(slept) >= 1
    assert all(seconds == 1.0 for seconds in slept)
class TestParseTtFinalResult:
    """Canonical final-result parser (score-semantics audit fix)."""

    def _payload(self, top_home=None, top_away=None, periods=None):
        scores = {}
        if top_home is not None:
            scores["home"] = top_home
        if top_away is not None:
            scores["away"] = top_away
        if periods is not None:
            scores["periods"] = periods
        return {"id": 1, "home": "A", "away": "B", "scores": scores, "status": "settled"}

    def _ft_payload(self, home, away, top_home=None, top_away=None, **periods):
        p = {"ft": {"home": home, "away": away}}
        p.update(periods)
        return self._payload(top_home, top_away, p)

    # ---- ft authoritative -------------------------------------------------

    def test_normal_3_0_ft(self):
        r = parse_tt_final_result(self._ft_payload(3, 0, 3, 0,
            p1={"home": 11, "away": 6}, p2={"home": 11, "away": 8}, p3={"home": 11, "away": 3}))
        assert r.status == "VERIFIED" and (r.home_score, r.away_score) == (3, 0)
        assert r.winner == "HOME" and r.source == "PERIODS_FT"

    def test_normal_3_1_ft(self):
        r = parse_tt_final_result(self._ft_payload(1, 3, 1, 3))
        assert r.status == "VERIFIED" and (r.home_score, r.away_score) == (1, 3)
        assert r.winner == "AWAY"

    def test_normal_3_2_ft(self):
        r = parse_tt_final_result(self._ft_payload(3, 2, 3, 2))
        assert r.status == "VERIFIED" and (r.home_score, r.away_score) == (3, 2)
        assert r.winner == "HOME"

    def test_ft_present_top_identical(self):
        r = parse_tt_final_result(self._ft_payload(3, 1, 3, 1))
        assert r.status == "VERIFIED" and r.source == "PERIODS_FT"

    def test_ft_present_top_is_point_score(self):
        r = parse_tt_final_result(self._ft_payload(3, 2, 11, 6))
        assert r.status == "VERIFIED" and (r.home_score, r.away_score) == (3, 2)

    def test_ft_top_disagree_winner_same(self):
        r = parse_tt_final_result(self._ft_payload(3, 2, 11, 6))
        assert r.winner == "HOME"

    def test_ft_top_disagree_winner_changes(self):
        r = parse_tt_final_result(self._ft_payload(2, 3, 11, 7))
        assert r.status == "VERIFIED" and (r.home_score, r.away_score) == (2, 3)
        assert r.winner == "AWAY"

    def test_ft_equal_is_void(self):
        r = parse_tt_final_result(self._ft_payload(3, 3, 3, 3))
        assert r.status == "VOID" and r.winner is None and r.reason_code == "FT_EQUAL"

    def test_ft_authoritative_over_complete_periods(self):
        # periods show a different majority (truncated/missing games) but ft
        # is the explicit final game count: ft wins.
        r = parse_tt_final_result(self._ft_payload(3, 2, 3, 2,
            p3={"home": 8, "away": 11}, p4={"home": 5, "away": 11}, p5={"home": 11, "away": 7}))
        assert r.status == "VERIFIED" and (r.home_score, r.away_score) == (3, 2)
        assert r.winner == "HOME"

# ---- period derivation (no ft) ---------------------------------------

    def test_top_2_2_periods_establish_2_3(self):
        r = parse_tt_final_result(self._payload(2, 2, {
            "p1": {"home": 6, "away": 11}, "p2": {"home": 3, "away": 11},
            "p3": {"home": 11, "away": 5}, "p4": {"home": 11, "away": 8},
            "p5": {"home": 10, "away": 12},
        }))
        assert r.status == "VERIFIED" and (r.home_score, r.away_score) == (2, 3)
        assert r.winner == "AWAY" and r.source == "DERIVED_PERIODS"

    def test_derived_majority_consistent_with_top_wins(self):
        r = parse_tt_final_result(self._payload(3, 2, {
            "p1": {"home": 11, "away": 6}, "p2": {"home": 11, "away": 8},
            "p3": {"home": 11, "away": 3},
        }))
        assert r.status == "VERIFIED" and (r.home_score, r.away_score) == (3, 0)
        assert r.winner == "HOME" and r.source == "DERIVED_PERIODS"

    def test_derived_majority_conflicts_with_top_void(self):
        r = parse_tt_final_result(self._payload(2, 3, {
            "p1": {"home": 11, "away": 6}, "p2": {"home": 11, "away": 8},
            "p3": {"home": 11, "away": 3},
        }))
        assert r.status == "VOID" and r.winner is None
        assert r.reason_code == "TOP_PERIODS_CONFLICT"

    def test_periods_tied_void(self):
        r = parse_tt_final_result(self._payload(2, 2, {
            "p1": {"home": 11, "away": 9}, "p2": {"home": 9, "away": 11},
            "p3": {"home": 11, "away": 8}, "p4": {"home": 8, "away": 11},
        }))
        assert r.status == "VOID" and r.winner is None and r.reason_code == "PERIODS_TIED"

# ---- single-game ------------------------------------------------------

    def test_single_completed_game_11_8(self):
        r = parse_tt_final_result(self._payload(8, 11, {"p1": {"home": 5, "away": 11}}))
        assert r.status == "VERIFIED" and (r.home_score, r.away_score) == (5, 11)
        assert r.winner == "AWAY" and r.source == "SINGLE_GAME"

    def test_deuce_game_14_12(self):
        r = parse_tt_final_result(self._payload(None, None, {"p1": {"home": 14, "away": 12}}))
        assert r.status == "VERIFIED" and (r.home_score, r.away_score) == (14, 12)
        assert r.winner == "HOME" and r.source == "SINGLE_GAME"

    def test_single_game_consistent_with_plausible_top(self):
        r = parse_tt_final_result(self._payload(0, 3, {"p1": {"home": 4, "away": 11}}))
        assert r.status == "VERIFIED" and (r.home_score, r.away_score) == (0, 3)
        assert r.winner == "AWAY" and r.source == "TOP_LEVEL_FALLBACK"

    def test_single_game_top_conflict_void(self):
        r = parse_tt_final_result(self._payload(6, 11, {"p1": {"home": 11, "away": 8}}))
        assert r.status == "VOID" and r.winner is None

    # ---- unfinished / abandoned ------------------------------------------

    def test_unfinished_9_9_period_void(self):
        r = parse_tt_final_result(self._payload(0, 0, {"p1": {"home": 9, "away": 9}}))
        assert r.status == "VOID" and r.winner is None

    def test_abandoned_match_void(self):
        r = parse_tt_final_result(self._payload(0, 0, {"p1": {"home": 10, "away": 10}}))
        assert r.status == "VOID" and r.winner is None

    def test_abandoned_with_plausible_top_accepted(self):
        # partial period snapshot is stale; top-level game count (0..3) is
        # reliable per corpus evidence (only 2/33122 contradicted by ft).
        r = parse_tt_final_result(self._payload(3, 0, {"p1": {"home": 1, "away": 2}}))
        assert r.status == "VERIFIED" and (r.home_score, r.away_score) == (3, 0)
        assert r.winner == "HOME" and r.source == "TOP_LEVEL_FALLBACK"

    # ---- missing data / malformed ----------------------------------------

    def test_missing_ft_top_game_count(self):
        r = parse_tt_final_result(self._payload(3, 1, {}))
        assert r.status == "VERIFIED" and (r.home_score, r.away_score) == (3, 1)
        assert r.winner == "HOME" and r.source == "TOP_LEVEL_FALLBACK"

    def test_missing_ft_missing_periods_legal_game_top(self):
        r = parse_tt_final_result(self._payload(11, 8))
        assert r.status == "VERIFIED" and (r.home_score, r.away_score) == (11, 8)
        assert r.winner == "HOME" and r.source == "SINGLE_GAME"

    def test_malformed_period_ignored_when_top_plausible(self):
        r = parse_tt_final_result(self._payload(3, 1, {"p1": {"home": 4, "away": 5}}))
        assert r.status == "VERIFIED" and (r.home_score, r.away_score) == (3, 1)

    def test_negative_score_unresolved(self):
        r = parse_tt_final_result(self._payload(-1, 3))
        assert r.status == "UNRESOLVED" and r.winner is None

    def test_missing_scores_unresolved(self):
        r = parse_tt_final_result({"id": 1, "home": "A", "away": "B", "status": "settled"})
        assert r.status == "UNRESOLVED" and r.reason_code == "NO_SCORE_DATA"

    def test_unknown_format_unresolved(self):
        r = parse_tt_final_result(self._payload(9, 6))
        assert r.status == "UNRESOLVED" and r.winner is None

    def test_top_equal_no_periods_void(self):
        r = parse_tt_final_result(self._payload(2, 2))
        assert r.status == "VOID" and r.winner is None and r.reason_code == "TOP_EQUAL"


class TestIsLegalFinalGame:
    def test_legal(self):
        assert _is_legal_final_game(11, 9)
        assert _is_legal_final_game(11, 0)
        assert _is_legal_final_game(14, 12)
        assert _is_legal_final_game(17, 15)

    def test_illegal(self):
        assert not _is_legal_final_game(11, 10)
        assert not _is_legal_final_game(10, 10)
        assert not _is_legal_final_game(9, 6)
        assert not _is_legal_final_game(4, 5)
        assert not _is_legal_final_game(3, 2)
        assert not _is_legal_final_game(11, 11)
        assert not _is_legal_final_game(None, 11)
