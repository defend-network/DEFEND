"""Opportunity snapshot, classification, deduplication and expiration.

An :class:`ArbOpportunity` is an immutable snapshot of every fact that
produced an arbitrage signal. Old snapshots are never mutated; new material
quote changes produce a new snapshot. Opportunities expire and are never
presented as currently actionable after ``expires_at``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
import hashlib

from defend_markets.arb.compatibility import CompatibilityResult, check_market_compatibility
from defend_markets.arb.freshness import FreshnessPolicy, FreshnessResult, evaluate_freshness
from defend_markets.arb.math import compute_inverse_sum, solve_equalized_plan
from defend_markets.arb.models import ArbQuote, ArbSettings, ExecutionCosts
from defend_markets.arb.risk import (
    RiskAssessment,
    RiskFlag,
    SettlementCompatibility,
    compute_risk_flags,
)
from defend_markets.arb.staking import (
    StakeConstraintState,
    StakingResult,
    solve_staking_plan,
)


class ArbClassification(str, Enum):
    NO_ARB = "NO_ARB"
    MATHEMATICAL_ARB = "MATHEMATICAL_ARB"
    EXECUTABLE_ARB = "EXECUTABLE_ARB"
    NEAR_ARB = "NEAR_ARB"
    INCOMPATIBLE = "INCOMPATIBLE"
    STALE = "STALE"
    INCOMPLETE = "INCOMPLETE"
    CONSTRAINT_BLOCKED = "CONSTRAINT_BLOCKED"
    POST_COMMENCE = "POST_COMMENCE"
    IDENTITY_AMBIGUOUS = "IDENTITY_AMBIGUOUS"
    EXPIRED = "EXPIRED"


NEAR_ARB_MAX_OVER = Decimal("0.005")


@dataclass(frozen=True)
class StakeLegPlan:
    bookmaker: str = ""
    quote_id: str = ""
    selection: str = ""
    selection_side: str = ""
    odds: Decimal = Decimal("0")
    stake: Decimal = Decimal("0")
    return_: Decimal = Decimal("0")
    max_stake: Decimal | None = None
    min_stake: Decimal | None = None


@dataclass(frozen=True)
class ArbOpportunity:
    """Immutable arbitrage opportunity snapshot."""

    opportunity_id: str = ""
    detected_at: datetime | None = None
    canonical_event_id: str = ""
    canonical_market_key: str = ""
    quotes: tuple[ArbQuote, ...] = ()
    bookmakers: tuple[str, ...] = ()
    outcomes: tuple[str, ...] = ()
    inverse_sum: Decimal = Decimal("0")
    raw_margin: Decimal = Decimal("0")
    total_stake: Decimal = Decimal("0")
    stake_plan: tuple[StakeLegPlan, ...] = ()
    return_by_outcome: tuple[Decimal, ...] = ()
    profit_by_outcome: tuple[Decimal, ...] = ()
    worst_case_profit: Decimal = Decimal("0")
    worst_case_roi: Decimal = Decimal("0")
    execution_cost: Decimal = Decimal("0")
    quote_age_by_leg: dict[str, float] = field(default_factory=dict)
    cross_book_time_delta: float | None = None
    compatibility_result: CompatibilityResult = CompatibilityResult.UNKNOWN
    stake_constraint_state: StakeConstraintState = StakeConstraintState.UNVERIFIED
    bankroll_constraint_state: str = "UNVERIFIED"
    freshness_state: str = "UNKNOWN"
    risk_flags: frozenset[RiskFlag] = frozenset()
    classification: ArbClassification = ArbClassification.NO_ARB
    policy_version: str = ""
    evidence_refs: tuple[str, ...] = ()
    expires_at: datetime | None = None
    last_verified_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "quotes", tuple(self.quotes))
        object.__setattr__(self, "bookmakers", tuple(self.bookmakers))
        object.__setattr__(self, "outcomes", tuple(self.outcomes))
        object.__setattr__(self, "stake_plan", tuple(self.stake_plan))
        object.__setattr__(self, "return_by_outcome", tuple(self.return_by_outcome))
        object.__setattr__(self, "profit_by_outcome", tuple(self.profit_by_outcome))
        object.__setattr__(self, "quote_age_by_leg", dict(self.quote_age_by_leg))
        object.__setattr__(self, "risk_flags", frozenset(self.risk_flags))
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))


def deduplication_fingerprint(
    canonical_market_key: str,
    quote_ids: tuple[str, ...],
    policy_version: str,
) -> str:
    """Stable fingerprint for an opportunity.

    Derived from the canonical market identity, the ordered quote IDs and the
    policy version. New material quote changes create a new snapshot.
    """
    payload = "|".join((canonical_market_key, "|".join(sorted(quote_ids)), policy_version))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def is_expired(opportunity: ArbOpportunity, *, now: datetime | None = None) -> bool:
    """True when the opportunity is past its ``expires_at`` (or has none)."""
    if opportunity.expires_at is None:
        return True
    now_value = now or datetime.now(timezone.utc)
    return now_value > opportunity.expires_at


def classify(
    *,
    is_arb: bool,
    compatibility: CompatibilityResult,
    freshness: FreshnessResult,
    staking: StakingResult | None,
    near_arb: bool = False,
    identity_ambiguous: bool = False,
    expired: bool = False,
    settlement_verified: bool = True,
    settlement_required: bool = False,
) -> ArbClassification:
    """Deterministic classification of an opportunity.

    EXECUTABLE_ARB requires more than ``inverse_sum < 1``: it additionally
    needs a compatible market, fresh quotes, feasible staking (rounding,
    limits, bankroll, fees) and — under strict policy — verified settlement
    rules.
    """
    if expired:
        return ArbClassification.EXPIRED

    if not is_arb and near_arb:
        return ArbClassification.NEAR_ARB

    if compatibility is CompatibilityResult.INCOMPATIBLE_EVENT:
        return ArbClassification.INCOMPATIBLE
    if compatibility is CompatibilityResult.INCOMPATIBLE_MARKET:
        return ArbClassification.INCOMPATIBLE
    if compatibility is CompatibilityResult.INCOMPATIBLE_PERIOD:
        return ArbClassification.INCOMPATIBLE
    if compatibility is CompatibilityResult.INCOMPATIBLE_LINE:
        return ArbClassification.INCOMPATIBLE
    if compatibility is CompatibilityResult.INCOMPATIBLE_SELECTION_SET:
        return ArbClassification.INCOMPATIBLE
    if compatibility is CompatibilityResult.INCOMPLETE_MARKET:
        return ArbClassification.INCOMPLETE
    if identity_ambiguous or compatibility is CompatibilityResult.AMBIGUOUS_IDENTITY:
        return ArbClassification.IDENTITY_AMBIGUOUS
    if compatibility is CompatibilityResult.POST_COMMENCE:
        return ArbClassification.POST_COMMENCE
    if compatibility is CompatibilityResult.STALE_QUOTE or not freshness.ok:
        return ArbClassification.STALE

    if not is_arb:
        return ArbClassification.NO_ARB

    if staking is None:
        return ArbClassification.MATHEMATICAL_ARB

    if not staking.feasible:
        return ArbClassification.CONSTRAINT_BLOCKED

    if staking.worst_case_profit <= 0 or staking.net_worst_case_roi <= 0:
        return ArbClassification.MATHEMATICAL_ARB

    if settlement_required and not settlement_verified:
        return ArbClassification.MATHEMATICAL_ARB

    return ArbClassification.EXECUTABLE_ARB


def build_opportunity(
    quotes: tuple[ArbQuote, ...],
    *,
    total_stake: Decimal,
    settings: ArbSettings | None = None,
    settlement: SettlementCompatibility | None = None,
    costs: ExecutionCosts | None = None,
    now: datetime | None = None,
    bankroll_by_book: dict[str, Decimal | None] | None = None,
    stake_settings: "StakeSettings | None" = None,
) -> ArbOpportunity:
    """Build an immutable opportunity from a set of quotes.

    Performs, in order: market compatibility, freshness, inverse-sum math,
    equalized staking, and deterministic classification. The returned
    opportunity is evidence-preserving and expires per policy.
    """
    settings = settings or ArbSettings()
    now_value = now or datetime.now(timezone.utc)

    if not quotes:
        raise ValueError("at least one quote is required")

    from defend_markets.arb.identity import CanonicalMarketKey

    canonical_key = CanonicalMarketKey.from_quote(quotes[0])
    canonical_market_key_str = canonical_key.human_key()

    # 1. Market compatibility.
    compatibility = check_market_compatibility(
        quotes,
        max_quote_age_seconds=settings.max_quote_age_seconds,
        now=now_value,
        pre_match_only=settings.pre_match_only,
    )

    # 2. Freshness.
    freshness = evaluate_freshness(
        quotes,
        FreshnessPolicy(
            max_quote_age_seconds=settings.max_quote_age_seconds,
            max_cross_book_delta_seconds=settings.max_cross_book_delta_seconds,
            pre_match_only=settings.pre_match_only,
        ),
        now=now_value,
    )

    # 3. Inverse-sum math (pure mathematical arb check).
    odds = tuple(q.decimal_odds for q in quotes)
    inverse_result = compute_inverse_sum(odds)
    is_arb = inverse_result.is_arb

    # 4. Staking.
    staking: StakingResult | None = None
    if is_arb and compatibility.compatible and freshness.ok:
        try:
            staking = solve_staking_plan(
                total_stake,
                odds,
                quotes,
                settings=stake_settings,
                costs=costs,
                bankroll_by_book=bankroll_by_book,
            )
        except ValueError:
            staking = None

    near_arb = (not is_arb) and (inverse_result.inverse_sum - Decimal("1") <= NEAR_ARB_MAX_OVER)

    # 5. Risk flags.
    settlement_obj = settlement or SettlementCompatibility()
    risk_assessment = compute_risk_flags(
        quotes,
        margin=inverse_result.margin,
        low_margin_threshold=settings.execution_buffer,
        max_quote_age_seconds=(
            settings.max_quote_age_seconds if freshness.stale_quotes else None
        ),
        cross_book_delta_seconds=freshness.cross_book.max_delta_seconds,
        rounding_sensitive=(
            staking is not None and staking.worst_case_roi > 0 and staking.worst_case_roi <= settings.execution_buffer
        ),
        identity_weak=not compatibility.compatible,
        settlement=settlement_obj,
    )

    classification = classify(
        is_arb=is_arb,
        compatibility=compatibility.result,
        freshness=freshness,
        staking=staking,
        near_arb=near_arb,
        identity_ambiguous=not compatibility.compatible and compatibility.result is CompatibilityResult.AMBIGUOUS_IDENTITY,
        settlement_verified=settlement_obj.verified,
        settlement_required=settings.settlement_required,
    )

    # 6. Stake plan representation.
    stake_plan: list[StakeLegPlan] = []
    if staking is not None:
        for i, quote in enumerate(quotes):
            stake_plan.append(
                StakeLegPlan(
                    bookmaker=quote.bookmaker,
                    quote_id=quote.quote_id,
                    selection=quote.selection,
                    selection_side=quote.selection_side.value,
                    odds=quote.decimal_odds,
                    stake=staking.rounded_stakes[i] if i < len(staking.rounded_stakes) else Decimal("0"),
                    return_=staking.return_by_outcome[i] if i < len(staking.return_by_outcome) else Decimal("0"),
                    max_stake=quote.max_stake,
                    min_stake=quote.min_stake,
                )
            )

    quote_age_by_leg: dict[str, float] = {}
    for quote in quotes:
        reference = quote.observed_at or quote.received_at or quote.provider_updated_at
        if reference is not None:
            quote_age_by_leg[quote.quote_id] = (now_value - reference).total_seconds()

    expires_at = now_value + timedelta(seconds=min(settings.max_quote_age_seconds, settings.max_cross_book_delta_seconds or settings.max_quote_age_seconds))

    fingerprint = deduplication_fingerprint(
        canonical_market_key_str,
        tuple(q.quote_id for q in quotes),
        settings.policy_id(),
    )

    bankroll_state = "VERIFIED"
    if bankroll_by_book:
        from defend_markets.arb.staking import bankroll_constraint_state

        stake_by_book = {quote.bookmaker: plan.stake for quote, plan in zip(quotes, stake_plan)} if stake_plan else {}
        bankroll_result = bankroll_constraint_state(stake_by_book, bankroll_by_book)
        bankroll_state = "PASS" if bankroll_result.ok else "FAIL"

    return ArbOpportunity(
        opportunity_id=fingerprint[:24],
        detected_at=now_value,
        canonical_event_id=quotes[0].canonical_event_id,
        canonical_market_key=canonical_market_key_str,
        quotes=quotes,
        bookmakers=tuple(sorted({q.bookmaker for q in quotes})),
        outcomes=tuple(q.selection_side.value for q in quotes),
        inverse_sum=inverse_result.inverse_sum,
        raw_margin=inverse_result.margin,
        total_stake=staking.total_stake if staking is not None else total_stake,
        stake_plan=tuple(stake_plan),
        return_by_outcome=staking.return_by_outcome if staking is not None else (),
        profit_by_outcome=staking.profit_by_outcome if staking is not None else (),
        worst_case_profit=staking.worst_case_profit if staking is not None else Decimal("0"),
        worst_case_roi=staking.net_worst_case_roi if staking is not None else Decimal("0"),
        execution_cost=staking.cost_total if staking is not None else Decimal("0"),
        quote_age_by_leg=quote_age_by_leg,
        cross_book_time_delta=freshness.cross_book.max_delta_seconds,
        compatibility_result=compatibility.result,
        stake_constraint_state=staking.constraint_state if staking is not None else StakeConstraintState.UNVERIFIED,
        bankroll_constraint_state=bankroll_state,
        freshness_state="FRESH" if freshness.ok else "STALE",
        risk_flags=risk_assessment.flags,
        classification=classification,
        policy_version=settings.policy_id(),
        evidence_refs=tuple(q.raw_hash for q in quotes),
        expires_at=expires_at,
        last_verified_at=now_value,
    )
