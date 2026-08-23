"""Stake optimization, rounding, bankroll and book-limit constraints.

Real stakes require rounding to a configurable increment. After rounding every
outcome return is recalculated and the worst-case profit/ROI is reported. A
theoretical arb that becomes zero/negative after rounding is
MATHEMATICAL_ARB_ONLY, never executable.

Constraints:

* bankroll by bookmaker (available capital per leg),
* max_stake / min_stake per quote where known (unknown means UNKNOWN, not
  infinite),
* stake increment and minimum stake from :class:`StakeSettings`.

The optimizer is deterministic and bounded: for simple constraints it scales
the unrounded equalized plan to the largest feasible total stake, then rounds
and reports the worst case. No general-purpose optimization dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from enum import Enum

from defend_markets.arb.math import solve_equalized_plan
from defend_markets.arb.models import (
    ArbQuote,
    ExecutionCosts,
    StakeSettings,
    validate_money_amount,
)


class StakeConstraintState(str, Enum):
    VERIFIED = "VERIFIED"
    MIN_STAKE_VIOLATED = "MIN_STAKE_VIOLATED"
    MAX_STAKE_VIOLATED = "MAX_STAKE_VIOLATED"
    BANKROLL_CONSTRAINT_FAIL = "BANKROLL_CONSTRAINT_FAIL"
    UNVERIFIED = "UNVERIFIED"


@dataclass(frozen=True)
class BankrollConstraintResult:
    ok: bool = True
    capital_required_by_book: dict[str, Decimal] = field(default_factory=dict)
    bankroll_by_book: dict[str, Decimal] = field(default_factory=dict)
    shortfall_by_book: dict[str, Decimal] = field(default_factory=dict)
    feasible_total_stake: Decimal | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "capital_required_by_book", dict(self.capital_required_by_book))
        object.__setattr__(self, "bankroll_by_book", dict(self.bankroll_by_book))
        object.__setattr__(self, "shortfall_by_book", dict(self.shortfall_by_book))


@dataclass(frozen=True)
class StakingResult:
    """Full stake plan: unrounded, rounded, per-outcome returns, worst case."""

    total_stake: Decimal = Decimal("0")
    unrounded_stakes: tuple[Decimal, ...] = ()
    rounded_stakes: tuple[Decimal, ...] = ()
    return_by_outcome: tuple[Decimal, ...] = ()
    profit_by_outcome: tuple[Decimal, ...] = ()
    worst_case_profit: Decimal = Decimal("0")
    worst_case_roi: Decimal = Decimal("0")
    net_worst_case_profit: Decimal = Decimal("0")
    net_worst_case_roi: Decimal = Decimal("0")
    gross_roi: Decimal = Decimal("0")
    net_roi: Decimal = Decimal("0")
    cost_total: Decimal = Decimal("0")
    feasible: bool = True
    constraint_state: StakeConstraintState = StakeConstraintState.VERIFIED
    constraint_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "unrounded_stakes", tuple(self.unrounded_stakes))
        object.__setattr__(self, "rounded_stakes", tuple(self.rounded_stakes))
        object.__setattr__(self, "return_by_outcome", tuple(self.return_by_outcome))
        object.__setattr__(self, "profit_by_outcome", tuple(self.profit_by_outcome))
        object.__setattr__(self, "constraint_reasons", tuple(self.constraint_reasons))


def _round_down_to_increment(value: Decimal, increment: Decimal) -> Decimal:
    return (value / increment).quantize(Decimal("1"), rounding=ROUND_DOWN) * increment


def _round_half_up_to_increment(value: Decimal, increment: Decimal) -> Decimal:
    return (value / increment).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * increment


def _leg_cost(odds: Decimal, stake: Decimal, costs: ExecutionCosts | None) -> Decimal:
    """Total execution cost for one leg in currency units."""
    if costs is None:
        return Decimal("0")
    total = Decimal("0")
    if costs.fixed_cost is not None:
        total += costs.fixed_cost
    if costs.commission_rate is not None:
        total += stake * costs.commission_rate
    if costs.exchange_fee_rate is not None:
        total += stake * costs.exchange_fee_rate
    if costs.other_rate is not None:
        total += stake * costs.other_rate
    return total


def _max_leg_stakes(quotes: tuple[ArbQuote, ...]) -> dict[int, Decimal | None]:
    return {i: quotes[i].max_stake for i in range(len(quotes))}


def _bankroll_map(quotes: tuple[ArbQuote, ...]) -> dict[str, Decimal]:
    return {q.bookmaker: q.max_stake for q in quotes if q.max_stake is not None}


def bankroll_constraint_state(
    stake_by_book: dict[str, Decimal],
    bankroll_by_book: dict[str, Decimal | None],
) -> BankrollConstraintResult:
    """Check that each book's required capital fits its bankroll.

    ``bankroll_by_book`` maps bookmaker -> available capital (None means
    UNKNOWN, which does not fail but leaves capacity unverified).
    """
    required: dict[str, Decimal] = {}
    for book, stake in stake_by_book.items():
        required[book] = validate_money_amount(f"stake for {book}", stake)

    shortfall: dict[str, Decimal] = {}
    ok = True
    reason: str | None = None
    for book, need in required.items():
        available = bankroll_by_book.get(book)
        if available is None:
            continue
        available_dec = validate_money_amount(f"bankroll for {book}", available)
        if need > available_dec:
            shortfall[book] = (need - available_dec).quantize(Decimal("0.01"))
            ok = False

    if not ok:
        reason = "bankroll insufficient for " + ", ".join(
            f"{book} (short {shortfall[book]})" for book in sorted(shortfall)
        )

    return BankrollConstraintResult(
        ok=ok,
        capital_required_by_book=required,
        bankroll_by_book={k: v for k, v in bankroll_by_book.items() if v is not None},
        shortfall_by_book=shortfall,
        reason=reason,
    )


def maximum_feasible_stake(
    odds: tuple[Decimal, ...],
    quotes: tuple[ArbQuote, ...],
    *,
    settings: StakeSettings | None = None,
    bankroll_by_book: dict[str, Decimal | None] | None = None,
) -> Decimal:
    """Largest equalized-return total stake feasible under all constraints.

    Deterministic closed-form solution: for a fixed total stake S the
    equalized leg stake is ``S * (1/O_i) / Q``. The tightest per-leg upper
    bound (book bankroll, then quote max stake) therefore yields the largest
    S. Unknown max stake / bankroll impose no upper bound. The result is
    rounded down to the stake increment.
    """
    settings = settings or StakeSettings()
    bankroll = bankroll_by_book or {}

    if not odds or len(odds) != len(quotes):
        raise ValueError("odds and quotes must have equal, non-empty length")

    q_full = sum((Decimal("1") / dec for dec in odds), Decimal("0"))
    if q_full <= 0:
        raise ValueError("inverse sum must be positive")

    upper: Decimal | None = None
    for i, dec in enumerate(odds):
        quote = quotes[i]
        bound: Decimal | None = None
        book_cap = bankroll.get(quote.bookmaker)
        if book_cap is not None:
            bound = validate_money_amount(f"bankroll for {quote.bookmaker}", book_cap)
        if quote.max_stake is not None:
            cap = validate_money_amount(f"max_stake for {quote.bookmaker}", quote.max_stake)
            bound = cap if bound is None else min(bound, cap)
        if bound is None:
            continue
        # Solve stake_i = S * (1/O_i) / Q for S given stake_i == bound:
        #   S = bound * Q / (1/O_i) = bound * Q * O_i
        leg_s = bound * q_full * dec
        upper = leg_s if upper is None else min(upper, leg_s)

    if upper is None:
        return Decimal("0")

    floor_upper = _round_down_to_increment(upper, settings.stake_increment)
    return max(floor_upper, Decimal("0"))


def stake_constraint_state(
    stakes: tuple[Decimal, ...],
    quotes: tuple[ArbQuote, ...],
    *,
    settings: StakeSettings | None = None,
) -> StakeConstraintState:
    """Classify stake plan against per-leg min/max limits and the increment."""
    settings = settings or StakeSettings()
    reasons: list[str] = []

    for i, stake in enumerate(stakes):
        quote = quotes[i]
        if quote.min_stake is not None and stake < quote.min_stake:
            reasons.append(f"leg {i} below min {quote.min_stake}")
        if quote.max_stake is not None and stake > quote.max_stake:
            reasons.append(f"leg {i} above max {quote.max_stake}")

    if reasons:
        # Return a specific state based on the dominant violation kind.
        below = any("below min" in r for r in reasons)
        above = any("above max" in r for r in reasons)
        if above and below:
            return StakeConstraintState.UNVERIFIED
        if above:
            return StakeConstraintState.MAX_STAKE_VIOLATED
        return StakeConstraintState.MIN_STAKE_VIOLATED

    return StakeConstraintState.VERIFIED


def solve_staking_plan(
    total_stake: Decimal,
    odds: tuple[Decimal, ...],
    quotes: tuple[ArbQuote, ...],
    *,
    settings: StakeSettings | None = None,
    costs: ExecutionCosts | None = None,
    bankroll_by_book: dict[str, Decimal | None] | None = None,
) -> StakingResult:
    """Compute a rounded stake plan and its worst-case returns.

    Steps:

    1. Solve the exactly equalized unrounded plan for ``total_stake``.
    2. Round every stake down to the configured increment.
    3. Recalculate each outcome return from the *rounded* stake.
    4. Subtract per-leg execution costs.
    5. Check min/max stake limits and bankroll; report worst-case profit/ROI.

    ``feasible`` is False when min-stake, max-stake or bankroll constraints
    fail. Worst-case profit is the minimum over outcomes of
    (return_i - sum(rounded stakes) - costs).
    """
    settings = settings or StakeSettings()
    bankroll = bankroll_by_book or {}

    plan = solve_equalized_plan(total_stake, odds)
    unrounded = tuple(leg.stake for leg in plan.legs)

    rounded = tuple(_round_down_to_increment(stake, settings.stake_increment) for stake in unrounded)
    if len(rounded) != len(quotes):
        raise ValueError("odds and quotes must have equal length")

    total_rounded = sum(rounded, Decimal("0"))

    returns: list[Decimal] = []
    cost_total = Decimal("0")
    for i, (stake, quote) in enumerate(zip(rounded, quotes)):
        dec = plan.legs[i].odds
        ret = stake * dec
        leg_cost = _leg_cost(dec, stake, costs)
        cost_total += leg_cost
        returns.append(ret)

    # Profit on outcome i = payout(i) - all stakes laid out (gross, pre-cost).
    gross_profits = [ret - total_rounded for ret in returns]
    net_profits = [p - cost_total for p in gross_profits]

    gross_profit = min(gross_profits) if gross_profits else Decimal("0")
    gross_roi = gross_profit / total_rounded if total_rounded > 0 else Decimal("0")
    net_worst = min(net_profits) if net_profits else Decimal("0")
    net_roi = net_worst / total_rounded if total_rounded > 0 else Decimal("0")

    # Constraint classification.
    constraint_state = StakeConstraintState.VERIFIED
    constraint_reasons: list[str] = []

    if len(rounded) == len(quotes):
        min_violations = [
            (i, quotes[i].min_stake, stake)
            for i, stake in enumerate(rounded)
            if quotes[i].min_stake is not None and stake < quotes[i].min_stake
        ]
        max_violations = [
            (i, quotes[i].max_stake, stake)
            for i, stake in enumerate(rounded)
            if quotes[i].max_stake is not None and stake > quotes[i].max_stake
        ]
        if min_violations:
            constraint_state = StakeConstraintState.MIN_STAKE_VIOLATED
            constraint_reasons.append(
                "min stake: " + "; ".join(f"leg {i} {stake} < {limit}" for i, limit, stake in min_violations)
            )
        if max_violations:
            constraint_state = StakeConstraintState.MAX_STAKE_VIOLATED
            constraint_reasons.append(
                "max stake: " + "; ".join(f"leg {i} {stake} > {limit}" for i, limit, stake in max_violations)
            )

    stake_by_book = {quote.bookmaker: stake for quote, stake in zip(quotes, rounded)}
    bankroll_result = bankroll_constraint_state(stake_by_book, bankroll)
    if not bankroll_result.ok:
        if constraint_state is StakeConstraintState.VERIFIED:
            constraint_state = StakeConstraintState.BANKROLL_CONSTRAINT_FAIL
        constraint_reasons.append(bankroll_result.reason or "bankroll constraint failed")

    feasible = constraint_state is StakeConstraintState.VERIFIED

    return StakingResult(
        total_stake=total_rounded,
        unrounded_stakes=unrounded,
        rounded_stakes=rounded,
        return_by_outcome=tuple(returns),
        profit_by_outcome=tuple(net_profits),
        worst_case_profit=gross_profit,
        worst_case_roi=gross_roi,
        net_worst_case_profit=net_worst,
        net_worst_case_roi=net_roi,
        gross_roi=plan.gross_roi,
        net_roi=net_roi,
        cost_total=cost_total,
        feasible=feasible,
        constraint_state=constraint_state,
        constraint_reasons=tuple(constraint_reasons),
    )
