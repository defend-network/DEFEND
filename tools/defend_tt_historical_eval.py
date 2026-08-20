"""DEFEND table-tennis historical evaluation (TT HISTORICAL ACTIVATION).

Computes a strictly time-forward evaluation of the Elo model from persisted
data only: tt_rating_history rows are per-participant point-in-time
predictions (``expected`` = Elo-implied win probability BEFORE the match,
``actual`` = observed outcome). No network calls, no fabricated data, no
writes to any database and nothing ever enters the live prediction journal.

Every evaluation record is labeled HISTORICAL_EVALUATION and written to a
JSONL artifact file (default: temp dir; override with --out).

Market-based metrics are reported as NOT_AVAILABLE because the free-tier
Odds-API.io account exposes no historical TT odds (all sampled events
returned empty ``bookmakers``).

Usage:
    python tools/defend_tt_historical_eval.py
    python tools/defend_tt_historical_eval.py --out eval.jsonl
    python tools/defend_tt_historical_eval.py --min-games 5
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from defend_markets.db import MarketsDatabase

_EPSILON = Decimal("1e-6")
_CALIBRATION_BUCKETS = (
    (Decimal("0.5"), Decimal("0.6")),
    (Decimal("0.6"), Decimal("0.7")),
    (Decimal("0.7"), Decimal("0.8")),
    (Decimal("0.8"), Decimal("0.9")),
    (Decimal("0.9"), Decimal("1.0")),
)
_LABEL = "HISTORICAL_EVALUATION"


def _bucket(expected: Decimal) -> str:
    for lower, upper in _CALIBRATION_BUCKETS:
        if lower <= expected < upper:
            return f"{lower}-{upper}"
    if expected == Decimal("1"):
        return "0.9-1.0"
    return "0.5-0.6"


def _log_loss(expected: Decimal, actual: Decimal) -> float:
    p = min(max(expected, _EPSILON), Decimal("1") - _EPSILON)
    a = float(actual)
    return -(a * math.log(float(p)) + (1 - a) * math.log(1 - float(p)))


def main() -> None:
    parser = argparse.ArgumentParser(description="DEFEND TT historical evaluation (Elo, time-forward)")
    parser.add_argument("--out", help="JSONL artifact path (default: temp dir)")
    parser.add_argument("--min-games", type=int, default=1, help="only evaluate participants with >= N games")
    parser.add_argument("--holdout-last", type=int, default=0, help="chronological holdout: evaluate only the last N matches, ratings built strictly from the earlier matches only")
    args = parser.parse_args()

    markets_url = os.environ.get("MARKETS_DATABASE_URL", "").strip()
    if not markets_url:
        print("[tt-historical-eval] MARKETS_DATABASE_URL must be set", file=sys.stderr)
        sys.exit(2)

    database = MarketsDatabase(markets_url)
    database.migrate()

    with database.connect() as connection:
        rows = connection.execute(
            "SELECT participant_key, ts, event_key, opponent_key, pre_rating, "
            "expected, actual, post_rating, result, model_version, "
            "source_provider, raw_ref "
            "FROM tt_rating_history ORDER BY ts, event_key"
        ).fetchall()

    games_per_player: Counter[str] = Counter()
    matches: set[str] = set()
    records: list[dict[str, object]] = []
    for row in rows:
        participant_key = str(row[0])
        games_per_player[participant_key] += 1
        matches.add(str(row[2]))

    selected = {
        player for player, games in games_per_player.items() if games >= args.min_games
    }
    total_brier = Decimal("0")
    total_logloss = Decimal("0")
    calibration: dict[str, list[Decimal]] = defaultdict(list)
    evaluated = 0
    for row in rows:
        participant_key = str(row[0])
        if participant_key not in selected:
            continue
        expected = Decimal(row[5])
        actual = Decimal(row[6])
        evaluated += 1
        total_brier += (expected - actual) ** 2
        total_logloss += Decimal(str(_log_loss(expected, actual)))
        calibration[_bucket(expected)].append(actual)
        records.append(
            {
                "label": _LABEL,
                "event_key": str(row[2]),
                "ts": row[1].isoformat() if row[1] is not None else None,
                "participant_key": participant_key,
                "opponent_key": str(row[3]),
                "pre_rating": str(row[4]),
                "expected_probability": str(expected),
                "actual": str(actual),
                "result": str(row[8]),
                "model_version": str(row[9]),
                "source_provider": str(row[10]),
                "raw_ref": row[11],
            }
        )

    if args.out:
        artifact = Path(args.out)
    else:
        artifact = (
            Path(tempfile.gettempdir())
            / "opencode"
            / f"tt_historical_eval_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.jsonl"
        )
    artifact.parent.mkdir(parents=True, exist_ok=True)
    with artifact.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    n_matches = len(matches)
    n_players_total = len(games_per_player)
    n_players_evaluated = len(selected)
    players_5_plus = sum(1 for games in games_per_player.values() if games >= 5)
    brier = float(total_brier / evaluated) if evaluated else None
    logloss = float(total_logloss / evaluated) if evaluated else None

    print(f"label={_LABEL}")
    print(f"artifact={artifact}")
    print(f"matches={n_matches}")
    print(f"players_total={n_players_total} players_evaluated={n_players_evaluated} players_5_plus={players_5_plus}")
    print(f"evaluation_records={evaluated}")
    print(f"elo_brier={brier if brier is not None else 'INSUFFICIENT_SAMPLE'}")
    print(f"elo_log_loss={logloss if logloss is not None else 'INSUFFICIENT_SAMPLE'}")
    for bucket, outcomes in sorted(calibration.items()):
        total = len(outcomes)
        win_rate = float(sum(outcomes)) / total
        print(
            f"calibration_bucket={bucket} records={total} win_rate={win_rate:.3f}"
        )
    print("market_brier=NOT_AVAILABLE market_log_loss=NOT_AVAILABLE reason=historical_odds_unavailable_on_free_tier")

    if args.holdout_last > 0:
        _run_holdout(database, args.holdout_last)


def _run_holdout(database: MarketsDatabase, holdout_last: int) -> None:
    from decimal import Decimal as D

    from defend_markets.domain import TTMatchResult
    from defend_markets.tt_rating import rebuild_rating_history, expected_score

    with database.connect() as connection:
        raw = connection.execute(
            "SELECT event_key, league_key, home_participant_key, away_participant_key, "
            "home_score, away_score, completed_at, source_provider, raw_ref "
            "FROM tt_match_results ORDER BY completed_at, event_key"
        ).fetchall()
    results = [
        TTMatchResult(
            event_key=str(row[0]),
            league_key=str(row[1]),
            home_participant_key=str(row[2]),
            away_participant_key=str(row[3]),
            home_score=int(row[4]),
            away_score=int(row[5]),
            completed_at=row[6],
            source_provider=str(row[7] or "unknown"),
            raw_ref=row[8],
        )
        for row in raw
    ]
    if holdout_last >= len(results):
        print(
            f"holdout_matches={len(results)} "
            "error=holdout_must_be_smaller_than_total_matches"
        )
        return
    train = results[: len(results) - holdout_last]
    holdout = results[len(results) - holdout_last :]

    final_ratings: dict[str, D] = {}
    for row in rebuild_rating_history(train):
        final_ratings[row.participant_key] = row.post_rating

    total_brier = D("0")
    total_logloss = D("0")
    correct = 0
    available = 0
    for match in holdout:
        home = final_ratings.get(match.home_participant_key)
        away = final_ratings.get(match.away_participant_key)
        if home is None or away is None:
            continue
        available += 1
        p_home = expected_score(home, away)
        home_won = match.home_score > match.away_score
        away_won = match.away_score > match.home_score
        drawn = not home_won and not away_won
        actual = D("0.5") if drawn else (D("1") if home_won else D("0"))
        total_brier += (p_home - actual) ** 2
        total_logloss += D(str(_log_loss(p_home, actual)))
        if (home_won and p_home >= D("0.5")) or (away_won and p_home < D("0.5")):
            correct += 1
    boundary = holdout[0].completed_at
    print("holdout_definition=chronological_last_{}_matches".format(holdout_last))
    print(
        "holdout_boundary={} train_matches={} holdout_matches={}".format(
            boundary.isoformat() if boundary is not None else None,
            len(train),
            len(holdout),
        )
    )
    if available == 0:
        print("holdout_brier=INSUFFICIENT_SAMPLE holdout_log_loss=INSUFFICIENT_SAMPLE")
        return
    print(
        "holdout_available={} holdout_brier={:.6f} holdout_log_loss={:.6f} "
        "holdout_accuracy={:.4f}".format(
            available,
            float(total_brier / D(available)),
            float(total_logloss / D(available)),
            correct / available,
        )
    )


if __name__ == "__main__":
    main()