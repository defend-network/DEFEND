"""DEFEND table-tennis replay tool (Phase 16).

Replays the prediction -> settlement pipeline from persisted data only:
odds snapshots in the Sports database and results in tt_match_results.
No network calls, no fabricated data. The same services used by the live
path run against point-in-time reads, so replay exercises exactly the
production logic (identity resolution, feature firewall, market state,
decision journal, idempotent settlement).

Usage:
    python tools/defend_tt_replay.py --all
    python tools/defend_tt_replay.py --event tt-live-001
    python tools/defend_tt_replay.py --event tt-live-001 --cutoff 2026-08-15T12:00:00Z
    python tools/defend_tt_replay.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from defend_markets.db import MarketsDatabase
from defend_markets.forecast_store import PostgresForecastStore
from defend_markets.identity import IdentityService
from defend_markets.pipeline import DecisionPipeline
from defend_markets.predict_service import TtPredictionService
from defend_markets.repositories import MarketsRepository
from defend_markets.settle_service import TtSettlementService
from defend_markets.sports_adapter import PostgresSportsDataReader
from defend_markets.store import PostgresMarketsStore
from defend_markets.strategies import build_default_registry
from defend_sports.db import SportsDatabase


def _parse_cutoff(raw: str | None) -> datetime:
    if not raw:
        return datetime.now(timezone.utc)
    value = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        print(f"[replay] invalid --cutoff {raw!r}; use ISO-8601 e.g. 2026-08-15T12:00:00Z")
        sys.exit(2)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description="DEFEND table-tennis replay")
    parser.add_argument("--all", action="store_true", help="replay every known TT event")
    parser.add_argument("--event", action="append", help="replay a specific event (repeatable)")
    parser.add_argument("--cutoff", help="point-in-time cutoff (ISO-8601); default: now")
    parser.add_argument("--dry-run", action="store_true", help="predict/settle nothing; report what would happen")
    args = parser.parse_args()

    markets_url = os.environ.get("MARKETS_DATABASE_URL", "").strip()
    sports_url = os.environ.get("SPORTS_DATABASE_URL", "").strip()
    if not markets_url or not sports_url:
        print("[replay] MARKETS_DATABASE_URL and SPORTS_DATABASE_URL must be set", file=sys.stderr)
        sys.exit(2)

    markets_database = MarketsDatabase(markets_url)
    markets_database.migrate()
    sports_database = SportsDatabase(sports_url)
    sports_database.migrate()

    cutoff = _parse_cutoff(args.cutoff)
    reader = PostgresSportsDataReader(sports_database)
    repository = MarketsRepository()
    store = PostgresMarketsStore(markets_database, repository)
    forecast = PostgresForecastStore(markets_database)
    pipeline = DecisionPipeline(
        reader=reader,
        registry=build_default_registry(),
        store=store,
        journal=forecast,
    )

    events = reader.tt_events()
    keys = set(args.event or [])
    if keys:
        known = {event["event_key"] for event in events}
        missing = keys - known
        if missing:
            print(f"[replay] unknown event keys: {sorted(missing)}")
            sys.exit(2)
        events = [event for event in events if event["event_key"] in keys]
    if not args.all and not keys:
        print("[replay] no events selected; use --all or --event KEY")
        sys.exit(2)

    predictor = TtPredictionService(
        reader=reader,
        store=store,
        forecast=forecast,
        pipeline=pipeline,
        identity=IdentityService(forecast),
    )
    settler = TtSettlementService(
        reader=reader,
        store=store,
        forecast=forecast,
        clock=lambda: cutoff,
    )

    print(f"[replay] cutoff={cutoff.isoformat()} events={len(events)} dry_run={args.dry_run}")
    totals = {"predictions": 0, "no_action": 0, "settled": 0, "unmapped": 0}
    for event in events:
        event_key = str(event["event_key"])
        print(f"[replay] {event_key}")
        if not args.dry_run:
            outcome = predictor.predict(event_key, cutoff=cutoff)
            totals["predictions" if outcome.decision == "OPPORTUNITY" else "no_action"] += 1
            print(
                f"  predict: decision={outcome.decision} "
                f"reason_codes={list(outcome.reason_codes)}"
            )
            for settled in settler.settle(event_key):
                totals["settled" if settled.settled else "unmapped"] += 1
                print(
                    f"  settle: {settled.reason} correct={settled.correct} "
                    f"raw_ref={settled.raw_ref or '-'}"
                )
        else:
            print("  (dry-run: no writes performed)")

    print(
        f"[replay] done: predictions={totals['predictions']} "
        f"no_action={totals['no_action']} settled={totals['settled']} "
        f"unmapped={totals['unmapped']}"
    )
    if args.dry_run:
        print("[replay] dry-run complete; re-run without --dry-run to write")


if __name__ == "__main__":
    main()