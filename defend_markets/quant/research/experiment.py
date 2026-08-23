"""Reproducible experiment specs, results, and the research runner.

An experiment pins its dataset snapshot, feature set, algorithm,
hyperparameters, seed, and windows; the result stores deterministic metrics at
full precision, paired out-of-sample lift with bootstrap CI, feature
diagnostics, gates under promotion policy v2, and the promotion decision.
The runner works without any LLM.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

import numpy as np

from defend_markets.quant.research.features import rows_to_feature_matrix
from defend_markets.quant.research.metrics import (
    brier_score,
    calibration_buckets,
    ece_score,
    log_loss_score,
)
from defend_markets.quant.research.models import fit_ridge_logistic, make_ridge_trainer, predict_ridge_logistic
from defend_markets.quant.research.paired import paired_lift
from defend_markets.quant.research.promotion import PROMOTION_POLICY_VERSION, PromotionGateSet
from defend_markets.quant.research.walkforward import WalkForwardEngine, aggregate_folds


def _commit_ref() -> str:
    import os
    import subprocess

    try:
        return (
            subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                cwd=os.getcwd(),
                check=False,
            ).stdout.strip()
            or "unknown"
        )
    except Exception:
        return "unknown"


@dataclass(frozen=True)
class ExperimentSpec:
    experiment_id: str
    hypothesis_id: str
    dataset_snapshot_id: str
    champion_version: str
    challenger_name: str
    feature_set: tuple[str, ...]
    algorithm: str
    hyperparameters: Mapping[str, Any]
    seed: int
    training_window: Mapping[str, Any]
    validation_windows: Mapping[str, Any]
    calibration_method: str
    metrics_requested: tuple[str, ...]
    created_by: str
    code_commit: str
    promotion_policy_version: int = PROMOTION_POLICY_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "hypothesis_id": self.hypothesis_id,
            "dataset_snapshot_id": self.dataset_snapshot_id,
            "champion_version": self.champion_version,
            "challenger_name": self.challenger_name,
            "feature_set": list(self.feature_set),
            "algorithm": self.algorithm,
            "hyperparameters": dict(self.hyperparameters),
            "seed": self.seed,
            "training_window": dict(self.training_window),
            "validation_windows": dict(self.validation_windows),
            "calibration_method": self.calibration_method,
            "metrics_requested": list(self.metrics_requested),
            "created_by": self.created_by,
            "code_commit": self.code_commit,
            "promotion_policy_version": self.promotion_policy_version,
        }


@dataclass
class ExperimentResult:
    experiment_id: str
    dataset_snapshot_id: str
    created_at: str
    rows_used: int
    n_windows: int
    challenger_metrics: dict[str, Any]
    baseline_metrics: dict[str, Any]
    challenger_metrics_raw: dict[str, Any]
    baseline_metrics_raw: dict[str, Any]
    metric_deltas: dict[str, Any]
    feature_diagnostics: dict[str, Any]
    calibration: list[dict[str, Any]]
    ece: float | None
    leakage: dict[str, Any]
    runtime_ms: int
    artifact_hash: str
    decision: str
    promotion_policy_version: int
    folds: list[dict[str, Any]] = field(default_factory=list)
    gates: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "dataset_snapshot_id": self.dataset_snapshot_id,
            "created_at": self.created_at,
            "rows_used": self.rows_used,
            "n_windows": self.n_windows,
            "challenger_metrics": self.challenger_metrics,
            "baseline_metrics": self.baseline_metrics,
            "challenger_metrics_raw": self.challenger_metrics_raw,
            "baseline_metrics_raw": self.baseline_metrics_raw,
            "metric_deltas": self.metric_deltas,
            "feature_diagnostics": self.feature_diagnostics,
            "calibration": self.calibration,
            "ece": self.ece,
            "leakage": self.leakage,
            "runtime_ms": self.runtime_ms,
            "artifact_hash": self.artifact_hash,
            "decision": self.decision,
            "promotion_policy_version": self.promotion_policy_version,
            "folds": self.folds,
            "gates": self.gates,
        }


_M5_BASE_FEATURES = [
    "home_indicator",
    "elo_diff",
    "recency_elo_diff",
    "form5_diff",
    "log_depth_diff",
    "rest_diff_days",
    "h2h_winrate_diff",
    "same_day_diff",
    "degree_diff",
]


def _feature_diagnostics(
    feature_set: Sequence[str],
    x: np.ndarray,
    base_matrix: np.ndarray,
    challenger_preds: np.ndarray,
    baseline_preds: np.ndarray,
) -> dict[str, Any]:
    added = [feature for feature in feature_set if feature not in _M5_BASE_FEATURES]
    diagnostics: dict[str, Any] = {"added_features": added}
    for feature_index, feature in enumerate(feature_set):
        if feature not in added:
            continue
        column = x[:, feature_index]
        non_null = int(np.sum(~np.isnan(column)))
        nonzero = int(np.sum(column != 0))
        finite = column[np.isfinite(column)]
        std = float(np.std(finite)) if finite.size else 0.0
        correlations: dict[str, float] = {}
        for base_feature in ("form5_diff", "recency_elo_diff", "elo_diff"):
            if base_feature in feature_set:
                base_index = feature_set.index(base_feature)
                base_col = base_matrix[:, base_index]
                if finite.size and np.std(base_col) > 0:
                    correlations[base_feature] = round(float(np.corrcoef(finite, base_col)[0, 1]), 4)
        diagnostics[feature] = {
            "row_count": int(len(column)),
            "non_null_count": non_null,
            "nonzero_count": nonzero,
            "zero_count": int(len(column)) - nonzero,
            "mean": round(float(np.mean(finite)), 8) if finite.size else None,
            "stddev": round(std, 8),
            "min": round(float(np.min(finite)), 8) if finite.size else None,
            "max": round(float(np.max(finite)), 8) if finite.size else None,
            "unique_value_count": int(np.unique(column).size),
            "correlation_with": correlations,
        }
    if added:
        delta = np.abs(challenger_preds - baseline_preds)
        diagnostics["prediction_delta_vs_baseline"] = {
            "max_abs": round(float(np.max(delta)), 10) if delta.size else 0.0,
            "mean_abs": round(float(np.mean(delta)), 10) if delta.size else 0.0,
            "p95_abs": round(float(np.percentile(delta, 95)), 10) if delta.size else 0.0,
        }
    return diagnostics


class ExperimentRunner:
    def __init__(
        self,
        *,
        snapshot: Any,
        promotion: PromotionGateSet | None = None,
        n_windows: int = 4,
    ) -> None:
        self._snapshot = snapshot
        self._promotion = promotion or PromotionGateSet()
        self._n_windows = n_windows

    def run(
        self,
        spec: ExperimentSpec,
        *,
        champion_brier: float | None = None,
        champion_log_loss: float | None = None,
        market_metrics_available: bool = False,
    ) -> ExperimentResult:
        started = time.perf_counter()
        rows = list(self._snapshot.rows)
        timestamps = [datetime.fromisoformat(str(row["ts"]).replace("Z", "+00:00")) for row in rows]
        feature_set = list(spec.feature_set)
        x_matrix, y_list = rows_to_feature_matrix(rows, feature_ids=feature_set)
        x = np.asarray(x_matrix, dtype=float)
        y = np.asarray(y_list, dtype=float)

        trainer = make_ridge_trainer(lam=float(spec.hyperparameters.get("lam", 1.0)))
        engine = WalkForwardEngine(model_fit=trainer, model_predict=predict_ridge_logistic)
        folds = engine.run(x=x, y=y, timestamps=timestamps, n_windows=self._n_windows)
        challenger_agg = aggregate_folds(folds)
        challenger_preds, challenger_actuals = self._fold_predictions(folds)

        base_set = list(_M5_BASE_FEATURES)
        base_matrix, _ = rows_to_feature_matrix(rows, feature_ids=base_set)
        base_folds = engine.run(
            x=np.asarray(base_matrix, dtype=float), y=y, timestamps=timestamps, n_windows=self._n_windows
        )
        baseline_preds, _ = self._fold_predictions(base_folds)
        baseline_agg = aggregate_folds(base_folds)

        raw_actuals = [float(value) for value in challenger_actuals]
        raw_challenger = [float(value) for value in challenger_preds]
        raw_baseline = [float(value) for value in baseline_preds]
        challenger_raw = {
            "brier": brier_score(raw_actuals, raw_challenger),
            "log_loss": log_loss_score(raw_actuals, raw_challenger),
        }
        baseline_raw = {
            "brier": brier_score(raw_actuals, raw_baseline),
            "log_loss": log_loss_score(raw_actuals, raw_baseline),
        }
        deltas = paired_lift(raw_actuals, raw_baseline, raw_challenger)

        calibration = calibration_buckets(raw_actuals, raw_challenger) if raw_actuals else []
        challenger_ece = ece_score(raw_actuals, raw_challenger) if raw_actuals else None

        feature_diag = _feature_diagnostics(feature_set, x, np.asarray(base_matrix, dtype=float), np.asarray(raw_challenger), np.asarray(raw_baseline))
        learned_coefficients: dict[str, Any] = {}
        if feature_diag["added_features"]:
            weights = fit_ridge_logistic(x, y)
            for feature in feature_diag["added_features"]:
                index = feature_set.index(feature)
                learned_coefficients[feature] = round(float(weights[index + 1]), 10)
        feature_diag["learned_coefficient"] = learned_coefficients

        added_complexity = bool(feature_diag["added_features"])
        calibration_improvement = False
        if added_complexity and baseline_raw["brier"] is not None:
            calibration_improvement = (challenger_ece is not None) and (
                baseline_raw["brier"] >= challenger_raw["brier"]
            ) and (challenger_ece <= 0.03)

        verdict = self._promotion.evaluate(
            leakage_detected=bool(self._snapshot.leakage_checks.get("accepted_rows_after_cutoff", 0)),
            sample_n=int(challenger_agg.get("val_rows", 0)),
            challenger_brier=challenger_raw["brier"],
            challenger_log_loss=challenger_raw["log_loss"],
            challenger_ece=challenger_ece,
            challenger_brier_std=challenger_agg.get("brier_std"),
            added_complexity=added_complexity,
            metric_deltas=deltas,
            calibration_improvement=calibration_improvement,
            champion_brier=champion_brier,
            champion_log_loss=champion_log_loss,
            market_metrics_available=market_metrics_available,
        )

        artifact_hash = hashlib.sha256(
            json.dumps(
                {
                    "spec": spec.to_dict(),
                    "challenger": challenger_agg,
                    "baseline": baseline_agg,
                    "deltas": deltas,
                },
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        runtime_ms = int((time.perf_counter() - started) * 1000)
        return ExperimentResult(
            experiment_id=spec.experiment_id,
            dataset_snapshot_id=spec.dataset_snapshot_id,
            created_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            rows_used=len(rows),
            n_windows=len(folds),
            challenger_metrics=challenger_agg,
            baseline_metrics=baseline_agg,
            challenger_metrics_raw={key: round(value, 8) for key, value in challenger_raw.items()},
            baseline_metrics_raw={key: round(value, 8) for key, value in baseline_raw.items()},
            metric_deltas=deltas,
            feature_diagnostics=feature_diag,
            calibration=calibration,
            ece=challenger_ece,
            leakage=dict(self._snapshot.leakage_checks),
            runtime_ms=runtime_ms,
            artifact_hash=artifact_hash,
            decision=verdict["promotion"],
            promotion_policy_version=verdict["promotion_policy_version"],
            folds=[fold.to_dict() for fold in folds],
            gates=verdict,
        )

    @staticmethod
    def _fold_predictions(folds: Sequence[Any]) -> tuple[list[float], list[float]]:
        preds: list[float] = []
        actuals: list[float] = []
        for fold in folds:
            preds.extend(fold.predictions)
            actuals.extend(fold.actuals)
        return preds, actuals


def build_spec(
    *,
    experiment_id: str,
    hypothesis_id: str,
    snapshot: Any,
    champion_version: str,
    challenger_name: str,
    feature_set: Sequence[str],
    created_by: str = "quant-director-v1",
    seed: int = 7,
) -> ExperimentSpec:
    return ExperimentSpec(
        experiment_id=experiment_id,
        hypothesis_id=hypothesis_id,
        dataset_snapshot_id=snapshot.snapshot_id,
        champion_version=champion_version,
        challenger_name=challenger_name,
        feature_set=tuple(feature_set),
        algorithm="regularized_logistic",
        hyperparameters={"lam": 1.0},
        seed=seed,
        training_window={"mode": "strictly-before", "note": "per-row chronological replay"},
        validation_windows={"mode": "walk_forward", "n_windows": 4},
        calibration_method="reliability_buckets",
        metrics_requested=("brier", "log_loss", "calibration", "accuracy", "ece", "paired_lift"),
        created_by=created_by,
        code_commit=_commit_ref(),
    )
