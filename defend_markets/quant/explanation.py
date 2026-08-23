"""Deterministic M5 feature-contribution explanation.

Produces exact numeric provenance for a logistic prediction: intercept,
per-feature weight x feature contribution, total logit, and sigmoid
probability. The Quant Director may interpret these numbers but never invents
feature importance.
"""

from __future__ import annotations

from typing import Any, Mapping


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + __import__("math").exp(-value))
    exp = __import__("math").exp(value)
    return exp / (1.0 + exp)


def explain_m5_prediction(
    features: Mapping[str, float],
    weights_doc: Mapping[str, Any],
    *,
    model_version: str | None = None,
) -> dict[str, Any]:
    names = list(weights_doc["feature_names"])
    weights = weights_doc["weights"]
    intercept = float(weights_doc["intercept"])
    logit = intercept
    contributions: list[dict[str, float]] = []
    for name in names:
        weight = float(weights.get(name, 0.0))
        feature = float(features.get(name, 0.0))
        contribution = weight * feature
        logit += contribution
        contributions.append(
            {
                "feature": name,
                "weight": round(weight, 10),
                "feature_value": round(feature, 10),
                "contribution": round(contribution, 10),
            }
        )
    contributions.sort(key=lambda item: abs(item["contribution"]), reverse=True)
    probability = _sigmoid(logit)
    return {
        "model_version": model_version or str(weights_doc.get("model_id", "")),
        "weights_sha256": str(weights_doc.get("sha256", "")),
        "intercept": round(intercept, 10),
        "total_logit": round(logit, 10),
        "probability": round(probability, 10),
        "contributions": contributions,
    }
