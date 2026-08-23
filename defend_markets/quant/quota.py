"""M4.7 versioned request quota governor (P15).

Explicit budget accounting per request class (EVENT_DISCOVERY, ODDS,
ATTESTATION, RESULT, HEALTH, RECONCILIATION). Results and near-commence odds
are reserved budget so low-value activity cannot consume the provider budget.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

QUOTA_GOVERNOR_POLICY_VERSION = "REQUEST_QUOTA_GOVERNOR_V1"

CLASS_EVENT_DISCOVERY = "EVENT_DISCOVERY"
CLASS_ODDS = "ODDS"
CLASS_ATTESTATION = "ATTESTATION"
CLASS_RESULT = "RESULT"
CLASS_HEALTH = "HEALTH"
CLASS_RECONCILIATION = "RECONCILIATION"

# Reserve a floor for RESULTS and near-commence ODDS so low-value calls
# (attestation sweeps, health checks) can never exhaust the provider budget.
RESERVED_FLOOR = {
    CLASS_RESULT: 15,
    CLASS_ODDS: 40,
}

DEFAULT_BUDGETS = {
    CLASS_EVENT_DISCOVERY: 60,
    CLASS_ODDS: 200,
    CLASS_ATTESTATION: 20,
    CLASS_RESULT: 80,
    CLASS_HEALTH: 10,
    CLASS_RECONCILIATION: 30,
}


class RequestQuotaGovernor:
    """Per-class request budget with a reserved floor for high-value classes."""

    def __init__(self, store: Any, *, period: datetime | None = None) -> None:
        self._store = store
        self._period = (period or datetime.now(timezone.utc)).replace(minute=0, second=0, microsecond=0)

    def _period_iso(self) -> str:
        return self._period.isoformat().replace("+00:00", "Z")

    def ensure_budget(self, request_class: str) -> None:
        budget = DEFAULT_BUDGETS.get(request_class, 50)
        reserved = RESERVED_FLOOR.get(request_class, 0)
        self._store.upsert_quota_budget(request_class, self._period_iso(), budget, reserved)

    def check(self, request_class: str, *, amount: int = 1) -> tuple[bool, dict[str, Any]]:
        self.ensure_budget(request_class)
        state = self._store.quota_used(request_class, self._period_iso())
        available = int(state.get("budget", 0)) - int(state.get("used", 0))
        return available >= amount, {
            "request_class": request_class,
            "budget": int(state.get("budget", 0)),
            "used": int(state.get("used", 0)),
            "available": available,
            "policy_version": QUOTA_GOVERNOR_POLICY_VERSION,
        }

    def consume(self, request_class: str, *, amount: int = 1) -> bool:
        allowed, state = self.check(request_class, amount=amount)
        if not allowed:
            return False
        self._store.consume_quota(request_class, self._period_iso(), amount)
        return True

    def snapshot(self) -> dict[str, Any]:
        out = {}
        for request_class in DEFAULT_BUDGETS:
            state = self._store.quota_used(request_class, self._period_iso())
            out[request_class] = {
                "budget": int(state.get("budget", 0)),
                "used": int(state.get("used", 0)),
                "reserved": int(state.get("reserved", 0)),
                "available": int(state.get("budget", 0)) - int(state.get("used", 0)),
            }
        return {"period": self._period_iso(), "policy_version": QUOTA_GOVERNOR_POLICY_VERSION, "classes": out}
