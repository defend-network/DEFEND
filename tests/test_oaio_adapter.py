"""Odds-API.io adapter normalization tests (no network, no DB)."""

from __future__ import annotations

import json
from types import SimpleNamespace

from defend_integrations.matching import match_event
from defend_markets.shadow import forward_fixtures_from_oddspapi
from tools.defend_tt_forward_collector import (
    OddsApiIOLiveClient,
    _oaio_event_to_fixture,
    _oaio_odds_to_oddspapi_shape,
)


def _event(**overrides):
    event = {
        "id": 73870732,
        "home": "Kowalewski, Kamil",
        "away": "Bucko, Damian",
        "date": "2026-08-20T20:00:00Z",
        "status": "pending",
        "sport": {"name": "Table Tennis", "slug": "table-tennis"},
        "league": {"name": "International - TT Cup", "slug": "international-tt-cup"},
        "bookmakers": {},
    }
    event.update(overrides)
    return event


class TestEventToFixture:
    def test_maps_event_to_oddspapi_fixture_shape(self):
        fx = _oaio_event_to_fixture(_event())
        assert fx["sportId"] == 25
        assert fx["fixtureId"] == "73870732"
        assert fx["tournamentName"] == "International - TT Cup"
        assert fx["participant1Name"] == "Kowalewski, Kamil"
        assert fx["participant2Name"] == "Bucko, Damian"
        assert fx["startTime"] == "2026-08-20T20:00:00Z"
        assert fx["statusName"] == "pending"
        assert fx["hasOdds"] is False

    def test_has_odds_flag_from_bookmakers(self):
        fx = _oaio_event_to_fixture(_event(bookmakers={"22Bet": []}))
        assert fx["hasOdds"] is True


class TestOddsToOddspapiShape:
    def test_empty_bookmakers_normalizes_to_empty(self):
        shape = _oaio_odds_to_oddspapi_shape(_event())
        assert shape["fixtureId"] == "73870732"
        assert shape["bookmakers"] == {}

    def test_ml_market_normalized(self):
        event = _event(
            bookmakers={
                "22Bet": [
                    {
                        "name": "ML",
                        "updatedAt": "2026-08-20T19:40:00Z",
                        "odds": [
                            {"home": "1.85", "away": "1.95", "label": "Match Winner"},
                            {"home": "1.90", "away": "1.90"},
                        ],
                    }
                ]
            }
        )
        shape = _oaio_odds_to_oddspapi_shape(event)
        assert list(shape["bookmakers"].keys()) == ["22Bet"]
        markets = shape["bookmakers"]["22Bet"]["markets"]
        assert len(markets) == 1
        players = markets["m0"]["outcomes"]["winner"]["players"]
        assert players == {
            "Kowalewski, Kamil": {"price": 1.90},
            "Bucko, Damian": {"price": 1.90},
        }

    def test_non_winner_markets_dropped(self):
        event = _event(
            bookmakers={
                "22Bet": [
                    {"name": "Totals", "odds": [{"over": "1.5"}]},
                    {"name": "Handicap", "odds": [{"home": "1.5", "away": "2.4"}]},
                ]
            }
        )
        shape = _oaio_odds_to_oddspapi_shape(event)
        assert shape["bookmakers"] == {}

    def test_odds_entry_parses_via_oddspapi_parser(self):
        from defend_markets.shadow import parse_oddspapi_odds
        from datetime import datetime, timezone

        event = _event(
            bookmakers={
                "888Sport": [
                    {"name": "ML", "odds": [{"home": "1.62", "away": "2.30"}]}
                ]
            }
        )
        shape = _oaio_odds_to_oddspapi_shape(event)
        prices = parse_oddspapi_odds(
            shape,
            provider_event_id="73870732",
            ingested_at=datetime(2026, 8, 20, 20, 0, tzinfo=timezone.utc),
        )
        assert len(prices) == 2
        by_side = {p.side: p.price for p in prices}
        assert by_side["Kowalewski, Kamil"] == 1.62
        assert by_side["Bucko, Damian"] == 2.30
        assert all(p.bookmaker == "888Sport" for p in prices)
        assert all(p.market == "match_winner" for p in prices)


class TestForwardMatchPipeline:
    """Engine discovery matches against canonical_events_map output shape."""

    def test_fixture_parser_provider_label(self):
        fx = forward_fixtures_from_oddspapi(
            [_oaio_event_to_fixture(_event())], provider="odds_api_io"
        )
        assert fx[0].provider == "odds_api_io"
        fx_default = forward_fixtures_from_oddspapi(
            [_oaio_event_to_fixture(_event())]
        )
        assert fx_default[0].provider == "oddspapi"

    def test_old_canonical_shape_never_matches(self):
        legacy = {
            "oaio:73870732": {
                "event_key": "oaio:73870732",
                "league_key": "international-tt-cup",
                "home_participant_key": "kowalewski kamil",
                "away_participant_key": "bucko damian",
                "completed_at": "2026-08-15T20:00:00-04:00",
            }
        }
        fx = forward_fixtures_from_oddspapi(
            [_oaio_event_to_fixture(_event())], provider="odds_api_io"
        )[0]
        match = match_event(
            provider_event_id=fx.provider_event_id,
            provider_prefix=fx.provider,
            participants=[fx.player_a, fx.player_b],
            competition=fx.competition,
            commence_at=fx.scheduled_commence.isoformat().replace("+00:00", "Z"),
            canonical_events=list(legacy.values()),
            window_hours=3.0,
        )
        assert match.matched_event_key is None


