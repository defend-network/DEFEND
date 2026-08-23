"""Centralized AI pricing and cost estimation.

Rates live in the external ``rate_card.json`` so pricing can be updated without
touching research logic. Cost estimation is deterministic from token counts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ModelRate:
    provider: str
    model: str
    input_per_million: float
    output_per_million: float
    cached_input_per_million: float
    effective_at: str


def _load_rate_card() -> list[ModelRate]:
    path = Path(__file__).with_name("rate_card.json")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        ModelRate(
            provider=str(entry["provider"]),
            model=str(entry["model"]),
            input_per_million=float(entry["input_per_million"]),
            output_per_million=float(entry["output_per_million"]),
            cached_input_per_million=float(entry["cached_input_per_million"]),
            effective_at=str(entry["effective_at"]),
        )
        for entry in raw
    ]


RATE_CARD = _load_rate_card()


def find_rate(provider: str, model: str) -> ModelRate | None:
    for rate in RATE_CARD:
        if rate.provider == provider and rate.model == model:
            return rate
    return None


def estimate_call_cost(
    *,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
) -> float:
    rate = find_rate(provider, model)
    if rate is None:
        return 0.0
    fresh_input = max(0, input_tokens - cached_input_tokens)
    cost = (
        fresh_input * rate.input_per_million / 1_000_000
        + cached_input_tokens * rate.cached_input_per_million / 1_000_000
        + output_tokens * rate.output_per_million / 1_000_000
    )
    return round(cost, 8)


def record_call(
    store: Any,
    *,
    profile_alias: str,
    provider: str,
    model: str,
    trigger_type: str | None = None,
    state_hash: str | None = None,
    reason_for_route: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cached_input_tokens: int = 0,
    latency_ms: int | None = None,
    retry_count: int = 0,
    status: str = "COMPLETED",
) -> float:
    cost = estimate_call_cost(
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=cached_input_tokens,
    )
    store.record_ai_call_full(
        {
            "profile_alias": profile_alias,
            "actual_provider": provider,
            "actual_model": model,
            "trigger_type": trigger_type,
            "state_hash": state_hash,
            "reason_for_route": reason_for_route,
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost_usd": cost,
            "latency_ms": latency_ms,
            "retry_count": retry_count,
            "status": status,
        }
    )
    return cost
