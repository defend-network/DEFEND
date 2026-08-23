"""Deterministic execution-risk flags and settlement compatibility boundary.

Risk flags are descriptive labels attached to an opportunity based on
observable facts (quote age, unknown limits, tight bankroll, low margin,
rounding sensitivity, weak identity, unknown timestamps). They are *not*
invented probabilities.

Settlement compatibility is a placeholder boundary: M1 does not research every
bookmaker rule, but EXECUTABLE_ARB under a strict policy requires
``VERIFIED_COMPATIBLE``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from defend_markets.arb.models import ArbQuote


class RiskFlag(str, Enum):
    QUOTE_AGE_HIGH = "QUOTE_AGE_HIGH"
    CROSS_BOOK_TIME_DELTA_HIGH = "CROSS_BOOK_TIME_DELTA_HIGH"
    MAX_STAKE_UNKNOWN = "MAX_STAKE_UNKNOWN"
    MIN_STAKE_UNKNOWN = "MIN_STAKE_UNKNOWN"
    BANKROLL_TIGHT = "BANKROLL_TIGHT"
    LOW_MARGIN = "LOW_MARGIN"
    ROUNDING_SENSITIVE = "ROUNDING_SENSITIVE"
    MARKET_IDENTITY_WEAK = "MARKET_IDENTITY_WEAK"
    PARTICIPANT_IDENTITY_WEAK = "PARTICIPANT_IDENTITY_WEAK"
    SETTLEMENT_RULES_UNVERIFIED = "SETTLEMENT_RULES_UNVERIFIED"
    PROVIDER_TIMESTAMP_UNKNOWN = "PROVIDER_TIMESTAMP_UNKNOWN"


class SettlementStatus(str, Enum):
    VERIFIED_COMPATIBLE = "VERIFIED_COMPATIBLE"
    UNKNOWN = "UNKNOWN"
    INCOMPATIBLE = "INCOMPATIBLE"


@dataclass(frozen=True)
class SettlementCompatibility:
    """Statement about whether two legs settle under compatible rules."""

    status: SettlementStatus = SettlementStatus.UNKNOWN
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.status, SettlementStatus):
            raise ValueError("status must be a SettlementStatus")
        object.__setattr__(self, "notes", tuple(self.notes))

    @property
    def verified(self) -> bool:
        return self.status is SettlementStatus.VERIFIED_COMPATIBLE


@dataclass(frozen=True)
class RiskAssessment:
    flags: frozenset[RiskFlag] = frozenset()
    notes: tuple[str, ...] = ()
    settlement: SettlementCompatibility = field(default_factory=SettlementCompatibility)

    def __post_init__(self) -> None:
        object.__setattr__(self, "flags", frozenset(self.flags))
        object.__setattr__(self, "notes", tuple(self.notes))


def compute_risk_flags(
    quotes: tuple[ArbQuote, ...],
    *,
    margin: Decimal | None = None,
    low_margin_threshold: Decimal | None = None,
    max_quote_age_seconds: float | None = None,
    cross_book_delta_seconds: float | None = None,
    rounding_sensitive: bool = False,
    identity_weak: bool = False,
    participant_identity_weak: bool = False,
    settlement: SettlementCompatibility | None = None,
    bankroll_tight: bool = False,
) -> RiskAssessment:
    """Compute deterministic risk flags for an opportunity.

    All thresholds are explicit arguments; nothing is silently hard-coded.
    """
    flags: set[RiskFlag] = set()

    for quote in quotes:
        if quote.max_stake is None:
            flags.add(RiskFlag.MAX_STAKE_UNKNOWN)
        if quote.min_stake is None:
            flags.add(RiskFlag.MIN_STAKE_UNKNOWN)
        if quote.observed_at is None and quote.received_at is None and quote.provider_updated_at is None:
            flags.add(RiskFlag.PROVIDER_TIMESTAMP_UNKNOWN)

    if max_quote_age_seconds is not None:
        flags.add(RiskFlag.QUOTE_AGE_HIGH)

    if cross_book_delta_seconds is not None and cross_book_delta_seconds > 0:
        flags.add(RiskFlag.CROSS_BOOK_TIME_DELTA_HIGH)

    if bankroll_tight:
        flags.add(RiskFlag.BANKROLL_TIGHT)

    if margin is not None and low_margin_threshold is not None and margin <= low_margin_threshold:
        flags.add(RiskFlag.LOW_MARGIN)

    if rounding_sensitive:
        flags.add(RiskFlag.ROUNDING_SENSITIVE)

    if identity_weak:
        flags.add(RiskFlag.MARKET_IDENTITY_WEAK)

    if participant_identity_weak:
        flags.add(RiskFlag.PARTICIPANT_IDENTITY_WEAK)

    settlement_obj = settlement or SettlementCompatibility()
    if settlement_obj.status is not SettlementStatus.VERIFIED_COMPATIBLE:
        flags.add(RiskFlag.SETTLEMENT_RULES_UNVERIFIED)

    notes: list[str] = []
    if RiskFlag.SETTLEMENT_RULES_UNVERIFIED in flags:
        notes.append("settlement rules not verified compatible")
    if RiskFlag.MAX_STAKE_UNKNOWN in flags:
        notes.append("max stake unknown for at least one leg")

    return RiskAssessment(flags=frozenset(flags), notes=tuple(notes), settlement=settlement_obj)
