"""Backfill job tests: dry-run unit coverage plus DB-gated integration runs."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from defend_sports.backfill import BackfillJob
from defend_sports.db import SportsDatabase
from defend_sports.ingestion import IngestionService
from defend_sports.providers.base import ProviderBatch

requires_database = pytest.mark.skipif(
    not os.environ.get("SPORTS_TEST_DATABASE_URL"),
    reason="SPORTS_TEST_DATABASE_URL is required for PostgreSQL integration tests",
)

_WINDOW_START = datetime(2026, 1, 1, tzinfo=timezone.utc)


class FakeProvider:
    provider_name = "odds_api_io"

    def __init__(
        self,
        pages: list[list[dict[str, object]]],
        *,
        repeat_pages: bool = False,
        odds_payloads: dict[str, dict[str, object]] | None = None,
    ) -> None:
        self.flat = [event for page in pages for event in page]
        self.requests = 0
        self.repeat_pages = repeat_pages
        self.odds_payloads = odds_payloads or {}
        self.odds_calls: list[str] = []

    def historical_events(
        self,
        from_dt: datetime,
        to_dt: datetime,
        *,
        skip: int = 0,
        limit: int = 200,
        league_slug: str | None = None,
    ) -> tuple[list[dict[str, object]], int]:
        self.requests += 1
        if self.repeat_pages:
            return self.flat[:limit], 200
        return self.flat[skip : skip + limit], 200

    def historical_odds(
        self,
        event_id: str,
        bookmakers: list[str] | tuple[str, ...] | None = None,
    ) -> dict[str, object]:
        self.odds_calls.append(event_id)
        return self.odds_payloads.get(event_id, {"bookmakers": {}})


def _settled_event(event_id: str, home: str, away: str, days: int) -> dict[str, object]:
    return {
        "id": event_id,
        "home": home,
        "away": away,
        "league": "TT Pro",
        "date": f"2026-01-{days:02d}T12:00:00Z",
        "status": "settled",
        "scores": {"home": 3, "away": 1},
    }


class FakeIngestion:
    def __init__(self) -> None:
        self.batches: list[ProviderBatch] = []
        self.created = 0

    def ingest(self, batch: ProviderBatch) -> object:
        self.batches.append(batch)
        self.created += len(batch.raw_events)
        return type(
            "IngestionResult",
            (),
            {"raw_events_created": len(batch.raw_events)},
        )()


class RecordingSink:
    def __init__(self) -> None:
        self.calls: list[list[object]] = []

    def __call__(self, results: list[object]) -> int:
        self.calls.append(list(results))
        return len(results)


@pytest.fixture(scope="session")
def database():
    url = os.environ.get("SPORTS_TEST_DATABASE_URL")
    if not url:
        return None
    database = SportsDatabase(url)
    database.migrate()
    return database


@pytest.fixture(autouse=True)
def _clean_backfill_tables(database):
    if database is None:
        yield
        return
    with database.connect() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    TRUNCATE backfill_checkpoints, odds_snapshots,
                             live_observations, raw_provider_events,
                             provider_health, selections, markets, sport_events,
                             leagues, participants, sports, provider_sources
                    RESTART IDENTITY CASCADE
                    """
                )
    yield


def _make_job(
    provider: FakeProvider,
    *,
    ingestion=None,
    sink=None,
    dry_run: bool = False,
    max_requests: int = 100,
    from_dt: datetime = _WINDOW_START,
    to_dt: datetime | None = None,
    resume: bool = True,
    database: SportsDatabase | None = None,
    window_days_max: int = 7,
    page_size: int = 200,
    odds_fetch_cap: int = 0,
    bookmakers: tuple[str, ...] = (),
) -> BackfillJob:
    return BackfillJob(
        database or SportsDatabase("unused-url"),
        provider,
        sport="table_tennis",
        league="",
        from_dt=from_dt,
        to_dt=to_dt or (from_dt + timedelta(days=5)),
        max_requests=max_requests,
        page_size=page_size,
        window_days_max=window_days_max,
        odds_fetch_cap=odds_fetch_cap,
        bookmakers=bookmakers,
        dry_run=dry_run,
        resume=resume,
        ingestion=ingestion,
        results_sink=sink,
    )


