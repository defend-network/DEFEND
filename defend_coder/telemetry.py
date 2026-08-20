"""Per-model-call telemetry (P2/P2A) and wall-clock accounting (P2B).

``ModelCallRecord`` captures everything we know about one model request:
provider-reported token counts (NULL when the serving API does not
report usage), the client-measured request round-trip, the visible
assistant payload size, and the phase/budget context. Estimates are
stored in their own fields so they can never be mistaken for provider
truth:

- ``request_roundtrip_seconds`` is exact (client wall-clock).
- ``generation_seconds`` is NULL unless the backend reports it.
- ``tokens_per_second`` is an ESTIMATE (output tokens / round-trip).
- ``assistant_visible_tokens`` is an ESTIMATE when not NULL.

``reasoning_content`` is never captured, never persisted, never logged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import median
from typing import Any


@dataclass(frozen=True)
class ModelCallRecord:
    step: int
    phase: str
    started_at: datetime
    finished_at: datetime
    request_roundtrip_seconds: float
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    finish_reason: str | None
    max_tokens_requested: int
    tool_calls_requested: int
    assistant_visible_chars: int
    assistant_visible_tokens: int | None
    context_tokens: int | None
    remaining_action_budget: int
    generation_seconds: float | None = None
    tokens_per_second: float | None = None
    error_class: str | None = None


def build_call_record(
    *,
    step: int,
    phase: str,
    roundtrip_seconds: float,
    max_tokens_requested: int,
    tool_calls_requested: int,
    remaining_action_budget: int,
    content: str | None = None,
    usage: dict[str, Any] | None = None,
    finish_reason: str | None = None,
    error_class: str | None = None,
) -> ModelCallRecord:
    """Assemble a record from client-visible facts.

    ``usage`` is the raw provider ``usage`` object when the serving API
    returned one; keys are read defensively. ``content`` is only the
    VISIBLE assistant text (never reasoning content). Estimates
    (``tokens_per_second``) are marked by their field and documented.
    """
    now = datetime.now(timezone.utc)
    started_at = now
    finished_at = now
    usage = usage if isinstance(usage, dict) else {}
    input_tokens = _int_or_none(usage.get("prompt_tokens"))
    output_tokens = _int_or_none(usage.get("completion_tokens"))
    total_tokens = _int_or_none(usage.get("total_tokens"))
    visible_chars = len(content or "")
    visible_tokens = None
    if output_tokens is not None:
        visible_tokens = max(0, int(round(visible_chars / 4)))
    tokens_per_second = None
    if (
        output_tokens is not None
        and roundtrip_seconds > 0.0
        and error_class is None
    ):
        tokens_per_second = round(output_tokens / roundtrip_seconds, 2)
    return ModelCallRecord(
        step=step,
        phase=phase,
        started_at=started_at,
        finished_at=finished_at,
        request_roundtrip_seconds=round(roundtrip_seconds, 3),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        finish_reason=finish_reason,
        max_tokens_requested=max_tokens_requested,
        tool_calls_requested=tool_calls_requested,
        assistant_visible_chars=visible_chars,
        assistant_visible_tokens=visible_tokens,
        context_tokens=input_tokens,
        remaining_action_budget=remaining_action_budget,
        generation_seconds=None,
        tokens_per_second=tokens_per_second,
        error_class=error_class,
    )


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return max(0, value)


def _percentile(sorted_values: list[float], percentile: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    index = (len(sorted_values) - 1) * percentile
    lower = int(index)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = index - lower
    return (
        sorted_values[lower] * (1.0 - fraction)
        + sorted_values[upper] * fraction
    )


def aggregate_model_calls(
    records: list[ModelCallRecord],
) -> dict[str, object]:
    """Aggregate a run's telemetry (totals + P50/P95/MAX).

    Fields that depend on provider-reported usage are only computed when
    at least one record carries the value; otherwise the aggregate is
    NOT_AVAILABLE (None) so estimates are never fabricated.
    """
    count = len(records)
    roundtrips = sorted(r.request_roundtrip_seconds for r in records)
    outputs = [r.output_tokens for r in records if r.output_tokens is not None]
    inputs = [r.input_tokens for r in records if r.input_tokens is not None]
    outputs_sorted = sorted(outputs)

    finish_reasons: dict[str, int] = {}
    error_classes: dict[str, int] = {}
    phases: dict[str, int] = {}
    for record in records:
        finish_reasons[record.finish_reason or "unknown"] = (
            finish_reasons.get(record.finish_reason or "unknown", 0) + 1
        )
        error_classes[record.error_class or "ok"] = (
            error_classes.get(record.error_class or "ok", 0) + 1
        )
        phases[record.phase] = phases.get(record.phase, 0) + 1

    return {
        "call_count": count,
        "total_request_roundtrip_seconds": round(sum(roundtrips), 3),
        "mean_request_roundtrip_seconds": (
            round(sum(roundtrips) / len(roundtrips), 3) if roundtrips else None
        ),
        "p50_request_roundtrip_seconds": round(
            _percentile(roundtrips, 0.5), 3
        ),
        "p95_request_roundtrip_seconds": round(
            _percentile(roundtrips, 0.95), 3
        ),
        "max_request_roundtrip_seconds": round(max(roundtrips), 3)
        if roundtrips
        else None,
        "total_output_tokens": sum(outputs) if outputs else None,
        "mean_output_tokens": (
            round(sum(outputs) / len(outputs), 1) if outputs else None
        ),
        "p95_output_tokens": (
            round(_percentile(outputs_sorted, 0.95), 1)
            if outputs_sorted
            else None
        ),
        "max_output_tokens": max(outputs_sorted) if outputs_sorted else None,
        "total_input_tokens": sum(inputs) if inputs else None,
        "generation_seconds_available": any(
            r.generation_seconds is not None for r in records
        ),
        "finish_reasons": finish_reasons,
        "error_classes": error_classes,
        "phases": phases,
        "estimate_fields": [
            "tokens_per_second",
            "assistant_visible_tokens",
        ],
    }


def wall_clock_accounting(
    records: list[ModelCallRecord],
    *,
    run_seconds: float,
    queue_wait_seconds: float | None,
    tool_execution_seconds: float | None,
    finalization_seconds: float | None,
    persistence_seconds: float | None,
) -> dict[str, object]:
    """P2B decomposition of one run's wall clock.

    Every bucket is measured once and never double-counted: model
    requests are their client-measured round-trips, tool execution is
    derived from message timestamps, persistence is measured in the
    runner, and everything else is UNATTRIBUTED. When only end-to-end
    latency is knowable, REQUEST_ROUNDTRIP_SECONDS is the exact figure
    and MODEL_GENERATION_SECONDS is reported NOT_AVAILABLE.
    """
    roundtrip = sum(r.request_roundtrip_seconds for r in records)
    finalization = sum(
        r.request_roundtrip_seconds
        for r in records
        if r.phase == "finalizing"
    )
    buckets = {
        "total_wall_seconds": round(run_seconds, 3),
        "queue_wait_seconds": queue_wait_seconds,
        "request_roundtrip_seconds": round(roundtrip, 3),
        "model_generation_seconds": None,
        "tool_execution_seconds": (
            round(tool_execution_seconds, 3)
            if tool_execution_seconds is not None
            else None
        ),
        "persistence_seconds": (
            round(persistence_seconds, 3)
            if persistence_seconds is not None
            else None
        ),
        "finalization_seconds": (
            round(finalization, 3) if finalization > 0 else None
        ),
    }
    accounted = 0.0
    for value in (
        queue_wait_seconds,
        roundtrip,
        tool_execution_seconds,
        persistence_seconds,
    ):
        if value is not None:
            accounted += value
    unattributed = max(0.0, run_seconds - accounted)
    buckets["unattributed_seconds"] = round(unattributed, 3)
    buckets["accounted_wall_clock_percent"] = (
        round(accounted / run_seconds * 100, 1) if run_seconds > 0 else 100.0
    )
    buckets["model_generation_seconds_available"] = False
    return buckets


def percentile(values: list[float], percentile_value: float) -> float:
    return _percentile(sorted(values), percentile_value)


def median_or_none(values: list[float]) -> float | None:
    return median(values) if values else None