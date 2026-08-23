"""Versioned market probability / price engine for Table Tennis h2h.

One bookmaker quote is never treated as "the market". Per-book raw
implied probabilities and overrounds are computed first; the aggregate
level reports best prices, median consensus, dispersion, staleness and
movement velocity when snapshots permit it.

Methodology is explicit and versioned (``MARKET_METHOD_VERSION``).
Raw implied probabilities and vig-adjusted values are kept separately;
malformed odds are rejected per book, never silently fixed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from statistics import median
from typing import Iterable, Sequence

from defend_markets.sports_adapter import SportsSelectionQuote

MARKET_METHOD_VERSION = "market_state.v1"
VIG_METHOD = "proportional"

_DEFAULT_MAX_AGE_SECONDS = 3600


@dataclass(frozen=True)
class BookState:
    book_key: str
    selection_a_key: str
    selection_b_key: str
    decimal_a: Decimal | None = None
    decimal_b: Decimal | None = None
    implied_p_a: Decimal | None = None
    implied_p_b: Decimal | None = None
    overround: Decimal | None = None
    vig_adjusted_p_a: Decimal | None = None
    vig_adjusted_p_b: Decimal | None = None
    freshness_seconds: Decimal | None = None
    stale: bool = False
    excluded: bool = False
    exclusion_reason: str | None = None


@dataclass(frozen=True)
class MarketState:
    method_version: str = MARKET_METHOD_VERSION
    vig_method: str = VIG_METHOD
    book_count: int = 0
    books: tuple[BookState, ...] = ()
    best_price_a: Decimal | None = None
    best_price_b: Decimal | None = None
    consensus_p_a: Decimal | None = None
    consensus_p_b: Decimal | None = None
    dispersion: Decimal | None = None
    overround: Decimal | None = None
    movement_velocity: Decimal | None = None
    data_age_seconds: Decimal | None = None
    stale: bool = False
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "method_version": self.method_version,
            "vig_method": self.vig_method,
            "book_count": self.book_count,
            "best_price_a": _d(self.best_price_a),
            "best_price_b": _d(self.best_price_b),
            "consensus_p_a": _d(self.consensus_p_a),
            "consensus_p_b": _d(self.consensus_p_b),
            "dispersion": _d(self.dispersion),
            "overround": _d(self.overround),
            "movement_velocity": _d(self.movement_velocity),
            "data_age_seconds": _d(self.data_age_seconds),
            "stale": self.stale,
            "notes": list(self.notes),
        }


def _d(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def implied_probability(decimal_odds: Decimal) -> Decimal:
    """Raw bookmaker implied probability; odds must be strictly > 1."""
    if not isinstance(decimal_odds, Decimal) or not decimal_odds.is_finite():
        raise ValueError("decimal odds must be a finite Decimal")
    if decimal_odds <= Decimal("1"):
        raise ValueError("decimal odds must be > 1")
    return Decimal("1") / decimal_odds


def vig_adjusted_two_way(raw_p_a: Decimal, raw_p_b: Decimal) -> tuple[Decimal, Decimal]:
    """Proportional overround removal for a two-way market.

    Adjusted probabilities sum to exactly 1; the method name is recorded
    so every edge can state which market estimate it consumed.
    """
    total = raw_p_a + raw_p_b
    if total <= Decimal("0"):
        raise ValueError("implied probabilities must sum above zero")
    return raw_p_a / total, raw_p_b / total


def _pair_quotes(
    quotes: Sequence[SportsSelectionQuote],
) -> tuple[list[tuple[str, list[SportsSelectionQuote]]], list[str]]:
    """Group quotes into two-way pairs per book (latest quote per selection).

    Returns ``(pairs, notes)`` where pairs are ``(book_key, [quote_a,
    quote_b])`` with selections in sorted key order (home first for h2h)
    and notes record malformed odds excluded per book.
    """
    by_book: dict[str, dict[str, SportsSelectionQuote]] = {}
    notes: list[str] = []
    for quote in quotes:
        if quote.decimal_odds is None:
            continue
        try:
            implied_probability(quote.decimal_odds)
        except ValueError:
            source = quote.provenance
            book_key = source.source_key if source is not None else "unknown"
            notes.append(f"malformed_odds_excluded:{book_key}:{quote.selection_key}")
            continue
        source = quote.provenance
        book_key = source.source_key if source is not None else "unknown"
        selections = by_book.setdefault(book_key, {})
        existing = selections.get(quote.selection_key)
        if existing is None or _observed_at(quote) > _observed_at(existing):
            selections[quote.selection_key] = quote
    pairs: list[tuple[str, list[SportsSelectionQuote]]] = []
    for book_key, selections in by_book.items():
        if len(selections) < 2:
            notes.append(f"malformed_book_excluded:{book_key}")
            continue
        ordered = sorted(selections.items())
        quotes = [quote for _, quote in ordered]
        if len(quotes) == 2 and {quotes[0].selection_key, quotes[1].selection_key} == {"home", "away"}:
            quotes.sort(key=lambda quote: 0 if quote.selection_key == "home" else 1)
        pairs.append((book_key, quotes))
    return pairs, notes


def build_market_state(
    quotes: Sequence[SportsSelectionQuote],
    *,
    cutoff: datetime | None = None,
    max_age_seconds: Decimal | int = _DEFAULT_MAX_AGE_SECONDS,
    previous_quotes: Sequence[SportsSelectionQuote] | None = None,
) -> MarketState:
    """Aggregate per-book quotes into a versioned market state.

    ``cutoff`` bounds which quotes are visible (point-in-time firewall);
    quotes observed after the cutoff are excluded. Stale books (older than
    ``max_age_seconds``) are excluded from aggregates and reported.
    ``previous_quotes`` is an optional earlier snapshot for movement
    velocity; velocity is None when no prior snapshot exists.
    """
    notes: list[str] = []
    books: list[BookState] = []

    pairs, pair_notes = _pair_quotes(quotes)
    notes.extend(pair_notes)
    for book_key, group in pairs:
        book = _book_state(book_key, group, cutoff=cutoff, max_age_seconds=max_age_seconds)
        if book is not None:
            books.append(book)

    usable = [book for book in books if not book.excluded]
    book_count = len(usable)
    if usable:
        adjusted = [book.vig_adjusted_p_a for book in usable if book.vig_adjusted_p_a is not None]
        if adjusted:
            consensus = Decimal(str(median([float(value) for value in adjusted])))
            consensus = min(Decimal("1"), max(Decimal("0"), consensus))
            best_a = max(book.decimal_a for book in usable if book.decimal_a is not None)
            best_b = max(book.decimal_b for book in usable if book.decimal_b is not None)
            overrounds = [book.overround for book in usable if book.overround is not None]
            dispersion = _std_dev([float(value) for value in adjusted])
            ages = [book.freshness_seconds for book in usable if book.freshness_seconds is not None]
            return MarketState(
                book_count=book_count,
                books=tuple(books),
                best_price_a=best_a,
                best_price_b=best_b,
                consensus_p_a=consensus,
                consensus_p_b=Decimal("1") - consensus,
                dispersion=Decimal(str(dispersion)) if dispersion is not None else None,
                overround=(
                    sum(overrounds, Decimal("0")) / Decimal(len(overrounds))
                    if overrounds
                    else None
                ),
                movement_velocity=_velocity(quotes, previous_quotes),
                data_age_seconds=max(ages) if ages else None,
                stale=any(book.stale for book in books),
                notes=tuple(notes),
            )

    return MarketState(
        book_count=book_count,
        books=tuple(books),
        stale=any(book.stale for book in books),
        notes=tuple(notes),
    )


def _book_state(
    book_key: str,
    quotes: list[SportsSelectionQuote],
    *,
    cutoff: datetime | None,
    max_age_seconds: Decimal | int,
) -> BookState | None:
    a, b = quotes[0], quotes[1]
    source_a = a.provenance
    source_b = b.provenance
    if cutoff is not None:
        for quote, source in ((a, source_a), (b, source_b)):
            if source is not None and source.observed_at is not None and source.observed_at > cutoff:
                return None
    ages: list[Decimal] = []
    if source_a is not None and source_a.observed_at is not None and cutoff is not None:
        ages.append(Decimal((cutoff - source_a.observed_at).total_seconds()))
    if source_b is not None and source_b.observed_at is not None and cutoff is not None:
        ages.append(Decimal((cutoff - source_b.observed_at).total_seconds()))
    raw_a = implied_probability(a.decimal_odds)
    raw_b = implied_probability(b.decimal_odds)
    try:
        vig_a, vig_b = vig_adjusted_two_way(raw_a, raw_b)
    except ValueError:
        return None
    overround = raw_a + raw_b
    max_age = Decimal(max_age_seconds)
    age = max(ages) if ages else None
    stale = age is not None and age > max_age
    return BookState(
        book_key=book_key,
        selection_a_key=a.selection_key,
        selection_b_key=b.selection_key,
        decimal_a=a.decimal_odds,
        decimal_b=b.decimal_odds,
        implied_p_a=raw_a,
        implied_p_b=raw_b,
        overround=overround,
        vig_adjusted_p_a=vig_a,
        vig_adjusted_p_b=vig_b,
        freshness_seconds=age,
        stale=stale,
        excluded=stale,
        exclusion_reason="stale" if stale else None,
    )


def _observed_at(quote: SportsSelectionQuote) -> datetime:
    source = quote.provenance
    if source is not None and source.observed_at is not None:
        return source.observed_at
    return datetime.min.replace(tzinfo=timezone.utc)


def _velocity(
    quotes: Sequence[SportsSelectionQuote],
    previous: Sequence[SportsSelectionQuote] | None,
) -> Decimal | None:
    """Mean absolute decimal-odds movement between two snapshots."""
    if not previous:
        return None
    current: dict[tuple[str, str], Decimal] = {}
    for quote in quotes:
        source = quote.provenance
        book = source.source_key if source is not None else "unknown"
        if quote.decimal_odds is not None:
            current[(book, quote.selection_key)] = quote.decimal_odds
    moves: list[Decimal] = []
    for quote in previous:
        source = quote.provenance
        book = source.source_key if source is not None else "unknown"
        key = (book, quote.selection_key)
        if quote.decimal_odds is None or key not in current:
            continue
        moves.append(abs(current[key] - quote.decimal_odds))
    if not moves:
        return None
    return sum(moves, Decimal("0")) / Decimal(len(moves))


def _std_dev(values: Iterable[float]) -> float | None:
    items = list(values)
    if not items:
        return None
    mean = sum(items) / len(items)
    variance = sum((value - mean) ** 2 for value in items) / len(items)
    return variance**0.5