"""M4.7.2 per-HTTP provider request governance (P5-P11).

Every external Odds-API.io HTTP request passes through one canonical boundary:
ProviderRequestExecutor.execute(...). Before each attempt it atomically reserves
provider-wide capacity, enforces class policy / protected reserve, evaluates the
circuit, acquires a HALF_OPEN lease if needed, marks the attempt, executes HTTP,
classifies the outcome, persists evidence, finalizes quota accounting and
updates the breaker.

Also provides the provider-wide shared operational capacity model (P9/P10):
a single atomic store of total budget + protected RESULT/ODDS reserves so
low-priority classes (ATTESTATION/HEALTH/RECONCILIATION) cannot consume
protected capacity.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from defend_markets.quant.circuit_breaker import ProviderCircuitBreaker

GOVERNANCE_POLICY_VERSION = "PROVIDER_REQUEST_GOVERNANCE_V1"
CAPACITY_POLICY_VERSION = "PROVIDER_CAPACITY_V1"

CLASS_EVENT_DISCOVERY = "EVENT_DISCOVERY"
CLASS_ODDS = "ODDS"
CLASS_ATTESTATION = "ATTESTATION"
CLASS_RESULT = "RESULT"
CLASS_HEALTH = "HEALTH"
CLASS_RECONCILIATION = "RECONCILIATION"

PROTECTED_CLASSES = (CLASS_RESULT, CLASS_ODDS)
LOW_PRIORITY_CLASSES = (CLASS_ATTESTATION, CLASS_HEALTH, CLASS_RECONCILIATION)

# P9 default shared provider operational budget + protected reserves.
DEFAULT_TOTAL_BUDGET = 100
DEFAULT_RESULT_RESERVE = 15
DEFAULT_ODDS_RESERVE = 40

# outcome classes (P8)
OUTCOME_SUCCESS = "SUCCESS"
OUTCOME_NOT_FOUND = "NOT_FOUND"  # 404 (event retention)
OUTCOME_CONFIGURATION = "CONFIGURATION_ERROR"  # 401/403
OUTCOME_RATE_LIMIT = "RATE_LIMIT"  # 429
OUTCOME_PROVIDER_FAILURE = "PROVIDER_FAILURE"  # 5xx/network
OUTCOME_PROTOCOL_ERROR = "PROVIDER_PROTOCOL_ERROR"  # schema-invalid 200
OUTCOME_NO_RESPONSE = "NO_RESPONSE"


def classify_http_outcome(*, status_code: int | None, schema_understood: bool = True) -> str:
    """P8: classify an HTTP outcome deterministically."""
    if status_code is None:
        return OUTCOME_NO_RESPONSE
    if status_code == 404:
        return OUTCOME_NOT_FOUND
    if status_code in (401, 403):
        return OUTCOME_CONFIGURATION
    if status_code == 429:
        return OUTCOME_RATE_LIMIT
    if 500 <= status_code < 600:
        return OUTCOME_PROVIDER_FAILURE
    if status_code == 200 and not schema_understood:
        return OUTCOME_PROTOCOL_ERROR
    return OUTCOME_SUCCESS


@dataclass(frozen=True)
class GovernedRequest:
    """Result of a governed HTTP attempt."""

    allowed: bool
    blocked_reason: str | None = None
    status_code: int | None = None
    outcome_class: str | None = None
    consumed: bool = False
    payload: Any = None
    evidence: dict[str, Any] | None = None
    governance_id: Any = None


class ProviderRequestExecutor:
    """Single canonical per-HTTP governance boundary (P5)."""

    def __init__(self, store: Any, *, breaker: ProviderCircuitBreaker | None = None) -> None:
        self._store = store
        self._breaker = breaker or ProviderCircuitBreaker(store)

    def execute(
        self,
        *,
        provider: str,
        request_class: str,
        operation: str,
        request_metadata: dict[str, Any] | None,
        callable: Callable[[], Any],
        amount: int = 1,
    ) -> GovernedRequest:
        """Govern and execute exactly one provider HTTP attempt.

        Returns a GovernedRequest; the callable result is only invoked when the
        request is allowed (capacity + circuit pass).
        """
        now = datetime.now(timezone.utc)
        period_start = now.replace(minute=0, second=0, microsecond=0)
        metadata = request_metadata or {}

        # 1. atomic provider-wide capacity reservation (P9/P10)
        reserved = self._store.reserve_provider_capacity(
            provider, period_start, request_class, amount=amount
        )
        if not reserved:
            return GovernedRequest(allowed=False, blocked_reason="capacity_unavailable")

        # 2. circuit evaluation (+ HALF_OPEN probe lease)
        if not self._breaker.allow_request(provider, operation):
            self._store.release_provider_capacity(provider, period_start, amount=amount)
            return GovernedRequest(allowed=False, blocked_reason="circuit_open")

        # 3. mark attempt + execute
        governance_id = self._store.record_http_governance(
            {
                "provider": provider,
                "request_class": request_class,
                "operation": operation,
                "reserved_at": now.isoformat().replace("+00:00", "Z"),
                "attempted_at": now.isoformat().replace("+00:00", "Z"),
                "blocked_before_send": False,
                "consumed": True,
                "request_evidence_id": metadata.get("request_id"),
            }
        )

        result: Any = None
        status_code: int | None = None
        schema_understood = True
        error: str | None = None
        try:
            result = callable()
            status_code = self._extract_status(result, metadata)
            schema_understood = self._extract_schema(result, metadata)
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"

        outcome = classify_http_outcome(status_code=status_code, schema_understood=schema_understood)

        # 4. finalize: mark completion + update breaker
        self._store.complete_http_governance(
            governance_id,
            {
                "completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "http_status": status_code,
                "outcome_class": outcome,
                "consumed": True,
            },
        )
        if outcome in (OUTCOME_PROVIDER_FAILURE, OUTCOME_NO_RESPONSE):
            self._breaker.record_failure(provider, operation, error=error or outcome)
        elif outcome == OUTCOME_CONFIGURATION:
            self._breaker.record_failure(provider, operation, error=error or outcome, configuration_error=True)
        elif outcome == OUTCOME_PROTOCOL_ERROR:
            self._breaker.record_failure(provider, operation, error=error or outcome)
        else:
            self._breaker.record_success(provider, operation)

        return GovernedRequest(
            allowed=True,
            status_code=status_code,
            outcome_class=outcome,
            consumed=True,
            payload=result,
            governance_id=governance_id,
        )

    def _extract_status(self, result: Any, metadata: dict[str, Any]) -> int | None:
        if metadata.get("status_code") is not None:
            return int(metadata["status_code"])
        if result is not None and isinstance(result, tuple):
            first = result[0]
            if hasattr(first, "status_code"):
                return int(first.status_code)
        return None

    def _extract_schema(self, result: Any, metadata: dict[str, Any]) -> bool:
        return bool(metadata.get("schema_understood", True))


class ProviderCapacity:
    """P9/P10: provider-wide shared operational capacity with protected reserves.

    Low-priority classes may only use capacity OUTSIDE the protected reserve;
    RESULT/ODDS may consume the protected reserve too. Reservations and
    consumption are atomic (single store operation) so two workers cannot both
    spend the final slot.
    """

    def __init__(self, store: Any, *, period: datetime | None = None) -> None:
        self._store = store
        self._period = (period or datetime.now(timezone.utc)).replace(minute=0, second=0, microsecond=0)

    def _period_iso(self) -> str:
        return self._period.isoformat().replace("+00:00", "Z")

    def ensure(self, provider: str = "odds_api_io") -> None:
        self._store.upsert_provider_capacity(
            provider,
            self._period_iso(),
            total_budget=DEFAULT_TOTAL_BUDGET,
            reserved_result=DEFAULT_RESULT_RESERVE,
            reserved_odds=DEFAULT_ODDS_RESERVE,
        )

    def snapshot(self, provider: str = "odds_api_io") -> dict[str, Any]:
        self.ensure(provider)
        row = self._store.get_provider_capacity(provider, self._period_iso())
        used = int(row.get("used", 0))
        total = int(row.get("total_budget", 0))
        return {
            "provider": provider,
            "period": self._period_iso(),
            "total_budget": total,
            "used": used,
            "available": total - used,
            "reserved_result": int(row.get("reserved_result", 0)),
            "reserved_odds": int(row.get("reserved_odds", 0)),
            "policy_version": CAPACITY_POLICY_VERSION,
        }
