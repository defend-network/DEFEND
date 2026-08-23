"""P3/P4: market-ruler research row construction + market baseline smoke.

Proves the market research row can be built for a small real sample:
OddsPapi historical-odds observations (archived evidence) joined to the
frozen M5 rating-history probabilities (read-only) and settled results.

Read-only: never writes to any database. Requires the sports corpus URL
(SPORTS_DATABASE_URL, or MARKETS_DATABASE_URL in this environment where the
corpus lives in the same local Postgres).

Emits docs/operations/TT_MARKET_RULER_SAMPLE_V1.json.
"""

from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from defend_integrations.matching import match_event

EVIDENCE = REPO / "docs" / "provider-contracts" / "oddspapi-empirical-2026-08-20.json"
PROBE = REPO / "docs" / "operations" / "TT_ODDSPAPI_PROBE_V1.json"
OUT = REPO / "docs" / "operations" / "TT_MARKET_RULER_SAMPLE_V1.json"
LEDGER_OUT = REPO / "docs" / "operations" / "TT_MARKET_RULER_LEDGER_V1.json"
DEEPEN_RUNS = {
    "mixed": REPO / "docs" / "operations" / "TT_ODDSPAPI_DEEPEN_V1.json",
    "onexbet": REPO / "docs" / "operations" / "TT_ODDSPAPI_DEEPEN_V1_1XBET.json",
}

EVENTS = [
    {
        "label": "r2_czech_1xbet",
        "league_key": "czech-liga-pro",
        "fixture_id": "id2503634973488400",
        "bookmaker": "1xbet",
        "market_id": "251",
        "outcome_home": "251",
        "outcome_away": "252",
    },
    {
        "label": "r3_cup_bet365",
        "league_key": "tt-cup",
        "fixture_id": "id2503212973530802",
        "bookmaker": "bet365",
        "market_id": "251",
        "outcome_home": "251",
        "outcome_away": "252",
    },
]

MIN_SAMPLE = 30


def _iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_evidence() -> dict[str, dict]:
    entries = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    by_label = {e["label"]: e for e in entries}
    return by_label


def load_fixture_meta() -> dict[str, dict]:
    probe = json.loads(PROBE.read_text(encoding="utf-8"))
    sample = probe["scores_sample"]
    by_id: dict[str, dict] = {}
    for key, bucket in sample.items():
        if not isinstance(bucket, dict):
            continue
        if bucket.get("fixtureId"):
            by_id[bucket["fixtureId"]] = bucket
            continue
        for entry in bucket.values():
            if isinstance(entry, dict) and entry.get("fixtureId"):
                by_id[entry["fixtureId"]] = entry
    return by_id


def load_canonical(cur) -> list[dict]:
    cur.execute(
        "SELECT event_key, league_key, home_participant_key, away_participant_key, "
        "home_score, away_score, completed_at FROM tt_match_results"
    )
    events = []
    for row in cur.fetchall():
        keys = [str(row[2]).split(":", 1)[-1], str(row[3]).split(":", 1)[-1]]
        events.append({
            "event_key": row[0],
            "competition": row[1],
            "participant_keys": keys,
            "commence_at": _utc(row[6]),
            "home_score": row[4],
            "away_score": row[5],
        })
    return events


def home_expected(cur, event_key: str) -> dict | None:
    cur.execute(
        "SELECT participant_key, expected, model_version, history_id FROM tt_rating_history "
        "WHERE event_key = %s ORDER BY ts LIMIT 2",
        (event_key,),
    )
    rows = cur.fetchall()
    home = next((r for r in rows if r[0] is not None), None)
    if not rows:
        return None
    first = rows[0]
    return {
        "expected": float(first[1]) if first[1] is not None else None,
        "model_version": first[2],
        "history_id": first[3],
        "participant_key": first[0],
        "row_count": len(rows),
    }


def outcome_timeline(market: dict, outcome_id: str) -> list[dict]:
    outcome = (market.get("outcomes") or {}).get(outcome_id) or {}
    snaps = []
    for players in (outcome.get("players") or {}).values():
        for snap in players or []:
            snaps.append({
                "ts": _iso(snap["createdAt"]),
                "price": float(snap["price"]),
            })
    return sorted(snaps, key=lambda s: s["ts"])


