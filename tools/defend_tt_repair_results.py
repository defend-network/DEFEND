"""Repair tt_match_results labels from raw_provider_events using the canonical
final-result parser (parse_tt_final_result). Preview mode (default) writes a
deterministic JSON artifact and prints counts without touching any database;
--apply persists corrected rows through the normal record_tt_results path in a
single transaction, then re-runs the preview to prove idempotency.

The plan/apply logic is pure (operates on in-memory rows) so the exact
repair semantics are unit-testable; only the loaders and the persist call
touch the databases.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from typing import Iterable, Sequence

import psycopg

from defend_markets.db import MarketsDatabase
from defend_markets.domain import TTMatchResult
from defend_markets.repositories import MarketsRepository
from defend_markets.store import PostgresMarketsStore
from defend_sports.providers.odds_api_io import parse_tt_final_result

ARTIFACT_PATH = r"C:\Users\thoma\AppData\Local\Temp\opencode\tt_audit\repair_preview.json"

SETTLED = ("settled", "finished", "completed", "ended")


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _winner(home: int, away: int) -> str | None:
    if home > away:
        return "HOME"
    if away > home:
        return "AWAY"
    return None


def _index_stored(
    rows: Sequence[Sequence[object]],
) -> dict[str, tuple]:
    by_ref: dict[str, tuple] = {}
    for row in rows:
        by_ref[str(row[8] or "")] = tuple(row)
        by_ref.setdefault(str(row[0]), tuple(row))
    return by_ref


def build_plan(
    raw_rows: Iterable[tuple[str, object]],
    stored_rows: Sequence[Sequence[object]],
) -> dict[str, object]:
    """Return the deterministic repair report for the given raw + stored rows.

    ``raw_rows`` are (provider_event_id, payload) pairs; ``stored_rows`` are
    tt_match_results rows ordered as (event_key, league_key,
    home_participant_key, away_participant_key, home_score, away_score,
    completed_at, source_provider, raw_ref). No database is touched.
    """
    raw = list(raw_rows)
    raw_by_key = {str(pid): payload for pid, payload in raw}
    stored = _index_stored(stored_rows)

    rows: list[dict[str, object]] = []
    for provider_event_id, payload in raw:
        status = (payload or {}).get("status", "")
        if status not in SETTLED:
            continue
        parsed = parse_tt_final_result(payload)
        rows.append(
            {
                "event_key": str(provider_event_id),
                "status": status,
                "new_status": parsed.status,
                "new_home_score": parsed.home_score,
                "new_away_score": parsed.away_score,
                "new_winner": parsed.winner,
                "source": parsed.source,
                "reason_code": parsed.reason_code,
            }
        )
    rows.sort(key=lambda r: r["event_key"])

    total_raw = len(raw)
    settled = len(rows)
    ft_present = 0
    ft_top_score_mismatch = 0
    ft_winner_mismatch = 0
    no_ft = 0
    no_ft_derivable = 0
    no_ft_single_game = 0
    true_void = 0
    unresolved = 0
    changed = {
        "winner_changed": 0, "score_changed_winner_same": 0, "unchanged": 0,
        "recovered_from_prior_void": 0, "now_void": 0, "unresolved": 0,
        "stored_missing": 0,
    }
    changes: list[dict[str, object]] = []

    for row in rows:
        key = row["event_key"]
        payload = raw_by_key.get(key, {})
        scores = (payload or {}).get("scores") or {}
        periods = scores.get("periods") or {}
        ft = periods.get("ft") if isinstance(periods, dict) else None
        if isinstance(ft, dict):
            fth, fta = _as_int(ft.get("home")), _as_int(ft.get("away"))
            if fth is not None and fta is not None:
                ft_present += 1
                toph, topa = _as_int(scores.get("home")), _as_int(scores.get("away"))
                if toph is not None and topa is not None:
                    if (toph, topa) != (fth, fta):
                        ft_top_score_mismatch += 1
                    if _winner(toph, topa) != _winner(fth, fta):
                        ft_winner_mismatch += 1
        else:
            no_ft += 1

        if row["new_status"] == "VERIFIED":
            if row["source"] == "DERIVED_PERIODS":
                no_ft_derivable += 1
            elif row["source"] == "SINGLE_GAME":
                no_ft_single_game += 1
        elif row["new_status"] == "VOID":
            true_void += 1
        else:
            unresolved += 1

        existing = stored.get(key)
        if existing is None:
            changed["stored_missing"] += 1
            continue
        old_h, old_a = existing[4], existing[5]
        old_winner = _winner(old_h, old_a)
        new_h, new_a = row["new_home_score"], row["new_away_score"]
        new_winner = row["new_winner"]
        if row["new_status"] == "UNRESOLVED":
            changed["unresolved"] += 1
            continue
        if (old_h, old_a) == (new_h, new_a):
            changed["unchanged"] += 1
            continue
        if new_winner is None:
            changed["now_void"] += 1
        elif old_winner is None:
            changed["recovered_from_prior_void"] += 1
        elif old_winner != new_winner:
            changed["winner_changed"] += 1
        else:
            changed["score_changed_winner_same"] += 1
        changes.append(
            {
                "event_key": key,
                "old_home_score": old_h,
                "old_away_score": old_a,
                "new_home_score": new_h,
                "new_away_score": new_a,
                "old_winner": old_winner,
                "new_winner": new_winner,
                "source": row["source"],
                "reason_code": row["reason_code"],
            }
        )

    return {
        "TOTAL_RAW_TT_EVENTS": total_raw,
        "TOTAL_SETTLED_RESULTS": settled,
        "FT_PRESENT": ft_present,
        "FT_TOP_SCORE_MISMATCH": ft_top_score_mismatch,
        "FT_WINNER_MISMATCH": ft_winner_mismatch,
        "NO_FT": no_ft,
        "NO_FT_DERIVABLE": no_ft_derivable,
        "NO_FT_SINGLE_GAME": no_ft_single_game,
        "TRUE_VOID_ABANDONED": true_void,
        "UNRESOLVED": unresolved,
        "OLD_LABELS_CHANGED": changed["winner_changed"] + changed["score_changed_winner_same"],
        "OLD_WINNERS_CHANGED": changed["winner_changed"],
        "PRIOR_VOID_ROWS_RECOVERED": changed["recovered_from_prior_void"],
        "NEW_VOID_ROWS": changed["now_void"],
        "ROWS_UNCHANGED": changed["unchanged"],
        "ROWS_UNRESOLVED": changed["unresolved"],
        "STORED_MISSING": changed["stored_missing"],
        "changes": changes,
    }


def collect_repair_results(
    report: dict[str, object],
    stored_rows: Sequence[Sequence[object]],
    raw_rows: Iterable[tuple[str, object]],
) -> list[TTMatchResult]:
    """Build the TTMatchResult updates for the report's changes.

    Each change is resolved against the *canonical stored row* (its own
    event_key, raw_ref and provider references are preserved); only the
    scores are replaced with the canonical parser output. Rows whose parser
    verdict is not VERIFIED are skipped. Pure: no database is touched.
    """
    stored = _index_stored(stored_rows)
    raw_by_key = {str(pid): payload for pid, payload in raw_rows}

    results: list[TTMatchResult] = []
    for change in report["changes"]:
        key = change["event_key"]
        existing = stored.get(key)
        if existing is None:
            continue
        payload = raw_by_key.get(key) or {}
        parsed = parse_tt_final_result(payload)
        if parsed.status != "VERIFIED":
            continue
        results.append(
            TTMatchResult(
                event_key=existing[0],
                league_key=existing[1],
                home_participant_key=existing[2],
                away_participant_key=existing[3],
                home_score=parsed.home_score,
                away_score=parsed.away_score,
                completed_at=existing[6],
                source_provider=existing[7],
                raw_ref=existing[8],
            )
        )
    return results


def _load_raw(sports_url: str) -> list[tuple[str, object]]:
    with psycopg.connect(sports_url) as connection:
        return connection.execute(
            "select provider_event_id, payload from raw_provider_events"
        ).fetchall()


def _load_stored(markets_url: str) -> list[tuple]:
    with psycopg.connect(markets_url) as connection:
        return connection.execute(
            "select event_key, league_key, home_participant_key, away_participant_key, "
            "home_score, away_score, completed_at, source_provider, raw_ref "
            "from tt_match_results"
        ).fetchall()


def _write_artifact(report: dict[str, object]) -> str:
    os.makedirs(os.path.dirname(ARTIFACT_PATH), exist_ok=True)
    text = json.dumps(report, indent=2, sort_keys=True)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    with open(ARTIFACT_PATH, "w", encoding="utf-8") as handle:
        handle.write(text)
    return digest


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair tt_match_results labels from raw evidence")
    parser.add_argument("--apply", action="store_true", help="persist corrected rows (default: preview only)")
    args = parser.parse_args()

    sports_url = os.environ.get("SPORTS_DATABASE_URL", "").strip()
    markets_url = os.environ.get("MARKETS_DATABASE_URL", "").strip()
    if not sports_url or not markets_url:
        raise SystemExit("SPORTS_DATABASE_URL and MARKETS_DATABASE_URL must be set")

    raw = _load_raw(sports_url)
    stored = _load_stored(markets_url)
    report = build_plan(raw, stored)
    digest = _write_artifact(report)
    print(f"REPAIR_PREVIEW_SHA256={digest}")
    print(f"artifact={ARTIFACT_PATH}")
    for field in (
        "TOTAL_RAW_TT_EVENTS", "TOTAL_SETTLED_RESULTS", "FT_PRESENT",
        "FT_TOP_SCORE_MISMATCH", "FT_WINNER_MISMATCH", "NO_FT", "NO_FT_DERIVABLE",
        "NO_FT_SINGLE_GAME", "TRUE_VOID_ABANDONED", "UNRESOLVED",
        "OLD_LABELS_CHANGED", "OLD_WINNERS_CHANGED", "PRIOR_VOID_ROWS_RECOVERED",
        "NEW_VOID_ROWS", "ROWS_UNCHANGED", "ROWS_UNRESOLVED", "STORED_MISSING",
    ):
        print(f"{field}={report[field]}")
    print(f"rows_to_update={len(report['changes'])}")

    if args.apply:
        results = collect_repair_results(report, stored, raw)
        database = MarketsDatabase(markets_url)
        store = PostgresMarketsStore(database, MarketsRepository())
        applied = store.record_tt_results(results)
        print(f"applied_updates={applied}")
        recheck = build_plan(raw, stored)
        recheck_digest = _write_artifact(recheck)
        print(f"POST_REPAIR_PREVIEW_SHA256={recheck_digest}")
        print(f"post_repair_changes={len(recheck['changes'])}")
        print("REPAIR_IDEMPOTENT=" + ("PASS" if len(recheck["changes"]) == 0 else "FAIL"))


if __name__ == "__main__":
    main()