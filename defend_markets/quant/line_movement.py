"""M4.8 line movement, cross-book consensus and Hard Rock reference price
(P20-P22).

Line/price movement is DERIVED from the append-only observation journal, never
stored by mutating raw observations. Hard Rock FL (via Owls) is the owner-facing
REFERENCE price; comparison books improve context/consensus but never replace
the Hard Rock execution/reference price merely because another book has more
favorable odds.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

REFERENCE_SPORTSBOOK = "hardrock_bet"
REFERENCE_PROVIDER = "owls_insight"


def _parse(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def line_movement(observations: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Derive line/price movement from a PIT observation series (P20).

    Observations are expected in ascending observed_at order (as stored by the
    append-only journal). Never mutates the raw observations.
    """
    ordered = sorted(observations, key=lambda o: _parse(o.get("observed_at")) or datetime.min.replace(tzinfo=timezone.utc))
    if len(ordered) < 2:
        return None
    first = ordered[0]
    last = ordered[-1]
    prev = ordered[-2]
    def _price(o: dict[str, Any]) -> Decimal | None:
        v = o.get("decimal_odds")
        if v is None:
            return None
        try:
            return Decimal(str(v))
        except Exception:
            return None
    first_price = _price(first)
    prev_price = _price(prev)
    current_price = _price(last)
    if current_price is None:
        return None
    delta = current_price - first_price if first_price is not None else None
    t_first = _parse(first.get("observed_at"))
    t_prev = _parse(prev.get("observed_at"))
    t_last = _parse(last.get("observed_at"))
    time_since_prev = None
    if t_prev is not None and t_last is not None:
        time_since_prev = (t_last - t_prev).total_seconds()
    direction = None
    if prev_price is not None and current_price != prev_price:
        direction = "UP" if current_price > prev_price else "DOWN"
    return {
        "first_seen_price": str(first_price) if first_price is not None else None,
        "previous_price": str(prev_price) if prev_price is not None else None,
        "current_price": str(current_price),
        "delta": str(delta) if delta is not None else None,
        "time_since_previous_seconds": round(time_since_prev, 3) if time_since_prev is not None else None,
        "num_changes": sum(1 for i in range(1, len(ordered)) if _price(ordered[i]) != _price(ordered[i - 1])),
        "direction": direction,
        "staleness_seconds": round((datetime.now(timezone.utc) - t_last).total_seconds(), 3) if t_last is not None else None,
    }


def cross_book_consensus(quotes_by_book: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """P21: synchronized comparison view across books for one canonical market.

    Quotes are grouped by sportsbook. Missing books are not fabricated.
    """
    books: dict[str, dict[str, Any]] = {}
    implied_values: list[Decimal] = []
    for book, quotes in quotes_by_book.items():
        if not quotes:
            continue
        # take the latest quote per book
        latest = max(quotes, key=lambda q: _parse(q.get("observed_at")) or datetime.min.replace(tzinfo=timezone.utc))
        dec = latest.get("decimal_odds")
        implied = latest.get("implied_probability")
        books[book] = {
            "decimal_odds": str(dec) if dec is not None else None,
            "implied_probability": str(implied) if implied is not None else None,
            "observed_at": latest.get("observed_at"),
        }
        if implied is not None:
            try:
                implied_values.append(Decimal(str(implied)))
            except Exception:
                pass
    consensus = None
    dispersion = None
    if implied_values:
        consensus = sum(implied_values, Decimal("0")) / len(implied_values)
        if len(implied_values) > 1:
            dispersion = max(implied_values) - min(implied_values)
    return {
        "books": books,
        "consensus_implied": str(consensus.quantize(Decimal("0.00000001"))) if consensus is not None else None,
        "dispersion": str(dispersion) if dispersion is not None else None,
    }


def hardrock_reference_price(quotes_by_book: dict[str, list[dict[str, Any]]]) -> dict[str, Any] | None:
    """P22: Hard Rock is the owner-facing reference price.

    Returns the Hard Rock quote (if present) plus its deviation from the
    cross-book consensus. Supplementary books never replace Hard Rock.
    """
    hardrock = quotes_by_book.get(REFERENCE_SPORTSBOOK) or quotes_by_book.get(REFERENCE_PROVIDER) or []
    if not hardrock:
        return None
    latest = max(hardrock, key=lambda q: _parse(q.get("observed_at")) or datetime.min.replace(tzinfo=timezone.utc))
    consensus = cross_book_consensus(quotes_by_book)
    reference_implied = latest.get("implied_probability")
    deviation = None
    if reference_implied is not None and consensus.get("consensus_implied") is not None:
        try:
            deviation = (Decimal(str(reference_implied)) - Decimal(str(consensus["consensus_implied"]))).quantize(Decimal("0.00000001"))
        except Exception:
            deviation = None
    return {
        "reference_sportsbook": REFERENCE_SPORTSBOOK,
        "reference_provider": REFERENCE_PROVIDER,
        "decimal_odds": str(latest.get("decimal_odds")) if latest.get("decimal_odds") is not None else None,
        "implied_probability": str(reference_implied) if reference_implied is not None else None,
        "observed_at": latest.get("observed_at"),
        "consensus_implied": consensus.get("consensus_implied"),
        "deviation_from_consensus": str(deviation) if deviation is not None else None,
        "comparison_books": sorted(book for book in quotes_by_book if book != REFERENCE_SPORTSBOOK and book != REFERENCE_PROVIDER),
    }