def price_at_or_before(timeline: list[dict], ts: datetime) -> float | None:
    best = None
    for snap in timeline:
        if snap["ts"] <= ts:
            best = snap["price"]
        else:
            break
    return best


def log_loss(p: float, y: int) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def build_ledger() -> dict:
    """Inclusion/exclusion disposition ledger for every candidate event that
    entered market evaluation (P3/P4). Read-only; never drops rows silently."""
    ruler = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    ledger_rows = []

    for spec in EVENTS:
        entry = EVIDENCE.read_text(encoding="utf-8")
        evidence_ref = f"{EVIDENCE.name}#{spec['label']}"
        included = (ruler.get("canonical_matches") or {}).get(spec["label"])
        if included:
            ledger_rows.append({
                "provider_event_id": spec["fixture_id"],
                "canonical_event_id": included["matched_event_key"],
                "disposition": "INCLUDED",
                "reason_code": "canonical match + M5 prediction + prematch odds available",
                "evidence_ref": evidence_ref,
                "evaluation_version": "MARKET_RULER_V1",
            })
        else:
            ledger_rows.append({
                "provider_event_id": spec["fixture_id"],
                "canonical_event_id": None,
                "disposition": "EXCLUDED_NO_CANONICAL_MATCH",
                "reason_code": "no deterministic canonical match (settlement lag)",
                "evidence_ref": evidence_ref,
                "evaluation_version": "MARKET_RULER_V1",
            })

    for run_name, run_path in DEEPEN_RUNS.items():
        run = json.loads(run_path.read_text(encoding="utf-8"))
        metrics = run.get("metrics", run)
        for event in metrics.get("per_event", []):
            if event.get("observations", 0) <= 0:
                ledger_rows.append({
                    "provider_event_id": event["fixture_id"],
                    "canonical_event_id": None,
                    "disposition": "EXCLUDED_OTHER",
                    "reason_code": "NO_HISTORICAL_ODDS_AVAILABLE (provider returned no odds history)",
                    "evidence_ref": f"{run_path.name}#{event['fixture_id']}",
                    "evaluation_version": "MARKET_RULER_V1",
                })
                continue
            match = event.get("match") or {}
            level = match.get("level")
            matched_key = match.get("matched_event_key")
            prematch = event.get("prematch_snapshots", 0)
            markets = event.get("markets_seen") or []
            if level == "AMBIGUOUS":
                disposition, reason = "EXCLUDED_AMBIGUOUS_MATCH", "multiple canonical candidates; fails closed"
            elif level != "EXACT_ID" and level != "NORMALIZED" and level != "IDENTITY_MAP" and level != "PARTICIPANT_ID":
                disposition, reason = "EXCLUDED_NO_CANONICAL_MATCH", "no deterministic canonical candidate"
            elif prematch == 0:
                disposition, reason = "EXCLUDED_POSTCOMMENCE_ONLY", "no prematch snapshots (post-commence only)"
            elif "251" not in markets:
                disposition, reason = "EXCLUDED_INVALID_MARKET", "match-winner market not identifiable (market ids vary)"
            else:
                disposition, reason = "INCLUDED", "canonical + prematch + match-winner market"
            ledger_rows.append({
                "provider_event_id": event["fixture_id"],
                "canonical_event_id": matched_key,
                "disposition": disposition,
                "reason_code": reason,
                "evidence_ref": f"{run_path.name}#{event['fixture_id']}",
                "evaluation_version": "MARKET_RULER_V1",
            })

    return {
        "schema": "P3/P4 market-ruler inclusion/exclusion ledger",
        "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "evaluation_version": "MARKET_RULER_V1",
        "policy": "every candidate event entering market evaluation receives a persistent "
            "machine-readable disposition; rows are never silently dropped",
        "disposition_codes": [
            "INCLUDED", "EXCLUDED_NO_CANONICAL_MATCH", "EXCLUDED_AMBIGUOUS_MATCH",
            "EXCLUDED_NO_M5_PREDICTION", "EXCLUDED_NO_PREMATCH_ODDS",
            "EXCLUDED_POSTCOMMENCE_ONLY", "EXCLUDED_INVALID_MARKET",
            "EXCLUDED_RESULT_UNAVAILABLE", "EXCLUDED_IDENTITY_CONFLICT", "EXCLUDED_OTHER"],
        "rows": ledger_rows,
    }


