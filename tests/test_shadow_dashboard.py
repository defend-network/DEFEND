"""Phase D shadow dashboard endpoints (P6): read-only, honest, hermetic."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from defend_markets import app as app_module
from defend_markets.app import MarketsDependencies
from defend_markets.config import MarketsSettings
from defend_markets.m5_live import FEATURE_NAMES
from defend_markets.shadow import OPEN, RulerRow
from defend_markets.shadow_store import InMemoryShadowStore

from tests.fakes_markets import InMemoryJournal, InMemoryStore

NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)
COMMENCE = datetime(2026, 8, 20, 22, 0, 0, tzinfo=timezone.utc)


def _seed_store() -> InMemoryShadowStore:
    store = InMemoryShadowStore()
    event_id = store.upsert_forward_event(
        provider="oddspapi",
        provider_event_id="id1",
        canonical_event_id="oaio:id1",
        competition="Czech Liga Pro",
        player_a_key="sobisemartin",
        player_b_key="chlebmarek",
        player_a_name="Sobisek Martin",
        player_b_name="Chlebecek Marek",
        scheduled_commence=COMMENCE,
        match_level="EXACT_ID",
        discovered_at=NOW - timedelta(hours=6),
    )
    store.set_last_odds_poll(event_id, NOW - timedelta(seconds=30))
    store.insert_observation(
        forward_event_id=event_id,
        canonical_event_id="oaio:id1",
        provider="oddspapi",
        provider_event_id="id1",
        bookmaker="1xbet",
        market="match_winner",
        provider_market_id="251",
        side="A",
        participant_key="sobisemartin",
        price=1.8,
        observed_at=NOW - timedelta(hours=2),
        scheduled_commence=COMMENCE,
        raw_provenance="oddspapi:odds",
        raw_evidence_ref="tt_raw_evidence:abc",
        observation_class=OPEN,
    )
    store.insert_m5_prediction(
        canonical_event_id="oaio:id1",
        player_a_key="sobisemartin",
        player_b_key="chlebmarek",
        model_id="M5_REGULARIZED_LOGISTIC",
        model_version="M5_REGULARIZED_LOGISTIC:test",
        feature_snapshot_id="frozen-snapshot-test",
        generated_at=NOW - timedelta(hours=2),
        p_a=0.56,
        p_b=0.44,
        availability="AVAILABLE",
        feature_payload={n: 0.0 for n in FEATURE_NAMES},
    )
    store.insert_ruler_row(
        RulerRow(
            observation_id=1,
            canonical_event_id="oaio:id1",
            observation_class=OPEN,
            observed_at=NOW - timedelta(hours=2),
            side_a_price=1.8,
            side_b_price=2.1,
            raw_implied_p_a=0.555556,
            raw_implied_p_b=0.476190,
            overround=1.031746,
            no_vig_p_a=0.538462,
            no_vig_p_b=0.461538,
            m5_p_a=0.56,
            model_market_disagreement=0.021538,
            observation_age_seconds=7200.0,
            seconds_to_commence=12 * 3600.0,
        ),
        raw={},
    )
    store.insert_evaluation_row(
        {
            "canonical_event_id": "oaio:id1",
            "result_id": 7,
            "settled_at": NOW + timedelta(hours=2),
            "model_id": "M5_REGULARIZED_LOGISTIC",
            "model_version": "M5_REGULARIZED_LOGISTIC:test",
            "reference_class": OPEN,
            "m5_p_a": 0.56,
            "market_no_vig_p_a": 0.538462,
            "actual": 1.0,
        }
    )
    return store


def _deps(store: InMemoryShadowStore) -> MarketsDependencies:
    return MarketsDependencies(
        settings=MarketsSettings(
            data_root=Path("."), database_url="postgresql://f:f@localhost:1/markets"
        ),
        database=None,
        sports_database=None,
        reader=None,
        store=InMemoryStore(),
        journal=InMemoryJournal(),
        clock=lambda: NOW,
        shadow=store,
    )


class TestShadowDashboard:
    def test_overview_is_honest(self):
        app = app_module.build_markets_app(_deps(_seed_store()))
        body = TestClient(app).get("/v1/sports/tt/shadow/overview").json()
        assert body["collector"]["events_discovered"] == 1
        assert body["collector"]["events_matched"] == 1
        assert body["collector"]["prematch_observations"] == 1
        assert body["collector"]["bookmakers"] == ["1xbet"]
        assert body["m5"]["available"] == 1
        assert body["evaluation"]["n"] == 1
        assert body["evaluation"]["market_edge_status"] == "INSUFFICIENT_SAMPLE"

    def test_overview_503_without_shadow(self):
        app = app_module.build_markets_app(
            MarketsDependencies(
                settings=MarketsSettings(
                    data_root=Path("."), database_url="postgresql://f:f@localhost:1/markets"
                ),
                store=InMemoryStore(),
                journal=InMemoryJournal(),
                clock=lambda: NOW,
            )
        )
        response = TestClient(app).get("/v1/sports/tt/shadow/overview")
        assert response.status_code == 503

    def test_events_listing(self):
        app = app_module.build_markets_app(_deps(_seed_store()))
        body = TestClient(app).get("/v1/sports/tt/shadow/events").json()
        events = body["events"]
        assert len(events) == 1
        event = events[0]
        assert event["status"] == "PREMATCH"
        assert event["canonical_event_id"] == "oaio:id1"
        assert event["m5_p_a"] == 0.56
        assert event["model_market_disagreement"] == 0.021538

    def test_events_live_after_commence(self):
        store = _seed_store()
        app = app_module.build_markets_app(_deps(store))
        body = TestClient(app).get("/v1/sports/tt/shadow/events").json()
        assert body["events"][0]["status"] == "PREMATCH"

    def test_evaluation_endpoint(self):
        app = app_module.build_markets_app(_deps(_seed_store()))
        body = TestClient(app).get("/v1/sports/tt/shadow/evaluation").json()
        assert body["evaluation"]["n"] == 1
        assert body["recent"][0]["reference_class"] == OPEN
        assert body["recent"][0]["actual"] == 1.0