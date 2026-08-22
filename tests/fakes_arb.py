"""Shared fixtures/builders for arb core tests.

Pure helpers: no provider calls, no network, no database. They produce
immutable :class:`ArbQuote` instances with controlled timestamps.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from defend_markets.arb.models import (
    ArbQuote,
    EventState,
    MarketFamily,
    SelectionSide,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def make_quote(
    *,
    quote_id: str = "q-1",
    bookmaker: str = "BookA",
    selection: str | None = None,
    selection_side: SelectionSide = SelectionSide.PARTICIPANT_A,
    odds: str | Decimal = "2.10",
    participant_a: str = "Player A",
    participant_b: str = "Player B",
    market_family: MarketFamily = MarketFamily.MATCH_WINNER_2WAY,
    canonical_event_id: str = "evt-1",
    period: str = "FULL_MATCH",
    line: Decimal | None = None,
    observed_at: datetime | None = None,
    received_at: datetime | None = None,
    provider_updated_at: datetime | None = None,
    commence_time: datetime | None = None,
    event_state: EventState = EventState.PRE_MATCH,
    max_stake: Decimal | None = None,
    min_stake: Decimal | None = None,
    sport: str = "table_tennis",
) -> ArbQuote:
    now = utc_now()
    observed = observed_at if observed_at is not None else now
    received = received_at if received_at is not None else now
    updated = provider_updated_at if provider_updated_at is not None else observed
    commence = commence_time if commence_time is not None else now + timedelta(hours=2)

    default_selection = {
        MarketFamily.MATCH_WINNER_2WAY: participant_a if selection_side is SelectionSide.PARTICIPANT_A else participant_b,
        MarketFamily.MATCH_WINNER_3WAY: participant_a if selection_side is SelectionSide.PARTICIPANT_A else (
            "Draw" if selection_side is SelectionSide.DRAW else participant_b
        ),
        MarketFamily.SPREAD: f"{participant_a} {line}",
        MarketFamily.TOTAL: "Over" if selection_side is SelectionSide.OVER else "Under",
    }[market_family]

    return ArbQuote(
        quote_id=quote_id,
        canonical_event_id=canonical_event_id,
        provider_event_id=f"prov-{quote_id}",
        bookmaker=bookmaker,
        sport=sport,
        competition="Test Cup",
        participant_a=participant_a,
        participant_b=participant_b,
        commence_time=commence,
        market_family=market_family,
        period=period,
        selection=selection if selection is not None else default_selection,
        selection_side=selection_side,
        line=line,
        decimal_odds=Decimal(str(odds)) if isinstance(odds, str) else odds,
        observed_at=observed,
        provider_updated_at=updated,
        received_at=received,
        event_state=event_state,
        max_stake=max_stake,
        min_stake=min_stake,
        currency="USD",
        source_ref=f"test:{quote_id}",
    )


def make_arb_pair(
    odds_a: str = "2.10",
    odds_b: str = "2.10",
    *,
    book_a: str = "BookA",
    book_b: str = "BookB",
    id_prefix: str = "q",
    event: str = "evt-1",
) -> tuple[ArbQuote, ArbQuote]:
    """Standard 2-way arb pair (Player A vs Player B)."""
    qa = make_quote(
        quote_id=f"{id_prefix}-a",
        bookmaker=book_a,
        selection_side=SelectionSide.PARTICIPANT_A,
        odds=odds_a,
        participant_a="Player A",
        participant_b="Player B",
        canonical_event_id=event,
    )
    qb = make_quote(
        quote_id=f"{id_prefix}-b",
        bookmaker=book_b,
        selection_side=SelectionSide.PARTICIPANT_B,
        odds=odds_b,
        participant_a="Player A",
        participant_b="Player B",
        canonical_event_id=event,
    )
    return qa, qb
