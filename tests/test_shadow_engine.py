"""Phase D shadow engine tests: schedule, gate, parsing, ruler math,
settlement, evaluation thresholds, idempotency. No network, no DB."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from defend_markets.m5_live import FEATURE_NAMES, FrozenM5, M5Match, M5StateBuilder
from defend_markets.shadow import (
    INTERMEDIATE,
    LAST_VALID_PREMATCH,
    OPEN,
    POST_COMMENCE,
    RulerRow,
    build_evaluation_rows,
    build_ruler_row,
    classify_observation,
    evaluation_report,
    last_valid_prematch,
    parse_oddspapi_odds,
    poll_delay_for,
    schedule_label_for,
    select_reference_rows,
)
from defend_markets.shadow_engine import ShadowEngine, ShadowConfig
from defend_markets.shadow_store import InMemoryShadowStore

NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)


class FakeM5:
    model_version = "M5_REGULARIZED_LOGISTIC:test"
    feature_snapshot_id = "frozen-snapshot-test"

    def predict(self, builder, home, away, ts, *, min_games=5):
        return 0.56, "AVAILABLE", {n: 0.0 for n in FEATURE_NAMES}


class FakeClient:
    def __init__(self):
        self.fixture_payload = None
        self.odds_payloads: dict[str, object] = {}
        self.calls = {"fixtures": 0, "odds": 0}

    def fetch_fixtures(self, *, from_iso, to_iso):
        self.calls["fixtures"] += 1
        return 200, self.fixture_payload, False

    def fetch_odds(self, provider_event_id):
        self.calls["odds"] += 1
        return 200, self.odds_payloads.get(provider_event_id), False


def _fixture_payload():
    return [
        {
            "sportId": 25,
            "fixtureId": "id1",
            "tournamentName": "Czech Liga Pro",
            "participant1Name": "Sobisek Martin",
            "participant2Name": "Chlebecek Marek",
            "startTime": "2026-08-21T00:00:00Z",
        },
        {
            "sportId": 25,
            "fixtureId": "id2",
            "tournamentName": "Czech Liga Pro",
            "participant1Name": "Novak Petr",
            "participant2Name": "Dvorak Jan",
            "startTime": "2026-08-21T02:00:00Z",
        },
        {"sportId": 20, "fixtureId": "id3", "tournamentName": "Other",
         "participant1Name": "X", "participant2Name": "Y",
         "startTime": "2026-08-21T03:00:00Z"},
    ]


def _odds_payload():
    return {
        "fixtureId": "id1",
        "bookmakers": {
            "1xbet": {
                "markets": {
                    "251": {
                        "outcomes": {
                            "o1": {"players": {"Sobisek Martin": {"price": 1.8, "changedAt": None}}},
                            "o2": {"players": {"Chlebecek Marek": {"price": 2.1, "changedAt": None}}},
                        }
                    }
                }
            }
        },
    }


# --------------------------------------------------------------------------- #
# P1 adaptive schedule
# --------------------------------------------------------------------------- #
class TestAdaptiveSchedule:
    def test_bands_decrease_with_proximity(self):
        assert poll_delay_for(25 * 3600) == 1800.0
        assert poll_delay_for(18 * 3600) == 600.0
        assert poll_delay_for(8 * 3600) == 300.0
        assert poll_delay_for(3 * 3600) == 120.0
        assert poll_delay_for(3600) == 45.0
        assert poll_delay_for(600) == 20.0
        assert poll_delay_for(60) == 10.0
        assert poll_delay_for(0) == 10.0

    def test_labels(self):
        assert schedule_label_for(25 * 3600) == "LOW"
        assert schedule_label_for(600) == "HIGHEST"
        assert schedule_label_for(60) == "COMMENCE"
        assert schedule_label_for(0) == "COMMENCE"


# --------------------------------------------------------------------------- #
# P2 contamination gate
# --------------------------------------------------------------------------- #
class TestContaminationGate:
    def test_post_commence_never_prematch(self):
        commence = NOW
        assert classify_observation(commence, commence, is_first_prematch=True) == POST_COMMENCE
        assert classify_observation(commence + timedelta(minutes=5), commence,
                                    is_first_prematch=True) == POST_COMMENCE

    def test_open_then_intermediate(self):
        commence = NOW + timedelta(hours=2)
        assert classify_observation(NOW, commence, is_first_prematch=True) == OPEN
        assert classify_observation(NOW + timedelta(minutes=10), commence,
                                    is_first_prematch=False) == INTERMEDIATE

    def test_last_valid_prematch_is_latest_prematch(self):
        observations = [
            {"observed_at": NOW, "observation_class": OPEN},
            {"observed_at": NOW + timedelta(minutes=5), "observation_class": INTERMEDIATE},
            {"observed_at": NOW + timedelta(hours=3), "observation_class": POST_COMMENCE},
        ]
        last = last_valid_prematch(observations)
        assert last["observed_at"] == NOW + timedelta(minutes=5)
        assert last_valid_prematch([]) is None


# --------------------------------------------------------------------------- #
# P1 odds parsing
# --------------------------------------------------------------------------- #
class TestOddsParsing:
    def test_live_shape(self):
        prices = parse_oddspapi_odds(
            _odds_payload(), provider_event_id="id1", ingested_at=NOW
        )
        assert len(prices) == 2
        by_side = {p.participant_key: p.price for p in prices}
        assert by_side == {"Sobisek Martin": 1.8, "Chlebecek Marek": 2.1}
        assert all(p.market == "match_winner" for p in prices)

    def test_historical_snapshot_shape(self):
        payload = {
            "fixtureId": "id1",
            "bookmakers": {
                "bet365": {
                    "markets": {
                        "251": {
                            "outcomes": {
                                "o1": {"players": {
                                    "Sobisek Martin": [
                                        {"createdAt": "2026-08-20T10:00:00Z", "price": 1.7},
                                    ]
                                }},
                            }
                        }
                    }
                }
            },
        }
        prices = parse_oddspapi_odds(payload, provider_event_id="id1", ingested_at=NOW)
        assert len(prices) == 1
        assert prices[0].price == 1.7
        assert prices[0].changed_at == datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)

    def test_garbage_payload_is_empty(self):
        assert parse_oddspapi_odds(None, provider_event_id="x", ingested_at=NOW) == []
        assert parse_oddspapi_odds({"bookmakers": "nope"}, provider_event_id="x", ingested_at=NOW) == []


# --------------------------------------------------------------------------- #
# P4 ruler math
# --------------------------------------------------------------------------- #
class TestRulerMath:
    def test_no_vig_and_disagreement(self):
        row = build_ruler_row(
            observation_id=1,
            canonical_event_id="oaio:1",
            observation_class=OPEN,
            price_a=2.0,
            price_b=2.0,
            m5_p_a=0.6,
            observed_at=NOW,
            commence_at=NOW + timedelta(hours=1),
            now=NOW,
        )
        assert row.raw_implied_p_a == pytest.approx(0.5)
        assert row.overround == pytest.approx(1.0)
        assert row.no_vig_p_a == pytest.approx(0.5)
        assert row.model_market_disagreement == pytest.approx(0.1)
        assert row.seconds_to_commence == pytest.approx(3600.0)
        assert row.observation_age_seconds == pytest.approx(0.0)

    def test_invalid_prices_never_produce_fake_no_vig(self):
        row = build_ruler_row(
            observation_id=2,
            canonical_event_id="oaio:1",
            observation_class=OPEN,
            price_a=1.0,
            price_b=2.0,
            m5_p_a=0.5,
            observed_at=NOW,
            commence_at=NOW + timedelta(hours=1),
            now=NOW,
        )
        assert row.overround is None
        assert row.no_vig_p_a is None
        assert row.model_market_disagreement is None

    def test_never_labeled_edge(self):
        row = build_ruler_row(
            observation_id=3,
            canonical_event_id="oaio:1",
            observation_class=OPEN,
            price_a=1.8,
            price_b=2.1,
            m5_p_a=0.61,
            observed_at=NOW,
            commence_at=NOW + timedelta(hours=1),
            now=NOW,
        )
        assert not hasattr(row, "edge")
        assert row.model_market_disagreement is not None


# --------------------------------------------------------------------------- #
# P5 settlement references + evaluation
# --------------------------------------------------------------------------- #
def _ruler_rows():
    def row(oid, obs_class, price_a, price_b, no_vig_a, seconds):
        return {
            "observation_id": oid,
            "observation_class": obs_class,
            "no_vig_p_a": no_vig_a,
            "side_a_price": price_a,
            "side_b_price": price_b,
            "seconds_to_commence": seconds,
            "observed_at": NOW + timedelta(seconds=seconds),
            "m5_p_a": 0.55,
        }

    return [
        row(1, OPEN, 2.0, 1.8, 0.5263, -7200),
        row(2, INTERMEDIATE, 1.9, 1.9, 0.5, -10800),
        row(3, INTERMEDIATE, 1.95, 1.85, 0.5132, -3600),
        row(4, LAST_VALID_PREMATCH, 1.75, 2.05, 0.5395, -300),
    ]


class TestSettlement:
    def test_reference_selection_open_last_and_intermediate(self):
        refs = select_reference_rows(_ruler_rows())
        classes = {r.reference_class for r in refs}
        assert classes == {OPEN, INTERMEDIATE, LAST_VALID_PREMATCH}
        by_class = {r.reference_class: r for r in refs}
        assert by_class[OPEN].no_vig_p_a == pytest.approx(0.5263)
        assert by_class[LAST_VALID_PREMATCH].no_vig_p_a == pytest.approx(0.5395)
        assert by_class[INTERMEDIATE].no_vig_p_a == pytest.approx(0.5)

    def test_evaluation_rows_are_built(self):
        rows = build_evaluation_rows(
            canonical_event_id="oaio:1",
            result_id=7,
            settled_at=NOW + timedelta(hours=2),
            ruler_rows=_ruler_rows(),
            m5_p_a=0.55,
            actual=1.0,
        )
        assert len(rows) == 3
        for row in rows:
            assert row.m5_p_a == pytest.approx(0.55)
            assert row.actual == 1.0

    def test_report_thresholds_and_status(self):
        rows = [
            {
                "m5_p_a": 0.5, "market_no_vig_p_a": 0.5, "actual": 1.0,
                "reference_class": OPEN, "settled_at": NOW,
            }
            for _ in range(5)
        ]
        report = evaluation_report(rows)
        assert report["n"] == 5
        assert report["market_edge_status"] == "INSUFFICIENT_SAMPLE"
        assert report["thresholds"]["30"] is None
        assert report["pooled"]["m5_brier"] == pytest.approx(0.25)

    def test_report_flips_only_at_100(self):
        rows = [
            {
                "m5_p_a": 0.5, "market_no_vig_p_a": 0.5, "actual": 1.0,
                "reference_class": OPEN, "settled_at": NOW,
            }
            for _ in range(99)
        ]
        assert evaluation_report(rows)["market_edge_status"] == "INSUFFICIENT_SAMPLE"
        rows.append(
            {"m5_p_a": 0.5, "market_no_vig_p_a": 0.5, "actual": 1.0,
             "reference_class": OPEN, "settled_at": NOW}
        )
        assert evaluation_report(rows)["market_edge_status"] == "PAIRWISE_MEASURED"
        assert evaluation_report(rows)["thresholds"]["100"]["n"] == 100


# --------------------------------------------------------------------------- #
# P0-P5 engine cycle (in-memory)
# --------------------------------------------------------------------------- #
class TestEngineCycle:
    def _engine(self, *, now=None):
        store = InMemoryShadowStore()
        client = FakeClient()
        client.fixture_payload = _fixture_payload()
        client.odds_payloads["id1"] = _odds_payload()
        engine = ShadowEngine(
            store=store,
            m5=FakeM5(),
            client=client,
            now=lambda: now or NOW,
        )
        engine.set_state_builder(object())  # not exercised by FakeM5
        return store, client, engine

    def test_cycle_discovery_matches_only_tt(self):
        store, client, engine = self._engine()
        canonical = {
            "oaio:id1": {
                "event_key": "oaio:id1",
                "provider_event_id": "id1",
                "participant_keys": ["Sobisek Martin", "Chlebecek Marek"],
                "competition": "Czech Liga Pro",
                "commence_at": "2026-08-21T00:00:00Z",
            }
        }
        metrics = engine.discover(canonical_events=canonical)
        assert metrics.events_discovered == 2  # sportId 25 only
        assert metrics.events_matched == 1
        assert metrics.ambiguous_events == 0
        events = store.list_forward_events()
        by_id = {e["provider_event_id"]: e for e in events}
        assert by_id["id1"]["canonical_event_id"] == "oaio:id1"
        assert by_id["id1"]["match_level"] == "EXACT_ID"
        assert by_id["id1"]["player_a_key"] == "Sobisek Martin"
        assert by_id["id1"]["player_b_key"] == "Chlebecek Marek"
        assert by_id["id2"]["canonical_event_id"] is None
        assert store.raw_evidence, "raw evidence must be persisted"

    def test_namespaced_canonical_keys_are_retained_for_m5_history(self):
        store = InMemoryShadowStore()
        client = FakeClient()
        client.fixture_payload = [{
            "sportId": 25,
            "fixtureId": "namespaced-id",
            "tournamentName": "International - TT Cup",
            "participant1Name": "Szymanski, Igor",
            "participant2Name": "Baron, Mariusz",
            "startTime": "2026-08-21T00:00:00Z",
        }]
        engine = ShadowEngine(
            store=store,
            m5=FakeM5(),
            client=client,
            now=lambda: NOW,
        )
        engine.discover(canonical_events={
            "oaio:namespaced-id": {
                "event_key": "oaio:namespaced-id",
                "provider_event_id": "namespaced-id",
                "participant_keys": ["szymanskiigor", "baronmariusz"],
                "canonical_participant_keys": [
                    "table_tennis:szymanskiigor",
                    "table_tennis:baronmariusz",
                ],
                "competition": "international-tt-cup",
                "commence_at": "2026-08-21T00:00:00Z",
            }
        })

        event = store.forward_event(1)
        assert event["canonical_event_id"] == "oaio:namespaced-id"
        assert event["player_a_key"] == "table_tennis:szymanskiigor"
        assert event["player_b_key"] == "table_tennis:baronmariusz"

    def test_new_event_gets_identity_map_only_for_unique_known_players(self):
        store = InMemoryShadowStore()
        client = FakeClient()
        client.fixture_payload = [{
            "sportId": 25,
            "fixtureId": "new-forward-id",
            "tournamentName": "International - TT Elite Series",
            "participant1Name": "Szymanski, Igor",
            "participant2Name": "Baron, Mariusz",
            "startTime": "2026-08-21T00:00:00Z",
        }]
        engine = ShadowEngine(
            store=store,
            m5=FakeM5(),
            client=client,
            provider_label="odds_api_io",
            now=lambda: NOW,
        )

        engine.discover(canonical_events={
            "oaio:old-event": {
                "event_key": "oaio:old-event",
                "provider_event_id": "old-event",
                "participant_keys": ["szymanskiigor", "baronmariusz"],
                "canonical_participant_keys": [
                    "table_tennis:szymanskiigor",
                    "table_tennis:baronmariusz",
                ],
                "competition": "international-tt-cup",
                "commence_at": "2026-08-01T00:00:00Z",
            }
        })

        event = store.forward_event(1)
        assert event["canonical_event_id"] == "oaio:new-forward-id"
        assert event["match_level"] == "IDENTITY_MAP"
        assert event["player_a_key"] == "table_tennis:szymanskiigor"

    def test_inference_skips_events_after_commence(self):
        store = InMemoryShadowStore()
        client = FakeClient()
        client.fixture_payload = [{
            "sportId": 25,
            "fixtureId": "past-id",
            "tournamentName": "Czech Liga Pro",
            "participant1Name": "Sobisek Martin",
            "participant2Name": "Chlebecek Marek",
            "startTime": "2026-08-20T10:00:00Z",
        }]
        engine = ShadowEngine(
            store=store,
            m5=FakeM5(),
            client=client,
            now=lambda: NOW,
        )
        engine.set_state_builder(object())
        engine.discover(canonical_events={
            "oaio:past-id": {
                "event_key": "oaio:past-id",
                "provider_event_id": "past-id",
                "participant_keys": ["Sobisek Martin", "Chlebecek Marek"],
                "competition": "Czech Liga Pro",
                "commence_at": "2026-08-20T10:00:00Z",
            }
        })

        metrics = engine.infer_m5()

        assert metrics.m5_predictions == 0
        assert metrics.m5_insufficient == 0
        assert store.m5_prediction("oaio:past-id") is None

    def test_provider_label_is_used_for_raw_evidence(self):
        store = InMemoryShadowStore()
        client = FakeClient()
        client.fixture_payload = _fixture_payload()
        engine = ShadowEngine(
            store=store,
            m5=FakeM5(),
            client=client,
            provider_label="odds_api_io",
            now=lambda: NOW,
        )

        engine.discover(canonical_events={})

        assert store.raw_evidence[0]["provider"] == "odds_api_io"

    def test_odds_poll_gate_and_ruler_flow(self):
        store, client, engine = self._engine(now=NOW)
        engine.discover(canonical_events={
            "oaio:id1": {
                "event_key": "oaio:id1",
                "provider_event_id": "id1",
                "participant_keys": ["Sobisek Martin", "Chlebecek Marek"],
                "competition": "Czech Liga Pro",
                "commence_at": "2026-08-21T00:00:00Z",
            }
        })
        engine._last_discovery_at = None
        metrics = engine.poll_odds()
        assert metrics.prematch_observations == 2
        assert metrics.postcommence_observations == 0
        obs = store.list_observations("oaio:id1")
        assert len(obs) == 2
        assert {o["observation_class"] for o in obs} == {OPEN, INTERMEDIATE}
        assert all(o["raw_evidence_ref"].startswith("tt_raw_evidence:") for o in obs)
        engine.infer_m5()
        assert store.m5_prediction("oaio:id1")["p_a"] == 0.56
        engine.build_ruler_rows()
        ruler = store.list_ruler_rows("oaio:id1")
        assert len(ruler) == 1
        no_vig = 0.5555556 / 1.0317460  # 1/1.8 divided by overround of (1/1.8 + 1/2.1)
        assert ruler[0]["model_market_disagreement"] == pytest.approx(0.56 - no_vig, abs=1e-4)

    def test_restart_idempotency_no_duplicates(self):
        store, client, engine = self._engine(now=NOW)
        engine.discover(canonical_events={
            "oaio:id1": {
                "event_key": "oaio:id1",
                "provider_event_id": "id1",
                "participant_keys": ["Sobisek Martin", "Chlebecek Marek"],
                "competition": "Czech Liga Pro",
                "commence_at": "2026-08-21T00:00:00Z",
            }
        })
        engine._last_discovery_at = None
        engine.poll_odds()
        engine.build_ruler_rows()
        first_obs = len(store.list_observations("oaio:id1"))
        first_ruler = len(store.list_ruler_rows("oaio:id1"))
        # simulate restart: fresh engine instance, same store, same now
        engine2 = ShadowEngine(
            store=store, m5=FakeM5(), client=client, now=lambda: NOW
        )
        engine2.discover(canonical_events={
            "oaio:id1": {
                "event_key": "oaio:id1",
                "provider_event_id": "id1",
                "participant_keys": ["Sobisek Martin", "Chlebecek Marek"],
                "competition": "Czech Liga Pro",
                "commence_at": "2026-08-21T00:00:00Z",
            }
        })
        engine2._last_discovery_at = None
        engine2.poll_odds()
        engine2.build_ruler_rows()
        assert len(store.list_observations("oaio:id1")) == first_obs
        assert len(store.list_ruler_rows("oaio:id1")) == first_ruler
        assert len(store.forward_events) == 2

    def test_last_valid_prematch_promotion_at_commence(self):
        store, client, engine = self._engine(now=NOW)
        canonical = {
            "oaio:id1": {
                "event_key": "oaio:id1",
                "provider_event_id": "id1",
                "participant_keys": ["Sobisek Martin", "Chlebecek Marek"],
                "competition": "Czech Liga Pro",
                "commence_at": "2026-08-21T00:00:00Z",
            }
        }
        engine.discover(canonical_events=canonical)
        engine._last_discovery_at = None
        engine.poll_odds()
        # advance past commence; freeze must promote latest prematch
        engine2 = ShadowEngine(
            store=store, m5=FakeM5(), client=client,
            now=lambda: NOW + timedelta(hours=30),
        )
        engine2.freeze_last_valid_prematch()
        obs = store.list_observations("oaio:id1")
        classes = {o["observation_class"] for o in obs}
        assert LAST_VALID_PREMATCH in classes
        event = store.forward_event(1)
        assert event["state"] == "LIVE"

    def test_settlement_persists_evaluation_rows(self):
        store, client, engine = self._engine(now=NOW)
        canonical = {
            "oaio:id1": {
                "event_key": "oaio:id1",
                "provider_event_id": "id1",
                "participant_keys": ["Sobisek Martin", "Chlebecek Marek"],
                "competition": "Czech Liga Pro",
                "commence_at": "2026-08-21T00:00:00Z",
            }
        }
        engine.discover(canonical_events=canonical)
        # three polls at distinct times -> OPEN, INTERMEDIATE, INTERMEDIATE
        for poll_at in (NOW, NOW + timedelta(minutes=10), NOW + timedelta(minutes=30)):
            engine2 = ShadowEngine(
                store=store, m5=FakeM5(), client=client, now=lambda: poll_at
            )
            engine2.set_state_builder(object())
            engine2._last_discovery_at = None
            engine2.poll_odds()
            engine2.infer_m5()
            engine2.build_ruler_rows()
        settled = {"result_id": 99, "actual": 1.0, "settled_at": NOW}
        engine3 = ShadowEngine(
            store=store, m5=FakeM5(), client=client,
            settled=lambda _key: settled,
            now=lambda: NOW + timedelta(hours=30),
        )
        engine3.freeze_last_valid_prematch()
        metrics = engine3.settle()
        assert metrics.settlements == 3
        assert len(store.evaluation_rows()) == 3
        classes = {r["reference_class"] for r in store.evaluation_rows()}
        assert classes == {OPEN, INTERMEDIATE, LAST_VALID_PREMATCH}


# --------------------------------------------------------------------------- #
# M5 frozen inference (deterministic, leakage-free)
# --------------------------------------------------------------------------- #
def _synthetic_matches():
    matches = []
    ts = datetime(2025, 6, 1, tzinfo=timezone.utc)
    players = ["p1", "p2", "p3", "p4"]
    for i in range(1200):
        home = players[i % 4]
        away = players[(i + 1 + (i // 4) % 2) % 4]
        if home == away:
            away = players[(i + 2) % 4]
        matches.append(
            M5Match(
                event_key=f"e{i}",
                home_key=home,
                away_key=away,
                ts=ts + timedelta(hours=6 * i),
                actual=1.0 if (i % 3) != 0 else 0.0,
            )
        )
    return matches


class TestFrozenM5:
    def test_freeze_is_deterministic(self):
        doc1 = FrozenM5.freeze(
            _synthetic_matches(), cutoff=datetime(2026, 3, 1, tzinfo=timezone.utc)
        )
        doc2 = FrozenM5.freeze(
            _synthetic_matches(), cutoff=datetime(2026, 3, 1, tzinfo=timezone.utc)
        )
        assert doc1["sha256"] == doc2["sha256"]
        assert doc1["intercept"] == doc2["intercept"]
        assert doc1["feature_names"] == FEATURE_NAMES

    def test_freeze_serializes_aware_cutoff_as_utc_instant(self):
        cutoff = datetime(
            2026, 2, 1, 20, 0, tzinfo=timezone(timedelta(hours=-4))
        )
        doc = FrozenM5.freeze(_synthetic_matches(), cutoff=cutoff)

        assert doc["cutoff"] == "2026-02-02T00:00:00Z"

    def test_predict_uses_strictly_before_state(self):
        doc = FrozenM5.freeze(
            _synthetic_matches(), cutoff=datetime(2026, 2, 1, tzinfo=timezone.utc)
        )
        model = FrozenM5(doc, source_ref="test")
        builder = M5StateBuilder(_synthetic_matches())
        p_a, availability, features = model.predict(
            builder, "p1", "p2", datetime(2026, 6, 1, tzinfo=timezone.utc)
        )
        assert availability == "AVAILABLE"
        assert 0.0 < p_a < 1.0
        assert set(features) == set(FEATURE_NAMES)

    def test_insufficient_history_returns_half(self):
        doc = FrozenM5.freeze(
            _synthetic_matches(), cutoff=datetime(2026, 2, 1, tzinfo=timezone.utc)
        )
        model = FrozenM5(doc, source_ref="test")
        builder = M5StateBuilder([])
        p_a, availability, _ = model.predict(
            builder, "nobody1", "nobody2", datetime(2026, 6, 1, tzinfo=timezone.utc),
            min_games=5,
        )
        assert availability == "INSUFFICIENT_HISTORY"
        assert p_a == 0.5

    def test_schema_mismatch_rejected(self):
        doc = FrozenM5.freeze(
            _synthetic_matches(), cutoff=datetime(2026, 2, 1, tzinfo=timezone.utc)
        )
        doc["feature_names"] = ["wrong"]
        with pytest.raises(ValueError):
            FrozenM5(doc, source_ref="test")


class TestTruncatedResponses:
    """OddsPapi free tier caps bodies at 16384 bytes; the parser must recover
    complete prefix objects and the engine must count truncations."""

    def test_full_body_parses_without_recovery(self):
        from defend_markets.shadow import parse_recovered_json

        payload, recovered = parse_recovered_json('[{"a": 1}, {"a": 2}]')
        assert payload == [{"a": 1}, {"a": 2}]
        assert recovered is False

    def test_truncated_body_recovers_complete_prefix(self):
        from defend_markets.shadow import parse_recovered_json

        body = '[{"a": 1}, {"a": 2}, {"a": 3'  # cut mid-object
        payload, recovered = parse_recovered_json(body)
        assert payload == [{"a": 1}, {"a": 2}]
        assert recovered is True

    def test_cut_mid_string_recovers(self):
        from defend_markets.shadow import parse_recovered_json

        body = '[{"name": "full"}, {"name": "partial'
        payload, recovered = parse_recovered_json(body)
        assert payload == [{"name": "full"}]
        assert recovered is True

    def test_garbage_body_returns_none(self):
        from defend_markets.shadow import parse_recovered_json

        payload, recovered = parse_recovered_json("{not json")
        assert payload is None
        assert recovered is True

    def test_truncated_fixtures_still_discover(self):
        from defend_markets.shadow import (
            forward_fixtures_from_oddspapi,
            parse_recovered_json,
        )

        full = _fixture_payload()
        body = "[" + ",".join(json.dumps(fx) for fx in full) + ", {'cut"
        payload, recovered = parse_recovered_json(body)
        assert recovered is True
        fixtures = forward_fixtures_from_oddspapi(payload)
        assert len(fixtures) == 2  # sportId 20 filtered
        assert fixtures[0].provider_event_id == "id1"

    def test_truncation_counted_in_metrics(self):
        client = FakeClient()
        client.fixture_payload = None
        calls = {"n": 0}

        class TruncClient:
            def fetch_fixtures(self, *, from_iso, to_iso):
                calls["n"] += 1
                return 200, _fixture_payload(), True

            def fetch_odds(self, provider_event_id):
                return 200, None, False

        engine = ShadowEngine(
            store=InMemoryShadowStore(),
            m5=FakeM5(),
            client=TruncClient(),
            now=lambda: NOW,
        )
        metrics = engine.discover(canonical_events={})
        assert metrics.truncated_responses == 1
        assert metrics.events_discovered >= 2
