"""Phase D forward collector: one shadow cycle (P0-P5) against live providers.

Usage:
    python tools/defend_tt_forward_collector.py --cycles N --interval SECONDS
    python tools/defend_tt_forward_collector.py --once            # single cycle

Reads ODDSPAPI_API_KEY via the DPAPI SecretRegistry (env override first),
MARKETS_DATABASE_URL for persistence. Never bets; M5 stays frozen.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import psycopg

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from defend_integrations.probing import probe_get  # noqa: E402
from defend_integrations.stores import (  # noqa: E402
    SecretRegistry,
    default_secret_path,
)
from defend_control.secrets import DpapiSecretStore  # noqa: E402
from defend_markets.db import MarketsDatabase  # noqa: E402
from defend_markets.m5_live import FrozenM5, M5Match, M5StateBuilder  # noqa: E402
from defend_markets.shadow import parse_recovered_json  # noqa: E402
from defend_markets.shadow_engine import OddsClient, ShadowEngine  # noqa: E402
from defend_markets.shadow_store import PostgresShadowStore  # noqa: E402

_ODDSPAPI_BASE = "https://api.oddspapi.io/v4"

# OddsPapi sits behind a Cloudflare WAF that returns error 1010 for generic
# client UAs; the free tier also 429s after a few requests. A browser-like UA
# is required to reach the fixtures/odds endpoints at all.
_WAF_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}


class OddspapiLiveClient:
    """Live OddsPapi client; every response is stored redacted via probe_get."""

    def __init__(self, key: str) -> None:
        self._key = key
        self._secrets = (key,)

    def fetch_fixtures(self, *, from_iso: str, to_iso: str) -> tuple[int | None, Any, bool]:
        url = (
            f"{_ODDSPAPI_BASE}/fixtures?sportId=25&from={from_iso}&to={to_iso}"
            f"&apiKey={self._key}"
        )
        result, evidence, parsed = probe_get(
            "oddspapi", "fixtures", url,
            known_secrets=self._secrets,
            headers=_WAF_HEADERS,
            max_response_bytes=8 * 1024 * 1024,
        )
        payload, recovered = parse_recovered_json(evidence.body or "")
        if payload is None:
            payload = parsed
        return result.status_code, payload, recovered

def fetch_odds(self, provider_event_id: str) -> tuple[int | None, Any, bool]:
        url = f"{_ODDSPAPI_BASE}/odds?fixtureId={provider_event_id}&apiKey={self._key}"
        result, evidence, parsed = probe_get(
            "oddspapi", "odds", url,
            known_secrets=self._secrets,
            headers=_WAF_HEADERS,
            max_response_bytes=8 * 1024 * 1024,
        )
        payload, recovered = parse_recovered_json(evidence.body or "")
        if payload is None:
            payload = parsed
        return result.status_code, payload, recovered


def canonical_events_map(db_url: str) -> dict[str, dict[str, Any]]:
    conn = psycopg.connect(db_url, connect_timeout=5)
    try:
        rows = conn.execute(
            "select event_key, league_key, home_participant_key, away_participant_key, "
            "completed_at from tt_match_results "
            "where source_provider='odds_api_io' and completed_at is not null"
        ).fetchall()
    finally:
        conn.close()
    out: dict[str, dict[str, Any]] = {}
    for event_key, league_key, hk, ak, ts in rows:
        out[str(event_key)] = {
            "event_key": str(event_key),
            "league_key": league_key,
            "home_participant_key": hk,
            "away_participant_key": ak,
            "completed_at": ts,
        }
    return out


def settled_reader(db_url: str):
    def _reader(canonical_event_id: str) -> dict[str, Any] | None:
        conn = psycopg.connect(db_url, connect_timeout=5)
        try:
            row = conn.execute(
                "select result_id, home_score, away_score, completed_at "
                "from tt_match_results where event_key = %s "
                "and home_score is not null and away_score is not null limit 1",
                (canonical_event_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        result_id, hs, aws, completed_at = row
        actual = 1.0 if (hs or 0) > (aws or 0) else 0.0
        return {
            "result_id": int(result_id),
            "actual": actual,
            "settled_at": completed_at,
        }

    return _reader


def load_state_builder(db_url: str) -> M5StateBuilder:
    conn = psycopg.connect(db_url, connect_timeout=5)
    try:
        rows = conn.execute(
            "select event_key, home_participant_key, away_participant_key, "
            "home_score, away_score, completed_at from tt_match_results "
            "where source_provider='odds_api_io' and completed_at is not null "
            "order by completed_at asc, event_key asc"
        ).fetchall()
    finally:
        conn.close()
    matches: list[M5Match] = []
    for event_key, hk, ak, hs, aws, ts in rows:
        if hk is None or ak is None or hs is None or aws is None or hs == aws:
            continue
        matches.append(
            M5Match(
                event_key=str(event_key),
                home_key=hk,
                away_key=ak,
                ts=ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc),
                actual=1.0 if hs > aws else 0.0,
            )
        )
    print(f"M5 state replay: {len(matches)} matches")
    return M5StateBuilder(matches)


def build_engine() -> ShadowEngine:
    reg = SecretRegistry(DpapiSecretStore(default_secret_path()))
    key = reg.get("ODDSPAPI_API_KEY")
    if not key:
        raise SystemExit("ODDSPAPI_API_KEY missing (DPAPI store or env)")
    db_url = os.environ.get("MARKETS_DATABASE_URL")
    if not db_url:
        raise SystemExit("MARKETS_DATABASE_URL is required")
    db = MarketsDatabase(db_url)
    db.migrate()
    m5_doc = json.loads(
        (REPO / "docs/operations/TT_M5_LIVE_WEIGHTS_V1.json").read_text(encoding="utf-8")
    )
    m5 = FrozenM5(m5_doc, source_ref="docs/operations/TT_M5_LIVE_WEIGHTS_V1.json")
    engine = ShadowEngine(
        store=PostgresShadowStore(db),
        m5=m5,
        client=OddspapiLiveClient(key),
        settled=settled_reader(db_url),
    )
    engine.set_state_builder(load_state_builder(db_url))
    return engine


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--interval", type=float, default=45.0)
    parser.add_argument("--output", default=None)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    engine = build_engine()
    canonical = canonical_events_map(
        os.environ["MARKETS_DATABASE_URL"]
    )
    print(f"canonical events loaded: {len(canonical)}")
    cycles = 1 if args.once else args.cycles
    results: list[dict[str, Any]] = []
    for index in range(cycles):
        if index:
            time.sleep(args.interval)
        metrics = engine.run_cycle(canonical_events=canonical)
        results.append(metrics)
        print(json.dumps(metrics, indent=2))
    out = Path(args.output) if args.output else (
        REPO / "docs/operations/TT_FORWARD_CYCLE_RESULTS_V1.json"
    )
    out.write_text(
        json.dumps(
            {"schema": "TT_FORWARD_CYCLE_RESULTS", "cycles": results, "count": len(results)},
            ensure_ascii=False, indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())