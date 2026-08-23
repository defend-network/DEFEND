"""M4.7 circuit breaker, quota governor and market reference tests (P12-P15)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from defend_markets.quant.circuit_breaker import (
    STATE_CLOSED,
    STATE_HALF_OPEN,
    STATE_OPEN,
    STATE_OPEN_CONFIGURATION,
    ProviderCircuitBreaker,
)
from defend_markets.quant.market_reference import (
    MARKET_REFERENCE_POLICY_VERSION,
    market_baseline_metrics,
    select_reference_observation,
)
from defend_markets.quant.quota import CLASS_ODDS, CLASS_RESULT, RequestQuotaGovernor
from defend_markets.quant.store import InMemoryQuantStore

NOW = datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)


class TestCircuitBreaker:
    def test_starts_closed(self):
        store = InMemoryQuantStore()
        breaker = ProviderCircuitBreaker(store, now=NOW)
        state = breaker.state("odds_api_io", "result")
        assert state["state"] == STATE_CLOSED

    def test_opens_after_threshold(self):
        store = InMemoryQuantStore()
        breaker = ProviderCircuitBreaker(store, now=NOW)
        breaker.record_failure("odds_api_io", "result", error="500")
        breaker.record_failure("odds_api_io", "result", error="500")
        state = breaker.record_failure("odds_api_io", "result", error="500")
        assert state == STATE_OPEN
        assert breaker.allow_request("odds_api_io", "result") is False

    def test_halves_open_after_cooldown(self):
        store = InMemoryQuantStore()
        breaker = ProviderCircuitBreaker(store, now=NOW)
        breaker.record_failure("odds_api_io", "result", error="500")
        breaker.record_failure("odds_api_io", "result", error="500")
        breaker.record_failure("odds_api_io", "result", error="500")
        assert breaker.allow_request("odds_api_io", "result") is False
        breaker = ProviderCircuitBreaker(store, now=NOW + timedelta(minutes=10))
        assert breaker.allow_request("odds_api_io", "result") is True
        state = breaker.state("odds_api_io", "result")
        assert state["state"] in (STATE_HALF_OPEN,)

    def test_success_closes(self):
        store = InMemoryQuantStore()
        breaker = ProviderCircuitBreaker(store, now=NOW)
        breaker.record_failure("odds_api_io", "result", error="500")
        breaker.record_failure("odds_api_io", "result", error="500")
        breaker.record_success("odds_api_io", "result")
        assert breaker.state("odds_api_io", "result")["state"] == STATE_CLOSED

    def test_configuration_error_opens_configuration(self):
        store = InMemoryQuantStore()
        breaker = ProviderCircuitBreaker(store, now=NOW)
        state = breaker.record_failure("odds_api_io", "odds", error="401 unauthorized", configuration_error=True)
        assert state == STATE_OPEN_CONFIGURATION
        assert breaker.allow_request("odds_api_io", "odds") is False

    def test_result_failure_does_not_block_odds(self):
        """P14: result-endpoint failure must not stop odds ingestion."""
        store = InMemoryQuantStore()
        breaker = ProviderCircuitBreaker(store, now=NOW)
        breaker.record_failure("odds_api_io", "result", error="500")
        breaker.record_failure("odds_api_io", "result", error="500")
        breaker.record_failure("odds_api_io", "result", error="500")
        assert breaker.allow_request("odds_api_io", "result") is False
        assert breaker.allow_request("odds_api_io", "odds") is True


class TestQuotaGovernor:
    def test_reserved_floor_for_results(self):
        store = InMemoryQuantStore()
        governor = RequestQuotaGovernor(store, period=NOW)
        allowed, state = governor.check(CLASS_RESULT)
        assert allowed is True
        assert state["budget"] >= 15

    def test_consume_reduces_available(self):
        store = InMemoryQuantStore()
        governor = RequestQuotaGovernor(store, period=NOW)
        assert governor.consume(CLASS_ODDS) is True
        state = governor.snapshot()["classes"][CLASS_ODDS]
        assert state["used"] == 1

    def test_snapshot_lists_classes(self):
        store = InMemoryQuantStore()
        governor = RequestQuotaGovernor(store, period=NOW)
        snapshot = governor.snapshot()
        assert set(snapshot["classes"].keys()) == {"EVENT_DISCOVERY", "ODDS", "ATTESTATION", "RESULT", "HEALTH", "RECONCILIATION"}
        assert snapshot["policy_version"] == "REQUEST_QUOTA_GOVERNOR_V1"


class TestMarketReference:
    def _row(self, event, market, side, bookmaker, price, observed_at, observation_id):
        return {
            "canonical_event_id": event,
            "market": market,
            "side": side,
            "bookmaker": bookmaker,
            "price": price,
            "observed_at": observed_at,
            "observation_id": observation_id,
        }

    def test_selects_latest_pre_cutoff(self):
        commence = NOW + timedelta(hours=1)
        rows = [
            self._row("e1", "MATCH_WINNER", "A", "Bet365", 1.8, NOW - timedelta(minutes=30), 1),
            self._row("e1", "MATCH_WINNER", "A", "Bet365", 1.85, NOW - timedelta(minutes=10), 2),
            self._row("e1", "MATCH_WINNER", "A", "Bet365", 2.0, NOW + timedelta(minutes=59, seconds=30), 3),  # after cutoff
        ]
        selected = select_reference_observation(rows, commence_at=commence, now=NOW)
        assert selected["observation_id"] == 2
        assert selected["price"] == 1.85

    def test_never_selects_after_result(self):
        commence = NOW - timedelta(hours=2)  # already started
        rows = [self._row("e1", "MATCH_WINNER", "A", "Bet365", 1.8, NOW - timedelta(minutes=1), 1)]
        selected = select_reference_observation(rows, commence_at=commence, now=NOW)
        assert selected is None

    def test_bookmaker_filter(self):
        commence = NOW + timedelta(hours=1)
        rows = [
            self._row("e1", "MATCH_WINNER", "A", "Bet365", 1.8, NOW - timedelta(minutes=30), 1),
            self._row("e1", "MATCH_WINNER", "A", "BetMGM", 1.9, NOW - timedelta(minutes=5), 2),
        ]
        selected = select_reference_observation(rows, commence_at=commence, now=NOW, bookmaker="BetMGM")
        assert selected["observation_id"] == 2

    def test_persist_and_baseline(self):
        store = InMemoryQuantStore()
        commence = NOW + timedelta(hours=1)
        for side, price, obs_id in (("A", 1.8, 1), ("B", 2.0, 2)):
            row = self._row("e1", "MATCH_WINNER", side, "Bet365", price, NOW - timedelta(minutes=30), obs_id)
            selected = select_reference_observation([row], commence_at=commence, now=NOW)
            store.upsert_market_reference(selected)
        # Add a market reference with a different event too (not scored).
        baseline = market_baseline_metrics(
            store,
            model_scores=[
                {"canonical_event_id": "e1", "model_id": "M5_REGULARIZED_LOGISTIC", "probability_a": 0.6, "actual_outcome": 1.0},
                {"canonical_event_id": "e1", "model_id": "challenger-recent-form20", "probability_a": 0.55, "actual_outcome": 1.0},
            ],
        )
        assert baseline["policy_version"] == MARKET_REFERENCE_POLICY_VERSION
        assert baseline["reference_events"] == 1
        assert baseline["m5_vs_market"]["events"] == 1
        assert baseline["shadow_vs_market"]["events"] == 1
