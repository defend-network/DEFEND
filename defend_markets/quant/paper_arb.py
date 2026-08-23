"""M4.7 paper arb ticket persistence and executable-boundary logic (P33-P48).

A mathematically valid cross-book arb is not automatically owner-executable
(P34). Executability requires separate, explicitly-verified facts: owner access,
stake limits, settlement rules, balance, jurisdiction. The paper arb store keeps
PAPER_ARB tickets separate from PAPER_MAIN / PAPER_RESEARCH predictive tickets
(P33). Paper bankrolls are configurable; real balances are never assumed (P43).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from defend_markets.arb.opportunity import ArbOpportunity
from defend_markets.arb.paper import snapshot_paper_ticket

PAPER_ARB_STRATEGY = "PAPER_ARB"
PAPER_ARB_POLICY_VERSION = "PAPER_ARB_V1"

# P34 executability facts. Unknown means UNKNOWN, never inferred.
FACT_OWNER_EXECUTION_ACCESS = "OWNER_EXECUTION_ACCESS"
FACT_STAKE_LIMIT_VERIFIED = "STAKE_LIMIT_VERIFIED"
FACT_SETTLEMENT_RULE_VERIFIED = "SETTLEMENT_RULE_VERIFIED"
FACT_BALANCE_VERIFIED = "BALANCE_VERIFIED"
FACT_JURISDICTION_ACCESS_VERIFIED = "JURISDICTION_ACCESS_VERIFIED"


def executability_boundary(access_profile: dict[str, Any] | None = None) -> dict[str, str]:
    """Return the explicit owner-executability fact set for a book.

    Default is UNKNOWN for every fact; nothing is inferred from geography or IP.
    """
    profile = access_profile or {}
    return {
        FACT_OWNER_EXECUTION_ACCESS: str(profile.get("owner_can_legally_access", "UNKNOWN")),
        FACT_STAKE_LIMIT_VERIFIED: "UNKNOWN" if not profile.get("known_stake_limits") else "VERIFIED",
        FACT_SETTLEMENT_RULE_VERIFIED: str(profile.get("settlement_rule_state", "UNKNOWN")),
        FACT_BALANCE_VERIFIED: "VERIFIED" if profile.get("known_balance") is not None else "UNKNOWN",
        FACT_JURISDICTION_ACCESS_VERIFIED: "UNKNOWN",
    }


def surface_classification(opportunity: ArbOpportunity, *, access_facts: dict[str, str] | None = None) -> str:
    """P36: production M2 classification surface.

    MATHEMATICAL_ARB stays mathematical unless the owner-execution facts are
    verified. PAPER_ACTIONABLE_ARB is used when all paper-level constraints
    pass; OWNER_EXECUTION_UNVERIFIED flags that real execution has not been
    verified.
    """
    base = opportunity.classification.value
    if base != "EXECUTABLE_ARB":
        return base
    facts = access_facts or executability_boundary()
    if all(v in ("VERIFIED",) for v in facts.values()):
        return "PAPER_ACTIONABLE_ARB"
    return "OWNER_EXECUTION_UNVERIFIED"


class PaperArbStore:
    """Persists immutable PAPER_ARB tickets and settles them via canonical
    FINAL settlement identity (P46)."""

    def __init__(self, store: Any, *, bankroll_by_book: dict[str, Decimal] | None = None) -> None:
        self._store = store
        self._bankroll_by_book = bankroll_by_book or {}

    def record_ticket(self, opportunity: ArbOpportunity, *, decision_time: datetime | None = None) -> dict[str, Any]:
        ticket = snapshot_paper_ticket(opportunity, decision_time=decision_time)
        row = self._ticket_row(ticket)
        created = self._store.insert_paper_arb_ticket(row)
        return {"created": created, "ticket": row}

    def _ticket_row(self, ticket: Any) -> dict[str, Any]:
        return {
            "opportunity_id": ticket.opportunity_id,
            "canonical_event_id": ticket.canonical_market_key.split("::")[0] if ticket.canonical_market_key else "",
            "canonical_market_key": ticket.canonical_market_key,
            "strategy": PAPER_ARB_STRATEGY,
            "decision_time": ticket.decision_time.isoformat().replace("+00:00", "Z") if ticket.decision_time else None,
            "legs": [
                {
                    "quote_id": leg.quote_id,
                    "bookmaker": leg.bookmaker,
                    "selection": leg.selection,
                    "selection_side": leg.selection_side,
                    "odds": str(leg.odds),
                    "stake": str(leg.stake),
                }
                for leg in ticket.legs
            ],
            "bookmakers": [leg.bookmaker for leg in ticket.legs],
            "odds": [str(leg.odds) for leg in ticket.legs],
            "stakes": [str(leg.stake) for leg in ticket.legs],
            "expected_return": float(ticket.expected_return),
            "worst_case_profit": float(ticket.worst_case_profit),
            "quote_age_seconds": {},
            "constraints": {
                "bankroll_by_book": {k: str(v) for k, v in self._bankroll_by_book.items()},
                "policy_version": PAPER_ARB_POLICY_VERSION,
            },
            "reason": "mathematical arb detected; paper-only (no real wager)",
        }

    def settle_for_event(self, *, canonical_event_id: str, settlement_id: int, actual_winner_side: str, result_status: str = "FINAL", settlement_revision: int = 1) -> dict[str, Any]:
        """P33-P36: settle every PAPER_ARB ticket sharing the canonical event.

        Uses the actual rounded ticket stakes/odds stored at decision time and
        the canonical FINAL result to compute the winning leg, realized payout,
        realized P/L and ROI. Never simply copies worst-case profit. VOID /
        CANCELLED / ABANDONED / review-required results are not settled as a
        normal win.
        """
        tickets = self._store.list_paper_arb_tickets(limit=5000)
        matched = [t for t in tickets if str(t.get("canonical_event_id")) == canonical_event_id]
        settled = 0
        for ticket in matched:
            if ticket.get("settlement_id") is not None:
                continue
            # P35: void/cancelled/abandoned/review results never settle as a win.
            if result_status in ("VOID", "CANCELLED", "ABANDONED", "REVIEW_REQUIRED", "SUPERSEDED"):
                self._store.settle_paper_arb_ticket(
                    str(ticket["opportunity_id"]),
                    settlement_id=settlement_id,
                    settlement_revision=settlement_revision,
                    realized_payout=0.0,
                    realized_pnl=0.0,
                    roi=0.0,
                    void_state=result_status,
                )
                settled += 1
                continue
            # P33/P34: settle actual legs from stored rounded stakes/odds.
            legs = ticket.get("legs") or []
            total_staked = Decimal("0")
            winning_payout = Decimal("0")
            for leg in legs:
                stake = Decimal(str(leg.get("stake") or "0"))
                odds = Decimal(str(leg.get("odds") or "0"))
                total_staked += stake
                side = str(leg.get("selection_side") or "")
                # 2-way match winner: the winning leg is PARTICIPANT_A when A wins,
                # PARTICIPANT_B when B wins.
                if actual_winner_side == "A" and side == "PARTICIPANT_A":
                    winning_payout += stake * odds
                elif actual_winner_side == "B" and side == "PARTICIPANT_B":
                    winning_payout += stake * odds
            realized_pnl = winning_payout - total_staked
            roi = (realized_pnl / total_staked) if total_staked > 0 else Decimal("0")
            self._store.settle_paper_arb_ticket(
                str(ticket["opportunity_id"]),
                settlement_id=settlement_id,
                settlement_revision=settlement_revision,
                realized_payout=float(winning_payout),
                realized_pnl=float(realized_pnl),
                roi=float(roi),
                void_state="SETTLED",
            )
            settled += 1
        return {"settled": settled, "canonical_event_id": canonical_event_id}


def paper_bankroll_scenarios() -> dict[str, dict[str, Decimal]]:
    """P43: configurable PAPER bankroll scenarios per book."""
    return {
        "100": {"Bet365": Decimal("100"), "BetMGM": Decimal("100")},
        "500": {"Bet365": Decimal("500"), "BetMGM": Decimal("500")},
        "1000": {"Bet365": Decimal("1000"), "BetMGM": Decimal("1000")},
    }
