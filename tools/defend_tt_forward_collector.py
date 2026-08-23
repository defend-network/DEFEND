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
        self.last_request_count = 0

    def fetch_fixtures(self, *, from_iso: str, to_iso: str) -> tuple[int | None, Any, bool]:
        self.last_request_count = 1
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
        self.last_request_count = 1
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


_OAIO_BASE = "https://api.odds-api.io/v3"

# Odds-API.io discovery responses are hard-capped at 16384 bytes like OddsPapi.
# Bookmaker selection is account-scoped; the exact labels below were attested
# through /v3/bookmakers/selected. /v3/events may omit embedded odds, so a
# pending event must still receive a per-event /odds request.
# Account-selected Solo bookmaker labels returned by
# /v3/bookmakers/selected. Keep the exact provider spelling; the endpoint
# accepts these labels as the bookmaker query values.
_OAIO_SELECTED_BOOKMAKERS = ("Sbobet", "SingBet")


def _oaio_event_to_fixture(event: dict[str, Any]) -> dict[str, Any]:
    league = event.get("league") or {}
    return {
        "sportId": 25,
        "fixtureId": str(event.get("id", "")),
        "tournamentName": str(league.get("name") or ""),
        "participant1Name": str(event.get("home") or ""),
        "participant2Name": str(event.get("away") or ""),
        "startTime": str(event.get("date") or ""),
        "statusName": str(event.get("status") or ""),
        "hasOdds": bool(event.get("bookmakers")),
        "raw_provider": "odds_api_io",
    }


