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
    python tools/defend_markets_ingest.py --test the_odds_api_tt
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
from defend_markets.feeds import FeedError, FeedService, build_default_feed_providers, odds_api_key, probe_odds_api_quota
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


def _test_odds_api() -> int:
    """Credential + quota check for the_odds_api_tt without polling feeds."""
    api_key = odds_api_key()
    if not api_key:
        print("the_odds_api_tt UNCONFIGURED missing THE_ODDS_API_KEY")
        print("enter it in Setup & Integrations -> The Odds API -> THE_ODDS_API_KEY")
        print("(or set the THE_ODDS_API_KEY environment variable)")
        return 2
    try:
        probe = probe_odds_api_quota(api_key)
    except FeedError as error:
        print(f"the_odds_api_tt UNAVAILABLE {error.detail}")
        return 2
    print(f"the_odds_api_tt HEALTHY sports={probe['sport_count']}")
    print(f"  tt_sport_keys={probe['tt_sport_keys']}")
    print(
        "  quota: "
        f"remaining={probe['requests_remaining'] or '-'} "
        f"used={probe['requests_used'] or '-'} "
        f"last_call_cost={probe['requests_last'] or '-'} credits"
    )
    print("  (free tier: 500 credits/month; h2h x 1 region = 1 credit per odds call)")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="DEFENDmarkets live feed collector")
    parser.add_argument("--once", action="store_true", help="poll every provider once and exit")
    parser.add_argument("--provider", help="poll a single provider")
    parser.add_argument("--test", help="validate credentials for a provider without polling feeds")
    parser.add_argument("--loop", action="store_true", help="poll forever")
    parser.add_argument("--interval", type=int, default=300, help="loop interval seconds")
    args = parser.parse_args()

    if args.test:
        if args.test == "the_odds_api_tt":
            sys.exit(_test_odds_api())
        print(f"[ingest] no --test probe implemented for provider {args.test!r}")
        sys.exit(2)

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