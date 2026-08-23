"""Reusable, resumable, quota-aware historical backfill for DEFEND Sports.

The backfill job is deliberately NOT a one-off script: it is a small
orchestrator that pages a provider's historical endpoints, hands every page
to the canonical ingestion service (which persists raw payloads, canonical
events, markets and odds snapshots transactionally and idempotently), and
records a durable checkpoint per (provider, sport, league, window) so a
crash or quota stop can resume without data loss or duplication.

Design rules:

* Idempotency is the crash-safety mechanism. Ingestion skips raw events
  that already exist, so re-running a window costs requests but never
  duplicates rows.
* Quota awareness: the job counts every provider request and stops at
  ``max_requests``, leaving the checkpoint RUNNING so the next invocation
  resumes.
* Provenance: every row keeps the provider source, the raw provider payload
  and a stable raw event reference (``oaio:<id>@hist:<date>``), so
  historical rows are independently attributable and never overwrite rows
  from a live provider (canonical event keys are namespaced by the
  provider adapter).
* Ambiguity: completed events whose participant names are missing cannot be
  mapped to canonical participant keys and are counted as ambiguous instead
  of being written as results. They never poison training history.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Sequence

from defend_markets.domain import TTMatchResult
from defend_markets.feeds import participant_key

from defend_sports.db import SportsDatabase
from defend_sports.ingestion import IngestionService
from defend_sports.providers.base import ProviderBatch, RawProviderEvent
from defend_sports.providers.odds_api_io import (
    OddsApiIoProviderError,
    OddsApiIoSportsProvider,
    _parse_scores,
    parse_event_payload,
    parse_odds_payload,
    parse_tt_final_result,
)

_WINDOW_DAYS_DEFAULT = 7

_MAX_PAGE_CAP = 1000


@dataclass(frozen=True)
class BackfillReport:
    provider: str
    sport: str
    league: str
    window_from: datetime
    window_to: datetime
    status: str
    dry_run: bool
    resumed: bool
    requests_used: int
    events_seen: int
    events_persisted: int
    odds_persisted: int
    results_persisted: int
    results_ambiguous: int
    cursor_value: str
    error_detail: str | None = None
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "sport": self.sport,
            "league": self.league,
            "window_from": self.window_from.isoformat(),
            "window_to": self.window_to.isoformat(),
            "status": self.status,
            "dry_run": self.dry_run,
            "resumed": self.resumed,
            "requests_used": self.requests_used,
            "events_seen": self.events_seen,
            "events_persisted": self.events_persisted,
            "odds_persisted": self.odds_persisted,
            "results_persisted": self.results_persisted,
            "results_ambiguous": self.results_ambiguous,
            "cursor_value": self.cursor_value,
            "error_detail": self.error_detail,
            "warnings": list(self.warnings),
        }


class BackfillJob:
    """One historical window run against one provider, resumable per window."""

    def __init__(
        self,
        database: SportsDatabase,
        provider: OddsApiIoSportsProvider,
        *,
        sport: str = "table_tennis",
        league: str = "",
        from_dt: datetime,
        to_dt: datetime,
        max_requests: int = 200,
        page_size: int = 1000,
        window_days_max: int = _WINDOW_DAYS_DEFAULT,
        odds_fetch_cap: int = 0,
        bookmakers: Sequence[str] = (),
        dry_run: bool = False,
        resume: bool = True,
        ingestion: IngestionService | None = None,
        results_sink: Callable[[Sequence[TTMatchResult]], int] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._database = database
        self._provider = provider
        self._ingestion = ingestion
        self._results_sink = results_sink
        self._sport = sport
        self._league = league or ""
        self._from_dt = from_dt
        self._to_dt = to_dt
        self._max_requests = max_requests
        self._page_size = page_size
        self._window_days_max = window_days_max
        self._odds_fetch_cap = odds_fetch_cap
        self._bookmakers = tuple(bookmakers)
        self._dry_run = dry_run
        self._resume = resume
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        if from_dt.tzinfo is None or to_dt.tzinfo is None:
            raise ValueError("window bounds must be timezone-aware datetimes")
        if to_dt <= from_dt:
            raise ValueError("window_to must be after window_from")

    # ------------------------------------------------------------ checkpoint

    def _checkpoint_row(
        self, connection: Any, window_from: datetime, window_to: datetime
    ) -> dict[str, object] | None:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT cursor_value, status, error_detail, events_seen
                FROM backfill_checkpoints
                WHERE provider = %s AND sport = %s AND league = %s
                  AND window_from = %s AND window_to = %s
                """,
                (
                    self._provider.provider_name,
                    self._sport,
                    self._league,
                    window_from,
                    window_to,
                ),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return {
                "cursor_value": row[0],
                "status": row[1],
                "error_detail": row[2],
                "events_seen": row[3],
            }

    def _write_checkpoint(
        self,
        connection: Any,
        *,
        window_from: datetime,
        window_to: datetime,
        status: str,
        cursor_value: str,
        events_seen: int,
        events_persisted: int,
        odds_persisted: int,
        results_persisted: int,
        error_detail: str | None = None,
    ) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO backfill_checkpoints
                    (provider, sport, league, window_from, window_to,
                     cursor_value, events_seen, events_persisted, odds_persisted,
                     results_persisted, requests_used, status, error_detail,
                     updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (provider, sport, league, window_from, window_to)
                DO UPDATE SET
                    cursor_value = EXCLUDED.cursor_value,
                    events_seen = EXCLUDED.events_seen,
                    events_persisted = EXCLUDED.events_persisted,
                    odds_persisted = EXCLUDED.odds_persisted,
                    results_persisted = EXCLUDED.results_persisted,
                    requests_used = EXCLUDED.requests_used,
                    status = EXCLUDED.status,
                    error_detail = EXCLUDED.error_detail,
                    updated_at = now()
                """,
                (
                    self._provider.provider_name,
                    self._sport,
                    self._league,
                    window_from,
                    window_to,
                    cursor_value,
                    events_seen,
                    events_persisted,
                    odds_persisted,
                    results_persisted,
                    self._requests_used,
                    status,
                    error_detail,
                ),
            )

    # ------------------------------------------------------------------ run

    def run(self) -> BackfillReport:
        self._requests_used = 0
        events_seen = 0
        events_persisted = 0
        odds_persisted = 0
        results_persisted = 0
        results_ambiguous = 0
        cursor_value = ""
        error_detail: str | None = None
        warnings: list[str] = []
        resumed = False
        quota_hit = False

        try:
            for window_from, window_to in self._windows():
                prior: dict[str, object] | None = None
                if not self._dry_run:
                    with self._database.connect() as connection:
                        with connection.transaction():
                            prior = self._checkpoint_row(connection, window_from, window_to)
                if (
                    prior is not None
                    and prior["status"] == "COMPLETED"
                    and self._resume
                ):
                    resumed = True
                    cursor_value = str(prior["cursor_value"] or "")
                    continue
                if prior is not None and self._resume:
                    resumed = True
                skip_start = (
                    int(prior["events_seen"] or 0)
                    if (prior is not None and self._resume)
                    else 0
                )
                batch, seen, ambiguous, page_warnings = self._fetch_window(
                    window_from, window_to, skip_start=skip_start
                )
                warnings.extend(page_warnings)
                events_seen += seen
                results_ambiguous += ambiguous
                if batch is not None:
                    odds_rows, odds_warnings = self._collect_odds(batch)
                    warnings.extend(odds_warnings)
                    if odds_rows:
                        batch = ProviderBatch(
                            raw_events=batch.raw_events,
                            events=batch.events,
                            odds=batch.odds + tuple(odds_rows),
                            live=batch.live,
                        )
                    events_persisted += self._persist_batch(batch)
                    results = self._persist_results(batch)
                    if results and not self._dry_run and self._results_sink is not None:
                        results_persisted += self._results_sink(results)
                    odds_persisted += len(batch.odds)
                    if batch.raw_events:
                        cursor_value = batch.raw_events[-1].provider_event_id
                if not self._dry_run:
                    with self._database.connect() as connection:
                        with connection.transaction():
                            self._write_checkpoint(
                                connection,
                                window_from=window_from,
                                window_to=window_to,
                                status=(
                                    "RUNNING"
                                    if self._requests_used >= self._max_requests
                                    else "COMPLETED"
                                ),
                                cursor_value=cursor_value,
                                events_seen=(
                                    int(prior["events_seen"] or 0) + seen
                                    if (prior is not None and self._resume)
                                    else seen
                                ),
                                events_persisted=events_persisted,
                                odds_persisted=odds_persisted,
                                results_persisted=results_persisted,
                                error_detail=error_detail,
                            )
                if self._requests_used >= self._max_requests:
                    quota_hit = True
                    break
            status = "RUNNING" if quota_hit else "COMPLETED"
        except (OddsApiIoProviderError, RuntimeError) as error:
            status = "FAILED"
            error_detail = f"{type(error).__name__}: {error}"
        except Exception as error:  # defensive: checkpoint must survive any crash
            status = "FAILED"
            error_detail = f"{type(error).__name__}: {error}"

        return BackfillReport(
            provider=self._provider.provider_name,
            sport=self._sport,
            league=self._league,
            window_from=self._from_dt,
            window_to=self._to_dt,
            status=status,
            dry_run=self._dry_run,
            resumed=resumed,
            requests_used=self._requests_used,
            events_seen=events_seen,
            events_persisted=events_persisted,
            odds_persisted=odds_persisted,
            results_persisted=results_persisted,
            results_ambiguous=results_ambiguous,
            cursor_value=cursor_value,
            error_detail=error_detail,
            warnings=tuple(warnings),
        )

    # -------------------------------------------------------------- internals

    def _windows(self) -> Sequence[tuple[datetime, datetime]]:
        windows: list[tuple[datetime, datetime]] = []
        cursor = self._from_dt
        while cursor < self._to_dt:
            next_bound = min(
                cursor + timedelta(days=self._window_days_max), self._to_dt
            )
            windows.append((cursor, next_bound))
            cursor = next_bound
        return windows

    def _fetch_window(
        self,
        window_from: datetime,
        window_to: datetime,
        *,
        skip_start: int = 0,
    ) -> tuple[ProviderBatch | None, int, int, list[str]]:
        rows: list[dict[str, object]] = []
        skip = skip_start
        warnings: list[str] = []
        previous_first_id: str | None = None
        while True:
            if self._requests_used >= self._max_requests:
                break
            page, _status = self._provider.historical_events(
                window_from,
                window_to,
                skip=skip,
                limit=self._page_size,
                league_slug=self._league or None,
            )
            self._requests_used += 1
            if page:
                first_id = str(page[0].get("id") or "")
                if first_id and first_id == previous_first_id:
                    warnings.append(
                        "PAGINATION_IGNORED: provider returned the same page "
                        "again; stopping paging for this window"
                    )
                    break
                previous_first_id = first_id
            rows.extend(page)
            if len(page) >= _MAX_PAGE_CAP:
                warnings.append(
                    "WINDOW_TRUNCATION_SUSPECTED: a window page hit the "
                    f"provider's {_MAX_PAGE_CAP}-row cap; shrink --window-days "
                    "to guarantee completeness"
                )
            if len(page) < self._page_size or len(rows) >= 5000:
                break
            skip += self._page_size

        if not rows:
            return None, 0, 0, warnings

        raw_events: list[RawProviderEvent] = []
        canonical_events = []
        ambiguous = 0
        for match in rows:
            event_id = str(match.get("id") or "").strip()
            if event_id and not (
                str(match.get("home") or "").strip()
                and str(match.get("away") or "").strip()
            ):
                ambiguous += 1
                continue
            observed_at = _parse_timestamp(match.get("date")) or window_from
            suffix = f"hist:{observed_at:%Y%m%d}"
            parsed = parse_event_payload(
                match,
                observed_at=observed_at,
                suffix=suffix,
                league_slug=self._league or None,
            )
            if parsed is None:
                continue
            raw_events.append(parsed[0])
            canonical_events.append(parsed[1])

        return (
            ProviderBatch(
                raw_events=tuple(raw_events),
                events=tuple(canonical_events),
            ),
            len(raw_events),
            ambiguous,
            warnings,
        )

    def _persist_batch(self, batch: ProviderBatch) -> int:
        if self._dry_run:
            return len(batch.raw_events)
        if self._ingestion is None:
            raise RuntimeError("ingestion service required when not dry-running")
        result = self._ingestion.ingest(batch)
        return result.raw_events_created

    def _collect_odds(
        self, batch: ProviderBatch
    ) -> tuple[list[object], list[str]]:
        """Fetch /historical/odds for settled events (bounded, quota-aware).

        Every provider request counts against the budget. The live API
        requires explicit bookmakers and returns an empty bookmakers mapping
        when an event carried no odds; both shapes are tolerated.
        """
        warnings: list[str] = []
        if self._odds_fetch_cap <= 0:
            return [], warnings
        rows: list[object] = []
        fetched = 0
        for raw in batch.raw_events:
            if fetched >= self._odds_fetch_cap:
                break
            if self._requests_used >= self._max_requests:
                warnings.append("ODDS_SKIPPED_QUOTA: budget exhausted")
                break
            payload = raw.payload
            status_value = str(payload.get("status") or "").lower()
            if status_value not in ("settled", "finished", "completed", "ended"):
                continue
            event_external_id = "oaio:" + str(payload.get("id") or "")
            try:
                odds_payload = self._provider.historical_odds(
                    str(payload.get("id") or ""),
                    bookmakers=self._bookmakers or None,
                )
                self._requests_used += 1
            except OddsApiIoProviderError as error:
                self._requests_used += 1
                warnings.append(f"ODDS_FAILED:{event_external_id}:{error}")
                continue
            fetched += 1
            observed_at = _parse_timestamp(payload.get("date")) or self._from_dt
            rows.extend(
                parse_odds_payload(
                    odds_payload,
                    event_external_id=event_external_id,
                    raw_event_ref=raw.provider_event_id,
                    default_observed_at=observed_at,
                    provider_name=self._provider.provider_name,
                )
            )
        return rows, warnings

    def _persist_results(self, batch: ProviderBatch) -> list[TTMatchResult]:
        results: list[TTMatchResult] = []
        for raw in batch.raw_events:
            payload = raw.payload
            event_external_id = "oaio:" + str(payload.get("id") or "")
            status_value = str(payload.get("status") or "").lower()
            if status_value not in ("settled", "finished", "completed", "ended"):
                continue
            final = parse_tt_final_result(payload)
            if final.status == "UNRESOLVED" or final.home_score is None or final.away_score is None:
                continue
            home = str(payload.get("home") or "").strip()
            away = str(payload.get("away") or "").strip()
            if not home or not away:
                continue
            league_key = self._league or "table_tennis"
            completed_at = _parse_timestamp(payload.get("date"))
            results.append(
                TTMatchResult(
                    event_key=event_external_id,
                    league_key=league_key,
                    home_participant_key=participant_key("table_tennis", home),
                    away_participant_key=participant_key("table_tennis", away),
                    home_score=final.home_score,
                    away_score=final.away_score,
                    completed_at=completed_at,
                    source_provider=self._provider.provider_name,
                    raw_ref=raw.provider_event_id,
                )
            )
        return results


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


__all__ = ["BackfillJob", "BackfillReport"]