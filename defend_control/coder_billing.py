"""DEFENDcoder billing domain — thin internal interfaces (runtime-v1).

No Stripe SDK, no HTTP, no API calls, no credentials. StripeBillingProvider
is a later, explicitly separate integration. TestBillingProvider is
deterministic/in-memory for unit tests only — it is not a production payment
backend and must never be used for real charges.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal, Protocol

AccountTier = Literal["COMMUNITY", "STANDARD", "HEAVY", "MAXIMUM"]
SpendingLimitSource = Literal["PLATFORM", "USER"]
ReservationStatus = Literal["ACTIVE", "RELEASED", "EXPIRED", "CANCELLED"]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Account:
    account_id: str
    display_name: str
    tier: AccountTier = "COMMUNITY"
    created_at: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True)
class CreditBalance:
    account_id: str
    credits: Decimal
    updated_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if self.credits < 0:
            raise ValueError("credits must be non-negative")


@dataclass(frozen=True)
class CreditGrant:
    grant_id: str
    account_id: str
    amount: Decimal
    reason: str
    granted_at: datetime
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.amount <= 0:
            raise ValueError("grant amount must be positive")


@dataclass(frozen=True)
class UsageLedgerEntry:
    entry_id: str
    account_id: str
    run_id: str
    model_alias: str
    credits_debited: Decimal
    provider: str
    instance_id: int | None
    occurred_at: datetime
    notes: str = ""

    def __post_init__(self) -> None:
        if self.credits_debited < 0:
            raise ValueError("credits_debited must be non-negative")


@dataclass(frozen=True)
class ComputeReservation:
    reservation_id: str
    account_id: str
    alias: str
    instance_id: int | None
    hourly_rate: Decimal
    reserved_at: datetime
    expires_at: datetime
    status: ReservationStatus = "ACTIVE"


@dataclass(frozen=True)
class SpendingLimit:
    account_id: str
    limit_credits: Decimal
    effective_at: datetime = field(default_factory=_utcnow)
    source: SpendingLimitSource = "USER"

    def __post_init__(self) -> None:
        if self.limit_credits < 0:
            raise ValueError("limit_credits must be non-negative")
        if self.source not in ("PLATFORM", "USER"):
            raise ValueError("source must be PLATFORM or USER")


@dataclass(frozen=True)
class BillingPolicy:
    free_monthly_credit_allowance: Decimal = Decimal("5.00")
    subsidized_groups: tuple[str, ...] = ()
    cost_multiplier: Decimal = Decimal("1.00")
    max_member_spend: Decimal = Decimal("100.00")
    heavy_availability: bool = True
    auto_escalation_eligible: bool = True


class BillingProvider(Protocol):
    """Provider boundary: TestBillingProvider now, Stripe later."""

    def balance(self, account_id: str) -> Decimal: ...

    def apply_grant(self, grant: CreditGrant) -> None: ...

    def record_usage(self, entry: UsageLedgerEntry) -> UsageLedgerEntry: ...

    def reserve(self, reservation: ComputeReservation) -> ComputeReservation: ...

    def release(self, reservation_id: str) -> ComputeReservation: ...

    def set_platform_limit(self, limit: SpendingLimit) -> Decimal: ...

    def set_user_limit(self, limit: SpendingLimit) -> Decimal: ...


@dataclass
class TestBillingProvider:
    """Deterministic in-memory billing provider for unit tests only."""

    __test__ = False  # imported into test modules; not a pytest class

    _balances: dict[str, Decimal] = field(default_factory=dict)
    _ledger: dict[str, list[UsageLedgerEntry]] = field(default_factory=dict)
    _reservations: dict[str, ComputeReservation] = field(default_factory=dict)
    _platform_limits: dict[str, Decimal] = field(default_factory=dict)
    _user_limits: dict[str, Decimal] = field(default_factory=dict)

    def balance(self, account_id: str) -> Decimal:
        return self._balances.get(account_id, Decimal("0"))

    def apply_grant(self, grant: CreditGrant) -> None:
        self._balances[grant.account_id] = (
            self.balance(grant.account_id) + grant.amount
        )

    def record_usage(self, entry: UsageLedgerEntry) -> UsageLedgerEntry:
        current = self.balance(entry.account_id)
        if entry.credits_debited > current:
            raise ValueError(
                f"insufficient credits for account {entry.account_id}: "
                f"balance {current}, debited {entry.credits_debited}"
            )
        self._balances[entry.account_id] = current - entry.credits_debited
        self._ledger.setdefault(entry.account_id, []).append(entry)
        return entry

    def ledger(self, account_id: str) -> list[UsageLedgerEntry]:
        return list(self._ledger.get(account_id, []))

    def reserve(self, reservation: ComputeReservation) -> ComputeReservation:
        self._reservations[reservation.reservation_id] = reservation
        return reservation

    def release(self, reservation_id: str) -> ComputeReservation:
        reservation = self._reservations[reservation_id]
        released = replace(reservation, status="RELEASED")
        self._reservations[reservation_id] = released
        return released

    def active_reservations(self, account_id: str) -> list[str]:
        return [
            r.reservation_id
            for r in self._reservations.values()
            if r.account_id == account_id and r.status == "ACTIVE"
        ]

    def set_platform_limit(self, limit: SpendingLimit) -> Decimal:
        self._platform_limits[limit.account_id] = limit.limit_credits
        return limit.limit_credits

    def set_user_limit(self, limit: SpendingLimit) -> Decimal:
        platform = self._platform_limits.get(limit.account_id)
        if platform is not None and limit.limit_credits > platform:
            raise ValueError(
                f"user limit exceeds platform limit {platform} for account "
                f"{limit.account_id}"
            )
        self._user_limits[limit.account_id] = limit.limit_credits
        return limit.limit_credits