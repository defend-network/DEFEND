"""DEFEND Sports live feed collector.

Polls the real The Odds API provider for table-tennis events and persists
the canonical batch into the sports database (provider_health / sport_events
/ odds_snapshots / live_observations). Never fabricates data: missing
credentials are reported as UNCONFIGURED, transport failures as UNAVAILABLE
with the actual error, an empty but successful poll as HEALTHY with no events.

Usage:
    python tools/defend_sports_ingest.py --once
    python tools/defend_sports_ingest.py --loop --interval 300
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from defend_sports.config import SportsSettings
from defend_sports.db import SportsDatabase
from defend_sports.ingestion import IngestionService
from defend_sports.providers.the_odds_api import (
    OddsApiProviderError,
    TheOddsApiSportsProvider,
)


def _summarize(result: object) -> str:
    return (
        f"{result.provider:24s} {result.health:12s} "
        f"events={result.events:3d} odds={result.odds_snapshots:5d} "
        f"live={result.live_observations:3d} raw={result.raw_events_created:4d} "
        f"markets={result.markets:3d} selections={result.selections:4d}"
    )


def _collect_once(provider: TheOddsApiSportsProvider, service: IngestionService) -> int:
    batch = provider.poll()
    if not batch.raw_events:
        print("the_odds_api HEALTHY no live table-tennis events right now")
        return 0
    result = service.ingest(batch)
    print(_summarize(result))
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="DEFEND Sports live feed collector")
    parser.add_argument("--once", action="store_true", help="poll once and exit")
    parser.add_argument("--loop", action="store_true", help="poll forever")
    parser.add_argument("--interval", type=int, default=300, help="loop interval seconds")
    args = parser.parse_args()

    settings = SportsSettings.from_env()
    database = SportsDatabase(settings.database_url)
    database.migrate()
    service = IngestionService(database)

    api_key = os.environ.get("THE_ODDS_API_KEY", "").strip()
    if not api_key:
        print("the_odds_api UNCONFIGURED missing THE_ODDS_API_KEY")
        sys.exit(2)

    provider = TheOddsApiSportsProvider(api_key=api_key)

    if args.loop:
        while True:
            try:
                _collect_once(provider, service)
            except OddsApiProviderError as error:
                print(f"the_odds_api UNAVAILABLE {error.detail}")
            print(f"[ingest] sleeping {args.interval}s (Ctrl+C to stop)")
            time.sleep(args.interval)
            print(f"[ingest] wake at {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
        return

    try:
        _collect_once(provider, service)
    except OddsApiProviderError as error:
        print(f"the_odds_api UNAVAILABLE {error.detail}")
        sys.exit(2)


if __name__ == "__main__":
    main()