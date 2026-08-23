"""Multi-book best-price search.

Given N bookmaker quotes for each outcome side, find the best compatible
price for each outcome and generate a best-price candidate. Compatibility and
freshness are evaluated first — never take an independent max price from
stale or incompatible quotes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from defend_markets.arb.compatibility import CompatibilityResult, check_market_compatibility
from defend_markets.arb.freshness import evaluate_freshness
from defend_markets.arb.identity import CanonicalMarketKey
from defend_markets.arb.models import ArbQuote


@dataclass(frozen=True)
class BestPriceLeg:
    """Best compatible price selected for one outcome side."""

    selection_side: str = ""
    bookmaker: str = ""
    quote_id: str = ""
    odds: Decimal = Decimal("0")
    max_stake: Decimal | None = None
    min_stake: Decimal | None = None
    price_tier: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "max_stake", self.max_stake)
        object.__setattr__(self, "min_stake", self.min_stake)


@dataclass(frozen=True)
class BestPriceCandidate:
    """Candidate combining the best compatible price for each outcome side."""

    canonical_market_key: str = ""
    legs: tuple[BestPriceLeg, ...] = ()
    source_quotes: tuple[ArbQuote, ...] = ()
    odds: tuple[Decimal, ...] = ()
    complete: bool = False
    note: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "legs", tuple(self.legs))
        object.__setattr__(self, "source_quotes", tuple(self.source_quotes))
        object.__setattr__(self, "odds", tuple(self.odds))


@dataclass(frozen=True)
class BestPriceResult:
    candidates: tuple[BestPriceCandidate, ...] = ()
    error: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidates", tuple(self.candidates))


def best_price_candidate(
    quotes: tuple[ArbQuote, ...],
    *,
    now: datetime | None = None,
) -> BestPriceResult:
    """Build the best-price candidate from a pool of quotes.

    Groups quotes by canonical market key, verifies that the group is
    compatible and fresh, then picks the highest odds for each selection side.
    Incomplete groups (missing an outcome side) are reported with
    ``complete=False`` and skipped for arbitrage.
    """
    if not quotes:
        return BestPriceResult(error="no quotes supplied")

    groups: dict[str, list[ArbQuote]] = {}
    for quote in quotes:
        key = CanonicalMarketKey.from_quote(quote).human_key()
        groups.setdefault(key, []).append(quote)

    now_value = now or datetime.now(timezone.utc)
    candidates: list[BestPriceCandidate] = []

    for key, group_quotes in groups.items():
        t_group = tuple(group_quotes)
        compatibility = check_market_compatibility(
            t_group,
            max_quote_age_seconds=None,
            now=now_value,
            pre_match_only=False,
        )
        if compatibility.result is not CompatibilityResult.COMPATIBLE:
            continue

        freshness = evaluate_freshness(t_group, now=now_value)
        if not freshness.ok:
            continue

        by_side: dict[str, ArbQuote] = {}
        for quote in t_group:
            side = quote.selection_side.value
            current = by_side.get(side)
            if current is None or quote.decimal_odds > current.decimal_odds:
                by_side[side] = quote

        legs = tuple(
            BestPriceLeg(
                selection_side=side,
                bookmaker=quote.bookmaker,
                quote_id=quote.quote_id,
                odds=quote.decimal_odds,
                max_stake=quote.max_stake,
                min_stake=quote.min_stake,
            )
            for side, quote in sorted(by_side.items())
        )

        source = tuple(sorted(by_side.values(), key=lambda q: q.selection_side.value))
        candidates.append(
            BestPriceCandidate(
                canonical_market_key=key,
                legs=legs,
                source_quotes=source,
                odds=tuple(leg.odds for leg in legs),
                complete=len(legs) >= 2,
                note=None if len(legs) >= 2 else "incomplete outcome set",
            )
        )

    return BestPriceResult(candidates=tuple(candidates))
