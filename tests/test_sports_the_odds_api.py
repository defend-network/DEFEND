"""Unit tests for the The Odds API sports provider adapter."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from defend_sports.providers.base import SportsProvider
from defend_sports.providers.the_odds_api import (
    OddsApiProviderError,
    TheOddsApiSportsProvider,
)

_NOW = datetime(2026, 8, 17, 10, 30, 0, tzinfo=timezone.utc)

_SPORTS_LIST = [
    {
        "key": "table_tennis_superliga",
        "group": "Table Tennis",
        "title": "Table Tennis Superliga",
        "active": True,
        "has_outrights": False,
    },
    {
        "key": "soccer_england_league1",
        "group": "Soccer",
        "title": "League One",
        "active": True,
        "has_outrights": False,
    },
]

_ODDS_PAYLOAD = [
    {
        "id": "tt-001",
        "sport_key": "table_tennis_superliga",
        "commence_time": "2026-08-17T11:00:00Z",
        "home_team": "Player A",
        "away_team": "Player B",
        "bookmakers": [
            {
                "key": "pinnacle",
                "title": "Pinnacle",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Home", "price": 1.85},
                            {"name": "Away", "price": 2.05},
                        ],
                    }
                ],
            },
            {
                "key": "bet365",
                "title": "Bet365",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Home", "price": "1.92"},
                            {"name": "Away", "price": "2.00"},
                            {"name": "Draw", "price": 4.0},
                        ],
                    }
                ],
            },
        ],
    },
    {
        "id": "tt-bad-price",
        "sport_key": "table_tennis_superliga",
        "commence_time": "2026-08-17T12:00:00Z",
        "home_team": "Player C",
        "away_team": "Player D",
        "bookmakers": [
            {
                "key": "pinnacle",
                "title": "Pinnacle",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Home", "price": 1.0},
                            {"name": "Away", "price": "oops"},
                        ],
                    }
                ],
            }
        ],
    },
]

_SCORES_PAYLOAD = [
    {
        "id": "tt-001",
        "sport_key": "table_tennis_superliga",
        "completed": False,
        "scores": [
            {"name": "Player A", "score": "1"},
            {"name": "Player B", "score": "0"},
        ],
    }
]


class StubHttp:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, url: str) -> tuple[object, int]:
        self.calls.append(url)
        if "sports/?" in url or url.endswith("/sports/?"):
            return list(_SPORTS_LIST), 200
        if "/odds/" in url:
            return list(_ODDS_PAYLOAD), 200
        if "/scores/" in url:
            return list(_SCORES_PAYLOAD), 200
        raise AssertionError(f"unexpected URL: {url}")


def _provider(http: StubHttp, **kwargs) -> TheOddsApiSportsProvider:
    return TheOddsApiSportsProvider(
        api_key="test-key",
        http_get=http,
        clock=lambda: _NOW,
        **kwargs,
    )


class TestOddsApiProviderInterface:
    def test_conforms_to_sports_provider_protocol(self):
        provider = TheOddsApiSportsProvider()
        assert isinstance(provider, SportsProvider)
        assert provider.provider_name == "the_odds_api"

    def test_poll_requires_api_key(self):
        with pytest.raises(OddsApiProviderError, match="THE_ODDS_API_KEY"):
            TheOddsApiSportsProvider().poll()

    def test_poll_without_configured_keys_discovers_table_tennis(self):
        http = StubHttp()
        batch = _provider(http).poll()
        assert batch.events
        sports_list_calls = [url for url in http.calls if "/sports/?" in url]
        assert len(sports_list_calls) == 1
        odds_calls = [url for url in http.calls if "/odds/" in url]
        assert any("table_tennis_superliga/odds/" in url for url in odds_calls)

    def test_poll_with_configured_keys_skips_discovery(self):
        http = StubHttp()
        batch = _provider(http, sport_keys=("table_tennis_superliga",)).poll()
        assert batch.events
        assert not [url for url in http.calls if "/sports/?" in url]


class TestOddsApiMapping:
    def test_maps_matches_to_canonical_events(self):
        batch = _provider(StubHttp()).poll()
        assert len(batch.raw_events) == 2
        assert len(batch.events) == 2
        event = next(e for e in batch.events if e.event_external_id == "tt-001")
        assert event.sport_key == "table_tennis"
        assert event.league_key == "table_tennis_superliga"
        assert event.display_name == "Player A vs Player B"
        assert event.scheduled_at == datetime(2026, 8, 17, 11, 0, tzinfo=timezone.utc)

    def test_maps_bookmaker_odds_with_normalized_selections(self):
        batch = _provider(StubHttp()).poll()
        odds = [o for o in batch.odds if o.event_external_id == "tt-001"]
        assert len(odds) == 4
        by_book: dict[str, dict[str, Decimal]] = {}
        for observation in odds:
            by_book.setdefault(observation.source.external_id, {})[
                observation.selection_key
            ] = observation.decimal_odds
        assert by_book["pinnacle"]["home"] == Decimal("1.85")
        assert by_book["pinnacle"]["away"] == Decimal("2.05")
        assert by_book["bet365"]["home"] == Decimal("1.92")
        assert by_book["bet365"]["away"] == Decimal("2.00")
        assert all(observation.market_key == "match_winner" for observation in odds)

    def test_skips_unpriced_outcomes_and_invalid_prices(self):
        batch = _provider(StubHttp()).poll()
        odds = [o for o in batch.odds if o.event_external_id == "tt-bad-price"]
        assert odds == []

    def test_emits_live_observation_for_in_progress_scored_match(self):
        batch = _provider(StubHttp()).poll()
        assert len(batch.live) == 1
        live = batch.live[0]
        assert live.event_external_id == "tt-001"
        assert live.state["status"] == "live"
        assert live.state["scores"] == [["Player A", "1"], ["Player B", "0"]]

    def test_live_observations_reference_raw_events_from_same_batch(self):
        batch = _provider(StubHttp()).poll()
        raw_refs = {raw.provider_event_id for raw in batch.raw_events}
        for observation in batch.live:
            assert observation.raw_event_ref in raw_refs

    def test_raw_events_carry_verbatim_payload_and_provenance(self):
        batch = _provider(StubHttp()).poll()
        raw = next(r for r in batch.raw_events if "tt-001" in r.provider_event_id)
        assert raw.payload["id"] == "tt-001"
        assert raw.payload["home_team"] == "Player A"
        assert raw.observed_at == _NOW
        assert raw.source.external_id == "table_tennis_superliga"


class TestOddsApiFailures:
    def test_unexpected_odds_payload_raises(self):
        def http(url: str) -> tuple[object, int]:
            if "/sports/?" in url:
                return list(_SPORTS_LIST), 200
            if "/odds/" in url:
                return {"not": "a list"}, 200
            return [], 200

        with pytest.raises(OddsApiProviderError, match="odds payload"):
            _provider(http).poll()

    def test_all_sport_keys_failing_raises_with_details(self):
        def http(url: str) -> tuple[object, int]:
            if "/odds/" in url:
                raise OddsApiProviderError("status 401")
            return list(_SPORTS_LIST), 200

        with pytest.raises(OddsApiProviderError, match="table_tennis_superliga: status 401"):
            _provider(http).poll()

    def test_partial_sport_key_failure_still_yields_other_matches(self):
        def http(url: str) -> tuple[object, int]:
            if "/odds/" in url and "key2" in url:
                raise OddsApiProviderError("status 429")
            return list(_ODDS_PAYLOAD), 200

        batch = _provider(http, sport_keys=("table_tennis_superliga", "table_tennis_key2")).poll()
        assert batch.events
        assert all(e.league_key == "table_tennis_superliga" for e in batch.events)

    def test_scores_failure_does_not_break_odds_batch(self):
        def http(url: str) -> tuple[object, int]:
            if "/sports/?" in url:
                return list(_SPORTS_LIST), 200
            if "/scores/" in url:
                raise OddsApiProviderError("status 500")
            return list(_ODDS_PAYLOAD), 200

        batch = _provider(http).poll()
        assert batch.events
        assert batch.live == ()

    def test_empty_odds_is_an_empty_batch(self):
        def http(url: str) -> tuple[object, int]:
            if "/odds/" in url:
                return [], 200
            return [], 200

        batch = _provider(http).poll()
        assert batch.raw_events == ()
        assert batch.events == ()