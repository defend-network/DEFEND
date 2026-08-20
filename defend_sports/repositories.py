"""Persistence API for DEFEND Sports canonical entities and observations."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from defend_sports.domain import (
    CanonicalEvent,
    CanonicalMarket,
    CanonicalSelection,
    LiveObservation,
    OddsObservation,
    SourceRef,
)
from defend_sports.providers.base import RawProviderEvent


def humanize_key(key: str) -> str:
    """Convert a canonical key like ``match_winner`` to display text."""
    words = key.replace("-", " ").split("_")
    return " ".join(word.capitalize() for word in words if word)


_HEALTH_STATUSES = ("HEALTHY", "DEGRADED", "UNAVAILABLE")


class SportsRepository:
    """Idempotent upserts and append-only observation writes.

    All methods run against a caller-managed psycopg connection so a whole
    ingestion batch can share one transaction.
    """

    def upsert_source(self, connection: Any, source: SourceRef, display_name: str | None = None) -> UUID:
        display_name = display_name if display_name else source.external_id
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO provider_sources (source_id, provider_name, source_key, display_name)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (provider_name, source_key)
                DO UPDATE SET display_name = EXCLUDED.display_name, is_active = TRUE
                RETURNING source_id
                """,
                (uuid4(), source.provider, source.external_id, display_name),
            )
            return cursor.fetchone()[0]

    def record_raw_event(
        self,
        connection: Any,
        raw: RawProviderEvent,
        *,
        source_id: UUID,
        received_at: datetime,
    ) -> tuple[UUID, bool]:
        """Persist a raw provider event; returns (raw_event_id, created)."""
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO raw_provider_events
                    (raw_event_id, source_id, provider_event_id, payload, observed_at, received_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_id, provider_event_id) DO NOTHING
                RETURNING raw_event_id
                """,
                (uuid4(), source_id, raw.provider_event_id, Jsonb(raw.payload), raw.observed_at, received_at),
            )
            row = cursor.fetchone()
            if row is not None:
                return row[0], True

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT raw_event_id
                FROM raw_provider_events
                WHERE source_id = %s AND provider_event_id = %s
                """,
                (source_id, raw.provider_event_id),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("raw provider event disappeared during ingest")
            return row[0], False

    def upsert_event(self, connection: Any, event: CanonicalEvent) -> UUID:
        sport_id = self._upsert_sport(connection, event.sport_key)
        league_id = self._upsert_league(connection, sport_id, event.league_key)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO sport_events (event_id, sport_id, league_id, event_key, display_name, scheduled_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (event_key)
                DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    scheduled_at = COALESCE(EXCLUDED.scheduled_at, sport_events.scheduled_at),
                    updated_at = now()
                RETURNING event_id
                """,
                (
                    uuid4(),
                    sport_id,
                    league_id,
                    event.event_external_id,
                    event.display_name,
                    event.scheduled_at,
                ),
            )
            return cursor.fetchone()[0]

    def append_live_observation(
        self,
        connection: Any,
        observation: LiveObservation,
        *,
        source_id: UUID,
        event_id: UUID,
        raw_event_id: UUID,
        received_at: datetime,
    ) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO live_observations (source_id, event_id, state_json, observed_at, received_at, raw_event_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (source_id, event_id, Jsonb(observation.state), observation.observed_at, received_at, raw_event_id),
            )

    def upsert_market(
        self,
        connection: Any,
        market: CanonicalMarket,
        *,
        event_id: UUID,
    ) -> UUID:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO markets (market_id, event_id, market_key, display_name)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (event_id, market_key)
                DO UPDATE SET display_name = EXCLUDED.display_name
                RETURNING market_id
                """,
                (uuid4(), event_id, market.market_key, market.display_name),
            )
            return cursor.fetchone()[0]

    def upsert_selection(
        self,
        connection: Any,
        selection: CanonicalSelection,
        *,
        market_id: UUID,
    ) -> UUID:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO selections (selection_id, market_id, selection_key, display_name)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (market_id, selection_key)
                DO UPDATE SET display_name = EXCLUDED.display_name
                RETURNING selection_id
                """,
                (uuid4(), market_id, selection.selection_key, selection.display_name),
            )
            return cursor.fetchone()[0]

    def append_odds_snapshot(
        self,
        connection: Any,
        observation: OddsObservation,
        *,
        source_id: UUID,
        market_id: UUID,
        selection_id: UUID,
        raw_event_id: UUID,
        received_at: datetime,
    ) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO odds_snapshots (source_id, market_id, selection_id, decimal_odds, observed_at, received_at, raw_event_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    source_id,
                    market_id,
                    selection_id,
                    observation.decimal_odds,
                    observation.observed_at,
                    received_at,
                    raw_event_id,
                ),
            )

    def record_provider_health(
        self,
        connection: Any,
        *,
        source_id: UUID,
        status: str,
        detail: dict[str, object],
        observed_at: datetime,
        received_at: datetime,
    ) -> None:
        if status not in _HEALTH_STATUSES:
            raise ValueError(f"status must be one of {_HEALTH_STATUSES}")
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO provider_health (source_id, status, detail_json, observed_at, received_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (source_id, status, Jsonb(detail), observed_at, received_at),
            )

    def record_discovery(
        self,
        connection: Any,
        *,
        source_id: UUID,
        provider: str,
        payload: list[dict[str, object]],
        observed_at: datetime,
        received_at: datetime,
    ) -> None:
        """Append a provider discovery snapshot (free endpoints, cached)."""
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO provider_discovery (source_id, provider, payload, observed_at, received_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (source_id, provider, Jsonb(payload), observed_at, received_at),
            )

    def record_quota(
        self,
        connection: Any,
        *,
        source_id: UUID,
        provider: str,
        requests_remaining: int | None,
        requests_used: int | None,
        requests_last: str | None,
        status: str,
        observed_at: datetime,
        received_at: datetime,
    ) -> None:
        """Append a provider quota observation read from response headers."""
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO provider_quota
                    (source_id, provider, requests_remaining, requests_used, requests_last,
                     status, observed_at, received_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    source_id,
                    provider,
                    requests_remaining,
                    requests_used,
                    requests_last,
                    status,
                    observed_at,
                    received_at,
                ),
            )

    def _upsert_sport(self, connection: Any, sport_key: str) -> UUID:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO sports (sport_id, sport_key, display_name)
                VALUES (%s, %s, %s)
                ON CONFLICT (sport_key)
                DO UPDATE SET display_name = EXCLUDED.display_name
                RETURNING sport_id
                """,
                (uuid4(), sport_key, humanize_key(sport_key)),
            )
            return cursor.fetchone()[0]

    def _upsert_league(self, connection: Any, sport_id: UUID, league_key: str) -> UUID:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO leagues (league_id, sport_id, league_key, display_name)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (sport_id, league_key)
                DO UPDATE SET display_name = EXCLUDED.display_name
                RETURNING league_id
                """,
                (uuid4(), sport_id, league_key, humanize_key(league_key)),
            )
            return cursor.fetchone()[0]