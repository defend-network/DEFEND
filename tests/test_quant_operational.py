"""M4 operational supervisor tests: champion seed, scheduler lease, triggers,
evaluation, prioritization, credential isolation, routing, budgets."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from defend_markets.quant.budget import estimate_call_cost
from defend_markets.quant.champion import ChampionConflictError, ensure_champion
from defend_markets.quant.evaluation import EvaluationService, PredictionOutcome
from defend_markets.quant.market import is_valid_close, market_metrics_status
from defend_markets.quant.orchestrator import MarketsIntelligenceOrchestrator
from defend_markets.quant.model_aliases import is_configured, runtime_credentials_present
from defend_markets.quant.prioritization import ResearchPrioritizer, seed_hypotheses
from defend_markets.quant.routing import should_escalate_to_pro
from defend_markets.quant.scheduler import Scheduler, SchedulerJob
from defend_markets.quant.store import InMemoryQuantStore
from defend_markets.quant.tools import InMemoryMarketTools
from defend_markets.quant.triggers import TriggerLedger

REPO = Path(__file__).resolve().parents[1]
M5_ARTIFACT = REPO / "docs" / "operations" / "TT_M5_LIVE_WEIGHTS_V1.json"
M5_WEIGHTS = json.loads(M5_ARTIFACT.read_text(encoding="utf-8"))
M5_FILE_HASH = hashlib.sha256(M5_ARTIFACT.read_bytes()).hexdigest()


def _store():
    return InMemoryQuantStore()


def _orchestrator(*, state="STOPPED", prices=0):
    store = _store()
    tools = InMemoryMarketTools(
        store,
        events_discovered=85,
        events_matched=85,
        available_predictions=50,
        price_observations=prices,
    )
    from defend_markets.quant.config import QuantDirectorSettings

    return MarketsIntelligenceOrchestrator(
        store=store, tools=tools, settings=QuantDirectorSettings(runtime_state=state)
    )


class TestChampionSeed:
    def test_seed_inserts_once(self):
        store = _store()
        result = ensure_champion(
            store, weights_doc=M5_WEIGHTS, artifact_path="docs/operations/TT_M5_LIVE_WEIGHTS_V1.json",
            artifact_sha256=M5_FILE_HASH,
        )
        assert result["status"] == "INSERTED"
        assert len(store.list_champions()) == 1

    def test_identical_seed_is_noop(self):
        store = _store()
        ensure_champion(store, weights_doc=M5_WEIGHTS, artifact_path="x", artifact_sha256=M5_FILE_HASH)
        result = ensure_champion(store, weights_doc=M5_WEIGHTS, artifact_path="x", artifact_sha256=M5_FILE_HASH)
        assert result["status"] == "NOOP"
        assert len(store.list_champions()) == 1

    def test_conflicting_hash_fails_closed(self):
        store = _store()
        ensure_champion(store, weights_doc=M5_WEIGHTS, artifact_path="x", artifact_sha256=M5_FILE_HASH)
        with pytest.raises(ChampionConflictError):
            ensure_champion(store, weights_doc=M5_WEIGHTS, artifact_path="x", artifact_sha256="0" * 64)

    def test_multiple_champions_fail_closed(self):
        store = _store()
        store.register_champion(model_id="a", model_version="a:1", artifact_path="x", artifact_sha256="aa", fit_n=1, cutoff="x", feature_schema_version=1)
        store.register_champion(model_id="b", model_version="b:1", artifact_path="x", artifact_sha256="bb", fit_n=1, cutoff="x", feature_schema_version=1)
        with pytest.raises(ChampionConflictError):
            ensure_champion(store, weights_doc=M5_WEIGHTS, artifact_path="x", artifact_sha256=M5_FILE_HASH)


class TestSchedulerLease:
    def test_lease_prevents_duplicate_leader_execution(self):
        store = _store()
        scheduler_a = Scheduler(store, owner="process-a")
        scheduler_b = Scheduler(store, owner="process-b")
        scheduler_a.register(SchedulerJob("DAILY_LIGHT_REVIEW", 86400))
        claimed_a = scheduler_a.claim("DAILY_LIGHT_REVIEW")
        claimed_b = scheduler_b.claim("DAILY_LIGHT_REVIEW")
        assert claimed_a is not None
        assert claimed_b is None

    def test_expired_lease_recoverable(self):
        store = _store()
        scheduler_a = Scheduler(store, owner="a")
        scheduler_b = Scheduler(store, owner="b", lease_seconds=120)
        scheduler_a.register(SchedulerJob("WEEKLY_RESEARCH_REVIEW", 604800))
        scheduler_a.claim("WEEKLY_RESEARCH_REVIEW")
        job = store.job("WEEKLY_RESEARCH_REVIEW")
        job["lease_expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        claimed = scheduler_b.claim("WEEKLY_RESEARCH_REVIEW")
        assert claimed is not None

    def test_completed_job_reschedules_forward_no_catchup_storm(self):
        store = _store()
        scheduler = Scheduler(store, owner="a")
        scheduler.register(SchedulerJob("DAILY_LIGHT_REVIEW", 86400))
        first = scheduler.claim("DAILY_LIGHT_REVIEW")
        assert first is not None
        scheduler.complete("DAILY_LIGHT_REVIEW", summary="ok")
        second = scheduler.claim("DAILY_LIGHT_REVIEW")
        assert second is None

    def test_stopped_product_zero_scheduled_ai(self):
        orchestrator = _orchestrator(state="STOPPED")
        assert orchestrator.run_scheduled_review()["ran"] is False


class TestTriggers:
    def test_same_state_hash_debounces_and_counts_suppression(self):
        store = _store()
        ledger = TriggerLedger(store)
        first = ledger.record("NEW_PREDICTION_BATCH", {"count": 5}, invoke=True)
        assert first["first_seen"] is True
        assert first["invoked"] is True
        second = ledger.record("NEW_PREDICTION_BATCH", {"count": 5}, invoke=False)
        assert second["first_seen"] is False
        triggers = store.list_triggers()
        assert triggers[0]["suppressed_count"] == 1

    def test_changed_state_hash_triggers_again(self):
        store = _store()
        ledger = TriggerLedger(store)
        ledger.record("NEW_PREDICTION_BATCH", {"count": 5}, invoke=True)
        second = ledger.record("NEW_PREDICTION_BATCH", {"count": 6}, invoke=True)
        assert second["first_seen"] is True


class TestEvaluation:
    def _outcome(self, prediction_id="p1", actual=1.0, outcome_version="2026-08-21T00:00:00Z"):
        return PredictionOutcome(
            prediction_id=prediction_id,
            event_id="oaio:1",
            model_id="M5_REGULARIZED_LOGISTIC",
            model_version="M5_REGULARIZED_LOGISTIC:54affc960a34",
            prediction_ts="2026-08-20T00:00:00Z",
            predicted_probability=0.70,
            actual=actual,
            outcome_version=outcome_version,
        )

    class _Source:
        def __init__(self, outcomes):
            self.outcomes = outcomes

        def settled_predictions(self):
            return self.outcomes

    def test_settled_prediction_creates_one_evaluation_and_error(self):
        store = _store()
        service = EvaluationService(store, outcome_source=self._Source([self._outcome()]))
        result = service.settle()
        assert result["inserted"] == 1
        assert store.evaluation_counts()["active"] == 1
        assert len(store.list_prediction_errors()) == 1
        error = store.list_prediction_errors()[0]
        assert error["abs_probability_error"] == pytest.approx(0.3)

    def test_rerun_settlement_no_duplicate(self):
        store = _store()
        service = EvaluationService(store, outcome_source=self._Source([self._outcome()]))
        service.settle()
        service.settle()
        assert store.evaluation_counts()["active"] == 1
        assert len(store.list_prediction_errors()) == 1

    def test_corrected_result_supersedes(self):
        store = _store()
        service = EvaluationService(store, outcome_source=self._Source([self._outcome(actual=1.0)]))
        service.settle()
        service = EvaluationService(
            store, outcome_source=self._Source([self._outcome(actual=0.0, outcome_version="2026-08-21T00:00:00Z-corrected")])
        )
        result = service.settle()
        assert result["corrected"] == 1
        counts = store.evaluation_counts()
        assert counts["active"] == 1
        assert counts["superseded"] == 1
        assert len(store.corrections) == 1

    def test_metrics_recalculate(self):
        store = _store()
        service = EvaluationService(store, outcome_source=self._Source([self._outcome()]))
        service.settle()
        metrics = service.compute_metrics()
        assert metrics["evaluation_rows"] == 1
        assert metrics["brier"] == pytest.approx(0.09)
        assert metrics["drift_state"] == "INSUFFICIENT_EVIDENCE"

    def test_evaluation_zero_state(self):
        store = _store()
        service = EvaluationService(store, outcome_source=self._Source([]))
        state = service.evaluation_state()
        assert state["state"] == "PREDICTIONS_UNSETTLED"
        assert state["evaluation_rows"] == 0


class TestPrioritization:
    def test_market_dependent_blocked_while_prices_absent(self):
        store = _store()
        hypotheses = seed_hypotheses(store, market_prices_available=False)
        market = next(h for h in hypotheses if "Market-aware" in h["title"])
        assert market["blocked_reason"] is not None

    def test_rejected_hypothesis_not_selected(self):
        store = _store()
        hypotheses = seed_hypotheses(store, market_prices_available=False)
        rejected = next(h for h in hypotheses if "elo_diff squared" in h["title"])
        assert rejected["status"] == "REJECTED"
        selection = ResearchPrioritizer(market_prices_available=False).select_next(hypotheses)
        assert selection["selected"] is True
        assert "elo_diff squared" not in selection["title"]

    def test_prioritizer_selects_usable_data_hypothesis(self):
        store = _store()
        hypotheses = seed_hypotheses(store, market_prices_available=False)
        selection = ResearchPrioritizer(market_prices_available=False).select_next(hypotheses)
        assert selection["selected"] is True
        assert selection["priority_score"] > 0


class TestCredentialIsolation:
    def test_deepseek_key_never_openai(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "dsk-dummy")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("MARKETS_AI_API_KEY", raising=False)
        assert is_configured("deepseek") is True
        assert is_configured("openai") is False

    def test_openai_key_never_deepseek(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-dummy")
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("MARKETS_AI_API_KEY", raising=False)
        assert is_configured("openai") is True
        assert is_configured("deepseek") is False

    def test_both_and_neither(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "dsk")
        monkeypatch.setenv("OPENAI_API_KEY", "sk")
        monkeypatch.delenv("MARKETS_AI_API_KEY", raising=False)
        assert is_configured("deepseek") is True
        assert is_configured("openai") is True
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert runtime_credentials_present() is False


class TestRoutingAndMarket:
    def test_429_does_not_escalate_to_pro(self):
        decision = should_escalate_to_pro(transport_kind="rate_limited", quality_claims_unsupported=True, attempt=1)
        assert decision["escalate"] is False

    def test_5xx_does_not_escalate(self):
        decision = should_escalate_to_pro(transport_kind="server_error", quality_claims_unsupported=True, attempt=1)
        assert decision["escalate"] is False

    def test_timeout_does_not_escalate(self):
        decision = should_escalate_to_pro(transport_kind="timeout", quality_claims_unsupported=True, attempt=1)
        assert decision["escalate"] is False

    def test_quality_failure_may_escalate_once(self):
        decision = should_escalate_to_pro(transport_kind=None, quality_claims_unsupported=True, attempt=1)
        assert decision["escalate"] is True
        second = should_escalate_to_pro(transport_kind=None, quality_claims_unsupported=True, attempt=2)
        assert second["escalate"] is False

    def test_market_metrics_not_available_not_zero(self):
        assert market_metrics_status(0) == "NOT_AVAILABLE"
        assert market_metrics_status(5) == "AVAILABLE"

    def test_post_commence_not_valid_close(self):
        assert is_valid_close("2026-08-21T00:00:00Z", "2026-08-21T01:00:00Z") is True
        assert is_valid_close("2026-08-21T02:00:00Z", "2026-08-21T01:00:00Z") is False


class TestBudgets:
    def test_cost_estimation_from_rate_card(self):
        cost = estimate_call_cost(provider="deepseek", model="deepseek-v4-flash", input_tokens=1_000_000, output_tokens=1_000_000)
        assert cost == pytest.approx(0.27 + 1.10, abs=1e-6)


class TestStageAuthority:
    def test_paper_is_max_autonomous_stage(self):
        orchestrator = _orchestrator()
        assert orchestrator.advance_stage(model_id="c", model_version="v", to_stage="PAPER")["allowed"] is True
        assert orchestrator.advance_stage(model_id="c", model_version="v", to_stage="REAL_MONEY")["allowed"] is False

    def test_advancing_challenger_does_not_change_champion(self):
        orchestrator = _orchestrator()
        orchestrator._store.register_champion(model_id="M5_REGULARIZED_LOGISTIC", model_version="M5_REGULARIZED_LOGISTIC:54affc960a34", artifact_path="x", artifact_sha256="fe6f", fit_n=1, cutoff="x", feature_schema_version=1)
        orchestrator.advance_stage(model_id="challenger-x", model_version="v1", to_stage="PAPER")
        champions = orchestrator._store.list_champions()
        assert len(champions) == 1
        assert champions[0]["model_id"] == "M5_REGULARIZED_LOGISTIC"


def test_m5_artifact_hash_unchanged():
    assert M5_FILE_HASH == "fe6f18d1fb5eea640fc42d904d9010470ee75f73e594b2c00a86982d3381e229"
