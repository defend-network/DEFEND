"""M3 intelligence layer tests: monitoring, weaknesses, hypotheses, proposals,
reviews, expensive-approval routing, and no-bypass guarantees. Deterministic
fixtures only; no network and no LLM."""

from __future__ import annotations

import pytest

from defend_markets.quant.config import MarketsRuntimeState, QuantDirectorSettings
from defend_markets.quant.intelligence import QuantIntelligence, collect_monitor_data
from defend_markets.quant.orchestrator import MarketsIntelligenceOrchestrator
from defend_markets.quant.model_aliases import SOL_ALIAS, resolve_runtime_profile
from defend_markets.quant.store import InMemoryQuantStore
from defend_markets.quant.tools import InMemoryMarketTools

OUTCOMES = [
    {"p": 0.90, "actual": 1.0},
    {"p": 0.85, "actual": 1.0},
    {"p": 0.60, "actual": 0.0},
    {"p": 0.55, "actual": 1.0},
    {"p": 0.30, "actual": 0.0},
    {"p": 0.20, "actual": 0.0},
]


def _orchestrator(*, state="STOPPED", outcomes=None, unmatched=0, prices=0):
    store = InMemoryQuantStore()
    tools = InMemoryMarketTools(
        store,
        events_discovered=85,
        events_matched=85 - unmatched,
        available_predictions=50,
        price_observations=prices,
        prediction_outcomes=list(OUTCOMES if outcomes is None else outcomes),
        confidence_distribution={"available": 50, "low_confidence_under_0.55": 30},
    )
    settings = QuantDirectorSettings(runtime_state=state)
    return MarketsIntelligenceOrchestrator(store=store, tools=tools, settings=settings)


class TestMonitoring:
    def test_monitor_reports_metrics_and_calibration(self):
        orchestrator = _orchestrator()
        monitor = orchestrator.monitor_m5()
        assert monitor["evaluation_rows"] == len(OUTCOMES)
        assert monitor["brier"] is not None
        assert monitor["ece"] is not None
        assert isinstance(monitor["calibration"], list)

    def test_no_outcomes_reports_absent_not_zero(self):
        orchestrator = _orchestrator(outcomes=[])
        monitor = orchestrator.monitor_m5()
        assert monitor["evaluation_rows"] == 0
        assert monitor["brier"] is None
        assert monitor["log_loss"] is None


class TestWeaknesses:
    def test_weakness_findings_are_structured(self):
        orchestrator = _orchestrator(unmatched=3)
        findings = orchestrator.analyze_weaknesses()
        assert findings
        first = findings[0]
        assert {"id", "category", "severity", "description", "supporting_data", "recommendation"} <= set(first)
        assert any("identity" in finding["category"] for finding in findings)


class TestHypotheses:
    def test_generates_top_ten_structured_hypotheses(self):
        orchestrator = _orchestrator()
        hypotheses = orchestrator.generate_hypotheses(limit=10)
        assert len(hypotheses) == 10
        required = {"title", "reason", "supporting_data", "expected_effect", "risk", "required_features", "evaluation_plan"}
        assert all(required <= set(hypothesis) for hypothesis in hypotheses)
        assert any("rejected" in hypothesis["evaluation_plan"] for hypothesis in hypotheses)


class TestProposals:
    def test_create_proposal_persists_as_proposed(self):
        orchestrator = _orchestrator()
        entry_id = orchestrator.create_proposal(
            title="Test player fatigue feature",
            reason="same-day density may matter",
            required_features=["same_day_games"],
            evaluation_plan="challenger = M5 + same_day_games; walk-forward only",
        )
        proposals = orchestrator.list_proposals()
        assert any(proposal["entry_id"] == entry_id and proposal["status"] == "PROPOSED" for proposal in proposals)


class TestReviews:
    def test_stopped_state_makes_no_review(self):
        orchestrator = _orchestrator(state=MarketsRuntimeState.STOPPED.value)
        assert orchestrator.run_daily_review()["ran"] is False
        assert orchestrator.run_weekly_review()["ran"] is False
        assert orchestrator.list_reviews() == []

    def test_daily_review_runs_and_persists_when_ready(self):
        orchestrator = _orchestrator(state=MarketsRuntimeState.READY.value)
        result = orchestrator.run_daily_review()
        assert result["ran"] is True
        assert result["report"]["model_health"]["evaluation_rows"] == len(OUTCOMES)
        assert orchestrator.list_reviews()

    def test_weekly_review_produces_research_report(self):
        orchestrator = _orchestrator(state=MarketsRuntimeState.READY.value)
        result = orchestrator.run_weekly_review()
        report = result["report"]
        assert {"model_health", "recent_mistakes", "possible_improvements", "new_experiments_proposed", "features_worth_testing", "rejected_ideas"} <= set(report)
        assert result["ran"] is True

    def test_budget_hard_limit_blocks_review(self):
        store = InMemoryQuantStore()
        tools = InMemoryMarketTools(store, prediction_outcomes=list(OUTCOMES))
        settings = QuantDirectorSettings(runtime_state="READY", max_daily_calls=1)
        orchestrator = MarketsIntelligenceOrchestrator(store=store, tools=tools, settings=settings)
        assert orchestrator.run_daily_review()["ran"] is True
        assert orchestrator.run_daily_review()["ran"] is False


class TestExpensiveApproval:
    def test_sol_requires_owner_approval(self):
        orchestrator = _orchestrator(state=MarketsRuntimeState.READY.value)
        profile = resolve_runtime_profile(SOL_ALIAS)
        assert profile.requires_approval is True
        with pytest.raises(RuntimeError, match="owner approval required"):
            orchestrator.chat(thread_id=None, message="deep analysis", sol=True)
        orchestrator.approve_expensive()
        result = orchestrator.chat(thread_id=None, message="deep analysis", sol=True)
        assert result["profile"]["model"] == "gpt-5.6-sol"


class TestNoBypass:
    def test_no_promotion_or_wagering_tools(self):
        orchestrator = _orchestrator()
        assert not hasattr(orchestrator, "promote")
        assert not hasattr(orchestrator, "place_bet")
        assert orchestrator.advance_stage(model_id="c", model_version="v", to_stage="REAL_MONEY")["allowed"] is False
