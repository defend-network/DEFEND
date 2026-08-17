"""Canonical typed domain models for DEFENDmarkets.

Point-in-time philosophy: thesis-driving observations distinguish the
event/effective time (``event_time``), the published/observed time
(``observed_at``) and the retrieved/ingested time (``received_at``).
Adapters must never fabricate a timestamp the source schema cannot
provide; unavailable fields stay ``None`` and are reported through
``PitAvailability`` so consumers can gate on what was knowable when.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Mapping


class InstrumentType(Enum):
    SPORTS_MARKET = "SPORTS_MARKET"
    EQUITY = "EQUITY"
    ETF = "ETF"
    INDEX = "INDEX"
    MACRO_SERIES = "MACRO_SERIES"
    PREDICTION_CONTRACT = "PREDICTION_CONTRACT"
    FUTURES = "FUTURES"
    OPTIONS = "OPTIONS"
    CRYPTO_SPOT = "CRYPTO_SPOT"
    CRYPTO_DERIVATIVE = "CRYPTO_DERIVATIVE"


class InstrumentStatus(Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class EventStatus(Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class StrategyLifecycle(Enum):
    PLANNED = "PLANNED"
    EXPERIMENTAL = "EXPERIMENTAL"
    PAPER = "PAPER"
    VALIDATED = "VALIDATED"
    RETIRED = "RETIRED"


class RiskTier(Enum):
    CONSERVATIVE = "CONSERVATIVE"
    CORE = "CORE"
    AGGRESSIVE = "AGGRESSIVE"


class DecisionType(Enum):
    OPPORTUNITY = "OPPORTUNITY"
    NO_ACTION = "NO_ACTION"


class NoActionReason(Enum):
    INSUFFICIENT_EDGE = "insufficient_edge"
    STALE_DATA = "stale_data"
    BELOW_RISK_POLICY = "below_risk_policy"
    MISSING_PROVENANCE = "missing_provenance"
    INSUFFICIENT_LIQUIDITY = "insufficient_liquidity"
    COSTS_EXCEED_EDGE = "costs_exceed_edge"
    COSTS_UNACCOUNTED = "costs_unaccounted"
    PROVIDER_UNHEALTHY = "provider_unhealthy"
    NO_ELIGIBLE_DATA = "no_eligible_data"
    STRATEGY_NOT_ELIGIBLE = "strategy_not_eligible"


def _require_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be blank")
    return value


def _require_aware_datetime(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    return value


def _require_optional_datetime(name: str, value: object) -> datetime | None:
    if value is None:
        return None
    return _require_aware_datetime(name, value)


def _require_probability(name: str, value: object) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite() or not (Decimal("0") <= value <= Decimal("1")):
        raise ValueError(f"{name} must be a finite Decimal between 0 and 1")
    return value


def _require_optional_decimal(name: str, value: object) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{name} must be a finite Decimal")
    return value


@dataclass(frozen=True)
class PitAvailability:
    """Explicit statement of which point-in-time fields a source provides.

    Never fabricate history: ``provided`` is the set of field names the
    source actually carries; missing PIT fields must be treated as unknown
    rather than synthesized.
    """

    provided: frozenset[str] = frozenset()
    limitations: tuple[str, ...] = ()

    def has(self, field_name: str) -> bool:
        return field_name in self.provided

    def __post_init__(self) -> None:
        object.__setattr__(self, "provided", frozenset(self.provided))
        object.__setattr__(self, "limitations", tuple(self.limitations))


@dataclass(frozen=True)
class ProvenanceStamp:
    """One observed fact plus where and when it was known."""

    source_key: str = ""
    observed_at: datetime | None = None
    received_at: datetime | None = None
    raw_ref: str | None = None
    normalization_version: str | None = None

    def __post_init__(self) -> None:
        _require_text("source_key", self.source_key)
        object.__setattr__(self, "observed_at", _require_optional_datetime("observed_at", self.observed_at))
        object.__setattr__(self, "received_at", _require_optional_datetime("received_at", self.received_at))
        if self.raw_ref is not None:
            object.__setattr__(self, "raw_ref", _require_text("raw_ref", self.raw_ref))


@dataclass(frozen=True)
class MarketInstrument:
    instrument_key: str = ""
    instrument_type: InstrumentType = InstrumentType.SPORTS_MARKET
    display_name: str = ""
    venue_key: str = ""
    status: InstrumentStatus = InstrumentStatus.ACTIVE
    taxonomy: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text("instrument_key", self.instrument_key)
        _require_text("display_name", self.display_name)
        _require_text("venue_key", self.venue_key)
        if not isinstance(self.instrument_type, InstrumentType):
            raise ValueError("instrument_type must be an InstrumentType")
        if not isinstance(self.status, InstrumentStatus):
            raise ValueError("status must be an InstrumentStatus")
        if not isinstance(self.taxonomy, Mapping):
            raise ValueError("taxonomy must be a mapping")


@dataclass(frozen=True)
class MarketEvent:
    event_key: str = ""
    event_type: str = ""
    title: str = ""
    event_time: datetime | None = None
    announced_at: datetime | None = None
    retrieved_at: datetime | None = None
    source_key: str = ""
    status: EventStatus = EventStatus.OPEN
    detail: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text("event_key", self.event_key)
        _require_text("event_type", self.event_type)
        _require_text("title", self.title)
        _require_text("source_key", self.source_key)
        object.__setattr__(self, "event_time", _require_optional_datetime("event_time", self.event_time))
        object.__setattr__(self, "announced_at", _require_optional_datetime("announced_at", self.announced_at))
        object.__setattr__(self, "retrieved_at", _require_optional_datetime("retrieved_at", self.retrieved_at))
        if not isinstance(self.status, EventStatus):
            raise ValueError("status must be an EventStatus")


@dataclass(frozen=True)
class EventEntity:
    entity_key: str = ""
    entity_type: str = ""
    display_name: str = ""
    taxonomy: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text("entity_key", self.entity_key)
        _require_text("entity_type", self.entity_type)
        _require_text("display_name", self.display_name)
        if not isinstance(self.taxonomy, Mapping):
            raise ValueError("taxonomy must be a mapping")


@dataclass(frozen=True)
class EventEntityLink:
    event_key: str = ""
    entity_key: str = ""
    role: str = ""
    valid_from: datetime | None = None
    valid_to: datetime | None = None

    def __post_init__(self) -> None:
        _require_text("event_key", self.event_key)
        _require_text("entity_key", self.entity_key)
        _require_text("role", self.role)
        object.__setattr__(self, "valid_from", _require_optional_datetime("valid_from", self.valid_from))
        object.__setattr__(self, "valid_to", _require_optional_datetime("valid_to", self.valid_to))


@dataclass(frozen=True)
class EventImpactWindow:
    event_key: str = ""
    instrument_key: str = ""
    window_start: datetime | None = None
    window_end: datetime | None = None
    direction: str = "UNKNOWN"
    strength: Decimal = Decimal("0")
    evidence_ref: str | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        _require_text("event_key", self.event_key)
        _require_text("instrument_key", self.instrument_key)
        if self.direction not in ("POSITIVE", "NEGATIVE", "NEUTRAL", "UNKNOWN"):
            raise ValueError("direction must be POSITIVE, NEGATIVE, NEUTRAL, or UNKNOWN")
        if not isinstance(self.strength, Decimal) or not (-1 <= self.strength <= 1):
            raise ValueError("strength must be a Decimal in -1..1")
        start = _require_optional_datetime("window_start", self.window_start)
        end = _require_optional_datetime("window_end", self.window_end)
        if start is not None and end is not None and end <= start:
            raise ValueError("window_end must be after window_start")


@dataclass(frozen=True)
class StrategyDefinition:
    strategy_key: str = ""
    version: int = 1
    display_name: str = ""
    hypothesis: str = ""
    lifecycle: StrategyLifecycle = StrategyLifecycle.EXPERIMENTAL
    params: Mapping[str, object] = field(default_factory=dict)
    source_ref: str | None = None

    def __post_init__(self) -> None:
        _require_text("strategy_key", self.strategy_key)
        _require_text("display_name", self.display_name)
        _require_text("hypothesis", self.hypothesis)
        if not isinstance(self.version, int) or self.version <= 0:
            raise ValueError("version must be a positive integer")
        if not isinstance(self.lifecycle, StrategyLifecycle):
            raise ValueError("lifecycle must be a StrategyLifecycle")
        if not isinstance(self.params, Mapping):
            raise ValueError("params must be a mapping")


@dataclass(frozen=True)
class RiskPolicy:
    policy_key: str = ""
    version: int = 1
    tier: RiskTier = RiskTier.CORE
    min_data_quality: Decimal = Decimal("0.7")
    min_confidence: Decimal = Decimal("0.5")
    max_concentration: Decimal = Decimal("0.2")
    allowed_desks: tuple[str, ...] = ("sports",)
    max_horizon: timedelta | None = None
    max_loss_pct: Decimal = Decimal("0.02")

    def __post_init__(self) -> None:
        _require_text("policy_key", self.policy_key)
        if not isinstance(self.version, int) or self.version <= 0:
            raise ValueError("version must be a positive integer")
        if not isinstance(self.tier, RiskTier):
            raise ValueError("tier must be a RiskTier")
        _require_probability("min_data_quality", self.min_data_quality)
        _require_probability("min_confidence", self.min_confidence)
        _require_probability("max_concentration", self.max_concentration)
        object.__setattr__(self, "allowed_desks", tuple(self.allowed_desks))
        if not self.allowed_desks:
            raise ValueError("allowed_desks must not be empty")
        if not isinstance(self.max_loss_pct, Decimal) or not (0 <= self.max_loss_pct <= 1):
            raise ValueError("max_loss_pct must be a Decimal in 0..1")


@dataclass(frozen=True)
class CostModel:
    """Execution costs. Unknown components are None, never zero."""

    vig: Decimal | None = None
    spread: Decimal | None = None
    slippage: Decimal | None = None
    fees: Decimal | None = None
    other_costs: Decimal | None = None

    def __post_init__(self) -> None:
        for name in ("vig", "spread", "slippage", "fees", "other_costs"):
            object.__setattr__(self, name, _require_optional_decimal(name, getattr(self, name)))

    def total(self) -> Decimal | None:
        parts = [value for value in (self.vig, self.spread, self.slippage, self.fees, self.other_costs) if value is not None]
        if not parts:
            return None
        return sum(parts, Decimal("0"))

    def components(self) -> Mapping[str, Decimal | None]:
        return {
            "vig": self.vig,
            "spread": self.spread,
            "slippage": self.slippage,
            "fees": self.fees,
            "other_costs": self.other_costs,
            "total": self.total(),
        }


@dataclass(frozen=True)
class Opportunity:
    """Ranked analysis artifact. Confidence and expected value are distinct.

    ``gross_edge`` is signal strength before costs; ``net_edge`` is the
    post-cost expected edge. Never claim a positive edge when costs are
    unknown: if costs are required and absent, ``net_edge`` must be None.
    """

    instrument_key: str = ""
    strategy_key: str = ""
    strategy_version: int = 1
    policy_key: str = ""
    policy_version: int = 1
    direction: str = ""
    horizon: str = ""
    thesis: str = ""
    counter_thesis: str | None = None
    evidence: tuple[Mapping[str, object], ...] = ()
    historical_analogs: tuple[Mapping[str, object], ...] = ()
    gross_edge: Decimal | None = None
    net_edge: Decimal | None = None
    costs: CostModel = field(default_factory=CostModel)
    confidence: Decimal = Decimal("0")
    expected_value: Decimal | None = None
    max_loss: Decimal | None = None
    data_quality: Decimal = Decimal("0")
    data_quality_note: str | None = None
    risk_tier: RiskTier = RiskTier.CORE
    model_version: str | None = None
    invalidation: str = ""
    provenance: tuple[ProvenanceStamp, ...] = ()
    generated_at: datetime | None = None
    reasoner_label: str | None = None

    def __post_init__(self) -> None:
        _require_text("instrument_key", self.instrument_key)
        _require_text("strategy_key", self.strategy_key)
        _require_text("policy_key", self.policy_key)
        _require_text("direction", self.direction)
        _require_text("horizon", self.horizon)
        _require_text("thesis", self.thesis)
        _require_text("invalidation", self.invalidation)
        _require_probability("confidence", self.confidence)
        _require_probability("data_quality", self.data_quality)
        for name in ("gross_edge", "net_edge", "expected_value", "max_loss"):
            object.__setattr__(self, name, _require_optional_decimal(name, getattr(self, name)))
        if not isinstance(self.costs, CostModel):
            raise ValueError("costs must be a CostModel")
        if not isinstance(self.risk_tier, RiskTier):
            raise ValueError("risk_tier must be a RiskTier")
        object.__setattr__(self, "evidence", tuple(self.evidence))
        object.__setattr__(self, "historical_analogs", tuple(self.historical_analogs))
        object.__setattr__(self, "provenance", tuple(self.provenance))
        object.__setattr__(self, "generated_at", _require_optional_datetime("generated_at", self.generated_at))

    @property
    def cost_estimate(self) -> Decimal | None:
        return self.costs.total()


@dataclass(frozen=True)
class DecisionRecord:
    """Append-only journal entry. Amendments are new records linked back.

    ``outcome`` starts None; historical content is never overwritten.
    """

    decision_id: str | None = None
    opportunity_id: str | None = None
    strategy_key: str = ""
    strategy_version: int = 1
    policy_key: str = ""
    policy_version: int = 1
    decision_type: DecisionType = DecisionType.NO_ACTION
    reason_codes: tuple[NoActionReason, ...] = ()
    thesis: str = ""
    counter_thesis: str | None = None
    confidence: Decimal | None = None
    estimated_edge: Decimal | None = None
    cost_estimate: Decimal | None = None
    data_cutoff_timestamp: datetime | None = None
    invalidation: str | None = None
    model_version: str | None = None
    created_at: datetime | None = None
    amendment_of: str | None = None
    outcome: "Outcome | None" = None
    note: str | None = None

    def __post_init__(self) -> None:
        _require_text("strategy_key", self.strategy_key)
        _require_text("policy_key", self.policy_key)
        _require_text("thesis", self.thesis)
        if not isinstance(self.decision_type, DecisionType):
            raise ValueError("decision_type must be a DecisionType")
        for name in ("confidence", "estimated_edge", "cost_estimate"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _require_optional_decimal(name, value))
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))
        if not all(isinstance(code, NoActionReason) for code in self.reason_codes):
            raise ValueError("reason_codes must be NoActionReason values")
        object.__setattr__(self, "data_cutoff_timestamp", _require_optional_datetime("data_cutoff_timestamp", self.data_cutoff_timestamp))
        object.__setattr__(self, "created_at", _require_optional_datetime("created_at", self.created_at))
        if self.decision_type is DecisionType.OPPORTUNITY and self.reason_codes:
            raise ValueError("OPPORTUNITY decisions must not carry NO_ACTION reason codes")

    @property
    def is_no_action(self) -> bool:
        return self.decision_type is DecisionType.NO_ACTION


@dataclass(frozen=True)
class Outcome:
    outcome_id: str | None = None
    decision_id: str = ""
    result: str = ""
    resolved_at: datetime | None = None
    pnl: Decimal | None = None
    clv: Decimal | None = None
    calibration_bucket: str | None = None
    detail: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text("decision_id", self.decision_id)
        if self.result not in ("WON", "LOST", "VOID", "PUSH", "UNREALIZED"):
            raise ValueError("result must be WON, LOST, VOID, PUSH, or UNREALIZED")
        object.__setattr__(self, "resolved_at", _require_optional_datetime("resolved_at", self.resolved_at))
        object.__setattr__(self, "pnl", _require_optional_decimal("pnl", self.pnl))
        object.__setattr__(self, "clv", _require_optional_decimal("clv", self.clv))


@dataclass(frozen=True)
class DataQualityAssessment:
    instrument_key: str = ""
    venue_key: str = ""
    score: Decimal = Decimal("0")
    freshness_ok: bool = False
    availability: str = "UNAVAILABLE"
    checks: Mapping[str, object] = field(default_factory=dict)
    as_of: datetime | None = None

    def __post_init__(self) -> None:
        _require_text("instrument_key", self.instrument_key)
        _require_text("venue_key", self.venue_key)
        _require_probability("score", self.score)
        if self.availability not in ("AVAILABLE", "STALE", "UNAVAILABLE"):
            raise ValueError("availability must be AVAILABLE, STALE, or UNAVAILABLE")
        object.__setattr__(self, "as_of", _require_optional_datetime("as_of", self.as_of))


@dataclass(frozen=True)
class RiskEvaluation:
    accepted: bool = False
    reasons: tuple[str, ...] = ()
    policy_key: str = ""
    policy_version: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "reasons", tuple(self.reasons))


@dataclass(frozen=True)
class HealthGateResult:
    """Data health gate outcome that can block or degrade a recommendation."""

    ok: bool = False
    freshness_ok: bool = False
    availability: str = "UNAVAILABLE"
    reasons: tuple[str, ...] = ()
    score: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        object.__setattr__(self, "reasons", tuple(self.reasons))
        _require_probability("score", self.score)


@dataclass(frozen=True)
class StrategyEvaluation:
    eligible: bool = False
    reasons: tuple[str, ...] = ()
    gross_edge: Decimal | None = None
    costs: CostModel = field(default_factory=CostModel)
    evidence: tuple[Mapping[str, object], ...] = ()
    confidence: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        object.__setattr__(self, "reasons", tuple(self.reasons))
        _require_probability("confidence", self.confidence)
        object.__setattr__(self, "gross_edge", _require_optional_decimal("gross_edge", self.gross_edge))
        object.__setattr__(self, "evidence", tuple(self.evidence))


@dataclass(frozen=True)
class DeskState:
    """Registry/presentation layer: what a desk offers right now, honestly."""

    desk_id: str = ""
    display_name: str = ""
    available: bool = False
    status: str = "pending"
    instruments: int = 0
    strategies: int = 0
    latest_decision_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_text("desk_id", self.desk_id)
        _require_text("display_name", self.display_name)
        _require_text("status", self.status)
        object.__setattr__(self, "latest_decision_at", _require_optional_datetime("latest_decision_at", self.latest_decision_at))


_KNOWN_HORIZONS: dict[str, timedelta] = {
    "scalping": timedelta(minutes=15),
    "intraday": timedelta(hours=8),
    "swing": timedelta(days=7),
    "positional": timedelta(days=90),
    "event": timedelta(days=2),
}


def horizon_duration(horizon: str) -> timedelta | None:
    return _KNOWN_HORIZONS.get((horizon or "").strip().lower())