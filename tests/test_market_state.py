from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from defend_markets.domain import ProvenanceStamp
from defend_markets.market_state import (
    VIG_METHOD,
    build_market_state,
    implied_probability,
    vig_adjusted_two_way,
)
from defend_markets.sports_adapter import SportsSelectionQuote

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)


def quote(book: str, selection: str, odds: str, hour: int = 11) -> SportsSelectionQuote:
    return SportsSelectionQuote(
        selection_key=selection,
        display_name=selection,
        decimal_odds=Decimal(odds),
        provenance=ProvenanceStamp(
            source_key=book,
            observed_at=datetime(2026, 8, 15, hour, 0, tzinfo=timezone.utc),
            received_at=datetime(2026, 8, 15, hour, 1, tzinfo=timezone.utc),
            raw_ref=f"raw-{book}-{selection}-{hour}",
            normalization_version=None,
        ),
        selection_id=f"sel-{book}-{selection}",
    )


def test_implied_probability_rejects_at_or_below_even_money():
    with pytest.raises(ValueError):
        implied_probability(Decimal("1"))
    with pytest.raises(ValueError):
        implied_probability(Decimal("0.5"))
    assert implied_probability(Decimal("2")) == Decimal("0.5")


def test_vig_adjusted_two_way_removes_overround_exactly():
    a, b = vig_adjusted_two_way(Decimal("0.55"), Decimal("0.45"))
    assert a + b == Decimal("1")
    assert a == pytest.approx(Decimal("0.55") / Decimal("1.0"))


def test_vig_adjusted_two_way_rejects_zero_total():
    with pytest.raises(ValueError):
        vig_adjusted_two_way(Decimal("0"), Decimal("0"))


def test_build_market_state_two_books_home_away():
    quotes = [
        quote("book-a", "home", "1.85"),
        quote("book-a", "away", "2.35"),
        quote("book-b", "home", "1.90"),
        quote("book-b", "away", "2.30"),
    ]
    state = build_market_state(quotes, cutoff=NOW)
    assert state.method_version == "market_state.v1"
    assert state.vig_method == VIG_METHOD
    assert state.book_count == 2
    assert len(state.books) == 2
    first = state.books[0]
    assert first.selection_a_key == "home"
    assert first.selection_b_key == "away"
    assert state.best_price_a == Decimal("1.90")
    assert state.best_price_b == Decimal("2.35")
    assert state.consensus_p_a + state.consensus_p_b == Decimal("1")
    assert state.consensus_p_a == pytest.approx(Decimal("0.5535714285714286"), rel=Decimal("1e-12"))
    assert state.overround > Decimal("0.95")
    assert not state.stale


def test_build_market_state_excludes_cutoff_future_quotes():
    quotes = [
        quote("book-a", "home", "1.85", hour=13),
        quote("book-a", "away", "2.35", hour=13),
    ]
    state = build_market_state(quotes, cutoff=NOW)
    assert state.book_count == 0
    assert state.consensus_p_a is None


def test_build_market_state_marks_stale_books_excluded():
    quotes = [
        quote("book-a", "home", "1.85", hour=1),
        quote("book-a", "away", "2.35", hour=1),
        quote("book-b", "home", "1.90", hour=11),
        quote("book-b", "away", "2.30", hour=11),
    ]
    state = build_market_state(quotes, cutoff=NOW, max_age_seconds=3600)
    assert state.stale
    assert state.book_count == 1
    assert state.books[0].excluded
    assert state.books[0].exclusion_reason == "stale"


def test_build_market_state_rejects_malformed_odds_per_book():
    malformed = SportsSelectionQuote(
        selection_key="home",
        display_name="home",
        decimal_odds=Decimal("0.9"),
        provenance=ProvenanceStamp(
            source_key="book-a",
            observed_at=datetime(2026, 8, 15, 10, 0, tzinfo=timezone.utc),
            received_at=datetime(2026, 8, 15, 10, 1, tzinfo=timezone.utc),
            raw_ref="raw",
            normalization_version=None,
        ),
        selection_id="s",
    )
    state = build_market_state(
        [malformed, quote("book-a", "away", "2.35")],
        cutoff=NOW,
    )
    assert state.book_count == 0
    assert any("malformed" in note for note in state.notes)


def test_build_market_state_dedups_latest_per_book():
    quotes = [
        quote("book-a", "home", "1.50", hour=10),
        quote("book-a", "home", "1.85", hour=11),
        quote("book-a", "away", "2.35", hour=11),
    ]
    state = build_market_state(quotes, cutoff=NOW)
    assert state.book_count == 1
    assert state.best_price_a == Decimal("1.85")


def test_build_market_state_velocity_with_previous_quotes():
    previous = [
        quote("book-a", "home", "1.80", hour=10),
        quote("book-a", "away", "2.40", hour=10),
    ]
    current = [
        quote("book-a", "home", "1.90", hour=11),
        quote("book-a", "away", "2.30", hour=11),
    ]
    state = build_market_state(current, cutoff=NOW, previous_quotes=previous)
    assert state.movement_velocity == pytest.approx(Decimal("0.1"))


def test_build_market_state_no_previous_no_velocity():
    state = build_market_state(
        [quote("book-a", "home", "1.85"), quote("book-a", "away", "2.35")],
        cutoff=NOW,
    )
    assert state.movement_velocity is None


def test_build_market_state_empty_quotes():
    state = build_market_state([], cutoff=NOW)
    assert state.book_count == 0
    assert state.consensus_p_a is None
    assert not state.stale


def test_build_market_state_book_needs_two_selections():
    state = build_market_state([quote("book-a", "home", "1.85")], cutoff=NOW)
    assert state.book_count == 0
