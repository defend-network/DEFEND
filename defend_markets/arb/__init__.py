"""DEFENDMarkets Sports Arbitrage Core (M1).

Isolated deterministic arbitrage engine. Pure math/domain logic only: no
database, no HTTP, no provider API calls, no filesystem side effects.

Input boundary is the immutable :class:`ArbQuote` schema; adapters that
produce quotes from live feeds are added after M1. The engine proves whether
an exact arbitrage exists, whether the markets are actually compatible,
computes precise stake allocation under rounding/bankroll/limits/fees and
classifies the result as a theoretical mathematical arb or a plausibly
executable arb.
"""

from __future__ import annotations

from defend_markets.arb.compatibility import (
    CompatibilityResult,
    MarketCompatibility,
    check_market_compatibility,
)
from defend_markets.arb.efficiency import CapitalEfficiency, capital_efficiency
from defend_markets.arb.freshness import (
    CrossBookFreshnessResult,
    FreshnessPolicy,
    FreshnessResult,
    QuoteFreshnessResult,
    evaluate_freshness,
)
from defend_markets.arb.identity import (
    AMBIGUOUS_IDENTITY,
    CanonicalMarketKey,
    MarketIdentity,
    resolve_canonical_identity,
)
from defend_markets.arb.math import (
    InverseSumResult,
    NWayMathCore,
    compute_inverse_sum,
    is_pure_arb,
    solve_equalized_plan,
)
from defend_markets.arb.models import (
    ArbQuote,
    ArbSettings,
    BookmakerLimits,
    EventState,
    ExecutionCosts,
    MarketFamily,
    SelectionSide,
    StakeSettings,
    validate_decimal_odds,
    validate_money_amount,
    validate_policy_probability,
)
from defend_markets.arb.opportunity import (
    ArbClassification,
    ArbOpportunity,
    build_opportunity,
    classify,
    deduplication_fingerprint,
    is_expired,
)
from defend_markets.arb.paper import PaperArbTicket, PaperLeg, snapshot_paper_ticket
from defend_markets.arb.risk import (
    RiskFlag,
    SettlementCompatibility,
    SettlementStatus,
    compute_risk_flags,
)
from defend_markets.arb.search import (
    BestPriceCandidate,
    BestPriceResult,
    best_price_candidate,
)
from defend_markets.arb.staking import (
    BankrollConstraintResult,
    StakingResult,
    StakeConstraintState,
    bankroll_constraint_state,
    maximum_feasible_stake,
    solve_staking_plan,
    stake_constraint_state,
)

__all__ = [
    "AMBIGUOUS_IDENTITY",
    "ArbClassification",
    "ArbOpportunity",
    "ArbQuote",
    "ArbSettings",
    "BankrollConstraintResult",
    "BestPriceCandidate",
    "BestPriceResult",
    "BookmakerLimits",
    "CanonicalMarketKey",
    "CapitalEfficiency",
    "CompatibilityResult",
    "CrossBookFreshnessResult",
    "EventState",
    "ExecutionCosts",
    "FreshnessPolicy",
    "FreshnessResult",
    "InverseSumResult",
    "MarketCompatibility",
    "MarketFamily",
    "MarketIdentity",
    "NWayMathCore",
    "PaperArbTicket",
    "PaperLeg",
    "QuoteFreshnessResult",
    "RiskFlag",
    "SelectionSide",
    "SettlementCompatibility",
    "SettlementStatus",
    "StakeConstraintState",
    "StakeSettings",
    "StakingResult",
    "best_price_candidate",
    "bankroll_constraint_state",
    "build_opportunity",
    "capital_efficiency",
    "check_market_compatibility",
    "classify",
    "compute_inverse_sum",
    "compute_risk_flags",
    "deduplication_fingerprint",
    "evaluate_freshness",
    "is_expired",
    "is_pure_arb",
    "maximum_feasible_stake",
    "resolve_canonical_identity",
    "snapshot_paper_ticket",
    "solve_equalized_plan",
    "solve_staking_plan",
    "stake_constraint_state",
    "validate_decimal_odds",
    "validate_money_amount",
    "validate_policy_probability",
]
