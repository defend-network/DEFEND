"""Freeze the recent-form20 shadow challenger weights for live forward use.

Fits the M5 feature set plus recent_form20_winrate_diff on the full pre-cutoff
canonical corpus exactly once, then pins the vector as a challenger artifact.
Never touches the M5 champion.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from defend_markets.m5_live import FEATURE_NAMES  # noqa: E402
from defend_markets.quant.research.features import rows_to_feature_matrix  # noqa: E402
from defend_markets.quant.research.models import fit_ridge_logistic  # noqa: E402

CUTOFF = datetime(2026, 8, 16, 0, 0, tzinfo=timezone.utc)
FEATURE_SET = list(FEATURE_NAMES) + ["recent_form20_winrate_diff"]


def main() -> int:
    db_url = os.environ.get("MARKETS_DATABASE_URL")
    if not db_url:
        print("MARKETS_DATABASE_URL is required", file=sys.stderr)
        return 2
    conn = psycopg.connect(db_url, connect_timeout=5)
    rows_raw = conn.execute(
        "select event_key, home_participant_key, away_participant_key, home_score, away_score, completed_at "
        "from tt_match_results where source_provider='odds_api_io' "
        "order by completed_at asc, event_key asc"
    ).fetchall()
    conn.close()
    rows = []
    for event_key, hk, ak, hs, aws, ts in rows_raw:
        if not ts or hk is None or ak is None:
            continue
        ts_dt = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        if ts_dt >= CUTOFF:
            continue
        if hs is not None and aws is not None and hs == aws:
            continue
        rows.append(
            {
                "event_key": event_key,
                "home_key": hk,
                "away_key": ak,
                "ts": ts_dt.isoformat(),
                "actual": 1.0 if (hs or 0) > (aws or 0) else 0.0,
            }
        )
    matrix, targets = rows_to_feature_matrix(rows, feature_ids=FEATURE_SET)
    import numpy as np

    x = np.asarray(matrix, dtype=float)
    y = np.asarray(targets, dtype=float)
    weights = fit_ridge_logistic(x, y)
    w_map = {
        name: round(float(value), 10)
        for name, value in zip(["intercept"] + FEATURE_SET, weights)
    }
    sha = hashlib.sha256(json.dumps(w_map, sort_keys=True).encode("utf-8")).hexdigest()
    doc = {
        "schema": "TT_SHADOW_RECENT_FORM20",
        "model_id": "challenger-recent-form20",
        "feature_names": FEATURE_SET,
        "intercept": w_map["intercept"],
        "weights": {name: w_map[name] for name in FEATURE_SET},
        "fit_n": len(rows),
        "cutoff": "2026-08-16T00:00:00Z",
        "sha256": sha,
    }
    out = REPO / "docs" / "operations" / "TT_SHADOW_RECENT_FORM20_V1.json"
    out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out} fit_n={len(rows)} sha256={sha[:12]}")
    print(f"form20_coefficient={w_map['recent_form20_winrate_diff']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
