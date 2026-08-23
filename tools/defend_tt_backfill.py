"""DEFEND table-tennis historical backfill (Odds-API.io, resumable + quota-aware).

Operational harness for the reusable backfill job. Supports dry-run
(no DB writes, shows what the window would produce), request budgets,
resume semantics, and honest status output:

* UNCONFIGURED when ODDS_API_IO_API_KEY is missing
* COMPLETED / RUNNING (quota budget exhausted, resume to continue)
* FAILED with detail when the provider or ingestion raises

The key resolves through the same DPAPI secret store used by Setup &
Integrations (never printed); ODDS_API_IO_API_KEY env var is the override.

Usage:
    python tools/defend_tt_backfill.py --from 2025-12-01 --to 2025-12-08
    python tools/defend_tt_backfill.py --from 2025-12-01 --to 2025-12-08 --dry-run
    python tools/defend_tt_backfill.py --from 2025-12-01 --to 2025-12-31 --max-requests 100
    python tools/defend_tt_backfill.py --status
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from defend_integrations.registry import find_provider
from defend_integrations.stores import SecretRegistry, default_secret_path
from defend_markets.db import MarketsDatabase
from defend_markets.repositories import MarketsRepository
from defend_markets.store import PostgresMarketsStore
from defend_sports.backfill import BackfillJob
from defend_sports.db import SportsDatabase
from defend_sports.ingestion import IngestionService
from defend_sports.providers.odds_api_io import OddsApiIoSportsProvider


def odds_api_io_key() -> str:
    """Resolve ODDS_API_IO_API_KEY: env override first, then the DPAPI store."""
    value = os.environ.get("ODDS_API_IO_API_KEY", "").strip()
    if value:
        return value
    try:
        from defend_control.secrets import DpapiSecretStore

        registry = SecretRegistry(DpapiSecretStore(default_secret_path()))
        return registry.get("ODDS_API_IO_API_KEY") or ""
    except Exception:
        return ""


def _parse_date(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def _print_report(report: object) -> None:
    print(f"provider={report.provider} status={report.status} dry_run={report.dry_run}")
    print(f"window={report.window_from:%Y-%m-%dT%H:%M:%SZ}..{report.window_to:%Y-%m-%dT%H:%M:%SZ} resumed={report.resumed}")
    print(
        f"requests_used={report.requests_used} events_seen={report.events_seen} "
        f"events_persisted={report.events_persisted} odds_persisted={report.odds_persisted}"
    )
    print(
        f"results_persisted={report.results_persisted} "
        f"results_ambiguous={report.results_ambiguous}"
    )
    if report.error_detail:
        print(f"error={report.error_detail}")
    if report.status == "RUNNING":
        print("budget exhausted; re-run with the same window to resume (idempotent)")


def main() -> None:
    parser = argparse.ArgumentParser(description="DEFEND TT historical backfill (Odds-API.io)")
    parser.add_argument("--from", dest="from_dt", required=False, help="window start (RFC3339 or YYYY-MM-DD)")
    parser.add_argument("--to", dest="to_dt", required=False, help="window end (RFC3339 or YYYY-MM-DD)")
    parser.add_argument("--league", default="", help="league slug to narrow historical events (auto-discovered when empty)")
    parser.add_argument("--max-requests", type=int, default=200, help="provider request budget per run")
    parser.add_argument("--page-size", type=int, default=1000, help="historical events page size (API caps pages at 1000 and ignores the value)")
    parser.add_argument("--window-days", type=int, default=7, help="max days per historical window (shorter windows avoid the 1000-row cap)")
    parser.add_argument("--odds-per-window", type=int, default=0, help="max /historical/odds fetches per window (0 disables odds fetching)")
    parser.add_argument("--bookmakers", default="", help="comma-separated bookmaker names for historical odds (max 2 on the free plan)")
    parser.add_argument("--dry-run", action="store_true", help="fetch and report without writing to any database")
    parser.add_argument("--no-resume", action="store_true", help="ignore existing checkpoints")
    parser.add_argument("--rebuild-ratings", action="store_true", help="rebuild tt_rating_history from tt_match_results after a COMPLETED run")
    parser.add_argument("--status", action="store_true", help="report credential state only")
    args = parser.parse_args()

    if args.status:
        key_configured = bool(odds_api_io_key())
        print(f"ODDS_API_IO_API_KEY configured={key_configured}")
        if not key_configured:
            print("enter it in Setup & Integrations -> Odds-API.io -> ODDS_API_IO_API_KEY")
            print("(or set the ODDS_API_IO_API_KEY environment variable)")
        sys.exit(0 if key_configured else 2)

    if not args.from_dt or not args.to_dt:
        parser.error("--from and --to are required (or use --status)")

    key = odds_api_io_key()
    if not key:
        print("ODDS_API_IO_API_KEY is not configured; refusing to run", file=sys.stderr)
        sys.exit(2)

    from_dt = _parse_date(args.from_dt)
    to_dt = _parse_date(args.to_dt)

    markets_url = os.environ.get("MARKETS_DATABASE_URL", "").strip()
    sports_url = os.environ.get("SPORTS_DATABASE_URL", "").strip()
    if not markets_url or not sports_url:
        print(
            "[tt-backfill] MARKETS_DATABASE_URL and SPORTS_DATABASE_URL must be set",
            file=sys.stderr,
        )
        sys.exit(2)

    markets_database = MarketsDatabase(markets_url)
    markets_database.migrate()
    sports_database = SportsDatabase(sports_url)
    sports_database.migrate()

    provider = OddsApiIoSportsProvider(
        api_key=key,
        bookmakers=tuple(
            name.strip() for name in args.bookmakers.split(",") if name.strip()
        ),
    )
    ingestion = None
    results_sink = None
    if not args.dry_run:
        ingestion = IngestionService(sports_database)
        markets_store = PostgresMarketsStore(
            markets_database, MarketsRepository()
        )
        results_sink = markets_store.record_tt_results

    job = BackfillJob(
        sports_database,
        provider,
        sport="table_tennis",
        league=args.league,
        from_dt=from_dt,
        to_dt=to_dt,
        max_requests=args.max_requests,
        page_size=args.page_size,
        window_days_max=args.window_days,
        odds_fetch_cap=args.odds_per_window,
        dry_run=args.dry_run,
        resume=not args.no_resume,
        ingestion=ingestion,
        results_sink=results_sink,
    )
    report = job.run()
    _print_report(report)
    if args.rebuild_ratings and not args.dry_run and report.status == "COMPLETED":
        written = _rebuild_ratings(markets_database)
        print(f"rating_history_written={written}")
    sys.exit(0 if report.status == "COMPLETED" else 1)


def _rebuild_ratings(markets_database: MarketsDatabase) -> int:
    """Rebuild tt_rating_history chronologically from tt_match_results."""
    from defend_markets.domain import TTMatchResult
    from defend_markets.store import PostgresMarketsStore
    from defend_markets.forecast_store import PostgresForecastStore
    from defend_markets.tt_rating import rebuild_rating_history

    store = PostgresMarketsStore(markets_database, MarketsRepository())
    results: list[TTMatchResult] = []
    offset = 0
    while True:
        page = store.catalog_tt_results(limit=50000, offset=offset)
        if not page:
            break
        results.extend(
            TTMatchResult(
                event_key=str(row["event_key"]),
                league_key=str(row["league_key"]),
                home_participant_key=str(row["home_participant_key"]),
                away_participant_key=str(row["away_participant_key"]),
                home_score=int(row["home_score"]),
                away_score=int(row["away_score"]),
                completed_at=row.get("completed_at"),
                source_provider=str(row.get("source_provider") or "unknown"),
                raw_ref=row.get("raw_ref"),
            )
            for row in page
        )
        offset += len(page)
    history = rebuild_rating_history(results)
    return PostgresForecastStore(markets_database).insert_rating_history(history)


if __name__ == "__main__":
    main()