def test_dry_run_reports_counts_without_database_or_sink():
    provider = FakeProvider(
        [
            [
                _settled_event("e1", "Alice", "Bob", 1),
                _settled_event("e2", "Carol", "Dave", 2),
            ]
        ]
    )
    report = _make_job(provider, dry_run=True).run()
    assert report.status == "COMPLETED"
    assert report.dry_run is True
    assert report.requests_used == 1
    assert report.events_seen == 2
    assert report.events_persisted == 2
    assert report.results_ambiguous == 0
    assert report.results_persisted == 0


def test_dry_run_counts_ambiguous_missing_names():
    event = _settled_event("e1", "", "", 1)
    provider = FakeProvider([[event]])
    report = _make_job(provider, dry_run=True).run()
    assert report.results_ambiguous == 1
    assert report.results_persisted == 0


def test_window_splitting_caps_at_requested_days():
    provider = FakeProvider([[]])
    job = _make_job(
        provider,
        dry_run=True,
        from_dt=_WINDOW_START,
        to_dt=_WINDOW_START + timedelta(days=95),
        window_days_max=31,
    )
    windows = job._windows()
    assert len(windows) == 4
    assert all((end - start).days <= 31 for start, end in windows)
    assert windows[0][0] == _WINDOW_START
    assert windows[-1][1] == _WINDOW_START + timedelta(days=95)

    short = _make_job(
        provider,
        dry_run=True,
        from_dt=_WINDOW_START,
        to_dt=_WINDOW_START + timedelta(days=10),
    )
    assert len(short._windows()) == 2  # default 7-day windows


def test_identical_pages_stop_pagination_with_warning():
    provider = FakeProvider(
        [[_settled_event(f"e{i}", "Alice", "Bob", i) for i in range(1, 5)]],
        repeat_pages=True,
    )
    report = _make_job(provider, dry_run=True, max_requests=10, page_size=2).run()
    assert report.status == "COMPLETED"
    assert report.requests_used == 2
    assert report.events_seen == 2  # no duplicate rows from repeated pages
    assert any("PAGINATION_IGNORED" in w for w in report.warnings)


def test_window_truncation_at_provider_cap_warns():
    provider = FakeProvider(
        [[_settled_event(f"e{i}", "Alice", "Bob", i) for i in range(1, 1001)]]
    )
    report = _make_job(provider, dry_run=True, page_size=1000).run()
    assert report.status == "COMPLETED"
    assert any("WINDOW_TRUNCATION_SUSPECTED" in w for w in report.warnings)


def test_odds_fetch_is_bounded_and_quota_aware():
    provider = FakeProvider(
        [
            [
                _settled_event("o1", "Alice", "Bob", 1),
                _settled_event("o2", "Carol", "Dave", 2),
                _settled_event("o3", "Eve", "Frank", 3),
            ]
        ],
        odds_payloads={
            "o1": {
                "bookmakers": {
                    "22Bet": {"markets": {"ML": {"home": 1.85, "away": 2.05}}}
                }
            },
            "o2": {"bookmakers": {}},
        },
    )
    report = _make_job(
        provider, dry_run=True, odds_fetch_cap=2, bookmakers=("22Bet", "888Sport")
    ).run()
    assert report.status == "COMPLETED"
    assert provider.odds_calls == ["o1", "o2"]  # cap of 2, settled only
    assert report.odds_persisted == 2  # home + away selections from o1
    assert report.requests_used == 3  # 1 window page + 2 odds fetches

    capped = _make_job(
        provider, dry_run=True, odds_fetch_cap=10, max_requests=1
    ).run()
    assert capped.status == "RUNNING"
    assert any("ODDS_SKIPPED_QUOTA" in w for w in capped.warnings)


