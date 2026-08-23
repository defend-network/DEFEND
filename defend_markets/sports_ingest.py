"""DEFENDmarkets-owned sports/odds persistence (M4.8.2D).

Markets-owned replacement for the legacy ``defend_sports`` ingestion service and
repository. Persists provider batches transactionally and idempotently into
Markets-owned tables (see migration 0025). No legacy application dependency, no
legacy Sports DB writes.

All methods run against a caller-managed psycopg connection so a whole ingestion
batch can share one transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from defend_markets.sports_domain import (
    CanonicalEvent,
    CanonicalMarket,
    CanonicalSelection,
    LiveObservation,
    OddsObservation,
    SourceRef,
)
from defend_markets.sports_provider import ProviderBatch, RawProviderEvent


def humanize_key(key: str) -> str:
    """Convert a canonical key like ``match_winner`` to display text."""
    words = key.replace("-", " ").split("_")
    return " ".join(word.capitalize() for word in words if word)


_HEALTH_STATUSES = ("HEALTHY", "DEGRADED", "UNAVAILABLE")


class SportsRepository:
    """Idempotent upserts and append-only observation writes (Markets-owned)."""

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
                (uuid4(), sport_id, league_id, event.event_external_id, event.display_name, event.scheduled_at),
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

    def upsert_market(self, connection: Any, market: CanonicalMarket, *, event_id: UUID) -> UUID:
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

    def upsert_selection(self, connection: Any, selection: CanonicalSelection, *, market_id: UUID) -> UUID:
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


@dataclass(frozen=True)
class IngestionResult:
    provider: str
    raw_events_created: int
    events: int
    live_observations: int
    odds_snapshots: int
    markets: int
    selections: int
    health: str


class IngestionService:
    """Persists provider batches transactionally and idempotently (Markets-owned)."""

    def __init__(
        self,
        database: Any,
        repository: SportsRepository | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._database = database
        self._repository = repository if repository is not None else SportsRepository()
        self._clock = clock if clock is not None else lambda: datetime.now(timezone.utc)

    def ingest(self, batch: ProviderBatch) -> IngestionResult:
        provider_name = self._provider_name(batch)
        self._validate_batch(batch)
        received_at = self._clock()

        try:
            with self._database.connect() as connection:
                with connection.transaction():
                    result = self._persist(connection, batch, provider_name, received_at)
        except Exception as error:
            self._record_failure(provider_name, error)
            raise
        return result

    def _persist(
        self, connection: Any, batch: ProviderBatch, provider_name: str, received_at: datetime
    ) -> IngestionResult:
        repository = self._repository
        root_ref = SourceRef(provider=provider_name, external_id=provider_name)
        raw_display_names = {
            raw.source.external_id: raw.display_name
            for raw in batch.raw_events
            if raw.display_name is not None
        }

        source_ids: dict[str, Any] = {
            root_ref.external_id: repository.upsert_source(
                connection, root_ref, display_name=raw_display_names.get(root_ref.external_id)
            )
        }
        for ref in self._distinct_sources(batch):
            if ref.external_id not in source_ids:
                source_ids[ref.external_id] = repository.upsert_source(
                    connection, ref, display_name=raw_display_names.get(ref.external_id)
                )

        raw_refs: dict[str, tuple[Any, bool]] = {}
        for raw in batch.raw_events:
            raw_event_id, created = repository.record_raw_event(
                connection,
                raw,
                source_id=source_ids[raw.source.external_id],
                received_at=received_at,
            )
            raw_refs[raw.provider_event_id] = (raw_event_id, created)

        event_ids: dict[str, Any] = {}
        for event in batch.events:
            event_ids[event.event_external_id] = repository.upsert_event(connection, event)

        live_appended = 0
        for observation in batch.live:
            raw_event_id, created = raw_refs[observation.raw_event_ref]
            if not created:
                continue
            repository.append_live_observation(
                connection,
                observation,
                source_id=source_ids[observation.source.external_id],
                event_id=event_ids[observation.event_external_id],
                raw_event_id=raw_event_id,
                received_at=received_at,
            )
            live_appended += 1

        market_ids: dict[tuple[str, str], Any] = {}
        selection_ids: dict[tuple[str, str, str], Any] = {}
        odds_appended = 0
        for observation in batch.odds:
            raw_event_id, created = raw_refs[observation.raw_event_ref]

            market_key = (observation.event_external_id, observation.market_key)
            if market_key not in market_ids:
                market_ids[market_key] = repository.upsert_market(
                    connection,
                    CanonicalMarket(
                        event_external_id=observation.event_external_id,
                        market_key=observation.market_key,
                        display_name=humanize_key(observation.market_key),
                    ),
                    event_id=event_ids[observation.event_external_id],
                )

            selection_key = (
                observation.event_external_id,
                observation.market_key,
                observation.selection_key,
            )
            if selection_key not in selection_ids:
                selection_ids[selection_key] = repository.upsert_selection(
                    connection,
                    CanonicalSelection(
                        market_key=observation.market_key,
                        selection_key=observation.selection_key,
                        display_name=humanize_key(observation.selection_key),
                    ),
                    market_id=market_ids[market_key],
                )

            if not created:
                continue
            repository.append_odds_snapshot(
                connection,
                observation,
                source_id=source_ids[observation.source.external_id],
                market_id=market_ids[market_key],
                selection_id=selection_ids[selection_key],
                raw_event_id=raw_event_id,
                received_at=received_at,
            )
            odds_appended += 1

        observed_at = max(
            (item.observed_at for item in batch.raw_events if item.observed_at is not None),
            default=received_at,
        )
        repository.record_provider_health(
            connection,
            source_id=source_ids[provider_name],
            status="HEALTHY",
            detail={
                "provider": provider_name,
                "raw_events": len(batch.raw_events),
                "events": len(batch.events),
                "live_appended": live_appended,
                "odds_appended": odds_appended,
            },
            observed_at=observed_at,
            received_at=received_at,
        )

        return IngestionResult(
            provider=provider_name,
            raw_events_created=sum(1 for _, created in raw_refs.values() if created),
            events=len(event_ids),
            live_observations=live_appended,
            odds_snapshots=odds_appended,
            markets=len(market_ids),
            selections=len(selection_ids),
            health="HEALTHY",
        )

    def _record_failure(self, provider_name: str, error: Exception) -> None:
        if not provider_name:
            return
        try:
            received_at = self._clock()
            with self._database.connect() as connection:
                with connection.transaction():
                    root_ref = SourceRef(provider=provider_name, external_id=provider_name)
                    source_id = self._repository.upsert_source(connection, root_ref)
                    self._repository.record_provider_health(
                        connection,
                        source_id=source_id,
                        status="UNAVAILABLE",
                        detail={"provider": provider_name, "error": f"{type(error).__name__}: {error}"},
                        observed_at=received_at,
                        received_at=received_at,
                    )
        except Exception:
            pass

    def _provider_name(self, batch: ProviderBatch) -> str:
        names = {ref.provider for ref in self._sources(batch)}
        if not names:
            raise ValueError("batch contains no provider sources")
        if len(names) > 1:
            raise ValueError(f"batch mixes multiple providers: {sorted(names)}")
        return names.pop()

    def _validate_batch(self, batch: ProviderBatch) -> None:
        raw_refs = {raw.provider_event_id for raw in batch.raw_events}
        event_keys = {event.event_external_id for event in batch.events}
        for observation in (*batch.live, *batch.odds):
            if not observation.raw_event_ref or observation.raw_event_ref not in raw_refs:
                raise ValueError(
                    f"observation raw_event_ref must reference a raw event in the same batch: {observation.raw_event_ref!r}"
                )
            if observation.event_external_id not in event_keys:
                raise ValueError(
                    f"observation event must be present in batch events: {observation.event_external_id!r}"
                )

    def _distinct_sources(self, batch: ProviderBatch) -> list[SourceRef]:
        seen: set[tuple[str, str]] = set()
        sources: list[SourceRef] = []
        for ref in self._sources(batch):
            key = (ref.provider, ref.external_id)
            if key in seen:
                continue
            seen.add(key)
            sources.append(ref)
        return sources

    def _sources(self, batch: ProviderBatch) -> Iterable[SourceRef]:
        for raw in batch.raw_events:
            yield raw.source
        for observation in batch.live:
            yield observation.source
        for observation in batch.odds:
            yield observation.source
