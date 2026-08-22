"""Reproducible experiment specs, results, and the research runner.

An experiment pins its dataset snapshot, feature set, algorithm,
hyperparameters, seed, and windows; the result stores deterministic metrics,
folds, calibration, ablation, leakage, runtime, and the promotion decision.
The runner works without any LLM.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

import numpy as np

from defend_markets.quant.research.features import rows_to_feature_matrix
from defend_markets.quant.research.metrics import (
    calibration_buckets,
    ece_score,
)
from defend_markets.quant.research.models import make_ridge_trainer, predict_ridge_logistic
from defend_markets.quant.research.promotion import PromotionGateSet
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
    calibration: list[dict[str, Any]]
    ece: float | None
    ablation: dict[str, Any]
    leakage: dict[str, Any]
    runtime_ms: int
    artifact_hash: str
    decision: str
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
            "calibration": self.calibration,
            "ece": self.ece,
            "ablation": self.ablation,
            "leakage": self.leakage,
            "runtime_ms": self.runtime_ms,
            "artifact_hash": self.artifact_hash,
            "decision": self.decision,
            "folds": self.folds,
            "gates": self.gates,
        }


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

    def _fold_predictions(self, folds: Sequence[Any]) -> tuple[list[float], list[float]]:
        preds: list[float] = []
        actuals: list[float] = []
        for fold in folds:
            preds.extend(fold.predictions)
            actuals.extend(fold.actuals)
        return preds, actuals

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

        base_set = [feature for feature in feature_set if feature != "elo_diff_sq"]
        base_matrix, _ = rows_to_feature_matrix(rows, feature_ids=base_set)
        base_folds = engine.run(
            x=np.asarray(base_matrix, dtype=float), y=y, timestamps=timestamps, n_windows=self._n_windows
        )
        baseline_agg = aggregate_folds(base_folds)

        calibration = calibration_buckets(challenger_actuals, challenger_preds) if challenger_preds else []
        challenger_ece = ece_score(challenger_actuals, challenger_preds) if challenger_preds else None

        challenger_brier = challenger_agg.get("weighted_brier")
        baseline_brier = baseline_agg.get("weighted_brier")
        ablation_kept = (
            challenger_brier is not None
            and baseline_brier is not None
            and float(challenger_brier) <= float(baseline_brier)
        )
        ablation = {
            "challenger_brier": challenger_brier,
            "baseline_brier": baseline_brier,
            "lift": round(float(challenger_brier) - float(baseline_brier), 6)
            if challenger_brier is not None and baseline_brier is not None
            else None,
            "kept": ablation_kept,
        }

        verdict = self._promotion.evaluate(
            leakage_detected=bool(self._snapshot.leakage_checks.get("accepted_rows_after_cutoff", 0)),
            sample_n=int(challenger_agg.get("val_rows", 0)),
            challenger_brier=challenger_agg.get("weighted_brier"),
            challenger_log_loss=challenger_agg.get("weighted_log_loss"),
            challenger_ece=challenger_ece,
            challenger_brier_std=challenger_agg.get("brier_std"),
            ablation_kept=ablation_kept,
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
                    "ablation": ablation,
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
            calibration=calibration,
            ece=challenger_ece,
            ablation=ablation,
            leakage=dict(self._snapshot.leakage_checks),
            runtime_ms=runtime_ms,
            artifact_hash=artifact_hash,
            decision=verdict["promotion"],
            folds=[fold.to_dict() for fold in folds],
            gates=verdict,
        )


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
        metrics_requested=("brier", "log_loss", "calibration", "accuracy", "ece"),
        created_by=created_by,
        code_commit=_commit_ref(),
    )
