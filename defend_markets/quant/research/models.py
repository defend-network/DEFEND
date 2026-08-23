"""Interpretable regularized-logistic trainer mirroring the M5 freeze fit.

This is a research trainer used to fit challengers (and an apples-to-apples
M5-equivalent baseline) on snapshot rows. It never writes to or mutates the
frozen M5 artifact.
"""

from __future__ import annotations

from typing import Callable

import numpy as np

_LAM = 1.0


def fit_ridge_logistic(x: np.ndarray, y: np.ndarray, *, lam: float = _LAM) -> np.ndarray:
    """Newton-Raphson L2-regularized logistic fit (intercept included)."""
    n, dimension = x.shape
    xb = np.column_stack([np.ones(n), x])
    weights = np.zeros(dimension + 1)
    for _ in range(40):
        z = xb @ weights
        p = 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))
        grad = xb.T @ (p - y) + np.concatenate([[0.0], lam * weights[1:]])
        r = p * (1.0 - p)
        hess = xb.T @ (r[:, None] * xb) + np.diag(
            np.concatenate([[0.0], np.full(dimension, lam)])
        )
        try:
            step = np.linalg.solve(hess, grad)
        except np.linalg.LinAlgError:
            break
        weights -= step
        if np.max(np.abs(step)) < 1e-7:
            break
    return weights


def predict_ridge_logistic(x: np.ndarray, weights: np.ndarray) -> np.ndarray:
    xb = np.column_stack([np.ones(len(x)), x])
    z = xb @ weights
    p = 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))
    return np.clip(p, 1e-9, 1.0 - 1e-9)


def make_ridge_trainer(lam: float = _LAM) -> Callable[[np.ndarray, np.ndarray], np.ndarray]:
    return lambda x, y: fit_ridge_logistic(x, y, lam=lam)
