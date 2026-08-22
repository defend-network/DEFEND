"""Run the first Quant Research Lab challenger experiment on real data.

Loads canonical TT results, builds an immutable dataset snapshot at the M5
cutoff, and runs a walk-forward comparison between an M5-equivalent baseline
and a challenger that adds the quadratic rating term (elo_diff_sq). M5 weights
are never touched.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from defend_markets.m5_live import M5Match  # noqa: E402
from defend_markets.quant.orchestrator import MarketsIntelligenceOrchestrator  # noqa: E402
from defend_markets.quant.research.experiment import build_spec  # noqa: E402
from defend_markets.quant.research.experiment import ExperimentRunner  # noqa: E402
from defend_markets.quant.research.features import (  # noqa: E402
    M5_FEATURE_NAMES,
)
from defend_markets.quant.research.snapshot import build_snapshot  # noqa: E402
from defend_markets.quant.store import InMemoryQuantStore  # noqa: E402
from defend_markets.quant.tools import InMemoryMarketTools  # noqa: E402

M5_FEATURE_IDS = list(M5_FEATURE_NAMES)
CUTOFF = "2026-08-16T00:00:00Z"
CHAMPION_VERSION = "M5_REGULARIZED_LOGISTIC:54affc960a34"


def load_result_rows(db_url: str) -> list[dict]:
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
    result_rows = []
    for event_key, hk, ak, hs, aws, ts in rows:
        if not ts or hk is None or ak is None:
            continue
        if hs is not None and aws is not None and hs == aws:
            continue
        actual = 1.0 if (hs or 0) > (aws or 0) else 0.0
        result_rows.append(
            {
                "event_key": event_key,
                "home_key": hk,
                "away_key": ak,
                "ts": ts.isoformat(),
                "actual": actual,
            }
        )
    return result_rows


def main() -> int:
    db_url = os.environ.get("MARKETS_DATABASE_URL")
    if not db_url:
        print("MARKETS_DATABASE_URL is required", file=sys.stderr)
        return 2
    rows = load_result_rows(db_url)
    snapshot = build_snapshot(
        rows,
        cutoff=CUTOFF,
        target_definition="tt_match_results source_provider=odds_api_io, home win probability",
        feature_schema_version=1,
        provenance={"source": "tt_match_results", "provider": "odds_api_io"},
    )
    store = InMemoryQuantStore()
    tools = InMemoryMarketTools(store)
    orchestrator = MarketsIntelligenceOrchestrator(store=store, tools=tools)
    store.create_snapshot(snapshot)

    spec = build_spec(
        experiment_id="exp-m2-challenger-elo-diff-sq",
        hypothesis_id="hyp-m2-001",
        snapshot=snapshot,
        champion_version=CHAMPION_VERSION,
        challenger_name="elo-diff-sq",
        feature_set=M5_FEATURE_IDS + ["elo_diff_sq"],
    )
    runner = ExperimentRunner(snapshot=snapshot, n_windows=4)
    result = runner.run(
        spec,
        champion_brier=0.242291,
        champion_log_loss=0.677174,
        market_metrics_available=False,
    )
    store.save_experiment(spec=spec, result=result)

    print(json.dumps(result.to_dict(), indent=2, default=str))
    out = REPO / "docs" / "operations" / "TT_QUANT_EXPERIMENT_M2_CHALLENGER_V1.json"
    out.write_text(json.dumps(result.to_dict(), indent=2, default=str) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
