"""Deterministic N-way arbitrage mathematics.

Pure math only: no I/O, no side effects. All arithmetic uses :class:`Decimal`.

For N complete mutually exclusive outcomes with decimal odds ``O_1..O_N``:

    Q = SUM(1/O_i)
    arb exists iff Q < 1
    raw margin = 1 - Q
    stake_i = S * (1/O_i) / Q
    equalized gross return = S / Q
    gross profit = R - S
    gross ROI = P / S

``solve_equalized_plan`` returns unrounded, exactly equalized per-outcome
stakes and returns so downstream rounding logic can report worst-case results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from defend_markets.arb.models import validate_decimal_odds

INVERSE_QUANTUM = Decimal("0.0000000001")


@dataclass(frozen=True)
class InverseSumResult:
    """Result of the inverse-probability sum Q for a set of odds."""

    inverse_sum: Decimal = Decimal("0")
    margin: Decimal = Decimal("0")
    is_arb: bool = False
    odds: tuple[Decimal, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "odds", tuple(self.odds))


@dataclass(frozen=True)
class EqualizedLeg:
    """One leg of an exactly equalized plan."""

    index: int = 0
    odds: Decimal = Decimal("0")
    stake: Decimal = Decimal("0")
    return_: Decimal = Decimal("0")
    inverse: Decimal = Decimal("0")


@dataclass(frozen=True)
class EqualizedPlan:
    """Exactly equalized N-way stake plan (unrounded)."""

    total_stake: Decimal = Decimal("0")
    legs: tuple[EqualizedLeg, ...] = ()
    inverse_sum: Decimal = Decimal("0")
    equalized_return: Decimal = Decimal("0")
    gross_profit: Decimal = Decimal("0")
    gross_roi: Decimal = Decimal("0")
    is_arb: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "legs", tuple(self.legs))


def compute_inverse_sum(odds: tuple[Decimal, ...]) -> InverseSumResult:
    """Compute Q = SUM(1/O_i) and the pure-arb flag (Q < 1).

    Each term is kept at full Decimal precision; only the final sum is
    quantized to the inverse quantum. Per-term quantization would truncate
    repeating decimals and fabricate phantom margins (e.g. 3.0/3.0/3.0).
    """
    if not odds:
        return InverseSumResult()
    total = Decimal("0")
    for value in odds:
        dec = validate_decimal_odds("odds", value)
        total += Decimal("1") / dec
    inverse = total.quantize(INVERSE_QUANTUM, rounding=ROUND_HALF_UP)
    return InverseSumResult(
        inverse_sum=inverse,
        margin=(Decimal("1") - inverse),
        is_arb=inverse < Decimal("1"),
        odds=tuple(Decimal(v) for v in odds),
    )


def is_pure_arb(odds: tuple[Decimal, ...]) -> bool:
    """True when the pure mathematical condition Q < 1 holds."""
    return compute_inverse_sum(odds).is_arb


def solve_equalized_plan(total_stake: Decimal, odds: tuple[Decimal, ...]) -> EqualizedPlan:
    """Solve the exactly equalized stake plan for N outcomes.

    ``total_stake`` is validated as a non-negative money amount. Stakes are
    computed at full Decimal precision from the unquantized inverse sum Q so
    equalization is exact; the reported ``inverse_sum`` is the quantized Q used
    as the arbitrage evidence value. If no pure arbitrage exists, the plan is
    still returned (with ``is_arb=False``) so callers can inspect
    margin/return without branching on special cases.
    """
    from defend_markets.arb.models import validate_money_amount

    stake = validate_money_amount("total_stake", total_stake)
    if not odds:
        return EqualizedPlan(total_stake=stake)

    normalized: list[Decimal] = []
    for value in odds:
        normalized.append(validate_decimal_odds("odds", value))

    q_full = sum((Decimal("1") / dec for dec in normalized), Decimal("0"))
    if q_full <= 0:
        raise ValueError("inverse sum must be positive")

    q = q_full.quantize(INVERSE_QUANTUM, rounding=ROUND_HALF_UP)
    is_arb = q < Decimal("1")

    legs: list[EqualizedLeg] = []
    for index, dec in enumerate(normalized):
        inv = Decimal("1") / dec
        leg_stake = stake * inv / q_full
        leg_return = leg_stake * dec
        legs.append(
            EqualizedLeg(
                index=index,
                odds=dec,
                stake=leg_stake,
                return_=leg_return,
                inverse=inv.quantize(INVERSE_QUANTUM, rounding=ROUND_HALF_UP),
            )
        )

    equalized_return = stake / q_full
    gross_profit = equalized_return - stake
    gross_roi = gross_profit / stake if stake > 0 else Decimal("0")

    return EqualizedPlan(
        total_stake=stake,
        legs=tuple(legs),
        inverse_sum=q,
        equalized_return=equalized_return,
        gross_profit=gross_profit,
        gross_roi=gross_roi,
        is_arb=is_arb,
    )


class NWayMathCore:
    """Reusable N-way calculation core (supports 2-way and 3-way markets)."""

    @staticmethod
    def inverse_sum(odds: tuple[Decimal, ...]) -> Decimal:
        return compute_inverse_sum(odds).inverse_sum

    @staticmethod
    def margin(odds: tuple[Decimal, ...]) -> Decimal:
        return compute_inverse_sum(odds).margin

    @staticmethod
    def is_arb(odds: tuple[Decimal, ...]) -> bool:
        return compute_inverse_sum(odds).is_arb

    @staticmethod
    def equalized_plan(total_stake: Decimal, odds: tuple[Decimal, ...]) -> EqualizedPlan:
        return solve_equalized_plan(total_stake, odds)
