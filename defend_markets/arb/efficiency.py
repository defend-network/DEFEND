"""Capital efficiency metrics for ranking opportunities.

Deterministic metrics only: capital required, guaranteed (worst-case) profit,
worst-case ROI and profit per $100 deployed, plus the capital split per book.
Ranking by these metrics is a later system concern; M1 computes them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from defend_markets.arb.opportunity import ArbOpportunity


@dataclass(frozen=True)
class CapitalEfficiency:
    capital_required: Decimal = Decimal("0")
    guaranteed_profit: Decimal = Decimal("0")
    worst_case_roi: Decimal = Decimal("0")
    profit_per_100: Decimal = Decimal("0")
    capital_by_book: dict[str, Decimal] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "capital_by_book", dict(self.capital_by_book))


def capital_efficiency(opportunity: ArbOpportunity) -> CapitalEfficiency:
    """Compute capital-efficiency metrics from an opportunity snapshot."""
    capital_by_book: dict[str, Decimal] = {}
    for leg in opportunity.stake_plan:
        capital_by_book[leg.bookmaker] = capital_by_book.get(leg.bookmaker, Decimal("0")) + leg.stake

    capital = sum(capital_by_book.values(), Decimal("0")) or opportunity.total_stake
    profit = opportunity.worst_case_profit
    roi = opportunity.worst_case_roi
    profit_per_100 = (profit / capital * Decimal("100")) if capital > 0 else Decimal("0")

    return CapitalEfficiency(
        capital_required=capital,
        guaranteed_profit=profit,
        worst_case_roi=roi,
        profit_per_100=profit_per_100,
        capital_by_book=capital_by_book,
    )
