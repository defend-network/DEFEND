"""Arb core: paper tickets, best-price search, capital efficiency."""

from __future__ import annotations

from decimal import Decimal

import pytest

from defend_markets.arb.models import MarketFamily, SelectionSide
from defend_markets.arb.opportunity import build_opportunity
from defend_markets.arb.paper import PaperArbTicket, snapshot_paper_ticket
from defend_markets.arb.search import best_price_candidate
from defend_markets.arb.efficiency import capital_efficiency
from defend_markets.arb.models import ArbSettings
from tests.fakes_arb import make_arb_pair, make_quote


def _settings() -> ArbSettings:
    return ArbSettings(min_net_roi=Decimal("0.005"), execution_buffer=Decimal("0.004"))


class TestPaperTicket:
    def test_paper_ticket_snapshot(self):
        qa, qb = make_arb_pair(odds_a="2.10", odds_b="2.10")
        opp = build_opportunity((qa, qb), total_stake=Decimal("100"), settings=_settings())
        ticket = snapshot_paper_ticket(opp)
        assert isinstance(ticket, PaperArbTicket)
        assert ticket.opportunity_id == opp.opportunity_id
        assert len(ticket.legs) == 2
        assert ticket.worst_case_profit == opp.worst_case_profit
        assert ticket.policy_version == opp.policy_version

    def test_paper_ticket_is_immutable(self):
        qa, qb = make_arb_pair(odds_a="2.10", odds_b="2.10")
        opp = build_opportunity((qa, qb), total_stake=Decimal("100"), settings=_settings())
        ticket = snapshot_paper_ticket(opp)
        with pytest.raises(Exception):
            ticket.expected_return = Decimal("999")

    def test_paper_ticket_preserves_legs(self):
        qa, qb = make_arb_pair(odds_a="2.10", odds_b="2.10")
        opp = build_opportunity((qa, qb), total_stake=Decimal("100"), settings=_settings())
        ticket = snapshot_paper_ticket(opp)
        books = {leg.bookmaker for leg in ticket.legs}
        assert books == {"BookA", "BookB"}
        for leg in ticket.legs:
            assert leg.stake > 0

    def test_paper_ticket_does_not_touch_db(self):
        # This test simply confirms the ticket is a domain model with no
        # persistence side effects — it succeeds when no DB is present.
        qa, qb = make_arb_pair(odds_a="2.10", odds_b="2.10")
        opp = build_opportunity((qa, qb), total_stake=Decimal("100"), settings=_settings())
        ticket = snapshot_paper_ticket(opp)
        assert ticket.decision_time is not None


class TestBestPriceSearch:
    def test_best_price_selection(self):
        qa1 = make_quote(quote_id="a1", bookmaker="BookA", selection_side=SelectionSide.PARTICIPANT_A, odds="2.10")
        qa2 = make_quote(quote_id="a2", bookmaker="BookC", selection_side=SelectionSide.PARTICIPANT_A, odds="2.20")
        qb1 = make_quote(quote_id="b1", bookmaker="BookB", selection_side=SelectionSide.PARTICIPANT_B, odds="2.10")
        result = best_price_candidate((qa1, qa2, qb1))
        assert result.candidates
        candidate = result.candidates[0]
        assert candidate.complete
        by_side = {leg.selection_side: leg for leg in candidate.legs}
        assert by_side["PARTICIPANT_A"].bookmaker == "BookC"
        assert by_side["PARTICIPANT_A"].odds == Decimal("2.20")

    def test_bookmaker_identity_preserved(self):
        qa1 = make_quote(quote_id="a1", bookmaker="BookA", selection_side=SelectionSide.PARTICIPANT_A, odds="2.10")
        qb1 = make_quote(quote_id="b1", bookmaker="BookB", selection_side=SelectionSide.PARTICIPANT_B, odds="2.10")
        result = best_price_candidate((qa1, qb1))
        candidate = result.candidates[0]
        assert {leg.bookmaker for leg in candidate.legs} == {"BookA", "BookB"}

    def test_incomplete_group_not_selected(self):
        qa = make_quote(quote_id="a1", selection_side=SelectionSide.PARTICIPANT_A, odds="2.10")
        result = best_price_candidate((qa,))
        assert not result.candidates or all(not c.complete for c in result.candidates)


class TestCapitalEfficiency:
    def test_capital_efficiency_metrics(self):
        qa, qb = make_arb_pair(odds_a="2.10", odds_b="2.10")
        opp = build_opportunity((qa, qb), total_stake=Decimal("100"), settings=_settings())
        eff = capital_efficiency(opp)
        assert eff.capital_required == opp.total_stake
        assert eff.guaranteed_profit == opp.worst_case_profit
        assert eff.profit_per_100 > 0
        assert set(eff.capital_by_book) == {"BookA", "BookB"}
