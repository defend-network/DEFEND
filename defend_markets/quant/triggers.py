"""Deterministic supervisory triggers with state hashing, debounce, and
persistence.

Each trigger produces a normalized state hash; the same trigger type with an
unchanged hash inside a cooldown is suppressed and counted. Severity is a
property of the event, never chosen by the model.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable


def utc_now_iso() -> datetime:
    return datetime.now(timezone.utc)


def state_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        repr(sorted(payload.items(), key=lambda item: str(item[0]))).encode("utf-8")
    ).hexdigest()


class Severity:
    INFO = "INFO"
    REVIEW = "REVIEW"
    IMPORTANT = "IMPORTANT"
    CRITICAL = "CRITICAL"


_TRIGGER_SEVERITY = {
    "PROVIDER_HEALTH_CHANGED": Severity.IMPORTANT,
    "NEW_PREDICTION_BATCH": Severity.INFO,
    "SETTLEMENT_BATCH_COMPLETED": Severity.REVIEW,
    "CALIBRATION_DRIFT": Severity.IMPORTANT,
    "DATA_DRIFT": Severity.REVIEW,
    "DATA_FRESHNESS_DEGRADED": Severity.IMPORTANT,
    "NEW_CHALLENGER_RESULT": Severity.REVIEW,
    "PROMOTION_GATE_RESULT": Severity.REVIEW,
    "MATERIAL_MODEL_MARKET_DISAGREEMENT": Severity.REVIEW,
    "MARKET_COVERAGE_BECAME_AVAILABLE": Severity.IMPORTANT,
    "MARKET_COVERAGE_BECAME_EMPTY": Severity.INFO,
    "CHAMPION_ARTIFACT_MISMATCH": Severity.CRITICAL,
}


@dataclass(frozen=True)
class TriggerSignal:
    trigger_type: str
    evidence: dict[str, Any]
    state_hash: str
    severity: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "trigger_type": self.trigger_type,
            "evidence": self.evidence,
            "state_hash": self.state_hash,
            "severity": self.severity,
        }


class TriggerLedger:
    """Persists trigger sightings and debounces unchanged state."""

    def __init__(
        self,
        store: Any,
        *,
        clock: Callable[[], datetime] | None = None,
        cooldown_seconds: int = 600,
    ) -> None:
        self._store = store
        self._clock = clock or utc_now_iso
        self._cooldown_seconds = cooldown_seconds

    def _severity(self, trigger_type: str) -> str:
        return _TRIGGER_SEVERITY.get(trigger_type, Severity.INFO)

    def record(
        self,
        trigger_type: str,
        evidence: dict[str, Any],
        *,
        invoke: bool,
        result: str | None = None,
    ) -> dict[str, Any]:
        now = self._clock()
        signal = TriggerSignal(
            trigger_type=trigger_type,
            evidence=evidence,
            state_hash=state_hash(evidence),
            severity=self._severity(trigger_type),
        )
        created = self._store.record_trigger(
            {
                "trigger_type": signal.trigger_type,
                "severity": signal.severity,
                "trigger_evidence": signal.evidence,
                "state_hash": signal.state_hash,
                "first_seen_at": now.isoformat(),
                "last_seen_at": now.isoformat(),
                "last_invoked_at": now.isoformat() if invoke else None,
                "invocation_result": result,
            }
        )
        return {
            "signal": signal.to_dict(),
            "first_seen": created,
            "invoked": invoke,
        }
