"""TT DATA QUALITY SCORECARD + IDENTITY GATE (offline, DB-only).

Phase 1/2 of the TT historical activation R&D phase. Reads persisted
tt_match_results + raw_provider_events, emits:
  - per-competition data quality scorecard (coverage, depth, duplicates,
    malformed rows, ambiguity)
  - identity gate counters:
    IDENTITY_EXACT_MATCHES, IDENTITY_NORMALIZED_MATCHES, IDENTITY_AMBIGUITIES,
    IDENTITY_COLLISIONS, UNRESOLVED_PLAYERS, DUPLICATE_EVENTS
  - fragmentation diagnostic (raw-name pairs that look like the same person
    but map to different participant keys) - NO auto fuzzy merge.

Writes a MODEL_RESEARCH artifact (JSONL) to the temp output dir; never
touches the live decision journal. Requires SPORTS_DATABASE_URL.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import psycopg

_ARTIFACT_LABEL = "MODEL_RESEARCH"
_IDENTITY_ARTIFACT = "tt_identity_gate"


def _slug(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum() or ch in "-_") or "unknown"


def _words(name: str) -> list[str]:
    return [w for w in re.split(r"[\s,.\-]+", name.lower()) if w]


def _looks_fragmented(a: str, b: str) -> bool:
    if a == b:
        return False
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return False
    if wa == wb:
        return False
    if len(wa) != len(wb):
        shorter, longer = (wa, wb) if len(wa) < len(wb) else (wb, wa)
        if longer[: len(shorter)] == shorter and len(longer) - len(shorter) <= 2:
            return True
        return False
    if all((x == y or y.startswith(x) or x.startswith(y)) for x, y in zip(wa, wb)):
        return any(x != y for x, y in zip(wa, wb))
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=None, help="artifact directory (default: temp)")
    parser.add_argument("--competition", default=None, help="filter league_key")
    args = parser.parse_args()

    db_url = os.environ.get("SPORTS_DATABASE_URL")
    if not db_url:
        print("SPORTS_DATABASE_URL is required")
        return 2

    out_dir = Path(args.output) if args.output else Path(tempfile.gettempdir()) / "opencode"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    artifact_path = out_dir / f"{_IDENTITY_ARTIFACT}_{stamp}.jsonl"

    conn = psycopg.connect(db_url)
    rows = conn.execute(
        "select event_key, league_key, home_participant_key, away_participant_key, "
        "home_score, away_score, completed_at, raw_ref "
        "from tt_match_results where source_provider='odds_api_io'"
    ).fetchall()

    if args.competition:
        rows = [r for r in rows if r[1] == args.competition]

    results = []
    for event_key, league_key, home_key, away_key, home_score, away_score, completed_at, raw_ref in rows:
        results.append(
            {
                "event_key": event_key,
                "league_key": league_key,
                "home_key": home_key,
                "away_key": away_key,
                "home_score": home_score,
                "away_score": away_score,
                "completed_at": completed_at.isoformat() if completed_at else None,
                "raw_ref": raw_ref,
            }
        )

    raw_names: dict[str, tuple[str, str]] = {}
    raw_rows = conn.execute(
        "select provider_event_id, payload from raw_provider_events"
    ).fetchall()
    for provider_event_id, payload in raw_rows:
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                continue
        if not isinstance(payload, dict):
            continue
        home = str(payload.get("home") or "").strip()
        away = str(payload.get("away") or "").strip()
        raw_names[str(provider_event_id)] = (home, away)

    # ------------------------------------------------------------- scorecard
    by_league: dict[str, dict[str, object]] = {}
    league_keys = sorted({r["league_key"] for r in results})
    for league in league_keys:
        subset = [r for r in results if r["league_key"] == league]
        events = {r["event_key"] for r in subset}
        event_ids = Counter(r["event_key"] for r in subset)
        duplicate_events = sorted({k for k, v in event_ids.items() if v > 1})
        completed = [r for r in subset if r["completed_at"]]
        completed_at = [r["completed_at"] for r in completed]
        home_keys = {r["home_key"] for r in subset} | {r["away_key"] for r in subset}
        malformed = [
            r for r in subset
            if r["home_score"] is None or r["away_score"] is None
            or r["completed_at"] is None
        ]
        months = Counter((c[:7]) for c in completed_at)
        by_league[league] = {
            "league": league,
            "event_count": len(events),
            "result_rows": len(subset),
            "unique_events": len(events),
            "duplicate_events": len(duplicate_events),
            "unique_players": len(home_keys),
            "malformed_rows": len(malformed),
            "earliest_completed": min(completed_at) if completed_at else None,
            "latest_completed": max(completed_at) if completed_at else None,
            "months_with_events": len(months),
            "events_per_month": dict(sorted(months.items())),
        }

    # ---------------------------------------------------------- identity gate
    name_to_key: dict[tuple[str, str], set[str]] = defaultdict(set)
    key_to_names: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for r in results:
        raw = raw_names.get(str(r["raw_ref"]))
        if raw and raw[0]:
            name_to_key[(raw[0], r["home_key"])].add(r["home_key"])
            key_to_names[r["home_key"]].add((raw[0], "home"))
        if raw and raw[1]:
            name_to_key[(raw[1], r["away_key"])].add(r["away_key"])
            key_to_names[r["away_key"]].add((raw[1], "away"))

    raw_spellings: dict[str, set[str]] = defaultdict(set)
    for r in results:
        raw = raw_names.get(str(r["raw_ref"]))
        if raw:
            if raw[0]:
                raw_spellings[r["home_key"]].add(raw[0])
            if raw[1]:
                raw_spellings[r["away_key"]].add(raw[1])

    fragmentation: list[dict[str, object]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for key_a, names_a in raw_spellings.items():
        for key_b, names_b in raw_spellings.items():
            if key_a >= key_b:
                continue
            for na in names_a:
                for nb in names_b:
                    pair = tuple(sorted((na, nb)))
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)
                    if _looks_fragmented(na, nb):
                        fragmentation.append(
                            {
                                "raw_a": na,
                                "raw_b": nb,
                                "key_a": key_a,
                                "key_b": key_b,
                            }
                        )

    substantive_collisions = [
        (key, sorted(names))
        for key, names in raw_spellings.items()
        if len({_slug(n) for n in names}) > 1
    ]
    unresolved = [
        (key, sorted(names))
        for key, names in raw_spellings.items()
        if len({_slug(n) for n in names}) > 1 and not any(
            _looks_fragmented(a, b)
            for a in names
            for b in names
        )
    ]

    participants = {r["home_key"] for r in results} | {r["away_key"] for r in results}
    identity = {
        "IDENTITY_EXACT_MATCHES": len(participants),
        "IDENTITY_NORMALIZED_MATCHES": len({_slug(n) for names in raw_spellings.values() for n in names}),
        "IDENTITY_AMBIGUITIES": len(fragmentation),
        "IDENTITY_COLLISIONS": len(substantive_collisions),
        "UNRESOLVED_PLAYERS": len(unresolved),
        "DUPLICATE_EVENTS": sum(len(v) for v in by_league.values() if isinstance(v, dict) and v.get("duplicate_events", 0)),
    }

    artifact = {
        "label": _ARTIFACT_LABEL,
        "kind": _IDENTITY_ARTIFACT,
        "generated_at": stamp,
        "scorecard": by_league,
        "identity": identity,
        "fragmentation_examples": fragmentation[:25],
        "fragmentation_pair_count": len(fragmentation),
    }
    with artifact_path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(artifact, default=str, indent=2) + "\n")

    print(f"artifact={artifact_path}")
    print("competitions discovered:", ", ".join(league_keys))
    for league, card in by_league.items():
        print(
            f"{league}: events={card['event_count']} results={card['result_rows']} "
            f"players={card['unique_players']} dup={card['duplicate_events']} "
            f"malformed={card['malformed_rows']} range="
            f"{card['earliest_completed']}..{card['latest_completed']}"
        )
    print("identity:", json.dumps(identity, default=str))
    print("fragmentation pairs:", len(fragmentation))
    for ex in fragmentation[:10]:
        print("  FRAG:", ex["raw_a"], "->", ex["key_a"], "|", ex["raw_b"], "->", ex["key_b"])
    return 0


if __name__ == "__main__":
    sys.exit(main())