class TestOddsApiIoClient:
    def test_uses_attested_selected_bookmakers(self):
        client = OddsApiIOLiveClient("synthetic-key")
        assert client._bookmakers_param() == "Bet365,Hard Rock"

    def test_pending_empty_embedded_books_still_fetches_odds(self, monkeypatch):
        calls = []

        def fake_probe(provider, endpoint, url, **kwargs):
            calls.append((provider, endpoint, url))
            payload = {
                "id": 73870732,
                "home": "Kowalewski, Kamil",
                "away": "Bucko, Damian",
                "bookmakers": {},
            }
            evidence = SimpleNamespace(
                body=json.dumps(payload), status_code=200
            )
            result = SimpleNamespace(status_code=200)
            return result, evidence, payload

        monkeypatch.setattr(
            "tools.defend_tt_forward_collector.probe_get", fake_probe
        )
        client = OddsApiIOLiveClient("synthetic-key")
        client._events["73870732"] = {
            "id": 73870732,
            "status": "pending",
            "bookmakers": {},
        }

        status, payload, truncated = client.fetch_odds("73870732")

        assert status == 200
        assert truncated is False
        assert calls and calls[0][1] == "odds"
        assert "bookmakers=Bet365" in calls[0][2]
        assert "markets=ML" in calls[0][2]
        assert payload["bookmakers"] == {}

    def test_new_canonical_shape_matches_by_exact_id(self):
        shaped = {
            "oaio:73870732": {
                "event_key": "oaio:73870732",
                "provider_event_id": "73870732",
                "participant_keys": ["kowalewski kamil", "bucko damian"],
                "competition": "international-tt-cup",
                "commence_at": "2026-08-15T20:00:00-04:00",
            }
        }
        fx = forward_fixtures_from_oddspapi(
            [_oaio_event_to_fixture(_event())], provider="odds_api_io"
        )[0]
        match = match_event(
            provider_event_id=fx.provider_event_id,
            provider_prefix=fx.provider,
            participants=[fx.player_a, fx.player_b],
            competition=fx.competition,
            commence_at=fx.scheduled_commence.isoformat().replace("+00:00", "Z"),
            canonical_events=list(shaped.values()),
            window_hours=3.0,
        )
        assert match.matched_event_key == "oaio:73870732"
        assert match.level.value == "EXACT_ID"

    def test_new_canonical_shape_matches_by_names_within_window(self):
        shaped = {
            "oaio:99999999": {
                "event_key": "oaio:99999999",
                "provider_event_id": "99999999",
                "participant_keys": ["kowalewski kamil", "bucko damian"],
                "competition": "international-tt-cup",
                "commence_at": "2026-08-20T21:30:00+00:00",
            }
        }
        fx = forward_fixtures_from_oddspapi(
            [_oaio_event_to_fixture(_event())], provider="odds_api_io"
        )[0]
        match = match_event(
            provider_event_id=fx.provider_event_id,
            provider_prefix=fx.provider,
            participants=[fx.player_a, fx.player_b],
            competition=fx.competition,
            commence_at=fx.scheduled_commence.isoformat().replace("+00:00", "Z"),
            canonical_events=list(shaped.values()),
            window_hours=3.0,
        )
        assert match.matched_event_key == "oaio:99999999"
        assert match.level.value == "NORMALIZED"

    def test_real_provider_names_match_normalized_canonical_candidate(self):
        shaped = {
            "oaio:normalized-real-sample": {
                "event_key": "oaio:normalized-real-sample",
                "provider_event_id": "different-provider-id",
                "participant_keys": ["chmelicek martin", "hruby radek"],
                "competition": "international-tt-cup",
                "commence_at": "2026-08-19T18:05:00Z",
            }
        }
        fx = forward_fixtures_from_oddspapi(
            [{
                **_oaio_event_to_fixture({
                    "id": 73850316,
                    "home": "Chmelicek, Martin",
                    "away": "Hruby, Radek",
                    "date": "2026-08-19T18:05:00Z",
                    "league": {"name": "International - TT Cup"},
                }),
            }],
            provider="odds_api_io",
        )[0]
        match = match_event(
            provider_event_id=fx.provider_event_id,
            provider_prefix=fx.provider,
            participants=[fx.player_a, fx.player_b],
            competition=fx.competition,
            commence_at=fx.scheduled_commence.isoformat().replace("+00:00", "Z"),
            canonical_events=list(shaped.values()),
            window_hours=3.0,
        )
        assert match.matched_event_key == "oaio:normalized-real-sample"
        assert match.level.value == "NORMALIZED"

    def test_new_canonical_shape_skips_far_future_commence(self):
        shaped = {
            "oaio:99999999": {
                "event_key": "oaio:99999999",
                "provider_event_id": "99999999",
                "participant_keys": ["kowalewski kamil", "bucko damian"],
                "competition": "international-tt-cup",
                "commence_at": "2026-08-15T20:00:00-04:00",
            }
        }
        fx = forward_fixtures_from_oddspapi(
            [_oaio_event_to_fixture(_event())], provider="odds_api_io"
        )[0]
        match = match_event(
            provider_event_id=fx.provider_event_id,
            provider_prefix=fx.provider,
            participants=[fx.player_a, fx.player_b],
            competition=fx.competition,
            commence_at=fx.scheduled_commence.isoformat().replace("+00:00", "Z"),
            canonical_events=list(shaped.values()),
            window_hours=3.0,
        )
        assert match.matched_event_key is None
