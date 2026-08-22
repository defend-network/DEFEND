"""Quant Director runtime configuration: lifecycle state and AI cost budgets.

Runtime state controls whether scheduled supervisory AI work may run. When
Markets is STOPPED/STARTING/STOPPING no scheduled LLM calls occur and no
silent AI spend happens. Admin-initiated chat remains governed by budgets.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import os


class MarketsRuntimeState(str, Enum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    READY = "READY"
    DEGRADED = "DEGRADED"
    STOPPING = "STOPPING"


MARKETS_RUNTIME_STATE_DEFAULT = "STOPPED"


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    if value is None:
        return default
    if not value.strip():
        raise ValueError(f"{name} must not be empty")
    return value


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"{name} must be an integer") from None


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class QuantDirectorSettings:
    runtime_state: str = MARKETS_RUNTIME_STATE_DEFAULT
    enabled: bool = True
    max_daily_calls: int = 20
    daily_cost_soft_limit: float = 1.0
    daily_cost_hard_limit: float = 3.0
    trigger_cooldown_seconds: int = 600
    deep_research_allowed: bool = False
    provider: str = "openai"
    model_alias: str = "defendmarkets-quant-director"

    @classmethod
    def from_env(cls) -> "QuantDirectorSettings":
        raw_state = _env("MARKETS_RUNTIME_STATE", MARKETS_RUNTIME_STATE_DEFAULT)
        if raw_state not in {state.value for state in MarketsRuntimeState}:
            raise ValueError(f"MARKETS_RUNTIME_STATE must be one of {[s.value for s in MarketsRuntimeState]}")
        return cls(
            runtime_state=raw_state,
            enabled=_env_bool("MARKETS_AI_ENABLED", True),
            max_daily_calls=_env_int("MARKETS_AI_MAX_DAILY_CALLS", 20),
            daily_cost_soft_limit=float(
                _env("MARKETS_AI_DAILY_COST_SOFT_LIMIT", "1.00")
            ),
            daily_cost_hard_limit=float(
                _env("MARKETS_AI_DAILY_COST_HARD_LIMIT", "3.00")
            ),
            trigger_cooldown_seconds=_env_int("MARKETS_AI_TRIGGER_COOLDOWN", 600),
            deep_research_allowed=_env_bool("MARKETS_AI_DEEP_RESEARCH_ALLOWED", False),
            provider=_env("MARKETS_AI_PROVIDER", "openai"),
            model_alias=_env("MARKETS_AI_MODEL_ALIAS", "defendmarkets-quant-director"),
        )

    @property
    def markets_ready(self) -> bool:
        return self.runtime_state in (MarketsRuntimeState.READY.value, MarketsRuntimeState.DEGRADED.value)
