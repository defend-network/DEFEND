"""Arb core: market compatibility and canonical identity."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from defend_markets.arb.compatibility import (
    CompatibilityResult,
    check_market_compatibility,
)
from defend_markets.arb.identity import (
    CanonicalMarketKey,
    MarketIdentity,
    ParticipantOrientation,
    resolve_canonical_identity,
)
from defend_markets.arb.models import EventState, MarketFamily, SelectionSide
from tests.fakes_arb import make_arb_pair, make_quote


def _fresh_pair(odds_a="2.10", odds_b="2.10"):
    return make_arb_pair(odds_a=odds_a, odds_b=odds_b)


class TestCompatibilityBasics:
    def test_compatible_two_way(self):
        qa, qb = _fresh_pair()
        result = check_market_compatibility((qa, qb))
        assert result.compatible
        assert result.result is CompatibilityResult.COMPATIBLE

    def test_incompatible_event(self):
        qa = make_quote(quote_id="a", canonical_event_id="evt-1", selection_side=SelectionSide.PARTICIPANT_A)
        qb = make_quote(quote_id="b", canonical_event_id="evt-2", selection_side=SelectionSide.PARTICIPANT_B)
        result = check_market_compatibility((qa, qb))
        assert result.result is CompatibilityResult.INCOMPATIBLE_EVENT

    def test_incompatible_market_family(self):
        qa = make_quote(quote_id="a", selection_side=SelectionSide.PARTICIPANT_A, market_family=MarketFamily.MATCH_WINNER_2WAY)
        qb = make_quote(
            quote_id="b",
            selection_side=SelectionSide.PARTICIPANT_B,
            market_family=MarketFamily.SPREAD,
            line=Decimal("-1.5"),
        )
        result = check_market_compatibility((qa, qb))
        assert result.result is CompatibilityResult.INCOMPATIBLE_MARKET

    def test_incompatible_period(self):
        qa = make_quote(quote_id="a", selection_side=SelectionSide.PARTICIPANT_A, period="FULL_MATCH")
        qb = make_quote(quote_id="b", selection_side=SelectionSide.PARTICIPANT_B, period="FIRST_GAME")
        result = check_market_compatibility((qa, qb))
        assert result.result is CompatibilityResult.INCOMPATIBLE_PERIOD

    def test_incompatible_spread_line(self):
        qa = make_quote(quote_id="a", selection_side=SelectionSide.PARTICIPANT_A, market_family=MarketFamily.SPREAD, line=Decimal("-1.5"))
        qb = make_quote(
            quote_id="b",
            selection_side=SelectionSide.PARTICIPANT_B,
            market_family=MarketFamily.SPREAD,
            line=Decimal("2.5"),
        )
        result = check_market_compatibility((qa, qb))
        assert result.result is CompatibilityResult.INCOMPATIBLE_LINE

    def test_incompatible_total_line(self):
        # Over 74.5 vs Under 75.5 is NOT the same market (a middle, not an arb).
        qa = make_quote(
            quote_id="a",
            selection_side=SelectionSide.OVER,
            market_family=MarketFamily.TOTAL,
            line=Decimal("74.5"),
        )
        qb = make_quote(
            quote_id="b",
            selection_side=SelectionSide.UNDER,
            market_family=MarketFamily.TOTAL,
            line=Decimal("75.5"),
        )
        result = check_market_compatibility((qa, qb))
        assert result.result is CompatibilityResult.INCOMPATIBLE_LINE

    def test_incomplete_market(self):
        # Only one of two sides present.
        qa = make_quote(quote_id="a", selection_side=SelectionSide.PARTICIPANT_A)
        result = check_market_compatibility((qa,))
        assert result.result is CompatibilityResult.INCOMPLETE_MARKET

    def test_incomplete_three_way(self):
        qa = make_quote(quote_id="a", selection_side=SelectionSide.PARTICIPANT_A, market_family=MarketFamily.MATCH_WINNER_3WAY)
        qb = make_quote(quote_id="b", selection_side=SelectionSide.PARTICIPANT_B, market_family=MarketFamily.MATCH_WINNER_3WAY)
        # Missing DRAW -> incomplete
        result = check_market_compatibility((qa, qb))
        assert result.result is CompatibilityResult.INCOMPLETE_MARKET

    def test_empty_input_unknown(self):
        result = check_market_compatibility(())
        assert result.result is CompatibilityResult.UNKNOWN


class TestParticipantOrientation:
    def test_participant_reversal_still_compatible(self):
        # Book B lists players in reversed order but same canonical selection.
        qa = make_quote(
            quote_id="a",
            bookmaker="BookA",
            selection_side=SelectionSide.PARTICIPANT_A,
            participant_a="Alice",
            participant_b="Bob",
            selection="Alice",
        )
        qb = make_quote(
            quote_id="b",
            bookmaker="BookB",
            selection_side=SelectionSide.PARTICIPANT_B,
            participant_a="Bob",
            participant_b="Alice",
            selection="Bob",
        )
        identity = resolve_canonical_identity((qa, qb))
        assert identity.resolved
        # Both quote selections must map to a canonical A/B.
        result = check_market_compatibility((qa, qb))
        assert result.compatible

    def test_ambiguous_participant_mapping_abstains(self):
        # Book B names a different participant set entirely -> no single
        # canonical orientation is consistent across the quotes.
        qa = make_quote(
            quote_id="a",
            bookmaker="BookA",
            selection_side=SelectionSide.PARTICIPANT_A,
            participant_a="Alice",
            participant_b="Bob",
            selection="Alice",
        )
        qb = make_quote(
            quote_id="b",
            bookmaker="BookB",
            selection_side=SelectionSide.PARTICIPANT_B,
            participant_a="Charlie",
            participant_b="Dave",
            selection="Dave",
        )
        identity = resolve_canonical_identity((qa, qb))
        assert not identity.resolved
        assert identity.state.value == "AMBIGUOUS"
        result = check_market_compatibility((qa, qb))
        assert result.result is CompatibilityResult.AMBIGUOUS_IDENTITY

    def test_known_orientation_overrides_provider_order(self):
        orientation = ParticipantOrientation(participant_a="Alice", participant_b="Bob", source="canonical")
        qa = make_quote(
            quote_id="a",
            selection_side=SelectionSide.PARTICIPANT_A,
            participant_a="Bob",
            participant_b="Alice",
            selection="Alice",
        )
        identity = resolve_canonical_identity((qa,), known_orientation=orientation)
        assert identity.resolved
        assert identity.maps_side(qa)


class TestCanonicalMarketKey:
    def test_line_mismatch_not_equal(self):
        k1 = CanonicalMarketKey(canonical_event_id="e", market_family=MarketFamily.TOTAL, line=Decimal("74.5"))
        k2 = CanonicalMarketKey(canonical_event_id="e", market_family=MarketFamily.TOTAL, line=Decimal("75.5"))
        assert not k1.matches(k2)

    def test_moneyline_never_carries_line(self):
        result = check_market_compatibility(
            (
                make_quote(quote_id="a", selection_side=SelectionSide.PARTICIPANT_A, line=Decimal("-1.5")),
                make_quote(quote_id="b", selection_side=SelectionSide.PARTICIPANT_B, line=Decimal("2.5")),
            )
        )
        assert result.result is CompatibilityResult.INCOMPATIBLE_LINE
