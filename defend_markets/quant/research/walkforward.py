"""Chronological walk-forward evaluation.

Train on past-only blocks, validate the next chronological block, roll
forward. No random train/test split is accepted as promotion evidence. Each
fold and its metrics are retained.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

import numpy as np

from defend_markets.quant.research.metrics import metrics_report

ModelFit = Callable[[np.ndarray, np.ndarray], np.ndarray]
ModelPredict = Callable[[np.ndarray, np.ndarray], np.ndarray]


@dataclass
class WalkForwardFold:
    index: int
    train_start: str
    train_end: str
    val_start: str
    val_end: str
    train_rows: int
    val_rows: int
    brier: float
    log_loss: float
    calibration_error: float
    metrics: dict[str, Any]
    predictions: list[float] = field(default_factory=list)
    actuals: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "train_start": self.train_start,
            "train_end": self.train_end,
            "val_start": self.val_start,
            "val_end": self.val_end,
            "train_rows": self.train_rows,
            "val_rows": self.val_rows,
            "brier": self.brier,
            "log_loss": self.log_loss,
            "calibration_error": self.calibration_error,
            "metrics": self.metrics,
        }


def walk_forward_blocks(
    timestamps: Sequence[Any],
    *,
    n_windows: int,
) -> list[tuple[int, int, int]]:
    """Return (train_end, val_start, val_end) index triples over sorted ts."""
    ordered = sorted(range(len(timestamps)), key=lambda index: timestamps[index])
    n = len(ordered)
    boundaries = [int(round(n * (fraction + 1) / (n_windows + 1))) for fraction in range(n_windows)]
    boundaries = [min(n, max(1, boundary)) for boundary in boundaries]
    blocks: list[tuple[int, int, int]] = []
    for index, val_end in enumerate(boundaries):
        val_start = boundaries[index - 1] if index > 0 else 0
        train_end = val_start
        if val_end > val_start:
            blocks.append((train_end, val_start, val_end))
    return blocks


class WalkForwardEngine:
    def __init__(
        self,
        *,
        model_fit: ModelFit,
        model_predict: ModelPredict,
    ) -> None:
        self._model_fit = model_fit
        self._model_predict = model_predict

    def run(
        self,
        *,
        x: np.ndarray,
        y: np.ndarray,
        timestamps: Sequence[Any],
        n_windows: int = 4,
    ) -> list[WalkForwardFold]:
        order = sorted(range(len(timestamps)), key=lambda index: timestamps[index])
        folds: list[WalkForwardFold] = []
        for train_end, val_start, val_end in walk_forward_blocks(timestamps, n_windows=n_windows):
            train_idx = order[:train_end]
            val_idx = order[val_start:val_end]
            if not train_idx or not val_idx:
                continue
            x_train = x[train_idx]
            y_train = y[train_idx]
            x_val = x[val_idx]
            y_val = y[val_idx]
            weights = self._model_fit(x_train, y_train)
            pred = self._model_predict(x_val, weights)
            report = metrics_report(y_val.tolist(), pred.tolist())
            folds.append(
                WalkForwardFold(
                    index=len(folds),
                    train_start=str(timestamps[order[0]]),
                    train_end=str(timestamps[order[train_end - 1]]),
                    val_start=str(timestamps[order[val_start]]),
                    val_end=str(timestamps[order[val_end - 1]]),
                    train_rows=int(len(train_idx)),
                    val_rows=int(len(val_idx)),
                    brier=report["brier"],
                    log_loss=report["log_loss"],
                    calibration_error=report["ece"],
                    metrics=report,
                    predictions=pred.tolist(),
                    actuals=y_val.tolist(),
                )
            )
        return folds


def aggregate_folds(folds: Sequence[WalkForwardFold]) -> dict[str, Any]:
    if not folds:
        return {"n_windows": 0}
    total_rows = sum(fold.val_rows for fold in folds)
    weighted_brier = sum(fold.brier * fold.val_rows for fold in folds) / total_rows
    weighted_log_loss = sum(fold.log_loss * fold.val_rows for fold in folds) / total_rows
    briers = [fold.brier for fold in folds]
    return {
        "n_windows": len(folds),
        "val_rows": total_rows,
        "weighted_brier": round(weighted_brier, 6),
        "weighted_log_loss": round(weighted_log_loss, 6),
        "mean_brier": round(float(np.mean(briers)), 6),
        "brier_std": round(float(np.std(briers)), 6),
        "best_window_brier": round(float(np.min(briers)), 6),
        "worst_window_brier": round(float(np.max(briers)), 6),
    }
