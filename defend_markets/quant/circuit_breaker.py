"""M4.7 versioned provider circuit breaker (P14).

States: CLOSED / OPEN / HALF_OPEN, plus OPEN_CONFIGURATION for auth/credential
failures (never an endless retry). Tracks consecutive failures per
provider/function; a result-endpoint failure must never stop odds ingestion —
the breaker is keyed per (provider, function_name).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

CIRCUIT_BREAKER_POLICY_VERSION = "PROVIDER_CIRCUIT_BREAKER_V1"

STATE_CLOSED = "CLOSED"
STATE_OPEN = "OPEN"
STATE_HALF_OPEN = "HALF_OPEN"
STATE_OPEN_CONFIGURATION = "OPEN_CONFIGURATION"

_FAILURE_THRESHOLD = 3
_COOLDOWN_SECONDS = 300
_HALF_OPEN_ALLOWED_FAILURES = 1


class ProviderCircuitBreaker:
    """DB-persisted circuit breaker per (provider, function_name).

    P22: HALF_OPEN permits EXACTLY ONE probe at a time via an atomic lease;
    concurrent callers are deferred. P23: auth/config failures open
    OPEN_CONFIGURATION (no endless retry); a 404 event lookup is result/retention
    evidence and must NOT trip the provider-system breaker.
    """

    def __init__(self, store: Any, *, now: datetime | None = None) -> None:
        self._store = store
        self._now = now

    def _clock(self) -> datetime:
        return self._now or datetime.now(timezone.utc)

    def state(self, provider: str, function_name: str) -> dict[str, Any]:
        row = self._store.get_circuit_breaker(provider, function_name)
        if row is None:
            return {
                "provider": provider,
                "function_name": function_name,
                "state": STATE_CLOSED,
                "consecutive_failures": 0,
                "policy_version": CIRCUIT_BREAKER_POLICY_VERSION,
            }
        # Auto-recover OPEN -> HALF_OPEN after cooldown.
        state = row["state"]
        if state == STATE_OPEN:
            cooldown_until = row.get("cooldown_until")
            if cooldown_until is not None:
                if isinstance(cooldown_until, str):
                    from defend_markets.quant.market import parse_dt
                    cooldown = parse_dt(cooldown_until)
                else:
                    cooldown = cooldown_until
                if cooldown is not None and self._clock() >= cooldown:
                    state = STATE_HALF_OPEN
                    self._store.upsert_circuit_breaker(
                        {
                            "provider": provider,
                            "function_name": function_name,
                            "state": STATE_HALF_OPEN,
                            "consecutive_failures": row.get("consecutive_failures", 0),
                            "opened_at": row.get("opened_at"),
                            "cooldown_until": None,
                            "last_error": row.get("last_error"),
                            "policy_version": CIRCUIT_BREAKER_POLICY_VERSION,
                        }
                    )
        return dict(row, state=state)

    def allow_request(self, provider: str, function_name: str) -> bool:
        row = self.state(provider, function_name)
        if row["state"] == STATE_OPEN:
            return False
        if row["state"] == STATE_OPEN_CONFIGURATION:
            return False
        if row["state"] == STATE_HALF_OPEN:
            # HALF_OPEN requires an atomic probe lease (P22): only the caller
            # that wins the lease may probe.
            return self._store.try_claim_half_open_probe(provider, function_name)
        return True

    def record_success(self, provider: str, function_name: str) -> None:
        self._store.upsert_circuit_breaker(
            {
                "provider": provider,
                "function_name": function_name,
                "state": STATE_CLOSED,
                "consecutive_failures": 0,
                "opened_at": None,
                "cooldown_until": None,
                "last_error": None,
                "policy_version": CIRCUIT_BREAKER_POLICY_VERSION,
            }
        )

    def record_failure(self, provider: str, function_name: str, *, error: str, configuration_error: bool = False) -> str:
        """Record a failure and return the resulting state."""
        row = self._store.get_circuit_breaker(provider, function_name) or {
            "state": STATE_CLOSED,
            "consecutive_failures": 0,
        }
        if configuration_error:
            self._store.upsert_circuit_breaker(
                {
                    "provider": provider,
                    "function_name": function_name,
                    "state": STATE_OPEN_CONFIGURATION,
                    "consecutive_failures": row.get("consecutive_failures", 0) + 1,
                    "opened_at": self._clock(),
                    "cooldown_until": None,
                    "last_error": error,
                    "policy_version": CIRCUIT_BREAKER_POLICY_VERSION,
                }
            )
            return STATE_OPEN_CONFIGURATION
        failures = int(row.get("consecutive_failures", 0)) + 1
        if row.get("state") == STATE_HALF_OPEN and failures > _HALF_OPEN_ALLOWED_FAILURES:
            state = STATE_OPEN
        elif failures >= _FAILURE_THRESHOLD:
            state = STATE_OPEN
        else:
            state = STATE_HALF_OPEN if row.get("state") == STATE_HALF_OPEN else STATE_CLOSED
        self._store.upsert_circuit_breaker(
            {
                "provider": provider,
                "function_name": function_name,
                "state": state,
                "consecutive_failures": failures,
                "opened_at": row.get("opened_at") if state != STATE_OPEN else self._clock(),
                "cooldown_until": (self._clock() + timedelta(seconds=_COOLDOWN_SECONDS)) if state == STATE_OPEN else None,
                "last_error": error,
                "policy_version": CIRCUIT_BREAKER_POLICY_VERSION,
            }
        )
        return state
