"""Quant Research Lab + health tests: snapshots, metrics, walk-forward,
calibration, ablation, promotion gates, market metrics, and failure
visibility. Deterministic fixtures only; no network and no LLM."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from defend_markets.quant.config import QuantDirectorSettings
from defend_markets.quant.health import QuantDirectorHealthState, detect_health
from defend_markets.quant.orchestrator import MarketsIntelligenceOrchestrator
from defend_markets.quant.research.experiment import (
    ExperimentRunner,
    build_spec,
)
from defend_markets.quant.research.features import (
    M5_FEATURE_NAMES,
    apply_challenger_features,
    challenger_feature_definitions,
    m5_feature_registry,
)
from defend_markets.quant.research.metrics import (
    brier_score,
    calibration_buckets,
    ece_score,
    log_loss_score,
    metrics_report,
)
from defend_markets.quant.research.models import fit_ridge_logistic, predict_ridge_logistic
from defend_markets.quant.research.promotion import PromotionGateSet
from defend_markets.quant.research.snapshot import build_snapshot
from defend_markets.quant.research.walkforward import (
    WalkForwardEngine,
    walk_forward_blocks,
)
from defend_markets.quant.store import InMemoryQuantStore
from defend_markets.quant.tools import InMemoryMarketTools

REPO = Path(__file__).resolve().parents[1]
M5_ARTIFACT = REPO / "docs" / "operations" / "TT_M5_LIVE_WEIGHTS_V1.json"


def _rows(n=600):
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    rows = []
    for index in range(n):
        home = f"p{index % 8}"
        away = f"p{(index + 1 + (index // 8) % 2) % 8}"
        if home == away:
            away = f"p{(index + 3) % 8}"
        rows.append(
            {
                "event_key": f"e{index}",
                "home_key": home,
                "away_key": away,
                "ts": (base + timedelta(hours=6 * index)).isoformat(),
                "actual": 1.0 if (index % 3) != 0 else 0.0,
            }
        )
    return rows


class TestSnapshot:
    def test_immutable_and_deterministic_hash(self):
        rows = _rows()
        snapshot_a = build_snapshot(rows, cutoff="2026-08-01T00:00:00Z", target_definition="t")
        snapshot_b = build_snapshot(rows, cutoff="2026-08-01T00:00:00Z", target_definition="t")
        assert snapshot_a.snapshot_id == snapshot_b.snapshot_id
        assert snapshot_a.content_hash == snapshot_b.content_hash
        with pytest.raises(Exception):
            snapshot_a.rows = ()

    def test_future_row_leakage_rejected(self):
        rows = _rows()
        future = {
            "event_key": "future",
            "home_key": "px",
            "away_key": "py",
            "ts": "2026-08-20T00:00:00Z",
            "actual": 1.0,
        }
        snapshot = build_snapshot(
            rows + [future], cutoff="2026-08-10T00:00:00Z", target_definition="t"
        )
        assert snapshot.leakage_checks["accepted_rows_after_cutoff"] == 0
        assert snapshot.leakage_checks["excluded_rows_after_cutoff"] == 1
        assert all(
            datetime.fromisoformat(row["ts"].replace("Z", "+00:00")) < datetime(2026, 8, 10, tzinfo=timezone.utc)
            for row in snapshot.rows
        )


class TestFeatureRegistry:
    def test_m5_features_active(self):
        registry = m5_feature_registry()
        active = {feature.feature_id for feature in registry.active()}
        assert active == set(M5_FEATURE_NAMES)

    def test_challenger_feature_candidate_status(self):
        definitions = challenger_feature_definitions()
        assert any(
            definition.feature_id == "recent_form20_winrate_diff" and definition.status == "CANDIDATE"
            for definition in definitions
        )
        assert any(
            definition.feature_id == "elo_diff_sq" and definition.status == "REJECTED"
            for definition in definitions
        )

    def test_duplicate_feature_version_rejected(self):
        registry = m5_feature_registry()
        with pytest.raises(ValueError):
            registry.register(m5_feature_registry().get("elo_diff", version=1))


class TestMetrics:
    def test_brier(self):
        assert brier_score([1.0, 0.0], [1.0, 0.0]) == pytest.approx(0.0)
        assert brier_score([1.0, 0.0], [0.5, 0.5]) == pytest.approx(0.25)

    def test_log_loss(self):
        assert log_loss_score([1.0], [0.9]) == pytest.approx(-math.log(0.9), rel=1e-6)
        assert log_loss_score([1.0, 0.0], [0.9, 0.9]) > 0.0

    def test_calibration_buckets(self):
        buckets = calibration_buckets([1.0] * 10 + [0.0] * 10, [0.9] * 10 + [0.1] * 10, bins=2)
        assert len(buckets) == 2
        assert all(bucket["count"] == 10.0 for bucket in buckets)
        ece = ece_score([1.0] * 10 + [0.0] * 10, [0.9] * 10 + [0.1] * 10, bins=2)
        assert ece == pytest.approx(0.1)

    def test_metrics_report_known_values(self):
        report = metrics_report([1.0, 0.0], [1.0, 0.0])
        assert report["brier"] == 0.0
        assert report["n"] == 2


class TestWalkForward:
    def test_blocks_chronological(self):
        blocks = walk_forward_blocks(list(range(200)), n_windows=4)
        assert blocks
        for train_end, val_start, val_end in blocks:
            assert val_start >= train_end
            assert val_end > val_start

    def test_engine_folds_aggregate(self):
        rows = _rows()
        x, y = [], []
        for index, row in enumerate(rows):
            x.append([float(index % 7), float((index // 7) % 5)])
            y.append(row["actual"])
        timestamps = [datetime.fromisoformat(row["ts"].replace("Z", "+00:00")) for row in rows]
        import numpy as np

        engine = WalkForwardEngine(model_fit=fit_ridge_logistic, model_predict=predict_ridge_logistic)
        folds = engine.run(x=np.asarray(x, dtype=float), y=np.asarray(y, dtype=float), timestamps=timestamps, n_windows=4)
        assert len(folds) >= 2
        for fold in folds:
            assert fold.val_rows > 0


class TestExperiment:
    def _snapshot(self):
        return build_snapshot(
            _rows(),
            cutoff="2026-08-01T00:00:00Z",
            target_definition="fixture",
            feature_schema_version=1,
        )

    def test_experiment_references_exact_snapshot(self):
        snapshot = self._snapshot()
        spec = build_spec(
            experiment_id="exp-1",
            hypothesis_id="hyp-1",
            snapshot=snapshot,
            champion_version="M5_REGULARIZED_LOGISTIC:abc",
            challenger_name="c1",
            feature_set=list(M5_FEATURE_NAMES) + ["elo_diff_sq"],
        )
        assert spec.dataset_snapshot_id == snapshot.snapshot_id

    def test_runner_produces_deterministic_result_and_ablation(self):
        snapshot = self._snapshot()
        spec = build_spec(
            experiment_id="exp-2",
            hypothesis_id="hyp-2",
            snapshot=snapshot,
            champion_version="M5_REGULARIZED_LOGISTIC:abc",
            challenger_name="c2",
            feature_set=list(M5_FEATURE_NAMES) + ["elo_diff_sq"],
        )
        runner = ExperimentRunner(snapshot=snapshot, n_windows=3)
        result = runner.run(spec)
        assert result.rows_used == snapshot.row_count
        assert result.challenger_metrics["n_windows"] >= 1
        assert "lift" in result.ablation
        assert isinstance(result.ablation["lift"], (int, float, type(None)))


class TestPromotion:
    def _gates(self):
        return PromotionGateSet(min_sample=100, brier_tolerance=0.01, logloss_tolerance=0.02, calibration_tolerance=0.05)

    def test_leakage_gate_blocks_promotion(self):
        verdict = self._gates().evaluate(
            leakage_detected=True,
            sample_n=200,
            challenger_brier=0.2,
            challenger_log_loss=0.6,
            challenger_ece=0.02,
            challenger_brier_std=0.01,
            ablation_kept=True,
        )
        assert verdict["promotion"] == "PROMOTION_BLOCKED"
        assert any("leakage" in reason for reason in verdict["blockers"])

    def test_bad_brier_blocks_promotion(self):
        verdict = self._gates().evaluate(
            leakage_detected=False,
            sample_n=200,
            challenger_brier=0.30,
            challenger_log_loss=0.6,
            challenger_ece=0.02,
            challenger_brier_std=0.01,
            ablation_kept=True,
            champion_brier=0.24,
        )
        assert verdict["promotion"] == "PROMOTION_BLOCKED"

    def test_calibration_regression_blocks_promotion(self):
        verdict = self._gates().evaluate(
            leakage_detected=False,
            sample_n=200,
            challenger_brier=0.22,
            challenger_log_loss=0.6,
            challenger_ece=0.20,
            challenger_brier_std=0.01,
            ablation_kept=True,
            champion_brier=0.24,
        )
        assert verdict["promotion"] == "PROMOTION_BLOCKED"

    def test_qualifying_fixture_advances(self):
        verdict = self._gates().evaluate(
            leakage_detected=False,
            sample_n=200,
            challenger_brier=0.22,
            challenger_log_loss=0.60,
            challenger_ece=0.02,
            challenger_brier_std=0.005,
            ablation_kept=True,
            champion_brier=0.24,
            champion_log_loss=0.67,
        )
        assert verdict["promotion"] == "PROMOTION_ALLOWED"

    def test_market_metrics_not_available_not_zero(self):
        verdict = self._gates().evaluate(
            leakage_detected=False,
            sample_n=200,
            challenger_brier=0.22,
            challenger_log_loss=0.6,
            challenger_ece=0.02,
            challenger_brier_std=0.01,
            ablation_kept=True,
            market_metrics_available=False,
        )
        market = next(gate for gate in verdict["gates"] if gate["gate"] == "MARKET_METRIC")
        assert market["status"] == "NOT_AVAILABLE"
        assert verdict["market_metrics"] == "NOT_AVAILABLE"


class TestStageAuthority:
    def _orchestrator(self):
        store = InMemoryQuantStore()
        tools = InMemoryMarketTools(store)
        return MarketsIntelligenceOrchestrator(store=store, tools=tools)

    def test_advance_to_shadow_allowed(self):
        orchestrator = self._orchestrator()
        result = orchestrator.advance_stage(model_id="challenger-x", model_version="v1", to_stage="SHADOW")
        assert result["allowed"] is True

    def test_real_money_impossible(self):
        orchestrator = self._orchestrator()
        result = orchestrator.advance_stage(model_id="challenger-x", model_version="v1", to_stage="REAL_MONEY")
        assert result["allowed"] is False

    def test_challenger_artifact_separate_from_champion(self):
        orchestrator = self._orchestrator()
        store = orchestrator._store
        store.register_model(
            model_id="M5_REGULARIZED_LOGISTIC", model_version="M5_REGULARIZED_LOGISTIC:54affc960a34",
            role="CHAMPION", stage="CHAMPION",
            artifact_sha256="fe6f18d1fb5eea640fc42d904d9010470ee75f73e594b2c00a86982d3381e229",
        )
        store.register_model(
            model_id="challenger-x", model_version="v1", role="CHALLENGER", stage="RESEARCH",
            artifact_sha256="0" * 64,
        )
        champion = store.champion()
        assert champion["artifact_sha256"].startswith("fe6f18d1")
        challenger = next(m for m in store.list_models() if m["model_id"] == "challenger-x")
        assert challenger["artifact_sha256"] == "0" * 64


class TestHealth:
    def test_missing_credential_not_configured_not_invisible(self):
        health = detect_health(initialized=True, ai_configured=False)
        assert health.state is QuantDirectorHealthState.NOT_CONFIGURED
        assert health.reason

    def test_initialization_exception_is_failed(self):
        health = detect_health(initialized=False, error_class="OperationalError")
        assert health.state is QuantDirectorHealthState.FAILED
        assert "OperationalError" in health.reason

    def test_ready_when_initialized(self):
        import defend_markets.quant.health as health_module

        original = health_module.runtime_credentials_present
        health_module.runtime_credentials_present = lambda: True
        try:
            health = detect_health(initialized=True)
            assert health.state is QuantDirectorHealthState.READY
        finally:
            health_module.runtime_credentials_present = original

    def test_quant_state_surfaces_budget_and_blockers(self):
        store = InMemoryQuantStore()
        tools = InMemoryMarketTools(store, events_discovered=85, events_matched=85, available_predictions=50, price_observations=0)
        orchestrator = MarketsIntelligenceOrchestrator(store=store, tools=tools)
        assert orchestrator.health_state()["state"] == "NOT_CONFIGURED"
        assert orchestrator.budget_policy()["max_daily_calls"] == 20
        assert orchestrator._tools.current_blocking_layers()["primary"] == "provider_tt_price_coverage"
