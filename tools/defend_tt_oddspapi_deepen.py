"""P4: OddsPapi historical-odds deepening (bounded sample, no mass backfill).

Samples OddsPapi fixtures across 3 leagues x 3 eras (early/mid/recent), calls
/v4/historical-odds per fixture with 2-3 bookmakers, and computes the P4
metric set. Canonical matching uses the deterministic hierarchy in
defend_integrations.matching (P5) - ambiguous matches fail closed.

Hard caps: PER_PROVIDER_PROBE_CAP=40 (4 retries already spent this sprint,
this run uses <=36), PAID_SPEND_USD=0, >=7s spacing between calls, raw
evidence archived sanitized via the probe layer. Read-only on the canonical
database; never writes tt_match_results.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from defend_integrations.matching import MatchLevel, match_event, normalize_name
from defend_integrations.phase_c_adapters import OddspapiPhaseCAdapter
from defend_integrations.probing import ProbeBudget
from defend_integrations.stores import SecretRegistry, default_secret_path
from defend_control.secrets import DpapiSecretStore

LEAGUE_MAP = {
    "czech-liga-pro": "czech-republic-czech-liga-pro",
    "tt-cup": "international-tt-cup",
    "tt-elite-series": "international-tt-elite-series",
}
BOOKMAKER_SETS = [
    ("bet365", "1xbet"),
    ("pinnacle", "1xbet"),
    ("bet365", "pinnacle"),
    ("1xbet", "bet365", "pinnacle"),
]


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 2) if values else None


def _p90(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(0.90 * len(ordered)))
    return round(ordered[index], 2)


def load_fixtures(path: Path, leagues: set[str]) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return []
    return [
        fx
        for fx in data
        if isinstance(fx, dict)
        and fx.get("statusId") == 2
        and fx.get("tournamentSlug") in leagues
        and fx.get("fixtureId")
    ]


def sample_fixtures(fixtures: list[dict], per_cell: int, rng: random.Random,
                    has_odds_only: bool = False) -> list[dict]:
    if has_odds_only:
        pool = [fx for fx in fixtures if fx.get("hasOdds")]
        if len(pool) > per_cell:
            return rng.sample(pool, per_cell)
        return pool
    by_odds: dict[str, list[dict]] = {"True": [], "False": []}
    for fx in fixtures:
        by_odds[str(bool(fx.get("hasOdds")))].append(fx)
    picks: list[dict] = []
    for has_odds in ("True", "False"):
        pool = by_odds[has_odds]
        take = per_cell // 2
        if take and len(pool) > take:
            picks.extend(rng.sample(pool, take))
        else:
            picks.extend(pool)
    rng.shuffle(picks)
    return picks[:per_cell]


def canonical_events(conn, league_keys: list[str]) -> list[dict]:
    rows = conn.execute(
        "SELECT event_key, league_key, home_participant_key, away_participant_key, "
        "home_score, away_score, completed_at "
        "FROM tt_match_results "
        "WHERE source_provider='odds_api_io' AND league_key = ANY(%s)",
        (league_keys,),
    ).fetchall()
    events: list[dict] = []
    for event_key, league_key, hk, ak, hs, aws, completed_at in rows:
        if not hk or not ak:
            continue
        events.append(
            {
                "event_key": event_key,
                "competition": league_key,
                "participant_keys": [
                    normalize_name(str(hk).replace("table_tennis:", "")),
                    normalize_name(str(ak).replace("table_tennis:", "")),
                ],
                "commence_at": (
                    completed_at.isoformat() if completed_at else None
                ),
            }
        )
    return events


def line_move_count(observations) -> int:
    series: dict[tuple, list] = {}
    for obs in observations:
        key = (
            obs.provider_bookmaker,
            obs.provider_market_id,
            obs.provider_outcome_id,
            obs.participant_key,
        )
        series.setdefault(key, []).append(obs)
    changes = 0
    for snapshots in series.values():
        ordered = sorted(
            snapshots,
            key=lambda o: _parse_ts(o.observed_at) or datetime.min.replace(tzinfo=timezone.utc),
        )
        previous: float | None = None
        for obs in ordered:
            if obs.price is None:
                continue
            if previous is not None and abs(obs.price - previous) > 1e-9:
                changes += 1
            previous = obs.price
    return changes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--era-fixtures", nargs=3, required=True,
                        help="three fixture JSON files: early, mid, recent")
    parser.add_argument("--seed", type=int, default=20260820)
    parser.add_argument("--per-cell", type=int, default=4)
    parser.add_argument("--has-odds-only", action="store_true",
                        help="sample only fixtures where OddsPapi reported odds")
    parser.add_argument("--bookmakers", default=None,
                        help="comma-separated override (e.g. '1xbet') for every call")
    parser.add_argument("--spacing-seconds", type=float, default=7.0)
    parser.add_argument("--budget", type=int, default=36)
    parser.add_argument("--evidence-dir", type=Path,
                        default=REPO / "docs" / "provider-contracts" / "evidence")
    parser.add_argument("--out", type=Path,
                        default=REPO / "docs" / "operations" / "TT_ODDSPAPI_DEEPEN_V1.json")
    args = parser.parse_args()

    db_url = os.environ.get("MARKETS_DATABASE_URL")
    if not db_url:
        print("MARKETS_DATABASE_URL is required (read-only access)")
        return 2

    reg = SecretRegistry(DpapiSecretStore(default_secret_path()))
    key = reg.get("ODDSPAPI_API_KEY")
    if not key:
        print("ODDSPAPI_API_KEY missing")
        return 2

    adapter = OddspapiPhaseCAdapter()
    adapter._key = key
    budget = ProbeBudget("oddspapi", cap=args.budget)
    rng = random.Random(args.seed)
    bookmaker_override = (
        tuple(b.strip() for b in args.bookmakers.split(",") if b.strip())
        if args.bookmakers
        else None
    )

    conn = psycopg.connect(db_url)
    try:
        canonical = canonical_events(conn, list(LEAGUE_MAP.values()))
    finally:
        conn.close()
    print(f"canonical events loaded: {len(canonical)}")

    cells = [
        ("early", "v4_fixtures_aug2025.json"),
        ("mid", "v4_fixtures_mar2026.json"),
        ("recent", "v4_fixtures_recent2026.json"),
    ]
    plan: list[dict] = []
    for era, fname in cells:
        fixtures = load_fixtures(Path(args.era_fixtures[0]).parent / fname, set(LEAGUE_MAP))
        for slug in LEAGUE_MAP:
            pool = [fx for fx in fixtures if fx["tournamentSlug"] == slug]
            for fx in sample_fixtures(pool, args.per_cell, rng, args.has_odds_only):
                plan.append(
                    {
                        "era": era,
                        "league_slug": slug,
                        "league_key": LEAGUE_MAP[slug],
                        "fixture": fx,
                        "bookmakers": bookmaker_override or BOOKMAKER_SETS[len(plan) % len(BOOKMAKER_SETS)],
                    }
                )
    print(f"plan: {len(plan)} historical-odds calls (budget {budget.remaining})")
    if len(plan) > budget.remaining:
        print("plan exceeds budget; truncating")
        plan = plan[: budget.remaining]

    results: list[dict] = []
    for index, cell in enumerate(plan):
        fx = cell["fixture"]
        if index:
            time.sleep(args.spacing_seconds)
        result, observations = adapter.probe_historical(
            budget,
            args.evidence_dir,
            fixture_id=fx["fixtureId"],
            bookmakers=list(cell["bookmakers"]),
            commence_at=fx.get("startTime"),
        )
        endpoint = result.endpoints.get(f"historical-odds:{fx['fixtureId']}", {})
        match = match_event(
            provider_event_id=fx["fixtureId"],
            provider_prefix="oddspapi",
            participants=[fx.get("participant1Name", ""), fx.get("participant2Name", "")],
            competition=cell["league_key"],
            commence_at=fx.get("startTime"),
            canonical_events=canonical,
            window_hours=3.0,
        )
        commence = _parse_ts(fx.get("startTime"))
        prematch = [o for o in observations if _parse_ts(o.observed_at) and commence
                    and _parse_ts(o.observed_at) < commence]
        post = [o for o in observations if _parse_ts(o.observed_at) and commence
                and _parse_ts(o.observed_at) >= commence]
        last_prematch_gap_h = None
        if prematch and commence:
            last_ts = max(_parse_ts(o.observed_at) for o in prematch)
            last_prematch_gap_h = round((commence - last_ts).total_seconds() / 3600.0, 2)
        markets = {o.provider_market_id for o in observations}
        bookmakers_seen = {o.provider_bookmaker for o in observations}
        results.append(
            {
                "era": cell["era"],
                "league": cell["league_slug"],
                "fixture_id": fx["fixtureId"],
                "participants": [fx.get("participant1Name"), fx.get("participant2Name")],
                "commence_at": fx.get("startTime"),
                "bookmakers_requested": list(cell["bookmakers"]),
                "status": endpoint.get("status_code"),
                "error_class": endpoint.get("error_class"),
                "observations": len(observations),
                "bookmakers_with_data": sorted(bookmakers_seen),
                "markets_seen": sorted(markets),
                "market_winner_251": "251" in markets,
                "prematch_snapshots": len(prematch),
                "post_commence_snapshots": len(post),
                "last_prematch_gap_hours": last_prematch_gap_h,
                "price_changes": line_move_count(observations),
                "match": match.to_dict(),
            }
        )
        print(
            f"[{index + 1}/{len(plan)}] {cell['era']} {cell['league_slug']} "
            f"{fx['fixtureId']} -> {endpoint.get('status_code')} "
            f"obs={len(observations)} match={match.level.value}"
        )
        sys.stdout.flush()

    events_with_odds = [r for r in results if r["observations"] > 0]
    snapshots_per_event = [r["observations"] for r in events_with_odds]
    bookmakers_per_event = [len(r["bookmakers_with_data"]) for r in events_with_odds]
    prematch_rates = []
    for r in results:
        total = r["prematch_snapshots"] + r["post_commence_snapshots"]
        if total:
            prematch_rates.append(r["prematch_snapshots"] / total)
    last_gaps = [r["last_prematch_gap_hours"] for r in events_with_odds
                 if r["last_prematch_gap_hours"] is not None]
    price_changes = [r["price_changes"] for r in events_with_odds]
    n = len(results)
    metrics = {
        "SAMPLE_EVENTS": n,
        "EVENTS_WITH_ODDS": len(events_with_odds),
        "EVENTS_WITH_ODDS_RATE": round(len(events_with_odds) / n, 4) if n else None,
        "EVENT_MATCH_RATE": round(
            sum(1 for r in results if r["match"]["level"] == MatchLevel.NORMALIZED.value) / n, 4
        ) if n else None,
        "AMBIGUOUS_MATCH_RATE": round(
            sum(1 for r in results if r["match"]["level"] == MatchLevel.AMBIGUOUS.value) / n, 4
        ) if n else None,
        "UNMATCHED_RATE": round(
            sum(1 for r in results if r["match"]["level"] == MatchLevel.UNMATCHED.value) / n, 4
        ) if n else None,
        "SNAPSHOTS_PER_EVENT": {
            "min": min(snapshots_per_event) if snapshots_per_event else None,
            "median": _median([float(v) for v in snapshots_per_event]),
            "p90": _p90([float(v) for v in snapshots_per_event]),
            "max": max(snapshots_per_event) if snapshots_per_event else None,
        },
        "BOOKMAKERS_PER_EVENT": {
            "min": min(bookmakers_per_event) if bookmakers_per_event else None,
            "median": _median([float(v) for v in bookmakers_per_event]),
            "max": max(bookmakers_per_event) if bookmakers_per_event else None,
        },
        "VALID_PREMATCH_RATE": round(statistics.mean(prematch_rates), 4) if prematch_rates else None,
        "VALID_CLOSE_RATE": round(
            sum(1 for r in events_with_odds if r["last_prematch_gap_hours"] is not None
                and r["last_prematch_gap_hours"] <= 24.0) / len(events_with_odds), 4
        ) if events_with_odds else None,
        "LAST_PREMATCH_GAP_HOURS": {
            "min": min(last_gaps) if last_gaps else None,
            "median": _median(last_gaps),
            "p90": _p90(last_gaps),
            "max": max(last_gaps) if last_gaps else None,
        },
        "POST_COMMENCE_CONTAMINATION_RATE": round(
            1.0 - (statistics.mean(prematch_rates) if prematch_rates else 0.0), 4
        ),
        "MARKET_WINNER_COVERAGE": round(
            sum(1 for r in events_with_odds if r["market_winner_251"]) / len(events_with_odds), 4
        ) if events_with_odds else None,
        "OTHER_MARKETS_AVAILABLE": sorted(
            {m for r in events_with_odds for m in r["markets_seen"] if m != "251"}
        ),
        "PRICE_CHANGE_COUNT": {
            "min": min(price_changes) if price_changes else None,
            "median": _median([float(v) for v in price_changes]),
            "max": max(price_changes) if price_changes else None,
        },
        "MEDIAN_LINE_MOVES_PER_EVENT": _median([float(v) for v in price_changes]),
        "REQUESTS_USED_THIS_RUN": budget.used,
        "REQUESTS_USED_SPRINT_TOTAL": 4 + budget.used,
        "per_event": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    print(json.dumps({k: v for k, v in metrics.items() if k != "per_event"}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())