def _oaio_price(value: Any) -> float | None:
    """Odds-API.io returns decimal odds as strings; engine parser needs floats."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _oaio_odds_to_oddspapi_shape(event: dict[str, Any]) -> dict[str, Any]:
    """Normalize /v3/odds event payload into the OddsPapi /odds shape.

    Odds-API.io markets are flat: {bookmakers: {name: [{name, odds:
    [{home, away, ...}]}]}}. We keep only 2-way match-winner markets and
    rekey them into the nested markets/outcomes/players shape that
    parse_oddspapi_odds consumes, using the participant names as player keys.
    """
    bookmakers: dict[str, Any] = {}
    home_name = str(event.get("home") or "")
    away_name = str(event.get("away") or "")
    for bname, markets in (event.get("bookmakers") or {}).items():
        winner_markets: list[dict[str, Any]] = []
        for market in markets or []:
            name = str(market.get("name") or "")
            if name.upper() not in {"ML", "MONEYLINE", "MONEY LINE", "MATCH WINNER", "1X2"}:
                continue
            home_price = away_price = None
            for entry in market.get("odds") or []:
                if not isinstance(entry, dict):
                    continue
                if entry.get("home") is not None:
                    home_price = entry.get("home")
                if entry.get("away") is not None:
                    away_price = entry.get("away")
            players: dict[str, Any] = {}
            if home_price is not None and home_name:
                players[home_name] = {"price": _oaio_price(home_price)}
            if away_price is not None and away_name:
                players[away_name] = {"price": _oaio_price(away_price)}
            if players:
                updated_at = market.get("updatedAt")
                winner_markets.append(
                    {"outcomes": {"winner": {"players": players}},
                     "updatedAt": updated_at}
                )
        if winner_markets:
            bookmakers[str(bname)] = {
                "markets": {f"m{i}": m for i, m in enumerate(winner_markets)}
            }
    return {"fixtureId": str(event.get("id", "")), "bookmakers": bookmakers}


class OddsApiIOLiveClient:
    """Odds-API.io live client, normalized to the engine's OddsPapi shape.

    Discovery uses /v3/events (sport=table-tennis, from/to window); odds use
    /v3/odds per event with the account's selected bookmakers. Responses are
    stored redacted via probe_get; truncated bodies are prefix-recovered.
    """

    def __init__(self, key: str) -> None:
        self._key = key
        self._secrets = (key,)
        self._events: dict[str, dict[str, Any]] = {}
        self.last_request_count = 0

    def _bookmakers_param(self) -> str:
        return ",".join(_OAIO_SELECTED_BOOKMAKERS)

    def fetch_fixtures(self, *, from_iso: str, to_iso: str) -> tuple[int | None, Any, bool]:
        """Two sweeps per call: upcoming events plus a recent settled slice.

        The canonical corpus is frozen at the M5 cutoff but is refreshed by
        the Phase C backfill loader; /v3/events retention only serves the last
        few days, so the second sweep targets yesterday's settled events
        (EXACT_ID by provider event id once the refresh covers them).
        """
        self.last_request_count = 2
        url = (
            f"{_OAIO_BASE}/events?sport=table-tennis&from={from_iso}&to={to_iso}"
            f"&apiKey={self._key}"
        )
        result, evidence, parsed = probe_get(
            "odds_api_io", "events", url,
            known_secrets=self._secrets,
            headers=_WAF_HEADERS,
            max_response_bytes=8 * 1024 * 1024,
        )
        payload, recovered = parse_recovered_json(evidence.body or "")
        if payload is None:
            payload = parsed
        fixtures: list[dict[str, Any]] = []
        if isinstance(payload, list):
            for event in payload:
                if not isinstance(event, dict) or (event.get("sport") or {}).get("slug") != "table-tennis":
                    continue
                self._events[str(event.get("id"))] = event
                fixtures.append(_oaio_event_to_fixture(event))
        try:
            base_from = datetime.fromisoformat(from_iso.replace("Z", "+00:00"))
            recent_from = base_from - timedelta(hours=24)
            recent_to = base_from - timedelta(hours=22)
        except ValueError:
            recent_from = recent_to = None
        if recent_from is not None:
            url2 = (
                f"{_OAIO_BASE}/events?sport=table-tennis"
                f"&from={recent_from.isoformat().replace('+00:00', 'Z')}"
                f"&to={recent_to.isoformat().replace('+00:00', 'Z')}"
                f"&apiKey={self._key}"
            )
            result2, evidence2, parsed2 = probe_get(
                "odds_api_io", "events-settled", url2,
                known_secrets=self._secrets,
                headers=_WAF_HEADERS,
                max_response_bytes=8 * 1024 * 1024,
            )
            payload2, _recovered2 = parse_recovered_json(evidence2.body or "")
            if payload2 is None:
                payload2 = parsed2
            if isinstance(payload2, list):
                for event in payload2:
                    if not isinstance(event, dict) or (event.get("sport") or {}).get("slug") != "table-tennis":
                        continue
                    self._events[str(event.get("id"))] = event
                    fixtures.append(_oaio_event_to_fixture(event))
        return result.status_code, fixtures, recovered

    def fetch_odds(self, provider_event_id: str) -> tuple[int | None, Any, bool]:
        event = self._events.get(provider_event_id)
        if event is not None and event.get("status") == "settled" and not event.get("bookmakers"):
            self.last_request_count = 0
            return 200, {"fixtureId": provider_event_id, "bookmakers": {}}, False
        self.last_request_count = 1
        url = (
            f"{_OAIO_BASE}/odds?eventId={provider_event_id}"
            f"&bookmakers={self._bookmakers_param()}&markets=ML&apiKey={self._key}"
        )
        result, evidence, parsed = probe_get(
            "odds_api_io", "odds", url,
            known_secrets=self._secrets,
            headers=_WAF_HEADERS,
            max_response_bytes=8 * 1024 * 1024,
        )
        payload, recovered = parse_recovered_json(evidence.body or "")
        if isinstance(payload, dict) and payload.get("bookmakers") is None and isinstance(parsed, dict):
            payload = parsed
        if isinstance(payload, dict):
            self._events[provider_event_id] = payload
            return result.status_code, _oaio_odds_to_oddspapi_shape(payload), recovered
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
        canonical_participants = [str(hk or ""), str(ak or "")]
        out[str(event_key)] = {
            "event_key": str(event_key),
            # match_event expects this shape (participant_keys, competition,
            # commence_at, provider_event_id); previously home/away keys were
            # emitted under names matching never reads, so EVENTS_MATCHED was
            # structurally 0 even when the corpus contained the event.
            "provider_event_id": str(event_key).removeprefix("oaio:"),
            # Stored M5 keys are namespaced (table_tennis:<player>). Matching
            # compares provider names, while the engine persists these full
            # keys so history lookup uses the same identity as the corpus.
            "participant_keys": [
                value.removeprefix("table_tennis:")
                for value in canonical_participants
            ],
            "canonical_participant_keys": canonical_participants,
            "competition": league_key,
            "commence_at": ts.isoformat() if ts else None,
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
    provider = os.environ.get("TT_FORWARD_PROVIDER", "oddspapi")
    if provider == "odds_api_io":
        key = reg.get("ODDS_API_IO_API_KEY")
        if not key:
            raise SystemExit("ODDS_API_IO_API_KEY missing (DPAPI store or env)")
        client: Any = OddsApiIOLiveClient(key)
    else:
        key = reg.get("ODDSPAPI_API_KEY")
        if not key:
            raise SystemExit("ODDSPAPI_API_KEY missing (DPAPI store or env)")
        client = OddspapiLiveClient(key)
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
        client=client,
        settled=settled_reader(db_url),
        provider_label=provider,
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
