"""Canonical sports arbitrage models.

Every externally supplied odds/money value is normalized into :class:`Decimal`
with an explicit precision policy. Binary float is never authoritative for
money or odds arithmetic.

Precision policy:

* Odds are quantized to 3 fractional digits (1.234) internally and must be
  strictly greater than ``1.0`` for a decodable decimal quote.
* Money amounts are quantized to 2 fractional digits (0.01) unless a caller
  supplies a different ``money_precision`` in the policy.
* NaN / Infinity / non-finite values are rejected outright.

The :class:`ArbQuote` is immutable evidence: a point-in-time observation of
one selection offered by one bookmaker. Quotes are never mutated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
import hashlib
from typing import Mapping

ODDS_QUANTUM = Decimal("0.001")
MONEY_QUANTUM = Decimal("0.01")
PROBABILITY_QUANTUM = Decimal("0.00000001")
MIN_DECIMAL_ODDS = Decimal("1.0")


def _as_decimal(name: str, value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a Decimal")
    if isinstance(value, (int, float, str)):
        try:
            return Decimal(str(value))
        except Exception as exc:  # noqa: BLE001 - any failure means invalid
            raise ValueError(f"{name} is not a valid decimal: {value!r}") from exc
    raise ValueError(f"{name} must be a decimal-compatible value")


def validate_decimal_odds(name: str, value: object, *, quantum: Decimal = ODDS_QUANTUM) -> Decimal:
    """Normalize a decimal odds value.

    Rejects NaN, Infinity and odds ``<= 1.0``. Returns a quantized Decimal.
    """
    dec = _as_decimal(name, value)
    if not dec.is_finite():
        raise ValueError(f"{name} must be finite (no NaN/Infinity)")
    if dec <= MIN_DECIMAL_ODDS:
        raise ValueError(f"{name} must be greater than 1.0, got {dec}")
    return dec.quantize(quantum, rounding=ROUND_HALF_UP)


def validate_money_amount(name: str, value: object, *, quantum: Decimal = MONEY_QUANTUM) -> Decimal:
    """Normalize a money amount (>= 0). Rejects NaN/Infinity/negative values."""
    dec = _as_decimal(name, value)
    if not dec.is_finite():
        raise ValueError(f"{name} must be finite (no NaN/Infinity)")
    if dec < 0:
        raise ValueError(f"{name} must not be negative")
    return dec.quantize(quantum, rounding=ROUND_HALF_UP)


def validate_policy_probability(name: str, value: object) -> Decimal:
    """Normalize a policy probability in [0, 1] as a Decimal."""
    dec = _as_decimal(name, value)
    if not dec.is_finite():
        raise ValueError(f"{name} must be finite (no NaN/Infinity)")
    if not (Decimal("0") <= dec <= Decimal("1")):
        raise ValueError(f"{name} must be in [0, 1]")
    return dec.quantize(PROBABILITY_QUANTUM, rounding=ROUND_HALF_UP)


def _require_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be blank")
    return value.strip()


def _require_aware_datetime(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    return value


def _require_optional_datetime(name: str, value: object) -> datetime | None:
    if value is None:
        return None
    return _require_aware_datetime(name, value)


class MarketFamily(str, Enum):
    """Canonical market families supported by M1.

    Only identical families may be combined in an arbitrage.
    """

    MATCH_WINNER_2WAY = "MATCH_WINNER_2WAY"
    MATCH_WINNER_3WAY = "MATCH_WINNER_3WAY"
    SPREAD = "SPREAD"
    TOTAL = "TOTAL"


class SelectionSide(str, Enum):
    """Canonical selection side relative to participant A/B orientation."""

    PARTICIPANT_A = "PARTICIPANT_A"
    PARTICIPANT_B = "PARTICIPANT_B"
    DRAW = "DRAW"
    OVER = "OVER"
    UNDER = "UNDER"


class EventState(str, Enum):
    PRE_MATCH = "PRE_MATCH"
    LIVE = "LIVE"
    POST_COMMENCE = "POST_COMMENCE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class BookmakerLimits:
    """Per-bookmaker stake limits. Unknown limits are None, never infinite."""

    max_stake: Decimal | None = None
    min_stake: Decimal | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_stake",
            validate_money_amount("max_stake", self.max_stake) if self.max_stake is not None else None,
        )
        object.__setattr__(
            self,
            "min_stake",
            validate_money_amount("min_stake", self.min_stake) if self.min_stake is not None else None,
        )
        if self.max_stake is not None and self.min_stake is not None:
            if self.min_stake > self.max_stake:
                raise ValueError("min_stake must not exceed max_stake")


@dataclass(frozen=True)
class ArbQuote:
    """Immutable canonical quote: one selection, one bookmaker, one point in time.

    ``quote_id`` is the provider quote identity when available; ``raw_hash`` is
    a stable hash of the raw evidence so the same feed row is never silently
    re-interpreted.
    """

    quote_id: str = ""
    canonical_event_id: str = ""
    provider_event_id: str | None = None
    bookmaker: str = ""
    sport: str = ""
    competition: str | None = None
    participant_a: str = ""
    participant_b: str = ""
    commence_time: datetime | None = None
    market_family: MarketFamily = MarketFamily.MATCH_WINNER_2WAY
    period: str = "FULL_MATCH"
    selection: str = ""
    selection_side: SelectionSide = SelectionSide.PARTICIPANT_A
    line: Decimal | None = None
    decimal_odds: Decimal = Decimal("1.0")
    observed_at: datetime | None = None
    provider_updated_at: datetime | None = None
    received_at: datetime | None = None
    event_state: EventState = EventState.PRE_MATCH
    max_stake: Decimal | None = None
    min_stake: Decimal | None = None
    currency: str = "USD"
    source_ref: str | None = None
    raw_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "quote_id", _require_text("quote_id", self.quote_id))
        object.__setattr__(self, "canonical_event_id", _require_text("canonical_event_id", self.canonical_event_id))
        object.__setattr__(self, "bookmaker", _require_text("bookmaker", self.bookmaker))
        object.__setattr__(self, "sport", _require_text("sport", self.sport))
        object.__setattr__(self, "participant_a", _require_text("participant_a", self.participant_a))
        object.__setattr__(self, "participant_b", _require_text("participant_b", self.participant_b))
        object.__setattr__(self, "selection", _require_text("selection", self.selection))
        object.__setattr__(self, "period", _require_text("period", self.period))
        object.__setattr__(self, "currency", _require_text("currency", self.currency))
        if not isinstance(self.market_family, MarketFamily):
            raise ValueError("market_family must be a MarketFamily")
        if not isinstance(self.selection_side, SelectionSide):
            raise ValueError("selection_side must be a SelectionSide")
        if not isinstance(self.event_state, EventState):
            raise ValueError("event_state must be an EventState")
        object.__setattr__(self, "decimal_odds", validate_decimal_odds("decimal_odds", self.decimal_odds))
        object.__setattr__(self, "observed_at", _require_optional_datetime("observed_at", self.observed_at))
        object.__setattr__(self, "provider_updated_at", _require_optional_datetime("provider_updated_at", self.provider_updated_at))
        object.__setattr__(self, "received_at", _require_optional_datetime("received_at", self.received_at))
        object.__setattr__(self, "commence_time", _require_optional_datetime("commence_time", self.commence_time))
        object.__setattr__(self, "max_stake", validate_money_amount("max_stake", self.max_stake) if self.max_stake is not None else None)
        object.__setattr__(self, "min_stake", validate_money_amount("min_stake", self.min_stake) if self.min_stake is not None else None)
        object.__setattr__(self, "line", _require_optional_line(self.line))
        if self.max_stake is not None and self.min_stake is not None:
            if self.min_stake > self.max_stake:
                raise ValueError("min_stake must not exceed max_stake")
        if not self.raw_hash:
            object.__setattr__(self, "raw_hash", self.compute_raw_hash())

    def compute_raw_hash(self) -> str:
        payload = "|".join(
            (
                self.quote_id,
                self.canonical_event_id,
                self.provider_event_id or "",
                self.bookmaker,
                self.sport,
                self.competition or "",
                self.participant_a,
                self.participant_b,
                str(self.commence_time.timestamp()) if self.commence_time else "",
                self.market_family.value,
                self.period,
                self.selection,
                self.selection_side.value,
                str(self.line) if self.line is not None else "",
                str(self.decimal_odds),
                str(self.observed_at.timestamp()) if self.observed_at else "",
                str(self.provider_updated_at.timestamp()) if self.provider_updated_at else "",
                str(self.received_at.timestamp()) if self.received_at else "",
                self.event_state.value,
                str(self.max_stake) if self.max_stake is not None else "",
                str(self.min_stake) if self.min_stake is not None else "",
                self.currency,
                self.source_ref or "",
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _require_optional_line(value: object) -> Decimal | None:
    if value is None:
        return None
    dec = _as_decimal("line", value)
    if not dec.is_finite():
        raise ValueError("line must be finite (no NaN/Infinity)")
    return dec


@dataclass(frozen=True)
class StakeSettings:
    """Stake rounding and minimums policy."""

    stake_increment: Decimal = MONEY_QUANTUM
    money_precision: int = 2
    min_stake: Decimal = MONEY_QUANTUM

    def __post_init__(self) -> None:
        object.__setattr__(self, "stake_increment", validate_money_amount("stake_increment", self.stake_increment))
        if self.stake_increment <= 0:
            raise ValueError("stake_increment must be positive")
        if not isinstance(self.money_precision, int) or self.money_precision < 0:
            raise ValueError("money_precision must be a non-negative integer")
        object.__setattr__(self, "min_stake", validate_money_amount("min_stake", self.min_stake))


@dataclass(frozen=True)
class ExecutionCosts:
    """Optional per-leg execution cost model.

    Unknown components are None, never zero. Fixed costs are absolute per leg;
    rate components are fractions of the stake. The sportsbook default is zero
    explicit commission after using displayed decimal odds.
    """

    fixed_cost: Decimal | None = None
    commission_rate: Decimal | None = None
    exchange_fee_rate: Decimal | None = None
    other_rate: Decimal | None = None

    def __post_init__(self) -> None:
        for name in ("fixed_cost", "commission_rate", "exchange_fee_rate", "other_rate"):
            value = getattr(self, name)
            if value is None:
                continue
            dec = _as_decimal(name, value)
            if not dec.is_finite():
                raise ValueError(f"{name} must be finite")
            if name == "fixed_cost" and dec < 0:
                raise ValueError("fixed_cost must not be negative")
            if name in ("commission_rate", "exchange_fee_rate", "other_rate") and not (Decimal("0") <= dec <= Decimal("1")):
                raise ValueError(f"{name} must be in [0, 1]")
            object.__setattr__(self, name, dec)


@dataclass(frozen=True)
class ArbSettings:
    """Execution/classification policy. Every threshold is versioned."""

    policy_version: str = "sports-arb-core-m1"
    max_quote_age_seconds: float = 30.0
    max_cross_book_delta_seconds: float = 10.0
    pre_match_only: bool = True
    min_net_roi: Decimal = Decimal("0.005")
    execution_buffer: Decimal = Decimal("0.004")
    settlement_required: bool = False
    allow_same_book: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.policy_version, str) or not self.policy_version.strip():
            raise ValueError("policy_version must not be blank")
        for name in ("max_quote_age_seconds", "max_cross_book_delta_seconds"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or value <= 0:
                raise ValueError(f"{name} must be a positive number")
        object.__setattr__(self, "min_net_roi", validate_policy_probability("min_net_roi", self.min_net_roi))
        object.__setattr__(self, "execution_buffer", validate_policy_probability("execution_buffer", self.execution_buffer))

    def policy_id(self) -> str:
        return f"{self.policy_version}@min_net_roi={self.min_net_roi}"
