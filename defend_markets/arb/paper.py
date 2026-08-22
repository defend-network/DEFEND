"""Domain-level paper arb ticket.

An isolated in-memory/domain model. M1 does NOT write to the live database.
A paper ticket preserves every decision-relevant fact of an executed-in-theory
arbitrage so a later integration step can persist it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from defend_markets.arb.models import validate_money_amount
from defend_markets.arb.opportunity import ArbOpportunity


@dataclass(frozen=True)
class PaperLeg:
    quote_id: str = ""
    bookmaker: str = ""
    selection: str = ""
    selection_side: str = ""
    odds: Decimal = Decimal("0")
    stake: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if not isinstance(self.odds, Decimal) or not self.odds.is_finite() or self.odds <= 0:
            raise ValueError("odds must be a positive finite Decimal")
        object.__setattr__(self, "stake", validate_money_amount("stake", self.stake))


@dataclass(frozen=True)
class PaperArbTicket:
    """Immutable paper ticket snapshot.

    Created by :func:`snapshot_paper_ticket` from an opportunity; captures
    decision time, legs, prices, books, expected return, worst-case profit and
    the exact policy version. Never mutated after creation.
    """

    ticket_id: str = ""
    opportunity_id: str = ""
    legs: tuple[PaperLeg, ...] = ()
    decision_time: datetime | None = None
    expected_return: Decimal = Decimal("0")
    worst_case_profit: Decimal = Decimal("0")
    policy_version: str = ""
    canonical_market_key: str = ""
    source_quotes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "legs", tuple(self.legs))
        object.__setattr__(self, "source_quotes", tuple(self.source_quotes))
        object.__setattr__(self, "expected_return", validate_money_amount("expected_return", self.expected_return))
        object.__setattr__(self, "worst_case_profit", validate_money_amount("worst_case_profit", self.worst_case_profit))


def snapshot_paper_ticket(
    opportunity: ArbOpportunity,
    *,
    ticket_id: str | None = None,
    decision_time: datetime | None = None,
) -> PaperArbTicket:
    """Build a paper ticket from an immutable opportunity snapshot."""
    decision = decision_time or datetime.now(timezone.utc)

    legs = tuple(
        PaperLeg(
            quote_id=leg.quote_id,
            bookmaker=leg.bookmaker,
            selection=leg.selection,
            selection_side=leg.selection_side,
            odds=leg.odds,
            stake=leg.stake,
        )
        for leg in opportunity.stake_plan
    )

    return PaperArbTicket(
        ticket_id=ticket_id or f"paper:{opportunity.opportunity_id}",
        opportunity_id=opportunity.opportunity_id,
        legs=legs,
        decision_time=decision,
        expected_return=opportunity.worst_case_profit + opportunity.total_stake,
        worst_case_profit=opportunity.worst_case_profit,
        policy_version=opportunity.policy_version,
        canonical_market_key=opportunity.canonical_market_key,
        source_quotes=tuple(q.raw_hash for q in opportunity.quotes),
    )
