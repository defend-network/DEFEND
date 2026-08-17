"""Read-only compatibility adapter exposing DEFEND Sports data through
DEFENDmarkets abstractions.

The Sports schema is never modified. Timestamps observed_at (published)
and received_at (retrieved) are preserved exactly. Fields the Sports
schema cannot provide — announced time, normalization version — are
reported as unavailable through ``pit_availability`` and left None rather
than fabricated.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping, Protocol, runtime_checkable

from defend_markets.domain import (
    CostModel,
    InstrumentType,
    MarketInstrument,
    PitAvailability,
    ProvenanceStamp,
)


def sports_instrument_key(event_key: str, market_key: str, selection_key: str) -> str:
    return f"sports:{event_key}:{market_key}:{selection_key}"


def sports_desk_of(instrument_key: str) -> str:
    return instrument_key.split(":", 1)[0] if ":" in instrument_key else instrument_key


@dataclass(frozen=True)
class SportsSelectionQuote:
    selection_key: str = ""
    display_name: str = ""
    decimal_odds: Decimal | None = None
    provenance: ProvenanceStamp | None = None
    selection_id: str | None = None
    costs: "CostModel | None" = None


@runtime_checkable
class SportsDataReader(Protocol):
    """Provider-neutral read access to Sports data used by decision loops."""

    def venues(self) -> list[dict[str, object]]: ...

    def tt_events(self) -> list[dict[str, object]]: ...

    def latest_live_state(
        self, event_key: str
    ) -> dict[str, object] | None: ...

    def market_selections(self, event_key: str, market_key: str) -> list[SportsSelectionQuote]: ...

    def latest_odds(
        self, event_key: str, market_key: str
    ) -> list[SportsSelectionQuote]: ...

    def provider_health(self) -> dict[str, Mapping[str, object]]: ...

    def pit_availability(self) -> PitAvailability: ...


_SPORTS_PIT_AVAILABILITY = PitAvailability(
    provided=frozenset({"observed_at", "received_at", "scheduled_at", "raw_ref"}),
    limitations=(
        "sport_events.announced_at is not modeled by the Sports schema",
        "normalization_version is not recorded by the Sports pipeline",
        "live state point times are not modeled per field",
    ),
)


class PostgresSportsDataReader:
    """Reads Sports tables directly; never writes."""

    def __init__(self, sports_database: Any) -> None:
        self._database = sports_database

    def venues(self) -> list[dict[str, object]]:
        with self._database.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT source_key, provider_name, display_name, is_active
                    FROM provider_sources
                    ORDER BY source_key
                    """
                )
                return [
                    {
                        "venue_key": row[0],
                        "provider": row[1],
                        "display_name": row[2],
                        "is_active": row[3],
                    }
                    for row in cursor.fetchall()
                ]

    def tt_events(self) -> list[dict[str, object]]:
        with self._database.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT e.event_key, e.display_name, e.scheduled_at, s.sport_key, l.league_key
                    FROM sport_events e
                    JOIN sports s ON s.sport_id = e.sport_id
                    LEFT JOIN leagues l ON l.league_id = e.league_id
                    WHERE s.sport_key = 'table_tennis'
                    ORDER BY e.event_key
                    """
                )
                return [
                    {
                        "event_key": row[0],
                        "display_name": row[1],
                        "scheduled_at": row[2],
                        "sport_key": row[3],
                        "league_key": row[4],
                    }
                    for row in cursor.fetchall()
                ]

    def latest_live_state(self, event_key: str) -> dict[str, object] | None:
        """Latest raw live observation for an event, passed through untouched.

        ``state_json`` is the provider's own shape (e.g. sets/games/points
        for table tennis); it is never normalized here so nothing is
        invented about its semantics. Returns None when no observation
        exists or the state cannot be parsed.
        """
        with self._database.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT lo.state_json, lo.observed_at, lo.received_at
                    FROM live_observations lo
                    JOIN sport_events e ON e.event_id = lo.event_id
                    WHERE e.event_key = %s
                    ORDER BY lo.observed_at DESC, lo.live_observation_id DESC
                    LIMIT 1
                    """,
                    (event_key,),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        state = row[0]
        if not isinstance(state, dict):
            return None
        return {
            "state": state,
            "observed_at": row[1],
            "received_at": row[2],
        }

    def market_selections(self, event_key: str, market_key: str) -> list[SportsSelectionQuote]:
        with self._database.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT sel.selection_key, sel.display_name, sel.selection_id
                    FROM selections sel
                    JOIN markets m ON m.market_id = sel.market_id
                    JOIN sport_events e ON e.event_id = m.event_id
                    WHERE e.event_key = %s AND m.market_key = %s
                    ORDER BY sel.selection_key
                    """,
                    (event_key, market_key),
                )
                return [
                    SportsSelectionQuote(
                        selection_key=row[0],
                        display_name=row[1],
                        selection_id=str(row[2]),
                    )
                    for row in cursor.fetchall()
                ]

    def latest_odds(self, event_key: str, market_key: str) -> list[SportsSelectionQuote]:
        with self._database.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT DISTINCT ON (sel.selection_key, ps.source_key)
                           sel.selection_key, sel.display_name, sel.selection_id,
                           o.decimal_odds, o.observed_at, o.received_at, ps.source_key,
                           rp.provider_event_id
                    FROM odds_snapshots o
                    JOIN selections sel ON sel.selection_id = o.selection_id
                    JOIN markets m ON m.market_id = sel.market_id
                    JOIN sport_events e ON e.event_id = m.event_id
                    JOIN provider_sources ps ON ps.source_id = o.source_id
                    JOIN raw_provider_events rp ON rp.raw_event_id = o.raw_event_id
                    WHERE e.event_key = %s AND m.market_key = %s
                    ORDER BY sel.selection_key, ps.source_key, o.observed_at DESC
                    """,
                    (event_key, market_key),
                )
                return [
                    SportsSelectionQuote(
                        selection_key=row[0],
                        display_name=row[1],
                        selection_id=str(row[2]),
                        decimal_odds=row[3],
                        provenance=ProvenanceStamp(
                            source_key=row[6],
                            observed_at=row[4],
                            received_at=row[5],
                            raw_ref=row[7],
                            normalization_version=None,
                        ),
                    )
                    for row in cursor.fetchall()
                ]

    def provider_health(self) -> dict[str, Mapping[str, object]]:
        with self._database.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT DISTINCT ON (ps.source_key)
                           ps.source_key, h.status, h.observed_at
                    FROM provider_health h
                    JOIN provider_sources ps ON ps.source_id = h.source_id
                    ORDER BY ps.source_key, h.provider_health_id DESC
                    """
                )
                return {
                    row[0]: {"status": row[1], "observed_at": row[2]}
                    for row in cursor.fetchall()
                }

    def pit_availability(self) -> PitAvailability:
        return _SPORTS_PIT_AVAILABILITY

    def instrument_view(self, event_key: str, market_key: str, selection_key: str, venue_key: str) -> MarketInstrument:
        return MarketInstrument(
            instrument_key=sports_instrument_key(event_key, market_key, selection_key),
            instrument_type=InstrumentType.SPORTS_MARKET,
            display_name=f"{event_key} {market_key} {selection_key}",
            venue_key=venue_key,
            taxonomy={
                "desk": "sports",
                "event_key": event_key,
                "market_key": market_key,
                "selection_key": selection_key,
            },
        )


def normalize_quotes(quotes: list[SportsSelectionQuote]) -> list[dict[str, object]]:
    """Normalize adapter quotes into strategy evaluation inputs.

    Provenance stamps are passed through untouched; quotes without an
    odds or provenance value stay explicit so missing provenance can be
    detected rather than hidden.
    """
    normalized: list[dict[str, object]] = []
    for quote in quotes:
        normalized.append(
            {
                "selection_key": quote.selection_key,
                "display_name": quote.display_name,
                "decimal_odds": quote.decimal_odds,
                "provenance": quote.provenance,
                "costs": quote.costs,
            }
        )
    return normalized