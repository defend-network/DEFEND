"""P2 owner-approved identity merges (reversible canonicalization).

Merges ONLY the three high-confidence pairs whose identity evidence is a
shared Odds-API.io provider participant ID with no contradictory evidence:

    M1  Havel, Ladislav          <-> Havel, Ladislav (1956)   id 899515
    M2  Bayer, Ales              <-> Bayer, Alesh             id 728577
    M3  Sebl, Jachym             <-> Sebl                     id 941929

Mechanism (reversible canonicalization, never rewrites tt_match_results):
  - resolve() the canonical variant through IdentityService (creates the
    canonical tt_participants row on first run)
  - confirm_alias() attaches each variant spelling as an explicit alias row
    in tt_participant_aliases with provider='odds_api_io' and the shared
    provider ID as raw_ref evidence, then marks the participant CONFIRMED
  - reverse = DELETE the alias rows (documented per merge in the artifact)

BENCHMARK_V1 inputs (tt_match_results, tt_rating_history, event labels) are
NOT modified. Impact is measured and reported separately.

Usage: python tools/defend_tt_identity_merge.py [--dry-run]
Requires MARKETS_DATABASE_URL.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from defend_markets.db import MarketsDatabase
from defend_markets.feeds import participant_key
from defend_markets.forecast_store import PostgresForecastStore
from defend_markets.identity import IdentityService, normalize_participant_name

ARTIFACT_PATH = (
    Path(__file__).resolve().parents[1] / "docs" / "operations" / "TT_IDENTITY_MERGES_V1.json"
)

MERGES = (
    {
        "merge_id": "M1",
        "canonical_name": "Havel, Ladislav",
        "aliases": ("Havel, Ladislav (1956)",),
        "provider": "odds_api_io",
        "provider_participant_id": "899515",
    },
    {
        "merge_id": "M2",
        "canonical_name": "Bayer, Ales",
        "aliases": ("Bayer, Alesh",),
        "provider": "odds_api_io",
        "provider_participant_id": "728577",
    },
    {
        "merge_id": "M3",
        "canonical_name": "Sebl, Jachym",
        "aliases": ("Sebl",),
        "provider": "odds_api_io",
        "provider_participant_id": "941929",
    },
)


def _variant_keys(merge: dict) -> list[str]:
    keys = [participant_key("table_tennis", merge["canonical_name"])]
    keys += [participant_key("table_tennis", alias) for alias in merge["aliases"]]
    return keys


def _impact(database: MarketsDatabase) -> dict:
    with database.connect() as connection, connection.cursor() as cursor:
        impact = {}
        for merge in MERGES:
            keys = _variant_keys(merge)
            cursor.execute(
                """
                SELECT COUNT(*) FROM tt_match_results
                WHERE home_participant_key = ANY(%s) OR away_participant_key = ANY(%s)
                """,
                (keys, keys),
            )
            total = cursor.fetchone()[0]
            per_key = {}
            for key in keys:
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM tt_match_results
                    WHERE home_participant_key = %s OR away_participant_key = %s
                    """,
                    (key, key),
                )
                per_key[key] = cursor.fetchone()[0]
            impact[merge["merge_id"]] = {
                "participant_keys": keys,
                "rows_per_key": per_key,
                "rows_any_variant": total,
            }
        cursor.execute("SELECT COUNT(*) FROM tt_match_results")
        impact["_tt_match_results_total"] = cursor.fetchone()[0]
    return impact


def run(database: MarketsDatabase, dry_run: bool) -> dict:
    store = PostgresForecastStore(database)
    service = IdentityService(store, clock=lambda: datetime.now(timezone.utc))
    applied_at = datetime.now(timezone.utc).isoformat()

    entries = []
    for merge in MERGES:
        participant = service.resolve(
            merge["canonical_name"], provider=merge["provider"]
        )
        aliases = []
        for alias in merge["aliases"]:
            aliases.append(
                {
                    "alias_name": alias,
                    "normalized_name": normalize_participant_name(alias),
                }
            )
            if not dry_run:
                service.confirm_alias(
                    int(participant["participant_id"]),
                    alias_name=alias,
                    provider=merge["provider"],
                    raw_ref=merge["provider_participant_id"],
                )
        entries.append(
            {
                "merge_id": merge["merge_id"],
                "canonical_name": merge["canonical_name"],
                "normalized_name": participant["normalized_name"],
                "participant_id": participant["participant_id"],
                "identity_state_after": "CONFIRMED" if not dry_run else participant["identity_state"],
                "aliases": aliases,
                "reason_code": "SHARED_PROVIDER_ID",
                "provider": merge["provider"],
                "evidence": {
                    "shared_provider_participant_id": merge["provider_participant_id"]
                },
                "reverse_if": "DELETE the alias rows for this participant from tt_participant_aliases",
            }
        )

    impact = _impact(database)

    if not dry_run:
        artifact = {
            "artifact": "TT_IDENTITY_MERGES_V1",
            "policy": "TT_IDENTITY_POLICY_V1 (reversible canonicalization via tt_participant_aliases)",
            "applied_at": applied_at,
            "benchmark_note": "BENCHMARK_V1 inputs (tt_match_results, tt_rating_history, labels) are NOT modified; impact measured only",
            "merges": entries,
            "impact": impact,
        }
        ARTIFACT_PATH.write_text(
            json.dumps(artifact, indent=2, sort_keys=True, default=str), encoding="utf-8"
        )
    return {"entries": entries, "impact": impact, "dry_run": dry_run}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="resolve + report only")
    args = parser.parse_args()

    url = os.environ.get("MARKETS_DATABASE_URL")
    if not url:
        print("MARKETS_DATABASE_URL is required", file=sys.stderr)
        return 2
    database = MarketsDatabase(url)
    result = run(database, dry_run=args.dry_run)
    print(json.dumps(result, indent=2, default=str))
    if not args.dry_run:
        print(f"artifact written: {ARTIFACT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())