def main() -> int:
    if "--ledger-only" in sys.argv:
        ledger = build_ledger()
        LEDGER_OUT.write_text(
            json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        included = sum(1 for r in ledger["rows"] if r["disposition"] == "INCLUDED")
        print(f"wrote {LEDGER_OUT} (rows={len(ledger['rows'])}, included={included})")
        return 0

    url = os.environ.get("SPORTS_DATABASE_URL") or os.environ.get("MARKETS_DATABASE_URL")
    if not url:
        print("SPORTS_DATABASE_URL (or MARKETS_DATABASE_URL) required")
        return 2

    import psycopg

    evidence = load_evidence()
    fixture_meta = load_fixture_meta()
    conn = psycopg.connect(url, connect_timeout=5)
    cur = conn.cursor()
    canonical = load_canonical(cur)

    rows_out: list[dict] = []
    matches: dict[str, dict] = {}

    for spec in EVENTS:
        entry = evidence.get(spec["label"])
        if not entry or entry.get("status") != 200:
            print(f"{spec['label']}: evidence missing or non-200")
            continue
        body = json.loads(entry["body"])
        market = (body.get("bookmakers") or {}).get(spec["bookmaker"], {}).get("markets", {}).get(spec["market_id"])
        if not market:
            print(f"{spec['label']}: market {spec['market_id']} not found in evidence")
            continue
        meta = fixture_meta.get(spec["fixture_id"])
        if not meta:
            print(f"{spec['label']}: fixture metadata missing")
            continue

        participants = list(meta["participants"])
        commence = _iso(meta["startTime"])
        result = match_event(
            provider_event_id=spec["fixture_id"],
            provider_prefix="oddspapi",
            participants=participants,
            competition=spec["league_key"],
            commence_at=meta["startTime"],
            canonical_events=canonical,
        )
        if result.level.value not in ("EXACT_ID", "NORMALIZED", "IDENTITY_MAP", "PARTICIPANT_ID"):
            retry = match_event(
                provider_event_id=spec["fixture_id"],
                provider_prefix="oddspapi",
                participants=participants,
                competition=None,
                commence_at=meta["startTime"],
                canonical_events=canonical,
            )
            if retry.level.value == "NORMALIZED":
                result = retry
            else:
                print(f"{spec['label']}: canonical match {result.level.value} "
                      f"(competition retry {retry.level.value}) ({result.note})")
                continue
        matches[spec["label"]] = result.to_dict()

        m5 = home_expected(cur, result.matched_event_key)
        home_won = bool(meta["result"]["participant1Score"] > meta["result"]["participant2Score"])

        home_tl = outcome_timeline(market, spec["outcome_home"])
        away_tl = outcome_timeline(market, spec["outcome_away"])
        prematch_home = [s for s in home_tl if s["ts"] < commence]
        prematch_away = [s for s in away_tl if s["ts"] < commence]
        all_prematch_ts = sorted({s["ts"] for s in prematch_home} | {s["ts"] for s in prematch_away})
        if not all_prematch_ts:
            print(f"{spec['label']}: no prematch snapshots")
            continue

        classes = {
            "OPEN": all_prematch_ts[0],
            "INTERMEDIATE": all_prematch_ts[len(all_prematch_ts) // 2],
            "LAST_VALID_PREMATCH": all_prematch_ts[-1],
        }
        for obs_class, obs_ts in classes.items():
            p_a = price_at_or_before(home_tl, obs_ts)
            p_b = price_at_or_before(away_tl, obs_ts)
            if p_a is None or p_b is None:
                continue
            ip_a = 1 / p_a
            ip_b = 1 / p_b
            total = ip_a + ip_b
            rows_out.append({
                "canonical_event_id": result.matched_event_key,
                "commence_ts": _utc(commence),
                "player_a": participants[0],
                "player_b": participants[1],
                "m5_probability": m5["expected"] if m5 else None,
                "bookmaker": spec["bookmaker"],
                "raw_decimal_odds_a": p_a,
                "raw_decimal_odds_b": p_b,
                "raw_implied_p_a": round(ip_a, 6),
                "raw_implied_p_b": round(ip_b, 6),
                "overround": round(total - 1, 6),
                "no_vig_market_p_a": round(ip_a / total, 6),
                "no_vig_market_p_b": round(ip_b / total, 6),
                "observation_ts": _utc(obs_ts),
                "seconds_before_commence": int((commence - obs_ts).total_seconds()),
                "market_observation_class": obs_class,
                "actual_result": "home_won" if home_won else "away_won",
                "raw_market_ref": f"{EVIDENCE.name}#{spec['label']}@market {spec['market_id']}",
                "m5_feature_snapshot_ref": (
                    f"tt_rating_history.history_id={m5['history_id']}" if m5 else None),
                "model_version": m5["model_version"] if m5 else None,
            })

    conn.close()

    if not rows_out:
        print("no rows constructed")
        return 1

    outcome_actual = {"home_won": 1.0, "away_won": 0.0}
    m5_errors = []
    market_errors = []
    matched_n = 0
    for row in rows_out:
        if row["market_observation_class"] != "LAST_VALID_PREMATCH":
            continue
        if row["m5_probability"] is None:
            continue
        y = outcome_actual[row["actual_result"]]
        p_m5 = row["m5_probability"]
        p_mkt = row["no_vig_market_p_a"]
        m5_errors.append((p_m5 - y) ** 2)
        market_errors.append((p_mkt - y) ** 2)
        m5_ll = log_loss(p_m5, y)
        mkt_ll = log_loss(p_mkt, y)
        row["m5_log_loss_row"] = round(m5_ll, 6)
        row["market_log_loss_row"] = round(mkt_ll, 6)
        matched_n += 1

    m5_brier = sum(m5_errors) / len(m5_errors) if m5_errors else None
    market_brier = sum(market_errors) / len(market_errors) if market_errors else None

    document = {
        "schema": "P3 market-ruler sample + P4 market baseline smoke",
        "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "evidence_source": EVIDENCE.name,
        "probe_source": PROBE.name,
        "database": "read-only (tt_match_results, tt_rating_history)",
        "canonical_matches": matches,
        "excluded_events": [
            {
                "label": "r3_cup_bet365",
                "reason": "canonical event not in corpus (settlement lag; probe found 28/40 "
                          "recent-era matches); odds evidence intact but no M5 join possible",
            },
        ],
        "M5_MARKET_MATCHED_N": matched_n,
        "M5_BRIER": round(m5_brier, 6) if m5_brier is not None else None,
        "MARKET_BRIER": round(market_brier, 6) if market_brier is not None else None,
        "M5_LOG_LOSS": round(sum(m5_ll for r in rows_out if "m5_log_loss_row" in r) / matched_n, 6) if matched_n else None,
        "MARKET_LOG_LOSS": round(sum(r["market_log_loss_row"] for r in rows_out if "market_log_loss_row" in r) / matched_n, 6) if matched_n else None,
        "M5_MINUS_MARKET_BRIER": round(m5_brier - market_brier, 6) if (m5_brier is not None and market_brier is not None) else None,
        "MARKET_BASELINE_STATUS": (
            "INFRASTRUCTURE_READY_INSUFFICIENT_SAMPLE" if matched_n < MIN_SAMPLE
            else "COMPUTED"),
        "notes": f"N={matched_n} < {MIN_SAMPLE}: Brier/log-loss reported as RESEARCH_PRELIMINARY "
                 "only; TRUE_CLOSE unavailable (no closing feed), LAST_VALID_PREMATCH used as "
                 "best available reference",
        "rows": rows_out,
    }
    OUT.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    print(f"rows={len(rows_out)} matched_n={matched_n} "
          f"m5_brier={document['M5_BRIER']} market_brier={document['MARKET_BRIER']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())