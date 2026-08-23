"""Freeze the M5 weight vector for Phase D live inference (P3).

M5 stays FROZEN: this tool fits the L2-regularized logistic exactly once on
all canonical TT matches strictly before the freeze cutoff and pins the weight
vector in docs/operations/TT_M5_LIVE_WEIGHTS_V1.json. It never refits, never
touches TT_M5_BASELINE_V1.json, and writes nothing else. Rerunning with the
same cutoff is byte-identical.

Usage:
    python tools/defend_tt_m5_freeze.py [--cutoff YYYY-MM-DD] [--output PATH]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from defend_markets.m5_live import FrozenM5, M5Match  # noqa: E402

DEFAULT_OUTPUT = REPO / "docs" / "operations" / "TT_M5_LIVE_WEIGHTS_V1.json"


def load_matches(db_url: str, max_matches: int = 0) -> list[M5Match]:
    conn = psycopg.connect(db_url, connect_timeout=5)
    try:
        rows = conn.execute(
            "select event_key, home_participant_key, away_participant_key, "
            "home_score, away_score, completed_at "
            "from tt_match_results where source_provider='odds_api_io' "
            "order by completed_at asc, event_key asc"
        ).fetchall()
    finally:
        conn.close()
    matches: list[M5Match] = []
    n_draws = 0
    for event_key, hk, ak, hs, aws, ts in rows:
        if not ts or hk is None or ak is None:
            continue
        if hs is not None and aws is not None and hs == aws:
            n_draws += 1
            continue
        actual = 1.0 if (hs or 0) > (aws or 0) else 0.0
        matches.append(
            M5Match(
                event_key=event_key,
                home_key=hk,
                away_key=ak,
                ts=ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts,
                actual=actual,
            )
        )
        if max_matches and len(matches) >= max_matches:
            break
    print(f"matches loaded: {len(matches)} (draws excluded: {n_draws})")
    return matches


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cutoff", default=None, help="YYYY-MM-DD freeze cutoff")
    parser.add_argument("--output", default=None)
    parser.add_argument("--max-matches", type=int, default=0)
    parser.add_argument("--min-train", type=int, default=200)
    args = parser.parse_args()

    db_url = os.environ.get("MARKETS_DATABASE_URL") or os.environ.get("SPORTS_DATABASE_URL")
    if not db_url:
        print("MARKETS_DATABASE_URL is required")
        return 2

    matches = load_matches(db_url, max_matches=args.max_matches)
    if not matches:
        print("no matches loaded")
        return 2
    if args.cutoff:
        cutoff = datetime.fromisoformat(args.cutoff).replace(tzinfo=timezone.utc)
    else:
        cutoff = matches[-1].ts
    doc = FrozenM5.freeze(matches, cutoff=cutoff, min_train=args.min_train)
    out = Path(args.output) if args.output else DEFAULT_OUTPUT
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    print(f"model_version={doc['model_id']}:{doc['sha256'][:12]} fit_n={doc['fit_n']} "
          f"cutoff={doc['cutoff']} fit_brier={doc['fit_brier']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())