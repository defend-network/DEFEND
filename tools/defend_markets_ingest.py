"""DEFENDmarkets live feed collector.

Polls the real configured providers and persists honest status + records
into the markets database (provider_feeds / market_feed_records /
tt_match_results). Never fabricates data: missing credentials are
recorded as UNCONFIGURED, transport failures as UNAVAILABLE with the
actual error, partial success as DEGRADED.

Usage:
    python tools/defend_markets_ingest.py --once
    python tools/defend_markets_ingest.py --provider world_bank
    python tools/defend_markets_ingest.py --loop --interval 300
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from defend_markets.config import MarketsSettings
from defend_markets.db import MarketsDatabase
from defend_markets.feeds import FeedService, build_default_feed_providers
from defend_markets.repositories import MarketsRepository
from defend_markets.store import PostgresMarketsStore


def _build_service() -> tuple[FeedService, PostgresMarketsStore]:
    settings = MarketsSettings.from_env()
    database = MarketsDatabase(settings.database_url)
    database.migrate()
    with database.connect() as connection:
        with connection.transaction():
            MarketsRepository().seed_defaults(connection)
    store = PostgresMarketsStore(database, MarketsRepository())
    service = FeedService(store, build_default_feed_providers())
    return service, store


def _summarize(result: object) -> str:
    return (
        f"{result.provider_id:24s} {result.status:12s} "
        f"records={result.record_count:5d} tt={len(result.tt_results):3d} "
        f"latency={result.latency_ms if result.latency_ms is not None else '-':>6}ms "
        f"error={result.error or '-'}"
    )


def run_once(service: FeedService) -> dict[str, object]:
    results = service.poll_all()
    for result in results.values():
        print(_summarize(result))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="DEFENDmarkets live feed collector")
    parser.add_argument("--once", action="store_true", help="poll every provider once and exit")
    parser.add_argument("--provider", help="poll a single provider")
    parser.add_argument("--loop", action="store_true", help="poll forever")
    parser.add_argument("--interval", type=int, default=300, help="loop interval seconds")
    args = parser.parse_args()

    service, store = _build_service()
    if args.provider:
        service.get(args.provider)  # raises on unknown provider
        print(_summarize(service.poll(args.provider)))
        return
    if args.loop:
        while True:
            run_once(service)
            print(f"[ingest] sleeping {args.interval}s (Ctrl+C to stop)")
            time.sleep(args.interval)
            print(f"[ingest] wake at {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
        return
    results = run_once(service)
    unavailable = [p for p, r in results.items() if r.status in ("UNAVAILABLE", "UNCONFIGURED")]
    if unavailable:
        print(f"[ingest] {len(unavailable)} providers not delivering: {', '.join(unavailable)}")
        sys.exit(2)
    return


if __name__ == "__main__":
    main()