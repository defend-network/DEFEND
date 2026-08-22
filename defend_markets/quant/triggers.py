"""Deterministic supervisory triggers.

The Quant Director never calls an LLM on every tick. State changes are
filtered by deterministic triggers; only a meaningful trigger may schedule an
AI call, and the trigger reason is recorded.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable


@dataclass(frozen=True)
class TriggerResult:
    should_run: bool
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"should_run": self.should_run, "reason": self.reason}


class SupervisoryTriggers:
    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._last_prediction_count: int | None = None
        self._last_settlement_count: int | None = None
        self._last_health: str | None = None
        self._last_daily_review: datetime | None = None

    def evaluate(
        self,
        *,
        markets_ready: bool,
        tool_state: dict[str, Any],
        forced: bool = False,
    ) -> TriggerResult:
        if not markets_ready:
            return TriggerResult(False, "runtime not ready; no AI spend")
        now = self._clock()

        health = str(tool_state.get("provider_state", {}).get("healthy"))
        if self._last_health is not None and health != self._last_health:
            self._last_health = health
            return TriggerResult(True, f"provider health transition to {health}")

        predictions = int(tool_state.get("provider_state", {}).get("available_predictions", 0))
        if self._last_prediction_count is not None and predictions != self._last_prediction_count:
            self._last_prediction_count = predictions
            return TriggerResult(True, f"prediction set changed: {predictions}")

        settlements = int(tool_state.get("journal_summary", {}).get("settled", 0))
        if self._last_settlement_count is not None and settlements != self._last_settlement_count:
            self._last_settlement_count = settlements
            return TriggerResult(True, f"settlement batch completed: {settlements}")

        if self._last_daily_review is None or now - self._last_daily_review >= timedelta(hours=24):
            self._last_daily_review = now
            return TriggerResult(True, "scheduled daily review")

        self._last_prediction_count = predictions
        self._last_settlement_count = settlements
        self._last_health = health
        return TriggerResult(False, "no meaningful state change")
