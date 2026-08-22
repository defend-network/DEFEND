"""Market compatibility engine.

Deterministically decides whether a set of quotes describe the *same*
economic market and can be compared for arbitrage. Every rejection states why.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from defend_markets.arb.identity import MarketIdentity, resolve_canonical_identity
from defend_markets.arb.models import ArbQuote, EventState, MarketFamily


class CompatibilityResult(str, Enum):
    COMPATIBLE = "COMPATIBLE"
    INCOMPATIBLE_EVENT = "INCOMPATIBLE_EVENT"
    INCOMPATIBLE_MARKET = "INCOMPATIBLE_MARKET"
    INCOMPATIBLE_PERIOD = "INCOMPATIBLE_PERIOD"
    INCOMPATIBLE_LINE = "INCOMPATIBLE_LINE"
    INCOMPATIBLE_SELECTION_SET = "INCOMPATIBLE_SELECTION_SET"
    AMBIGUOUS_IDENTITY = "AMBIGUOUS_IDENTITY"
    INCOMPLETE_MARKET = "INCOMPLETE_MARKET"
    STALE_QUOTE = "STALE_QUOTE"
    POST_COMMENCE = "POST_COMMENCE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class MarketCompatibility:
    """Compatibility decision plus the exact reason chain."""

    result: CompatibilityResult = CompatibilityResult.UNKNOWN
    reasons: tuple[str, ...] = ()
    canonical_key: object | None = None
    identity: MarketIdentity | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "reasons", tuple(self.reasons))

    @property
    def compatible(self) -> bool:
        return self.result is CompatibilityResult.COMPATIBLE


def _group_by_canonical_market(quotes: tuple[ArbQuote, ...]) -> dict[tuple[object, ...], list[ArbQuote]]:
    groups: dict[tuple[object, ...], list[ArbQuote]] = {}
    for quote in quotes:
        key = (
            quote.canonical_event_id,
            quote.market_family.value,
            quote.period,
            quote.line if quote.line is not None else None,
        )
        groups.setdefault(key, []).append(quote)
    return groups


def _expected_selection_sides(family: MarketFamily) -> frozenset[str]:
    if family is MarketFamily.MATCH_WINNER_2WAY:
        return frozenset({"PARTICIPANT_A", "PARTICIPANT_B"})
    if family is MarketFamily.MATCH_WINNER_3WAY:
        return frozenset({"PARTICIPANT_A", "DRAW", "PARTICIPANT_B"})
    if family is MarketFamily.SPREAD:
        return frozenset({"PARTICIPANT_A", "PARTICIPANT_B"})
    if family is MarketFamily.TOTAL:
        return frozenset({"OVER", "UNDER"})
    return frozenset()


def check_market_compatibility(
    quotes: tuple[ArbQuote, ...],
    *,
    max_quote_age_seconds: float | None = None,
    now: datetime | None = None,
    pre_match_only: bool = True,
) -> MarketCompatibility:
    """Check whether a set of quotes forms a comparable market.

    The quotes must share canonical event, market family, period and line; the
    selection set must be complete and consistent; participant orientation must
    resolve; quotes must be fresh enough and, when ``pre_match_only`` is set,
    must not be post-commence.
    """
    if not quotes:
        return MarketCompatibility(
            result=CompatibilityResult.UNKNOWN,
            reasons=("no quotes supplied",),
        )

    for quote in quotes:
        if not isinstance(quote, ArbQuote):
            return MarketCompatibility(
                result=CompatibilityResult.UNKNOWN,
                reasons=("all inputs must be ArbQuote",),
            )

    # 1. Same canonical event.
    events = {q.canonical_event_id for q in quotes}
    if len(events) != 1:
        return MarketCompatibility(
            result=CompatibilityResult.INCOMPATIBLE_EVENT,
            reasons=(f"quotes span {len(events)} canonical events",),
        )

    # 2. Same market family / period / line.
    families = {q.market_family for q in quotes}
    if len(families) != 1:
        return MarketCompatibility(
            result=CompatibilityResult.INCOMPATIBLE_MARKET,
            reasons=(f"quotes span {len(families)} market families",),
        )

    periods = {q.period for q in quotes}
    if len(periods) != 1:
        return MarketCompatibility(
            result=CompatibilityResult.INCOMPATIBLE_PERIOD,
            reasons=(f"quotes span {len(periods)} periods",),
        )

    family = next(iter(families))
    if family is MarketFamily.SPREAD or family is MarketFamily.TOTAL:
        lines = {q.line for q in quotes}
        if len(lines) != 1 or None in lines:
            return MarketCompatibility(
                result=CompatibilityResult.INCOMPATIBLE_LINE,
                reasons=(f"quotes span {len(lines)} lines or line is missing",),
            )
    else:
        for quote in quotes:
            if quote.line is not None:
                return MarketCompatibility(
                    result=CompatibilityResult.INCOMPATIBLE_LINE,
                    reasons=("moneyline quotes must not carry a line",),
                )

    # 3. Complete selection universe for the family.
    expected = _expected_selection_sides(family)
    present = {q.selection_side for q in quotes}
    missing = expected - {s.value for s in present}
    if missing:
        return MarketCompatibility(
            result=CompatibilityResult.INCOMPLETE_MARKET,
            reasons=("missing selection sides", sorted(missing)),
        )
    if len(present) > len(expected):
        return MarketCompatibility(
            result=CompatibilityResult.INCOMPATIBLE_SELECTION_SET,
            reasons=("duplicate or extra selection sides present",),
        )

    # 4. Participant orientation.
    identity = resolve_canonical_identity(quotes)
    if not identity.resolved:
        return MarketCompatibility(
            result=CompatibilityResult.AMBIGUOUS_IDENTITY,
            reasons=identity.notes,
            canonical_key=identity.canonical_key,
            identity=identity,
        )

    # 5. Post-commence check.
    if pre_match_only:
        for quote in quotes:
            if quote.event_state in (EventState.POST_COMMENCE, EventState.CLOSED, EventState.CANCELLED):
                return MarketCompatibility(
                    result=CompatibilityResult.POST_COMMENCE,
                    reasons=(f"quote {quote.quote_id} is {quote.event_state.value}",),
                    canonical_key=identity.canonical_key,
                    identity=identity,
                )

    # 6. Freshness.
    if max_quote_age_seconds is not None:
        now_value = now or datetime.now(timezone.utc)
        for quote in quotes:
            reference = quote.observed_at or quote.received_at
            if reference is None:
                return MarketCompatibility(
                    result=CompatibilityResult.STALE_QUOTE,
                    reasons=(f"quote {quote.quote_id} has no observed/received timestamp",),
                    canonical_key=identity.canonical_key,
                    identity=identity,
                )
            age = (now_value - reference).total_seconds()
            if age > max_quote_age_seconds:
                return MarketCompatibility(
                    result=CompatibilityResult.STALE_QUOTE,
                    reasons=(f"quote {quote.quote_id} age {age:.2f}s exceeds {max_quote_age_seconds}s",),
                    canonical_key=identity.canonical_key,
                    identity=identity,
                )

    return MarketCompatibility(
        result=CompatibilityResult.COMPATIBLE,
        reasons=(),
        canonical_key=identity.canonical_key,
        identity=identity,
    )
