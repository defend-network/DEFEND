"""Deterministic research metrics: Brier, log loss, calibration, ECE.

No LLM math. Every metric is a pure function of observed outcomes and
predicted probabilities.
"""

from __future__ import annotations

import math
from typing import Any, Sequence


def brier_score(y_true: Sequence[float], y_pred: Sequence[float]) -> float:
    values = [float((truth - pred) ** 2) for truth, pred in zip(y_true, y_pred)]
    return sum(values) / len(values) if values else float("nan")


def log_loss_score(y_true: Sequence[float], y_pred: Sequence[float], *, eps: float = 1e-9) -> float:
    total = 0.0
    count = 0
    for truth, pred in zip(y_true, y_pred):
        clipped = min(max(float(pred), eps), 1.0 - eps)
        total += -(
            float(truth) * math.log(clipped)
            + (1.0 - float(truth)) * math.log(1.0 - clipped)
        )
        count += 1
    return total / count if count else float("nan")


def accuracy_score(y_true: Sequence[float], y_pred: Sequence[float]) -> float:
    correct = sum(1 for truth, pred in zip(y_true, y_pred) if (float(pred) >= 0.5) == (float(truth) >= 0.5))
    return correct / len(y_true) if y_true else float("nan")


def calibration_buckets(
    y_true: Sequence[float],
    y_pred: Sequence[float],
    *,
    bins: int = 10,
) -> list[dict[str, float]]:
    rows = sorted(zip(y_pred, y_true), key=lambda pair: pair[0])
    size = max(1, math.ceil(len(rows) / bins))
    buckets: list[dict[str, float]] = []
    for index in range(0, len(rows), size):
        bucket = rows[index:index + size]
        if not bucket:
            continue
        pred_mean = sum(pred for pred, _ in bucket) / len(bucket)
        obs_rate = sum(truth for _, truth in bucket) / len(bucket)
        buckets.append(
            {
                "bin_start": float(index) / len(rows),
                "bin_end": float(index + len(bucket)) / len(rows),
                "predicted_mean": round(pred_mean, 6),
                "observed_rate": round(obs_rate, 6),
                "count": float(len(bucket)),
                "abs_calibration_error": round(abs(pred_mean - obs_rate), 6),
            }
        )
    return buckets


def ece_score(
    y_true: Sequence[float],
    y_pred: Sequence[float],
    *,
    bins: int = 10,
) -> float:
    rows = sorted(zip(y_pred, y_true), key=lambda pair: pair[0])
    if not rows:
        return float("nan")
    size = max(1, math.ceil(len(rows) / bins))
    weighted_error = 0.0
    for index in range(0, len(rows), size):
        bucket = rows[index:index + size]
        pred_mean = sum(pred for pred, _ in bucket) / len(bucket)
        obs_rate = sum(truth for _, truth in bucket) / len(bucket)
        weighted_error += (len(bucket) / len(rows)) * abs(pred_mean - obs_rate)
    return round(weighted_error, 6)


def metrics_report(y_true: Sequence[float], y_pred: Sequence[float]) -> dict[str, Any]:
    return {
        "n": len(list(y_true)),
        "brier": round(brier_score(y_true, y_pred), 6),
        "log_loss": round(log_loss_score(y_true, y_pred), 6),
        "accuracy": round(accuracy_score(y_true, y_pred), 6),
        "ece": ece_score(y_true, y_pred),
        "calibration": calibration_buckets(y_true, y_pred),
    }
