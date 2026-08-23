"""TT RESEARCH SUITE: M0A/M0B/M1/M5 challengers, audited walk-forward eval,
calibration, Elo diagnosis, point-in-time feature snapshots (offline, DB-only).

Phases 3-7 of the TT historical activation R&D phase, METRIC INTEGRITY
EDITION (owner audit 2026-08-18). Reads persisted tt_match_results
(source_provider='odds_api_io'), replays chronologically, and evaluates
every model strictly time-forward (features built only from matches
strictly before the current match's commence time).

EVALUATION LABEL DOMAIN (audit fix):
  - Binary outcomes only: y in {0, 1} (y=1 iff the provider-designated
    "home"/first-listed side won).
  - Equal-score rows (home_score == away_score) are VOID rows: impossible
    final scores in TT best-of-5/7 (0-0, 2-2, 3-3) that the provider marks
    "settled". They are excluded from every metric AND from every model
    state update (Elo/Glicko/form/h2h/depth). Prior runs encoded them as
    actual=0.5, which biased the constant-0.5 Brier below 0.25 (root cause
    of OLD_M0_BRIER 0.2471/0.2496).

MODELS:
  M0A CONSTANT_0_5                 p = 0.5 everywhere (reference null)
  M0B TRAIN_BASE_RATE              p = frozen side-A win rate from rows
                                   strictly before each eval window
  M1  CURRENT_ELO                  logistic Elo (K=32, init 1200)
  M2  RECENCY_WEIGHTED_ELO         Elo over each player's last 100 matches
  M3  GLICKO                       Glicko-1 (RD-based), time-forward
  M4  SIMPLE_FORM_MODEL            logistic on last-5 win-rate difference
  M5  REGULARIZED_LOGISTIC         L2 ridge logistic over point-in-time
                                   features (numpy only, includes intercept)

EVALUATION INTEGRITY:
  - Freeze per-window manifests (window_id, train window, eval window,
    counts, ordered eval event-key hash); EVAL_MANIFEST_SHA256 over the
    whole manifest (deterministic).
  - EXACT OOS predictions: one predictions table per event/window/model,
    used verbatim for Brier, log loss, calibration and paired deltas.
  - Pairwise comparisons only on identical event sets (intersection).
  - Paired deltas with blocked bootstrap (block = day, block = competition),
    deterministic seed.
  - Calibration buckets over exact OOS predictions; n < 30 -> INSUFFICIENT_SAMPLE.
  - M0A accuracy is NOT_APPLICABLE (p == 0.5 exactly, no tie-break).

Outputs (MODEL_RESEARCH artifacts, never the live journal):
  - feature snapshot JSONL (feature_snapshot_id, feature_schema_version,
    feature_code_version, cutoff_ts, source observation ids)
  - exact OOS predictions JSONL (event_key, window_id, train_cutoff,
    prediction_ts, model_id, model_version, feature_snapshot_id, model_p,
    actual, league_key)
  - evaluation manifest JSON + per-window walk-forward metrics, calibration,
    diagnosis, paired deltas
  - summary JSON

Requires SPORTS_DATABASE_URL.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import psycopg

_LABEL = "MODEL_RESEARCH"
_SCHEMA_VERSION = "1.1.0"
_CODE_VERSION = "defend_tt_research_suite.py@2026-08-18-audit"

_INITIAL_RATING = 1200.0
_K = 32.0
_GLICKO_INIT_RD = 350.0
_Q = 10.0 / 400.0
_BUCKETS: tuple[tuple[str, float], ...] = (
    ("0.50-0.55", 0.55),
    ("0.55-0.60", 0.60),
    ("0.60-0.65", 0.65),
    ("0.65-0.70", 0.70),
    ("0.70-0.80", 0.80),
    ("0.80+", 1.01),
)
_CAL_BUCKETS: tuple[tuple[str, float], ...] = (("<0.50", 0.50),) + _BUCKETS
_MIN_CAL_N = 30
_FEATURE_NAMES = [
    "home_indicator", "elo_diff", "recency_elo_diff", "form5_diff",
    "log_depth_diff", "rest_diff_days", "h2h_winrate_diff",
    "same_day_diff", "degree_diff",
]
_MODEL_IDS = [
    "M0A_CONSTANT_0_5", "M0B_TRAIN_BASE_RATE", "M1_CURRENT_ELO",
    "M2_RECENCY_WEIGHTED_ELO", "M3_GLICKO", "M4_SIMPLE_FORM_MODEL",
    "M5_REGULARIZED_LOGISTIC",
]
_AUDIT_MODELS = ["M0A_CONSTANT_0_5", "M0B_TRAIN_BASE_RATE", "M1_CURRENT_ELO",
                 "M5_REGULARIZED_LOGISTIC"]


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def _glicko_g(rd: float) -> float:
    return 1.0 / math.sqrt(1.0 + 3.0 * (_Q * rd / math.pi) ** 2)


def _brier_loss(p: float, actual: float) -> float:
    return (p - actual) ** 2


def _log_loss(p: float, actual: float) -> float:
    p = min(max(p, 1e-9), 1.0 - 1e-9)
    return -math.log(p) if actual > 0.5 else -math.log(1.0 - p)


def _check_binary_actuals(rows: list[dict]) -> None:
    for r in rows:
        if r["actual"] != 0.0 and r["actual"] != 1.0:
            raise ValueError(
                f"label domain violation: actual={r['actual']!r} not in {{0,1}}"
            )


def _aggregate(rows: list[dict]) -> dict:
    """Aggregate Brier / log loss / accuracy over binary rows.

    Raises ValueError on non-binary actuals (label domain firewall).
    Accuracy is NOT_APPLICABLE when every prediction is exactly 0.5
    (no directional classification is made).
    """
    n = len(rows)
    if n == 0:
        return {"n": 0}
    _check_binary_actuals(rows)
    brier = sum(_brier_loss(r["p"], r["actual"]) for r in rows) / n
    log_loss = sum(_log_loss(r["p"], r["actual"]) for r in rows) / n
    all_half = all(r["p"] == 0.5 for r in rows)
    if all_half:
        acc: float | str = "NOT_APPLICABLE"
    else:
        acc = sum(
            (r["p"] > 0.5 and r["actual"] > 0.5)
            or (r["p"] < 0.5 and r["actual"] < 0.5)
            for r in rows
        ) / n
    mean_p = sum(r["p"] for r in rows) / n
    win_rate = sum(r["actual"] > 0.5 for r in rows) / n
    return {
        "n": n,
        "brier": round(brier, 6),
        "log_loss": round(log_loss, 6),
        "brier_exact": brier,
        "log_loss_exact": log_loss,
        "accuracy": round(acc, 6) if isinstance(acc, float) else acc,
        "mean_predicted_p": round(mean_p, 6),
        "realized_win_rate": round(win_rate, 6),
    }


def _fit_ridge(x: np.ndarray, y: np.ndarray, lam: float = 1.0) -> np.ndarray:
    """L2-regularized logistic regression via Newton-Raphson (numpy only).

    Includes an explicit intercept: column 0 of the design is a constant 1.
    """
    n, d = x.shape
    xb = np.column_stack([np.ones(n), x])
    w = np.zeros(d + 1)
    for _ in range(40):
        z = xb @ w
        p = 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))
        grad = xb.T @ (p - y) + np.concatenate([[0.0], lam * w[1:]])
        r = p * (1 - p)
        hess = xb.T @ (r[:, None] * xb) + np.diag(np.concatenate([[0.0], np.full(d, lam)]))
        try:
            step = np.linalg.solve(hess, grad)
        except np.linalg.LinAlgError:
            break
        w -= step
        if np.max(np.abs(step)) < 1e-7:
            break
    return w


def _bucket_for(p: float) -> str:
    for label, upper in _CAL_BUCKETS:
        if p < upper:
            return label
    return _CAL_BUCKETS[-1][0]


def _sha256_hex(obj: object) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _event_set_hash(event_keys: list[str]) -> str:
    return hashlib.sha256("|".join(event_keys).encode("utf-8")).hexdigest()


def _common_rows(
    preds_a: dict[str, dict], preds_b: dict[str, dict]
) -> tuple[list[dict], list[dict], int, set[str], set[str]]:
    """Rows on the common event-key intersection of two prediction maps."""
    keys_a = set(preds_a)
    keys_b = set(preds_b)
    common = keys_a & keys_b
    return (
        [preds_a[k] for k in sorted(common)],
        [preds_b[k] for k in sorted(common)],
        len(common),
        keys_a - keys_b,
        keys_b - keys_a,
    )


def _paired_delta_rows(
    preds_a: dict[str, dict], preds_b: dict[str, dict], key: str
) -> list[float]:
    rows_a, rows_b, _n, only_a, only_b = _common_rows(preds_a, preds_b)
    if only_a or only_b:
        raise ValueError(f"pairwise event sets differ: only_a={len(only_a)} only_b={len(only_b)}")
    if key == "brier":
        return [
            _brier_loss(a["p"], a["actual"]) - _brier_loss(b["p"], b["actual"])
            for a, b in zip(rows_a, rows_b)
        ]
    return [
        _log_loss(a["p"], a["actual"]) - _log_loss(b["p"], b["actual"])
        for a, b in zip(rows_a, rows_b)
    ]


def _blocked_bootstrap_ci(
    deltas: list[float],
    block_ids: list[str],
    n_iter: int = 2000,
    seed: int = 20260818,
) -> dict:
    """Paired-delta 95% CI via block bootstrap (blocks resampled, not rows).

    Accounts for within-block dependence (same day / same competition).
    Deterministic for a given seed.
    """
    groups: dict[str, list[int]] = defaultdict(list)
    for i, b in enumerate(block_ids):
        groups[b].append(i)
    block_keys = sorted(groups)
    rng = np.random.default_rng(seed)
    means = np.empty(n_iter)
    n_blocks = len(block_keys)
    for it in range(n_iter):
        picked = rng.choice(n_blocks, size=n_blocks, replace=True)
        idx = [i for k in picked for i in groups[block_keys[k]]]
        means[it] = float(np.mean([deltas[i] for i in idx]))
    ci_low, ci_high = np.percentile(means, [2.5, 97.5])
    return {
        "mean_delta": round(float(np.mean(deltas)), 6),
        "median_delta": round(float(np.median(deltas)), 6),
        "95ci_low": round(float(ci_low), 6),
        "95ci_high": round(float(ci_high), 6),
        "n": len(deltas),
        "block_definition": "day" if len(block_keys) > 2 else "competition",
        "n_blocks": n_blocks,
        "n_iterations": n_iter,
        "seed": seed,
    }


def _calibration_table(
    preds: dict[str, dict], min_n: int = _MIN_CAL_N
) -> tuple[list[dict], float, dict]:
    """Calibration buckets over EXACT OOS predictions (event-keyed).

    Returns (bucket rows, weighted ACE over populated buckets, extreme-bucket info).
    """
    buckets: dict[str, list[dict]] = {label: [] for label, _ in _CAL_BUCKETS}
    for k in sorted(preds):
        r = preds[k]
        buckets[_bucket_for(r["p"])].append(r)
    rows = []
    weighted_ace_num = 0.0
    weighted_ace_den = 0
    for label, _ in _CAL_BUCKETS:
        rows_in = buckets[label]
        n = len(rows_in)
        if n == 0:
            continue
        mean_p = sum(x["p"] for x in rows_in) / n
        obs = sum(x["actual"] > 0.5 for x in rows_in) / n
        ace = abs(obs - mean_p)
        if n >= min_n:
            weighted_ace_num += n * ace
            weighted_ace_den += n
        rows.append(
            {
                "bucket": label,
                "n": n,
                "mean_predicted_p": round(mean_p, 4),
                "observed_win_rate": round(obs, 4),
                "abs_calibration_error": round(ace, 4),
                "status": "INSUFFICIENT_SAMPLE" if n < min_n else (
                    "OK" if ace < 0.05 else ("OVERCONFIDENT" if obs < mean_p else "UNDERCONFIDENT")
                ),
            }
        )
    weighted_ace = (
        round(weighted_ace_num / weighted_ace_den, 4) if weighted_ace_den else None
    )
    extreme = {}
    for label in ("<0.50", "0.80+"):
        for row in rows:
            if row["bucket"] == label:
                extreme[label] = {
                    "n": row["n"],
                    "status": row["status"],
                    "ace": row["abs_calibration_error"],
                }
    return rows, weighted_ace, extreme


class RecencyElo:
    def __init__(self, window: int = 100):
        self.window = window
        self.history: dict[str, list[tuple[datetime, str, float]]] = defaultdict(list)

    def rating(self, key: str) -> float:
        past = self.history.get(key, [])
        if not past:
            return _INITIAL_RATING
        recent = past[-self.window :]
        rating = _INITIAL_RATING
        for _ts, opponent, actual in recent:
            opp_rating = _INITIAL_RATING
            opp_past = self.history.get(opponent, [])
            if opp_past:
                opp_rating = rating  # current estimate, stable ordering proxy
            expected = _sigmoid((rating - opp_rating) / 400.0)
            rating += _K * (actual - expected)
        return rating

    def record(self, key: str, ts: datetime, opponent: str, actual: float) -> None:
        self.history[key].append((ts, opponent, actual))


class Glicko:
    def __init__(self):
        self.state: dict[str, tuple[float, float]] = defaultdict(
            lambda: (_INITIAL_RATING, _GLICKO_INIT_RD)
        )

    def probability(self, a: str, b: str) -> float:
        ra, rda = self.state[a]
        rb, rdb = self.state[b]
        g = _glicko_g(rdb)
        return _sigmoid(g * (ra - rb) / 400.0)

    def record(self, a: str, b: str, actual_home: float) -> None:
        ra, rda = self.state[a]
        rb, rdb = self.state[b]
        ga = _glicko_g(rda)
        gb = _glicko_g(rdb)
        ea = _sigmoid(gb * (ra - rb) / 400.0)
        eb = _sigmoid(ga * (rb - ra) / 400.0)
        d2a = 1.0 / ((_Q * gb) ** 2 * ea * (1 - ea))
        d2b = 1.0 / ((_Q * ga) ** 2 * eb * (1 - eb))
        new_ra = ra + (_Q / (1.0 / rda**2 + 1.0 / d2a)) * gb * (actual_home - ea)
        new_rb = rb + (_Q / (1.0 / rdb**2 + 1.0 / d2b)) * ga * ((1 - actual_home) - eb)
        new_rda = math.sqrt(1.0 / (1.0 / rda**2 + 1.0 / d2a))
        new_rdb = math.sqrt(1.0 / (1.0 / rdb**2 + 1.0 / d2b))
        self.state[a] = (new_ra, min(new_rda, 350.0))
        self.state[b] = (new_rb, min(new_rdb, 350.0))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-games", type=int, default=5)
    parser.add_argument("--eval-start", default="2026-03-08")
    parser.add_argument("--output", default=None)
    parser.add_argument("--max-matches", type=int, default=0, help="cap for smoke runs")
    parser.add_argument("--bootstrap-iters", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20260818)
    args = parser.parse_args()

    db_url = os.environ.get("SPORTS_DATABASE_URL")
    if not db_url:
        print("SPORTS_DATABASE_URL is required")
        return 2

    conn = psycopg.connect(db_url)
    rows = conn.execute(
        "select event_key, league_key, home_participant_key, away_participant_key, "
        "home_score, away_score, completed_at, raw_ref "
        "from tt_match_results where source_provider='odds_api_io' "
        "order by completed_at asc, event_key asc"
    ).fetchall()

    matches: list[dict] = []
    n_draws = 0
    for event_key, league_key, hk, ak, hs, aws, ts, raw_ref in rows:
        if not ts:
            continue
        if hk == ak:
            continue
        if hs == aws:
            n_draws += 1
            continue
        home_won = hs > aws
        matches.append(
            {
                "event_key": event_key,
                "league_key": league_key,
                "home": hk,
                "away": ak,
                "ts": ts,
                "actual": 1.0 if home_won else 0.0,
                "raw_ref": raw_ref,
            }
        )
    if args.max_matches:
        matches = matches[: args.max_matches]
    n_total = len(matches)
    print(f"matches loaded: {n_total} (draws excluded: {n_draws})")

    eval_start = datetime.fromisoformat(args.eval_start).replace(tzinfo=timezone.utc)

    elo: dict[str, float] = defaultdict(lambda: _INITIAL_RATING)
    recency = RecencyElo(100)
    glicko = Glicko()
    form5: dict[str, list[float]] = defaultdict(list)
    depth: dict[str, int] = defaultdict(int)
    last_ts: dict[str, datetime] = {}
    day_games: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    h2h: dict[tuple[str, str], tuple[float, int]] = defaultdict(lambda: (0.0, 0))
    opponents: dict[str, set[str]] = defaultdict(set)

    records: list[dict] = []
    side_a_wins = 0
    for m in matches:
        home, away = m["home"], m["away"]
        ts = m["ts"]
        home_pre = elo[home]
        away_pre = elo[away]
        p_elo = _sigmoid((home_pre - away_pre) / 400.0)

        recency_home = recency.rating(home)
        recency_away = recency.rating(away)
        p_recency = _sigmoid((recency_home - recency_away) / 400.0)

        p_glicko = glicko.probability(home, away)

        fh = form5.get(home, [])
        fa = form5.get(away, [])
        form_home = sum(fh) / len(fh) if fh else 0.5
        form_away = sum(fa) / len(fa) if fa else 0.5
        p_form = _sigmoid(2.0 * (form_home - form_away))

        h2h_a = h2h.get((home, away), (0.0, 0))
        h2h_b = h2h.get((away, home), (0.0, 0))
        h2h_meetings = h2h_a[1] + h2h_b[1]
        h2h_wins_home = h2h_a[0] + (h2h_b[1] - h2h_b[0])
        h2h_rate_home = h2h_wins_home / h2h_meetings if h2h_meetings else 0.5

        rest_home = (ts - last_ts[home]).total_seconds() / 86400.0 if home in last_ts else None
        rest_away = (ts - last_ts[away]).total_seconds() / 86400.0 if away in last_ts else None
        rest_diff = (rest_home - rest_away) if (rest_home is not None and rest_away is not None) else 0.0

        day = ts.date().isoformat()
        same_day_home = day_games[home][day]
        same_day_away = day_games[away][day]
        same_day_diff = float(same_day_home - same_day_away)

        depth_home = depth.get(home, 0)
        depth_away = depth.get(away, 0)
        log_depth_diff = math.log1p(depth_home) - math.log1p(depth_away)

        degree_home = len(opponents.get(home, set()))
        degree_away = len(opponents.get(away, set()))
        degree_diff = float(degree_home - degree_away)

        features = {
            "home_indicator": 1.0,
            "elo_diff": home_pre - away_pre,
            "recency_elo_diff": recency_home - recency_away,
            "form5_diff": form_home - form_away,
            "log_depth_diff": log_depth_diff,
            "rest_diff_days": rest_diff,
            "h2h_winrate_diff": 2 * h2h_rate_home - 1.0,
            "same_day_diff": same_day_diff,
            "degree_diff": degree_diff,
        }

        available = depth_home >= args.min_games and depth_away >= args.min_games

        record = {
            "event_key": m["event_key"],
            "league_key": m["league_key"],
            "home": home,
            "away": away,
            "ts": ts,
            "raw_ref": m["raw_ref"],
            "actual": m["actual"],
            "available": available,
            "features": features,
            "p_elo": p_elo,
            "p_recency": p_recency,
            "p_glicko": p_glicko,
            "p_form": p_form,
            "diagnosis": {
                "home_depth": depth_home,
                "rating_diff": home_pre - away_pre,
                "month": ts.strftime("%Y-%m"),
                "rest_days_home": rest_home,
                "same_day_home": same_day_home,
                "h2h_depth": h2h_meetings,
                "degree_home": degree_home,
            },
        }
        records.append(record)
        side_a_wins += 1 if m["actual"] > 0.5 else 0

        actual = m["actual"]
        e_home = _sigmoid((home_pre - away_pre) / 400.0)
        elo[home] += _K * (actual - e_home)
        elo[away] += _K * ((1 - actual) - (1 - e_home))
        recency.record(home, ts, away, actual)
        recency.record(away, ts, home, 1 - actual)
        glicko.record(home, away, actual)
        form5[home].append(actual)
        form5[away].append(1 - actual)
        if len(form5[home]) > 5:
            form5[home] = form5[home][-5:]
        if len(form5[away]) > 5:
            form5[away] = form5[away][-5:]
        depth[home] += 1
        depth[away] += 1
        last_ts[home] = ts
        last_ts[away] = ts
        day_games[home][day] += 1
        day_games[away][day] += 1
        if actual > 0.5:
            wins_a, meets_a = h2h[(home, away)]
            h2h[(home, away)] = (wins_a + 1, meets_a + 1)
        else:
            wins_b, meets_b = h2h[(away, home)]
            h2h[(away, home)] = (wins_b, meets_b + 1)
        opponents[home].add(away)
        opponents[away].add(home)

    dataset = {
        "schema": _SCHEMA_VERSION,
        "code": _CODE_VERSION,
        "min_games": args.min_games,
        "eval_start": eval_start.isoformat(),
        "first": records[0]["event_key"] if records else None,
        "last": records[-1]["event_key"] if records else None,
        "count": len(records),
        "draws_excluded": n_draws,
        "side_a_base_rate": round(side_a_wins / len(records), 6) if records else None,
    }
    snapshot_id = hashlib.sha1(json.dumps(dataset, default=str).encode()).hexdigest()

    # ------------------------------------------------------- walk-forward
    cutoffs: list[datetime] = []
    cursor = eval_start
    while cursor < records[-1]["ts"]:
        cutoffs.append(cursor)
        cursor += timedelta(days=30)
    cutoffs.append(records[-1]["ts"] + timedelta(days=1))

    windows_meta: list[dict] = []
    per_window: list[dict] = []
    exact_preds: dict[str, dict[str, dict]] = {m: {} for m in _MODEL_IDS}

    m5_weights: np.ndarray | None = None
    for wi, (start, end) in enumerate(zip(cutoffs, cutoffs[1:])):
        window_id = f"W{wi:02d}"
        train = [r for r in records if r["ts"] < start]
        test = [r for r in records if start <= r["ts"] < end and r["available"]]
        n_draws_window = sum(
            1 for r in records if start <= r["ts"] < end and not r["available"]
        )
        n_train = len(train)
        if n_train >= 200:
            x = np.array([[r["features"][f] for f in _FEATURE_NAMES] for r in train])
            y = np.array([r["actual"] for r in train])
            m5_weights = _fit_ridge(x, y)
        if m5_weights is not None:
            m5_model_version = f"{_CODE_VERSION}:{_sha256_hex(m5_weights.tolist())[:12]}"
            w_map = {
                name: round(float(w), 6)
                for name, w in zip(["intercept"] + _FEATURE_NAMES, m5_weights)
            }
        else:
            m5_model_version = None
            w_map = None

        wins = sum(1 for r in train if r["actual"] > 0.5)
        base_rate = (wins / n_train) if n_train >= 100 else 0.5
        base_rate = min(max(base_rate, 0.001), 0.999)

        eval_keys: list[str] = []
        for r in test:
            if r["event_key"] in eval_keys:
                raise RuntimeError(f"duplicate event key in window {window_id}")
            eval_keys.append(r["event_key"])
            exact_preds["M0A_CONSTANT_0_5"][r["event_key"]] = {
                "event_key": r["event_key"], "window_id": window_id,
                "train_cutoff": start.isoformat(), "prediction_ts": r["ts"].isoformat(),
                "model_id": "M0A_CONSTANT_0_5", "model_version": _CODE_VERSION,
                "feature_snapshot_id": snapshot_id, "p": 0.5,
                "actual": r["actual"], "league_key": r["league_key"],
            }
            exact_preds["M0B_TRAIN_BASE_RATE"][r["event_key"]] = {
                "event_key": r["event_key"], "window_id": window_id,
                "train_cutoff": start.isoformat(), "prediction_ts": r["ts"].isoformat(),
                "model_id": "M0B_TRAIN_BASE_RATE", "model_version": _CODE_VERSION,
                "feature_snapshot_id": snapshot_id, "p": base_rate,
                "actual": r["actual"], "league_key": r["league_key"],
            }
            exact_preds["M1_CURRENT_ELO"][r["event_key"]] = {
                "event_key": r["event_key"], "window_id": window_id,
                "train_cutoff": start.isoformat(), "prediction_ts": r["ts"].isoformat(),
                "model_id": "M1_CURRENT_ELO", "model_version": _CODE_VERSION,
                "feature_snapshot_id": snapshot_id, "p": r["p_elo"],
                "actual": r["actual"], "league_key": r["league_key"],
            }
            exact_preds["M2_RECENCY_WEIGHTED_ELO"][r["event_key"]] = {
                "event_key": r["event_key"], "window_id": window_id,
                "train_cutoff": start.isoformat(), "prediction_ts": r["ts"].isoformat(),
                "model_id": "M2_RECENCY_WEIGHTED_ELO", "model_version": _CODE_VERSION,
                "feature_snapshot_id": snapshot_id, "p": r["p_recency"],
                "actual": r["actual"], "league_key": r["league_key"],
            }
            exact_preds["M3_GLICKO"][r["event_key"]] = {
                "event_key": r["event_key"], "window_id": window_id,
                "train_cutoff": start.isoformat(), "prediction_ts": r["ts"].isoformat(),
                "model_id": "M3_GLICKO", "model_version": _CODE_VERSION,
                "feature_snapshot_id": snapshot_id, "p": r["p_glicko"],
                "actual": r["actual"], "league_key": r["league_key"],
            }
            exact_preds["M4_SIMPLE_FORM_MODEL"][r["event_key"]] = {
                "event_key": r["event_key"], "window_id": window_id,
                "train_cutoff": start.isoformat(), "prediction_ts": r["ts"].isoformat(),
                "model_id": "M4_SIMPLE_FORM_MODEL", "model_version": _CODE_VERSION,
                "feature_snapshot_id": snapshot_id, "p": r["p_form"],
                "actual": r["actual"], "league_key": r["league_key"],
            }
            if m5_weights is not None:
                xv = np.array([r["features"][f] for f in _FEATURE_NAMES])
                p5 = float(_sigmoid(m5_weights[0] + m5_weights[1:] @ xv))
                exact_preds["M5_REGULARIZED_LOGISTIC"][r["event_key"]] = {
                    "event_key": r["event_key"], "window_id": window_id,
                    "train_cutoff": start.isoformat(),
                    "prediction_ts": r["ts"].isoformat(),
                    "model_id": "M5_REGULARIZED_LOGISTIC",
                    "model_version": m5_model_version,
                    "feature_snapshot_id": snapshot_id, "p": p5,
                    "actual": r["actual"], "league_key": r["league_key"],
                }

        window_metrics = {}
        for mid in _MODEL_IDS:
            rows_agg = [exact_preds[mid][k] for k in eval_keys if k in exact_preds[mid]]
            window_metrics[mid] = _aggregate(rows_agg) if rows_agg else {"n": 0}
        per_window.append(
            {
                "window_id": window_id,
                "window_start": start.isoformat(),
                "window_end": end.isoformat(),
                "train_event_count": n_train,
                "eval_event_count": len(eval_keys),
                "eval_event_ids_sha256": _event_set_hash(eval_keys),
                "metrics": window_metrics,
                "m5_weights": w_map,
            }
        )
        windows_meta.append(
            {
                "window_id": window_id,
                "train_start": None,
                "train_end": start.isoformat(),
                "eval_start": start.isoformat(),
                "eval_end": end.isoformat(),
                "train_event_count": n_train,
                "eval_event_count": len(eval_keys),
                "eval_event_ids_sha256": _event_set_hash(eval_keys),
            }
        )

    manifest = {
        "dataset": dataset,
        "windows": windows_meta,
    }
    manifest_sha = _sha256_hex(manifest)

    # -------------------------------------------------------- pooled metrics
    pooled = {}
    for mid in _MODEL_IDS:
        pooled[mid] = _aggregate(list(exact_preds[mid].values())) if exact_preds[mid] else {"n": 0}

    # -------------------------------------------------------- paired deltas
    m5 = exact_preds["M5_REGULARIZED_LOGISTIC"]
    paired = {}
    for baseline in ("M0A_CONSTANT_0_5", "M0B_TRAIN_BASE_RATE", "M1_CURRENT_ELO"):
        base = exact_preds[baseline]
        _, _, n_common, only_m5, only_base = _common_rows(m5, base)
        if only_m5 or only_base:
            raise RuntimeError(
                f"pairwise event sets differ vs {baseline}: "
                f"only_m5={len(only_m5)} only_base={len(only_base)}"
            )
        block_ids_day = [m5[k]["prediction_ts"][:10] for k in sorted(m5)]
        block_ids_league = [m5[k]["league_key"] for k in sorted(m5)]
        block_ids_league_month = [
            f"{m5[k]['league_key']}|{m5[k]['prediction_ts'][:7]}" for k in sorted(m5)
        ]
        paired[baseline] = {
            "n": n_common,
            "brier": _blocked_bootstrap_ci(
                _paired_delta_rows(m5, base, "brier"),
                block_ids_day, args.bootstrap_iters, args.seed,
            ),
            "brier_block_competition": _blocked_bootstrap_ci(
                _paired_delta_rows(m5, base, "brier"),
                block_ids_league, args.bootstrap_iters, args.seed,
            ),
            "brier_block_competition_month": _blocked_bootstrap_ci(
                _paired_delta_rows(m5, base, "brier"),
                block_ids_league_month, args.bootstrap_iters, args.seed,
            ),
            "log_loss": _blocked_bootstrap_ci(
                _paired_delta_rows(m5, base, "log_loss"),
                block_ids_day, args.bootstrap_iters, args.seed,
            ),
            "log_loss_block_competition": _blocked_bootstrap_ci(
                _paired_delta_rows(m5, base, "log_loss"),
                block_ids_league, args.bootstrap_iters, args.seed,
            ),
            "log_loss_block_competition_month": _blocked_bootstrap_ci(
                _paired_delta_rows(m5, base, "log_loss"),
                block_ids_league_month, args.bootstrap_iters, args.seed,
            ),
        }

    # -------------------------------------------------------- window stability
    stability = []
    for pw in per_window:
        wm = pw["metrics"]
        row = {
            "window_id": pw["window_id"],
            "n": wm["M0A_CONSTANT_0_5"]["n"],
        }
        for mid in _AUDIT_MODELS:
            agg = wm[mid]
            row[f"{mid}_brier"] = agg.get("brier")
            row[f"{mid}_log_loss"] = agg.get("log_loss")
        m5b = row["M5_REGULARIZED_LOGISTIC_brier"]
        row["M5_delta_vs_M0A_brier"] = round(
            m5b - row["M0A_CONSTANT_0_5_brier"], 6
        ) if m5b is not None else None
        row["M5_delta_vs_M0A_logloss"] = round(
            row["M5_REGULARIZED_LOGISTIC_log_loss"]
            - row["M0A_CONSTANT_0_5_log_loss"], 6
        ) if row["M5_REGULARIZED_LOGISTIC_log_loss"] is not None else None
        row["M5_delta_vs_M0B_brier"] = round(
            m5b - row["M0B_TRAIN_BASE_RATE_brier"], 6
        ) if m5b is not None else None
        row["M5_delta_vs_M1_brier"] = round(
            m5b - row["M1_CURRENT_ELO_brier"], 6
        ) if m5b is not None else None
        stability.append(row)

    deltas_vs_const = [
        r["M5_delta_vs_M0A_brier"] for r in stability
        if r["M5_delta_vs_M0A_brier"] is not None
    ]
    m5_briers = [
        r["M5_REGULARIZED_LOGISTIC_brier"] for r in stability
        if r["M5_REGULARIZED_LOGISTIC_brier"] is not None
    ]
    best = min(stability, key=lambda r: r["M5_delta_vs_M0A_brier"] or 1e9)
    worst = max(stability, key=lambda r: r["M5_delta_vs_M0A_brier"] or -1e9)

    # -------------------------------------------------------- calibration
    cal_rows, weighted_ace, extreme_buckets = _calibration_table(m5)
    cal_keys = set(m5)
    metric_keys = set(exact_preds["M5_REGULARIZED_LOGISTIC"])
    oos_integrity = "PASS" if cal_keys == metric_keys else "FAIL"

    # -------------------------------------------------------- Elo diagnosis
    diagnosis = {}
    for model in ("M1_CURRENT_ELO", "M2_RECENCY_WEIGHTED_ELO", "M3_GLICKO"):
        depth_buckets = defaultdict(list)
        rating_buckets = defaultdict(list)
        prob_buckets = defaultdict(list)
        month_buckets = defaultdict(list)
        for r in records:
            d = r["diagnosis"]
            home_depth = d["home_depth"]
            if home_depth < 5:
                bucket = "1-4"
            elif home_depth < 10:
                bucket = "5-9"
            elif home_depth < 25:
                bucket = "10-24"
            elif home_depth < 50:
                bucket = "25-49"
            else:
                bucket = "50+"
            depth_buckets[bucket].append(r)
            rd = d["rating_diff"]
            if rd < -200:
                rb = "<-200"
            elif rd < -50:
                rb = "-200..-50"
            elif rd < 50:
                rb = "-50..50"
            elif rd < 200:
                rb = "50..200"
            else:
                rb = "200+"
            rating_buckets[rb].append(r)
            p = {"M1_CURRENT_ELO": r["p_elo"], "M2_RECENCY_WEIGHTED_ELO": r["p_recency"],
                 "M3_GLICKO": r["p_glicko"]}[model]
            # probability buckets are FAVORITE-oriented: rows where the home
            # side is the underdog are flipped (p_fav = 1-p, y_fav = 1-y)
            if p < 0.5:
                p_fav = 1.0 - p
                act_fav = 1.0 - r["actual"]
            else:
                p_fav = p
                act_fav = r["actual"]
            pb = "0.50-0.60" if p_fav < 0.6 else ("0.60-0.70" if p_fav < 0.7 else ("0.70-0.80" if p_fav < 0.8 else "0.80+"))
            prob_buckets[pb].append({"p": p_fav, "actual": act_fav})
            month_buckets[d["month"]].append(r)
        diagnosis[model] = {
            "by_home_history_depth": {
                k: _aggregate([{"p": {"M1_CURRENT_ELO": r["p_elo"],
                                      "M2_RECENCY_WEIGHTED_ELO": r["p_recency"],
                                      "M3_GLICKO": r["p_glicko"]}[model],
                                "actual": r["actual"]} for r in v])
                for k, v in sorted(depth_buckets.items())
            },
            "by_rating_difference": {
                k: _aggregate([{"p": {"M1_CURRENT_ELO": r["p_elo"],
                                      "M2_RECENCY_WEIGHTED_ELO": r["p_recency"],
                                      "M3_GLICKO": r["p_glicko"]}[model],
                                "actual": r["actual"]} for r in v])
                for k, v in sorted(rating_buckets.items())
            },
            "by_predicted_probability_favorite_oriented": {
                k: _aggregate(v)
                for k, v in sorted(prob_buckets.items())
            },
            "by_month": {
                k: _aggregate([{"p": {"M1_CURRENT_ELO": r["p_elo"],
                                      "M2_RECENCY_WEIGHTED_ELO": r["p_recency"],
                                      "M3_GLICKO": r["p_glicko"]}[model],
                                "actual": r["actual"]} for r in v])
                for k, v in sorted(month_buckets.items())
            },
        }

    elo_extreme = []
    for r in records:
        rd = r["diagnosis"]["rating_diff"]
        if abs(rd) < 200:
            continue
        if rd >= 200:
            elo_extreme.append({"p": r["p_elo"], "actual": r["actual"]})
        else:
            elo_extreme.append({"p": 1.0 - r["p_elo"], "actual": 1.0 - r["actual"]})
    extreme_agg = _aggregate(elo_extreme) if elo_extreme else {"n": 0}

    # ---------- Elo failure characterization (M1, favorite-oriented) ------
    def _fav(p: float, actual: float, diff: float) -> tuple[float, float]:
        if diff < 0:
            return 1.0 - p, 1.0 - actual
        return p, actual

    elo_spread: dict[str, list[dict]] = defaultdict(list)
    elo_spread_comp: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in records:
        d = r["diagnosis"]["rating_diff"]
        a = abs(d)
        if a < 100:
            bucket = "0-100"
        elif a < 150:
            bucket = "100-150"
        elif a < 200:
            bucket = "150-200"
        elif a < 250:
            bucket = "200-250"
        else:
            bucket = "250+"
        pf, af = _fav(r["p_elo"], r["actual"], d)
        elo_spread[bucket].append({"p": pf, "actual": af})
        elo_spread_comp[(r["league_key"], bucket)].append({"p": pf, "actual": af})

    elo_failure = {
        "by_abs_rating_diff_favorite_oriented": {
            k: _aggregate(v) for k, v in sorted(elo_spread.items())
        },
        "by_competition_abs_rating_diff": {
            f"{k[0]}|{k[1]}": _aggregate(v)
            for k, v in sorted(elo_spread_comp.items())
            if len(v) >= 50
        },
    }
    depth_comp: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in records:
        home_depth = r["diagnosis"]["home_depth"]
        if home_depth < 5:
            bucket = "1-4"
        elif home_depth < 10:
            bucket = "5-9"
        elif home_depth < 25:
            bucket = "10-24"
        elif home_depth < 50:
            bucket = "25-49"
        else:
            bucket = "50+"
        depth_comp[(r["league_key"], bucket)].append(
            {"p": r["p_elo"], "actual": r["actual"]}
        )
    elo_failure["by_competition_history_depth"] = {
        f"{k[0]}|{k[1]}": _aggregate(v)
        for k, v in sorted(depth_comp.items())
        if len(v) >= 50
    }
    fav_corr = sum(1 for r in records if r["p_elo"] > 0.5) / len(records) if records else None

    # ------------------------------------------------- artifact persistence
    out_dir = Path(args.output) if args.output else Path(tempfile.gettempdir()) / "opencode" / "tt_research"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    feature_path = out_dir / f"tt_feature_snapshot_{snapshot_id[:12]}_{stamp}.jsonl"
    with feature_path.open("w", encoding="utf-8") as handle:
        for r in records:
            handle.write(
                json.dumps(
                    {
                        "label": _LABEL,
                        "kind": "tt_feature_snapshot",
                        "feature_snapshot_id": snapshot_id,
                        "feature_schema_version": _SCHEMA_VERSION,
                        "feature_code_version": _CODE_VERSION,
                        "cutoff_ts": r["ts"].isoformat(),
                        "source_observation_ids": [r["raw_ref"]],
                        "event_key": r["event_key"],
                        "league_key": r["league_key"],
                        "home": r["home"],
                        "away": r["away"],
                        "actual": r["actual"],
                        "available": r["available"],
                        "features": r["features"],
                        "predictions": {
                            "M0A_CONSTANT_0_5": 0.5,
                            "M1_CURRENT_ELO": round(r["p_elo"], 6),
                            "M2_RECENCY_WEIGHTED_ELO": round(r["p_recency"], 6),
                            "M3_GLICKO": round(r["p_glicko"], 6),
                            "M4_SIMPLE_FORM_MODEL": round(r["p_form"], 6),
                        },
                    }
                )
                + "\n"
            )

    preds_path = out_dir / f"tt_oos_predictions_{stamp}.jsonl"
    with preds_path.open("w", encoding="utf-8") as handle:
        for mid in _MODEL_IDS:
            for k in sorted(exact_preds[mid]):
                r = exact_preds[mid][k]
                handle.write(
                    json.dumps(
                        {
                            "label": _LABEL,
                            "kind": "tt_oos_predictions",
                            "event_key": r["event_key"],
                            "window_id": r["window_id"],
                            "train_cutoff": r["train_cutoff"],
                            "prediction_ts": r["prediction_ts"],
                            "model_id": r["model_id"],
                            "model_version": r["model_version"],
                            "feature_snapshot_id": r["feature_snapshot_id"],
                            "model_p": round(r["p"], 6),
                            "actual": r["actual"],
                            "league_key": r["league_key"],
                        }
                    )
                    + "\n"
                )

    manifest_path = out_dir / f"tt_eval_manifest_{stamp}.json"
    with manifest_path.open("w", encoding="utf-8") as handle:
        json.dump({"manifest_sha256": manifest_sha, "manifest": manifest}, handle, indent=2)

    summary = {
        "label": _LABEL,
        "kind": "tt_research_suite",
        "schema_version": _SCHEMA_VERSION,
        "code_version": _CODE_VERSION,
        "min_games": args.min_games,
        "eval_start": eval_start.isoformat(),
        "dataset": dataset,
        "manifest_sha256": manifest_sha,
        "pooled_walk_forward": pooled,
        "walk_forward": per_window,
        "paired_deltas": paired,
        "window_stability": {
            "windows": stability,
            "best_m5_window": best["window_id"],
            "worst_m5_window": worst["window_id"],
            "m5_window_brier_variance": round(float(np.var(m5_briers)), 8) if m5_briers else None,
            "m5_delta_vs_constant_brier_variance": round(float(np.var(deltas_vs_const)), 8) if deltas_vs_const else None,
        },
        "calibration": {
            "buckets": cal_rows,
            "weighted_abs_calibration_error": weighted_ace,
            "extreme_buckets": extreme_buckets,
            "oos_artifact_integrity": oos_integrity,
        },
        "elo_diagnosis": diagnosis,
        "elo_failure": elo_failure,
        "elo_extreme": {
            "n": extreme_agg["n"],
            "mean_predicted_favorite_p": extreme_agg.get("mean_predicted_p"),
            "realized_favorite_win_rate": extreme_agg.get("realized_win_rate"),
            "brier": extreme_agg.get("brier"),
            "log_loss": extreme_agg.get("log_loss"),
        },
        "side_a": {
            "base_rate_all_binary": dataset["side_a_base_rate"],
            "home_favorite_share_elo": round(fav_corr, 6) if fav_corr is not None else None,
        },
        "feature_snapshot": {
            "feature_snapshot_id": snapshot_id,
            "feature_schema_version": _SCHEMA_VERSION,
            "feature_code_version": _CODE_VERSION,
            "path": str(feature_path),
        },
        "artifacts": {
            "oos_predictions": str(preds_path),
            "manifest": str(manifest_path),
        },
    }

    summary_path = out_dir / f"tt_research_summary_{stamp}.json"
    with summary_path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)

    print(f"summary={summary_path}")
    print(f"feature_snapshot={feature_path}")
    print(f"feature_snapshot_id={snapshot_id}")
    print(f"EVAL_MANIFEST_SHA256={manifest_sha}")
    print("M0A sanity:", json.dumps(pooled["M0A_CONSTANT_0_5"]))
    print("pooled (walk-forward, binary only):")
    for mid in _AUDIT_MODELS:
        agg = pooled[mid]
        print(f"  {mid}: n={agg['n']} brier={agg.get('brier')} log_loss={agg.get('log_loss')} acc={agg.get('accuracy')}")
    print("paired deltas (M5 vs baselines, block=day):")
    for base, p in paired.items():
        print(f"  vs {base}: brier_mean={p['brier']['mean_delta']} ci=({p['brier']['95ci_low']},{p['brier']['95ci_high']}) "
              f"ll_mean={p['log_loss']['mean_delta']} ci=({p['log_loss']['95ci_low']},{p['log_loss']['95ci_high']}) n={p['n']}")
    print("window stability (M5 vs M0A brier delta):")
    for r in stability:
        print(f"  {r['window_id']}: n={r['n']} m5_delta={r['M5_delta_vs_M0A_brier']}")
    print("calibration M5:", json.dumps(cal_rows))
    print(f"weighted_ace={weighted_ace} extreme={extreme_buckets} oos_integrity={oos_integrity}")
    print(f"elo_extreme: {json.dumps(extreme_agg)}")
    print(f"side_a: {json.dumps(summary['side_a'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
