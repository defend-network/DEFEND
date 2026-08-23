"""Quant research lab: dataset snapshots, feature registry, experiments."""

from __future__ import annotations

from defend_markets.quant.research.experiment import (
    ExperimentResult,
    ExperimentRunner,
    ExperimentSpec,
    build_spec,
)
from defend_markets.quant.research.features import (
    FEATURE_SCHEMA_VERSION,
    FeatureDefinition,
    FeatureRegistry,
    apply_challenger_features,
    challenger_feature_definitions,
    extract_m5_features,
    m5_feature_registry,
    rows_to_feature_matrix,
)
from defend_markets.quant.research.metrics import (
    accuracy_score,
    brier_score,
    calibration_buckets,
    ece_score,
    log_loss_score,
    metrics_report,
)
from defend_markets.quant.research.models import (
    fit_ridge_logistic,
    make_ridge_trainer,
    predict_ridge_logistic,
)
from defend_markets.quant.research.promotion import GateResult, PromotionGateSet
from defend_markets.quant.research.snapshot import DatasetSnapshot, build_snapshot
from defend_markets.quant.research.walkforward import (
    WalkForwardEngine,
    WalkForwardFold,
    aggregate_folds,
    walk_forward_blocks,
)

__all__ = [
    "DatasetSnapshot",
    "ExperimentResult",
    "ExperimentRunner",
    "ExperimentSpec",
    "FEATURE_SCHEMA_VERSION",
    "FeatureDefinition",
    "FeatureRegistry",
    "GateResult",
    "PromotionGateSet",
    "WalkForwardEngine",
    "WalkForwardFold",
    "accuracy_score",
    "aggregate_folds",
    "apply_challenger_features",
    "brier_score",
    "build_snapshot",
    "build_spec",
    "calibration_buckets",
    "challenger_feature_definitions",
    "ece_score",
    "extract_m5_features",
    "fit_ridge_logistic",
    "log_loss_score",
    "m5_feature_registry",
    "make_ridge_trainer",
    "metrics_report",
    "predict_ridge_logistic",
    "rows_to_feature_matrix",
    "walk_forward_blocks",
]
