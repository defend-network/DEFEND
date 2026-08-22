"""M4.6 forward evidence engine tests: official prediction identity, unique
event pairing, unpriced taxonomy, scoring, settlement catch-up."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from defend_markets.quant.forward_evidence import (
    classify_unpriced_event,
    register_official_predictions,
    score_prediction,
    select_official_prediction,
    settlement_catchup,
    unique_event_pairing,
)
from defend_markets.quant.store import InMemoryQuantStore

NOW = datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)


class TestOfficialPredictionSelection:
    def test_earliest_available_pre_commence(self):
        rows = [
            {"generated_at": NOW, "availability": "AVAILABLE", "p_a": 0.6},
            {"generated_at": NOW - timedelta(minutes=5), "availability": "AVAILABLE", "p_a": 0.55},
            {"generated_at": NOW + timedelta(minutes=5), "availability": "AVAILABLE", "p_a": 0.9},
        ]
        selected = select_official_prediction(rows, commence_at=NOW + timedelta(hours=1))
        assert selected["p_a"] == 0.55
        assert selected["generated_at"] == NOW - timedelta(minutes=5)

    def test_post_commence_rejected(self):
        rows = [{"generated_at": NOW, "availability": "AVAILABLE", "p_a": 0.6}]
        assert select_official_prediction(rows, commence_at=NOW - timedelta(minutes=1)) is None


class TestUniqueEventPairing:
    def test_distinct_events_no_inflation(self):
        store = InMemoryQuantStore()
        for event in ("e1", "e2", "e3"):
            store.upsert_official_prediction({
                "canonical_event_id": event, "model_id": "M5_REGULARIZED_LOGISTIC", "model_version": "v1",
                "prediction_id": f"m-{event}", "prediction_role": "M5_FORWARD",
                "generated_at": NOW, "commence_at": NOW, "probability_a": 0.6, "policy_version": 1,
            })
        for event in ("e1", "e2"):
            store.upsert_official_prediction({
                "canonical_event_id": event, "model_id": "challenger-recent-form20", "model_version": "v1",
                "prediction_id": f"s-{event}", "prediction_role": "SHADOW_FORWARD",
                "generated_at": NOW, "commence_at": NOW, "probability_a": 0.6, "policy_version": 1,
            })
        pairing = unique_event_pairing(store)
        assert pairing["m5_events"] == 3
        assert pairing["shadow_events"] == 2
        assert pairing["pair_complete_events"] == 2
        assert pairing["m5_only_events"] == 1
        assert pairing["pair_rate"] == pytest.approx(0.6667, abs=0.0001)

    def test_duplicate_official_prediction_fails_closed(self):
        store = InMemoryQuantStore()
        first = store.upsert_official_prediction({
            "canonical_event_id": "e1", "model_id": "M5_REGULARIZED_LOGISTIC", "model_version": "v1",
            "prediction_id": "m1", "prediction_role": "M5_FORWARD",
            "generated_at": NOW, "commence_at": NOW, "probability_a": 0.6, "policy_version": 1,
        })
        duplicate = store.upsert_official_prediction({
            "canonical_event_id": "e1", "model_id": "M5_REGULARIZED_LOGISTIC", "model_version": "v1",
            "prediction_id": "m2", "prediction_role": "M5_FORWARD",
            "generated_at": NOW, "commence_at": NOW, "probability_a": 0.9, "policy_version": 1,
        })
        assert first is True
        assert duplicate is False


class TestUnpricedTaxonomy:
    def test_market_not_posted_requires_evidence(self):
        assert classify_unpriced_event(filtered=True, priced=False, commenced_before_capture=False, identity_unresolved=False, provider_error=False, polled_in_time=True, market_evidence=True) == "MARKET_NOT_POSTED_YET"

    def test_no_evidence_defaults_to_unknown_unexplained(self):
        assert classify_unpriced_event(filtered=True, priced=False, commenced_before_capture=False, identity_unresolved=False, provider_error=False, polled_in_time=True, market_evidence=False) == "UNKNOWN_UNEXPLAINED"

    def test_mutually_exclusive_states(self):
        cases = [
            (dict(priced=False, commenced_before_capture=True), "POST_COMMENCE_FIRST_CAPTURE"),
            (dict(priced=False, identity_unresolved=True), "IDENTITY_UNRESOLVED"),
            (dict(priced=False, provider_error=True), "PROVIDER_ERROR"),
            (dict(priced=False, polled_in_time=False), "NOT_POLLED_IN_TIME"),
        ]
        for overrides, expected in cases:
            kwargs = dict(filtered=True, priced=False, commenced_before_capture=False, identity_unresolved=False, provider_error=False, polled_in_time=True, market_evidence=False)
            kwargs.update(overrides)
            assert classify_unpriced_event(**kwargs) == expected


class TestScoring:
    def test_brier_and_logloss(self):
        import math

        brier, logloss, clipped = score_prediction(probability_a=0.7, actual_outcome=1.0)
        assert brier == pytest.approx(0.09)
        assert logloss == pytest.approx(-math.log(0.7))
        assert clipped is None

    def test_clipping_versioned(self):
        brier, logloss, clipped = score_prediction(probability_a=0.0, actual_outcome=1.0)
        assert clipped is not None
        assert 0 < logloss < 50


class _FakeResultsDB:
    def __init__(self, results):
        self._results = results

    def connect(self):
        return _ResultsConn(self._results)


class _ResultsConn:
    def __init__(self, results):
        self._results = results
        self._sql = ""

    def cursor(self):
        return self

    def execute(self, sql, params=None):
        self._sql = sql

    def fetchall(self):
        if "FROM tt_match_results" in self._sql:
            return self._results
        return []

    def fetchone(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class TestSettlementCatchup:
    def _seed(self):
        store = InMemoryQuantStore()
        for event in ("e1", "e2", "e3"):
            store.upsert_official_prediction({
                "canonical_event_id": event, "model_id": "M5_REGULARIZED_LOGISTIC", "model_version": "v1",
                "prediction_id": f"m-{event}", "prediction_role": "M5_FORWARD",
                "generated_at": NOW - timedelta(hours=5), "commence_at": NOW - timedelta(hours=2),
                "probability_a": 0.6, "policy_version": 1,
            })
            store.upsert_official_prediction({
                "canonical_event_id": event, "model_id": "challenger-recent-form20", "model_version": "v1",
                "prediction_id": f"s-{event}", "prediction_role": "SHADOW_FORWARD",
                "generated_at": NOW - timedelta(hours=5), "commence_at": NOW - timedelta(hours=2),
                "probability_a": 0.55, "policy_version": 1,
            })
        return store

    def test_classifies_and_settles(self):
        store = self._seed()
        db = _FakeResultsDB([
            ("e1", "home-a", "away-b", 3, 1, NOW - timedelta(hours=1)),
            ("e3", "home-c", "away-d", None, None, NOW - timedelta(hours=1)),
        ])
        result = settlement_catchup(db, store)
        assert result["classified"].get("SETTLED") == 1
        assert result["classified"].get("RESULT_PROVIDER_EMPTY") == 1
        assert result["classified"].get("RESULT_NOT_AVAILABLE_YET") == 1
        assert result["settled"] == 1
        assert result["scores"] == 2  # M5 + shadow for the settled event
        scores = store.list_forward_scores()
        assert len(scores) == 2
        assert all(s["model_id"] in ("M5_REGULARIZED_LOGISTIC", "challenger-recent-form20") for s in scores)
        # rerun is idempotent
        result2 = settlement_catchup(db, store)
        assert result2["settled"] == 0
        assert result2["scores"] == 0

    def test_result_provider_empty_classified(self):
        store = self._seed()
        db = _FakeResultsDB([])
        result = settlement_catchup(db, store)
        assert result["classified"].get("RESULT_PROVIDER_EMPTY") == 3
        assert result["settled"] == 0
