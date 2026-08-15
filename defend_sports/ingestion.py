"""Canonical ingestion service for DEFEND Sports provider batches."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from defend_sports.db import SportsDatabase
from defend_sports.domain import CanonicalMarket, CanonicalSelection, SourceRef
from defend_sports.providers.base import ProviderBatch, RawProviderEvent
from defend_sports.repositories import SportsRepository, humanize_key


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
    """Persists provider batches transactionally and idempotently.

    Raw provider payloads are recorded first; canonical events, markets and
    selections are upserted; live observations and odds snapshots append
    historically and are skipped when their raw provider event already
    exists. Provider health is recorded inside the same transaction and an
    UNAVAILABLE row is appended in a fresh transaction on failure.
    """

    def __init__(
        self,
        database: SportsDatabase,
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

    def _persist(self, connection: Any, batch: ProviderBatch, provider_name: str, received_at: datetime) -> IngestionResult:
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

            selection_key = (observation.event_external_id, observation.market_key, observation.selection_key)
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