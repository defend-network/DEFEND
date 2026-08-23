"""Phase D P8: 12-hour shadow soak harness (no bets).

Runs the forward collector in SHADOW MODE for a bounded duration, persists a
soak run record, and verifies restart idempotency: rerunning with the same
inputs produces no duplicated rows (unique natural keys).

Usage:
    python tools/defend_tt_live_soak.py --minutes 5 --cycle-interval 45
    python tools/defend_tt_live_soak.py --verify-idempotent
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from defend_markets.shadow import evaluation_report  # noqa: E402
from defend_markets.shadow_store import PostgresShadowStore  # noqa: E402
from defend_markets.db import MarketsDatabase  # noqa: E402
from tools.defend_tt_forward_collector import (  # noqa: E402
    build_engine,
    canonical_events_map,
)

DEFAULT_OUTPUT = REPO / "docs" / "operations" / "TT_LIVE_SOAK_V1.json"


def _snapshot_counts(store: PostgresShadowStore) -> dict[str, int]:
    counts = {
        "observations": len(store.list_observations("")),
        "forward_events": len(store.list_forward_events()),
        "evaluation_rows": len(store.evaluation_rows()),
    }
    observations = 0
    for event in store.list_forward_events():
        observations += len(store.list_observations_for_event_id(int(event["forward_event_id"])))
    counts["observations"] = observations
    return counts


def _stale_quotes(store: PostgresShadowStore) -> int:
    stale = 0
    for event in store.list_forward_events():
        canonical = event.get("canonical_event_id")
        if not canonical:
            continue
        rows = store.list_observations(canonical)
        by_key: dict[tuple[str, str], list[dict]] = {}
        for obs in rows:
            by_key.setdefault((obs["bookmaker"], obs["side"]), []).append(obs)
        for key, series in by_key.items():
            series.sort(key=lambda o: o["observed_at"])
            for prev, cur in zip(series, series[1:]):
                if float(prev["price"]) == float(cur["price"]):
                    stale += 1
    return stale


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minutes", type=float, default=0.0)
    parser.add_argument("--cycles", type=int, default=3)
    parser.add_argument("--cycle-interval", type=float, default=45.0)
    parser.add_argument("--verify-idempotent", action="store_true")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    db_url = os.environ["MARKETS_DATABASE_URL"]
    store = PostgresShadowStore(MarketsDatabase(db_url))
    if args.verify_idempotent:
        engine = build_engine()
        canonical = canonical_events_map(db_url)
        before = _snapshot_counts(store)
        engine.run_cycle(canonical_events=canonical)
        after = _snapshot_counts(store)
        stable = {k: v for k, v in before.items() if after[k] == v}
        changed = {k: v for k, v in after.items() if before[k] != v}
        print(json.dumps({"before": before, "after": after, "stable": stable,
                          "changed": changed}, indent=2))
        print("RESTART_IDEMPOTENT=YES" if not changed else "RESTART_IDEMPOTENT=NO")
        return 0

    engine = build_engine()
    canonical = canonical_events_map(db_url)
    started_at = datetime.now(timezone.utc)
    run_id = store.start_soak(started_at)
    print(f"soak run_id={run_id} started={started_at.isoformat()}")

    cycle_count = 0
    api_requests = 0
    api_errors = 0
    rate_limit_events = 0
    truncated_responses = 0
    deadline = None
    if args.minutes > 0:
        deadline = started_at.timestamp() + args.minutes * 60.0
    while True:
        if deadline is not None and time.time() >= deadline:
            break
        if cycle_count >= args.cycles and deadline is None:
            break
        cycle_count += 1
        metrics = engine.run_cycle(canonical_events=canonical)
        api_requests += metrics["odds"]["api_requests"] + metrics["discovery"]["api_requests"]
        api_errors += metrics["odds"]["api_errors"] + metrics["discovery"]["api_errors"]
        rate_limit_events += (
            metrics["odds"]["rate_limit_events"] + metrics["discovery"]["rate_limit_events"]
        )
        truncated_responses += (
            metrics["odds"]["truncated_responses"] + metrics["discovery"]["truncated_responses"]
        )
        print(f"cycle {cycle_count}: {json.dumps(metrics)}")
        store.update_soak(
            run_id,
            cycle_count=cycle_count,
            api_requests=api_requests,
            api_errors=api_errors,
            rate_limit_events=rate_limit_events,
            cost_usd=0.0,
            metrics={
                "last_cycle": metrics,
                "stale_quotes": _stale_quotes(store),
                "eval": evaluation_report(store.evaluation_rows()),
            },
        )
        if deadline is None or time.time() + args.cycle_interval < deadline:
            time.sleep(args.cycle_interval)
    finished_at = datetime.now(timezone.utc)
    store.finish_soak(run_id, finished_at)

    evaluation_rows = store.evaluation_rows()
    events = store.list_forward_events()
    events_matched = sum(1 for e in events if e.get("canonical_event_id"))
    events_ambiguous = sum(1 for e in events if e["match_level"] == "AMBIGUOUS")
    events_with_odds = 0
    prematch_obs = 0
    postcommence_obs = 0
    bookmakers: set[str] = set()
    events_with_m5 = sum(
        1 for e in events
        if e.get("canonical_event_id")
        and store.m5_prediction(e["canonical_event_id"]) is not None
    )
    for event in events:
        canonical = event.get("canonical_event_id")
        if not canonical:
            continue
        obs = store.list_observations(canonical)
        if obs:
            events_with_odds += 1
            bookmakers.update(o["bookmaker"] for o in obs)
            prematch_obs += sum(1 for o in obs if o["observation_class"] != "POST_COMMENCE")
            postcommence_obs += sum(1 for o in obs if o["observation_class"] == "POST_COMMENCE")
    settled = sum(1 for e in events if e["state"] == "SETTLED")
    report = {
        "schema": "TT_LIVE_SOAK",
        "run_id": run_id,
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "finished_at": finished_at.isoformat().replace("+00:00", "Z"),
        "status": "COMPLETED",
        "duration_seconds": round((finished_at - started_at).total_seconds(), 1),
        "EVENTS_DISCOVERED": len(events),
        "EVENTS_MATCHED": events_matched,
        "CANONICAL_MATCH_RATE": round(events_matched / len(events), 4) if events else None,
        "AMBIGUOUS_MATCH_RATE": round(events_ambiguous / len(events), 4) if events else None,
        "EVENTS_WITH_M5": events_with_m5,
        "EVENTS_WITH_ODDS": events_with_odds,
        "PREMATCH_OBSERVATIONS": prematch_obs,
        "POSTCOMMENCE_REJECTED": postcommence_obs,
        "BOOKMAKERS": sorted(bookmakers),
        "API_REQUESTS": api_requests,
        "API_ERRORS": api_errors,
        "RATE_LIMIT_EVENTS": rate_limit_events,
        "TRUNCATED_RESPONSES": truncated_responses,
        "STALE_QUOTES": _stale_quotes(store),
        "SETTLED_EVENTS": settled,
        "MARKET_SAMPLE_N": len(evaluation_rows),
        "COST_USD": 0.0,
        "evaluation_report": evaluation_report(evaluation_rows),
    }
    out = Path(args.output) if args.output else DEFAULT_OUTPUT
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())