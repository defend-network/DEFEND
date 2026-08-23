"""Deterministic paired out-of-sample lift estimation.

Baseline and challenger are evaluated on the same chronological observations,
so metric deltas are paired. A seeded bootstrap gives a conservative CI that
distinguishes measurable positive lift from "<= happened to be True".
"""

from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np


def _logloss_per_obs(actuals: np.ndarray, preds: np.ndarray, eps: float = 1e-9) -> np.ndarray:
    clipped = np.clip(preds, eps, 1.0 - eps)
    return -(actuals * np.log(clipped) + (1.0 - actuals) * np.log(1.0 - clipped))


def paired_lift(
    actuals: Sequence[float],
    baseline_preds: Sequence[float],
    challenger_preds: Sequence[float],
    *,
    seed: int = 7,
    n_boot: int = 2000,
) -> dict[str, Any]:
    actual = np.asarray(actuals, dtype=float)
    base = np.asarray(baseline_preds, dtype=float)
    chall = np.asarray(challenger_preds, dtype=float)
    n = int(actual.size)
    if n == 0:
        return {"n": 0, "delta_brier": None, "delta_logloss": None}

    brier_obs = (base - actual) ** 2 - (chall - actual) ** 2
    ll_obs = _logloss_per_obs(actual, base) - _logloss_per_obs(actual, chall)
    delta_brier = float(np.mean(brier_obs))
    delta_logloss = float(np.mean(ll_obs))

    rng = np.random.default_rng(seed)
    brier_samples: list[float] = []
    ll_samples: list[float] = []
    for _ in range(n_boot):
        indices = rng.integers(0, n, size=n)
        brier_samples.append(float(np.mean(brier_obs[indices])))
        ll_samples.append(float(np.mean(ll_obs[indices])))

    def ci(samples: list[float]) -> tuple[float, float]:
        return (float(np.percentile(samples, 2.5)), float(np.percentile(samples, 97.5)))

    brier_ci = ci(brier_samples)
    ll_ci = ci(ll_samples)
    return {
        "n": n,
        "delta_brier": round(delta_brier, 8),
        "delta_brier_ci_low": round(brier_ci[0], 8),
        "delta_brier_ci_high": round(brier_ci[1], 8),
        "delta_logloss": round(delta_logloss, 8),
        "delta_logloss_ci_low": round(ll_ci[0], 8),
        "delta_logloss_ci_high": round(ll_ci[1], 8),
        "positive_lift": delta_brier > 0 and brier_ci[0] > 0,
    }


def classify_lift(delta_brier: float | None, delta_ci_low: float | None, *, min_lift: float) -> str:
    if delta_brier is None:
        return "INSUFFICIENT_EVIDENCE"
    if delta_brier <= -min_lift:
        return "MEASURABLE_REGRESSION"
    if delta_ci_low is not None and delta_ci_low > 0 and delta_brier >= min_lift:
        return "MEASURABLE_POSITIVE_LIFT"
    return "NO_MEASURABLE_LIFT"
