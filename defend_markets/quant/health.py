"""Explicit Quant Director health state.

Quant Director initialization/operation failures must be observable. State is
one of READY / NOT_CONFIGURED / DEGRADED / FAILED with a sanitized reason.
No exception is silently swallowed; credentials and stack traces are never
exposed to consumer surfaces.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from defend_markets.quant.model_aliases import runtime_credentials_present


class QuantDirectorHealthState(str, Enum):
    READY = "READY"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class QuantDirectorHealth:
    state: QuantDirectorHealthState
    reason: str
    runtime_model: str = ""
    initialized: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "reason": self.reason,
            "runtime_model": self.runtime_model,
            "initialized": self.initialized,
        }


def detect_health(
    *,
    initialized: bool,
    ai_configured: bool | None = None,
    runtime_model: str = "",
    error_class: str | None = None,
    degraded_reason: str | None = None,
) -> QuantDirectorHealth:
    if not initialized:
        if ai_configured is False or error_class is not None:
            return QuantDirectorHealth(
                state=QuantDirectorHealthState.FAILED,
                reason=f"initialization failed: {error_class or 'unknown error'}",
                runtime_model=runtime_model,
                initialized=False,
            )
        return QuantDirectorHealth(
            state=QuantDirectorHealthState.NOT_CONFIGURED,
            reason="not initialized",
            runtime_model=runtime_model,
            initialized=False,
        )
    if runtime_credentials_present():
        return QuantDirectorHealth(
            state=QuantDirectorHealthState.READY,
            reason="ready",
            runtime_model=runtime_model,
            initialized=True,
        )
    if degraded_reason:
        return QuantDirectorHealth(
            state=QuantDirectorHealthState.DEGRADED,
            reason=degraded_reason,
            runtime_model=runtime_model,
            initialized=True,
        )
    return QuantDirectorHealth(
        state=QuantDirectorHealthState.NOT_CONFIGURED,
        reason="no runtime AI credential configured; deterministic mock available",
        runtime_model=runtime_model,
        initialized=True,
    )