def test_quota_stop_leaves_running_and_rerun_completes():
    provider = FakeProvider(
        [
            [_settled_event(f"e{i}", "Alice", "Bob", i) for i in range(1, 200)],
            [_settled_event(f"e{i}", "Alice", "Bob", i) for i in range(200, 251)],
        ]
    )
    first = _make_job(provider, dry_run=True, max_requests=1).run()
    assert first.status == "RUNNING"
    assert first.requests_used == 1
    assert first.events_seen == 200
    second = _make_job(provider, dry_run=True, max_requests=5).run()
    assert second.status == "COMPLETED"
    assert second.requests_used == 2
    assert second.events_seen == 250
    assert provider.requests == 3  # re-run is safe; idempotency prevents dupes


@requires_database
def test_quota_stop_resumes_from_checkpoint(database):
    provider = FakeProvider(
        [
            [_settled_event(f"e{i}", "Alice", "Bob", i) for i in range(1, 200)],
            [_settled_event(f"e{i}", "Alice", "Bob", i) for i in range(200, 251)],
        ]
    )
    first = _make_job(
        provider,
        database=database,
        ingestion=IngestionService(database),
        sink=RecordingSink(),
        max_requests=1,
    ).run()
    assert first.status == "RUNNING"
    assert first.events_seen == 200

    second = _make_job(
        provider,
        database=database,
        ingestion=IngestionService(database),
        sink=RecordingSink(),
        max_requests=5,
    ).run()
    assert second.status == "COMPLETED"
    assert second.resumed is True
    assert second.requests_used == 1
    assert second.events_seen == 50
    assert provider.requests == 2  # resumed from skip 200, no refetch

    with database.connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM raw_provider_events")
            assert cursor.fetchone()[0] == 250


@requires_database
def test_backfill_persists_events_and_checkpoint(database):
    provider = FakeProvider(
        [
            [
                _settled_event("b1", "Alice", "Bob", 1),
                _settled_event("b2", "Carol", "Dave", 2),
            ]
        ]
    )
    sink = RecordingSink()
    job = _make_job(
        provider,
        database=database,
        ingestion=IngestionService(database),
        sink=sink,
    )
    report = job.run()
    assert report.status == "COMPLETED"
    assert report.events_persisted == 2
    assert report.requests_used == 1
    assert len(sink.calls) == 1
    assert len(sink.calls[0]) == 2
    assert sink.calls[0][0].event_key == "oaio:b1"
    assert sink.calls[0][0].source_provider == "odds_api_io"
    assert sink.calls[0][0].home_participant_key == "table_tennis:alice"

    with database.connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM raw_provider_events")
            assert cursor.fetchone()[0] == 2
            cursor.execute(
                "SELECT status FROM backfill_checkpoints"
                " WHERE provider = 'odds_api_io'"
            )
            assert cursor.fetchone()[0] == "COMPLETED"


@requires_database
def test_backfill_rerun_is_idempotent_when_resume_disabled(database):
    provider = FakeProvider(
        [[_settled_event("c1", "Alice", "Bob", 1)]]
    )
    sink = RecordingSink()
    first = _make_job(
        provider,
        database=database,
        ingestion=IngestionService(database),
        sink=sink,
    ).run()
    assert first.status == "COMPLETED"
    second = _make_job(
        provider,
        database=database,
        ingestion=IngestionService(database),
        sink=sink,
        resume=False,
    ).run()
    assert second.status == "COMPLETED"
    assert second.resumed is False
    with database.connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM raw_provider_events")
            assert cursor.fetchone()[0] == 1
            cursor.execute("SELECT count(*) FROM sport_events")
            assert cursor.fetchone()[0] == 1
    assert len(sink.calls) == 2  # results upserted again; no duplicates by event_key


@requires_database
def test_completed_checkpoint_short_circuits(database):
    provider = FakeProvider(
        [[_settled_event("d1", "Alice", "Bob", 1)]]
    )
    first = _make_job(
        provider,
        database=database,
        ingestion=IngestionService(database),
        sink=RecordingSink(),
    ).run()
    assert first.status == "COMPLETED"
    second = _make_job(
        provider,
        database=database,
        ingestion=IngestionService(database),
        sink=RecordingSink(),
    ).run()
    assert second.status == "COMPLETED"
    assert second.resumed is True
    assert second.requests_used == 0
    assert provider.requests == 1