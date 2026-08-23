"""DEFEND table-tennis live collector (scores + h2h odds, quota governed).

Operational harness for the Phase 2 collector. Reuses the existing
the_odds_api_tt scores feed and the h2h odds provider, with:

* honest status: UNCONFIGURED when THE_ODDS_API_KEY is missing,
  QUOTA_PROTECTED when remaining credits fall below the floor,
  UNAVAILABLE on transport/provider errors, HEALTHY otherwise
* durable collector state in tt_collector_state
* 1 request/second pacing and bounded 429 backoff inside the provider

Usage:
    python tools/defend_tt_collector.py --once
    python tools/defend_tt_collector.py --loop
    python tools/defend_tt_collector.py --once --floor 50
    python tools/defend_tt_collector.py --status
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from defend_markets.collector import TtCollector, tt_collector_config_from_env
from defend_markets.db import MarketsDatabase
from defend_markets.feeds import FeedService, TheOddsApiTTResultsFeedProvider, odds_api_key
from defend_markets.forecast_store import PostgresForecastStore
from defend_markets.repositories import MarketsRepository
from defend_markets.store import PostgresMarketsStore
from defend_sports.db import SportsDatabase


def _build_collector(*, floor: int | None = None) -> TtCollector:
    markets_url = os.environ.get("MARKETS_DATABASE_URL", "").strip()
    sports_url = os.environ.get("SPORTS_DATABASE_URL", "").strip()
    if not markets_url or not sports_url:
        print(
            "[tt-collector] MARKETS_DATABASE_URL and SPORTS_DATABASE_URL must be set",
            file=sys.stderr,
        )
        sys.exit(2)
    markets_database = MarketsDatabase(markets_url)
    markets_database.migrate()
    sports_database = SportsDatabase(sports_url)
    sports_database.migrate()

    forecast = PostgresForecastStore(markets_database)
    markets_store = PostgresMarketsStore(markets_database, MarketsRepository())
    feed_service = FeedService(markets_store, (TheOddsApiTTResultsFeedProvider(),))

    config = tt_collector_config_from_env()
    if floor is not None:
        from dataclasses import replace

        config = replace(config, credit_floor=floor)
    return TtCollector(
        sports_database=sports_database,
        feed_service=feed_service,
        markets_forecast=forecast,
        config=config,
    )


def _print_run(run: object) -> None:
    print(f"provider={run.provider} configured={run.configured}")
    print(f"status={run.status} mode={run.mode} detail={run.detail or '-'}")
    print(
        f"scores_results={run.scores_results} tt_results={run.tt_results} "
        f"events={run.events} odds_snapshots={run.odds_snapshots} "
        f"live_observations={run.live_observations}"
    )
    quota = run.quota_protected or run.credits_remaining is not None
    if quota:
        print(
            f"quota: remaining={run.credits_remaining or '-'} "
            f"used={run.credits_used or '-'} protected={run.quota_protected}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="DEFEND table-tennis live collector")
    parser.add_argument("--once", action="store_true", help="run one cycle and exit")
    parser.add_argument("--loop", action="store_true", help="run adaptively until Ctrl+C")
    parser.add_argument("--floor", type=int, help="override TT_ODDS_CREDIT_FLOOR")
    parser.add_argument("--cycles", type=int, default=0, help="loop for N cycles then exit (0 = forever)")
    parser.add_argument("--status", action="store_true", help="report configured/credential state only")
    args = parser.parse_args()

    if args.status:
        key_configured = bool(odds_api_key())
        print(f"THE_ODDS_API_KEY configured={key_configured}")
        if not key_configured:
            print("enter it in Setup & Integrations -> The Odds API -> THE_ODDS_API_KEY")
            print("(or set the THE_ODDS_API_KEY environment variable)")
        config = tt_collector_config_from_env()
        print(
            f"credit_floor={config.credit_floor} "
            f"active_poll={config.active_poll_seconds}s idle_poll={config.idle_poll_seconds}s"
        )
        sys.exit(0 if key_configured else 2)

    collector = _build_collector(floor=args.floor)

    if args.loop or args.cycles:
        cycles = args.cycles or 0
        done = 0
        while cycles == 0 or done < cycles:
            run = collector.one_shot()
            _print_run(run)
            done += 1
            if run.mode == "active":
                print(f"[tt-collector] next cycle after active poll interval (Ctrl+C to stop)")
            else:
                print(f"[tt-collector] next cycle after idle poll interval (Ctrl+C to stop)")
        return

    run = collector.one_shot()
    _print_run(run)
    if not run.configured:
        print("[tt-collector] enter THE_ODDS_API_KEY in Setup & Integrations -> The Odds API")
        sys.exit(2)
    if run.status in ("UNAVAILABLE", "QUOTA_PROTECTED"):
        sys.exit(2)


if __name__ == "__main__":
    main()