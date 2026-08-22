"""M4.4 active improvement engine tests: weakness registry/detectors, evidence
levels, data-derived hypotheses, paper-model correction (immutable decision
evaluations + paper tickets), knowledge/repair boundaries."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from defend_markets.m5_live import FEATURE_NAMES
from defend_markets.quant.improve import ImprovementOrchestrator, collect_operational_snapshot
from defend_markets.quant.store import InMemoryQuantStore
from defend_markets.quant.weakness import WeaknessDetector, WeaknessRegistry, evidence_level, state_hash

REPO = Path(__file__).resolve().parents[1]
M5_ARTIFACT = REPO / "docs" / "operations" / "TT_M5_LIVE_WEIGHTS_V1.json"


def _snapshot(**overrides):
    base = {
        "prices": {"observations": 122, "unique_events_priced": 31},
        "events": {"discovered": 87, "matched": 87},
        "predictions": {"total": 122, "m5_available": 119, "shadow_available": 66},
        "coverage": {"eligible_events": 51, "priced_events": 21, "coverage_rate": 0.4118, "cohort_aligned": True},
        "pairing": {"eligible": 119, "complete": 66, "rate": 0.5546, "failure_reasons": {"m5_without_shadow": 53}},
        "bookmakers": {
            "Bet365": {"bookmaker_id": "Bet365", "selected": True, "attestation_state": "AVAILABLE"},
            "Betway": {"bookmaker_id": "Betway", "selected": True, "attestation_state": "ZERO_CURRENT_COVERAGE"},
        },
        "selected_bookmakers": ["Bet365", "Betway"],
        "pass_reasons": {"NO_PRICE": 120, "DISAGREEMENT_TOO_SMALL": 60},
    }
    base.update(overrides)
    return base


class TestWeaknessDetection:
    def test_low_price_coverage_detected(self):
        specs = WeaknessDetector().detect(_snapshot())
        assert any(spec["weakness_type"] == "PRICE_COVERAGE_LOW" for spec in specs)

    def test_dedup_by_stable_state_hash(self):
        store = InMemoryQuantStore()
        registry = WeaknessRegistry(store)
        snapshot = _snapshot()
        first = registry.record(snapshot)
        second = registry.record(snapshot)
        assert first and second
        assert store.weakness_counts()["total"] == len(snapshot_present_specs(snapshot))
        # second run updates evidence_count, does not duplicate
        weakness = store.list_weaknesses()[0]
        assert weakness["evidence_count"] >= 1

    def test_tiny_sample_is_early_signal(self):
        assert evidence_level(sample_size=10, effect_size=0.05) == "EARLY_SIGNAL"
        assert evidence_level(sample_size=200, effect_size=0.02, ci_low=0.01) == "STRONG"
        assert evidence_level(sample_size=50, effect_size=0.001) == "SUPPORTED"

    def test_pass_reason_spike_detected(self):
        snapshot = _snapshot(pass_reasons={"NO_PRICE": 180, "DISAGREEMENT_TOO_SMALL": 20})
        assert any(spec["weakness_type"] == "PASS_REASON_SPIKE" for spec in WeaknessDetector().detect(snapshot))

    def test_provider_coverage_detected_generically(self):
        specs = WeaknessDetector().detect(_snapshot())
        assert any(spec["weakness_type"] == "PROVIDER_COVERAGE" and "Betway" in spec["title"] for spec in specs)

    def test_no_bookmaker_hardcoding_in_detector(self):
        source = open("defend_markets/quant/weakness.py", encoding="utf-8").read()
        assert "hard_rock" not in source.casefold()

    def test_weakness_can_reopen(self):
        store = InMemoryQuantStore()
        registry = WeaknessRegistry(store)
        registry.record(_snapshot())
        weakness = store.list_weaknesses()[0]
        store.update_weakness_status(weakness["weakness_id"], status="RESOLVED")
        store.update_weakness_status(weakness["weakness_id"], status="REOPENED")
        assert store.list_weaknesses()[0]["status"] == "REOPENED"


def snapshot_present_specs(snapshot):
    return WeaknessDetector().detect(snapshot)


class TestImprovementOrchestrator:
    def _orchestrator(self):
        store = InMemoryQuantStore()
        return ImprovementOrchestrator(store, _FakeDatabase(), live_selected=["Bet365", "Betway"])

    def test_run_once_records_and_selects_action(self):
        store = InMemoryQuantStore()
        orchestrator = ImprovementOrchestrator(store, _FakeDatabase(), live_selected=["Bet365", "Betway"])
        result = orchestrator.run_once()
        assert result["recorded"]
        assert store.weakness_counts()["total"] >= 1
        assert store.list_improvement_actions()

    def test_actions_have_verification_metric(self):
        store = InMemoryQuantStore()
        ImprovementOrchestrator(store, _FakeDatabase(), live_selected=["Bet365", "Betway"]).run_once()
        action = store.list_improvement_actions()[0]
        assert action["verification_metric"]

    def test_actions_close_with_measured_outcome(self):
        store = InMemoryQuantStore()
        ImprovementOrchestrator(store, _FakeDatabase(), live_selected=["Bet365", "Betway"]).run_once()
        actions = store.list_improvement_actions()
        assert all(action["status"] == "COMPLETED" for action in actions)
        assert all(action["outcome"] in ("IMPROVED", "RESOLVED", "NO_CHANGE", "INCONCLUSIVE") for action in actions)

    def test_daily_learning_review(self):
        store = InMemoryQuantStore()
        review = ImprovementOrchestrator(store, _FakeDatabase(), live_selected=["Bet365", "Betway"]).daily_learning_review()
        assert review["current_champion"] == "M5_REGULARIZED_LOGISTIC"
        assert "top_5_weaknesses" in review
        assert "bookmaker_state" in review


class _FakeCursor:
    def __init__(self, db):
        self._db = db
        self._sql = ""

    def execute(self, sql, params=None):
        self._sql = sql

    def fetchone(self):
        s = self._sql
        if "min(generated_at)" in s:
            return (datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc),)
        if "count(distinct provider_event_id)" in s:
            return (31,)
        if "JOIN quant_shadow_predictions" in s:
            return (66,)
        if "FROM quant_shadow_predictions WHERE availability" in s:
            return (66,)
        if "tt_m5_live_predictions WHERE availability" in s:
            return (119,)
        if "FROM tt_m5_live_predictions" in s:
            return (122,)
        if "FROM tt_forward_events WHERE canonical_event_id IS NOT NULL" in s:
            return (87,)
        if "FROM tt_forward_events" in s:
            return (87,)
        if "FROM tt_market_observations" in s:
            return (122,)
        return (0,)

    def fetchall(self):
        if "GROUP BY reason" in self._sql:
            return [("NO_PRICE", 120), ("DISAGREEMENT_TOO_SMALL", 60)]
        return []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class _FakeConnection:
    def cursor(self):
        return _FakeCursor(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class _FakeDatabase:
    def connect(self):
        return _FakeConnection()


class TestPaperModelCorrection:
    def test_multiple_immutable_evaluations_per_event(self):
        store = InMemoryQuantStore()
        now = datetime.now(timezone.utc)
        store.insert_decision_evaluation({
            "canonical_event_id": "oaio:1", "model_id": "M5_REGULARIZED_LOGISTIC",
            "model_version": "v1", "strategy": "PAPER_MAIN_V1", "decision": "PASS",
            "reason": "NO_PRICE", "decision_ts": now,
        })
        store.insert_decision_evaluation({
            "canonical_event_id": "oaio:1", "model_id": "M5_REGULARIZED_LOGISTIC",
            "model_version": "v1", "strategy": "PAPER_MAIN_V1", "decision": "PAPER_DECISION",
            "reason": "MODEL_EDGE_GE_THRESHOLD", "decision_ts": now,
        })
        assert store.decision_evaluation_counts()["total"] == 2
        assert store.decision_evaluation_counts()["by_decision"]["PAPER_DECISION"] == 1

    def test_main_and_research_strategies_separate(self):
        store = InMemoryQuantStore()
        now = datetime.now(timezone.utc)
        store.insert_decision_evaluation({
            "canonical_event_id": "oaio:1", "model_id": "M5_REGULARIZED_LOGISTIC",
            "model_version": "v1", "strategy": "PAPER_MAIN_V1", "decision": "PAPER_DECISION",
            "reason": "x", "decision_ts": now,
        })
        store.insert_decision_evaluation({
            "canonical_event_id": "oaio:1", "model_id": "challenger-recent-form20",
            "model_version": "v1", "strategy": "PAPER_RESEARCH_V1", "decision": "PASS",
            "reason": "DISAGREEMENT_TOO_SMALL", "decision_ts": now,
        })
        rows = store.list_decision_evaluations()
        assert {row["strategy"] for row in rows} == {"PAPER_MAIN_V1", "PAPER_RESEARCH_V1"}
        assert {row["model_id"] for row in rows} == {"M5_REGULARIZED_LOGISTIC", "challenger-recent-form20"}

    def test_committed_paper_ticket_immutable(self):
        store = InMemoryQuantStore()
        now = datetime.now(timezone.utc)
        created = store.commit_paper_ticket({
            "canonical_event_id": "oaio:1", "strategy": "PAPER_MAIN_V1",
            "model_id": "M5_REGULARIZED_LOGISTIC", "model_version": "v1",
            "side": "home", "price": 1.80, "decision_ts": now,
        })
        duplicate = store.commit_paper_ticket({
            "canonical_event_id": "oaio:1", "strategy": "PAPER_MAIN_V1",
            "model_id": "M5_REGULARIZED_LOGISTIC", "model_version": "v1",
            "side": "away", "price": 99.0, "decision_ts": now,
        })
        assert created is True
        assert duplicate is False
        ticket = store.list_paper_tickets()[0]
        assert ticket["price"] == 1.80


class TestRepairAndKnowledge:
    def test_repair_packet_never_auto_merges(self):
        store = InMemoryQuantStore()
        packet_id = store.create_repair_packet({
            "symptom": "price URL space not encoded",
            "suspected_boundary": "fetch_odds url construction",
            "status": "PENDING",
        })
        packets = store.list_repair_packets()
        assert packets[0]["packet_id"] == packet_id
        assert packets[0]["status"] == "PENDING"

    def test_knowledge_finding_point_in_time_safe(self):
        store = InMemoryQuantStore()
        finding_id = store.add_knowledge_finding({
            "claim": "Bet365 provides TT prices on three circuits",
            "source": "live provider attestation",
            "source_type": "provider",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "point_in_time_safe": True,
            "approved_for_feature_use": False,
        })
        findings = store.list_knowledge_findings()
        assert findings[0]["finding_id"] == finding_id
        assert findings[0]["point_in_time_safe"] is True
        assert findings[0]["approved_for_feature_use"] is False


def test_m5_artifact_hash_unchanged():
    blob = M5_ARTIFACT.read_bytes()
    assert hashlib.sha256(blob).hexdigest() == "fe6f18d1fb5eea640fc42d904d9010470ee75f73e594b2c00a86982d3381e229"


class TestMarketHypothesisUnblock:
    def test_market_hypothesis_available_once_prices_exist(self):
        from defend_markets.quant.prioritization import ResearchPrioritizer, seed_hypotheses

        store = InMemoryQuantStore()
        hypotheses = seed_hypotheses(store, market_prices_available=True)
        market = next(h for h in hypotheses if "Market-aware" in h["title"])
        assert market["blocked_reason"] is None
        assert market["status"] != "BLOCKED"
