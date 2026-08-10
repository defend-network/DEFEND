"""Small SQLite persistence layer for the owner-only TableTennis panel."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parent

def _default_data_root() -> Path:
    configured = os.getenv("DEFEND_DATA_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        return Path(r"C:\DEFEND_DATA")
    return Path("./DEFEND_DATA").resolve()

LEGACY_DB_PATH = ROOT / "data" / "tabletennis.db"
DB_PATH = Path(
    os.getenv(
        "DEFEND_TT_DB",
        str(_default_data_root() / "db" / "tabletennis.db"),
    )
)
SCHEMA_PATH = ROOT / "tt_schema.sql"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_prefix() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as con:
        con.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        con.commit()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    init_db()
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def _rowdict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def add_event(event_type: str, message: str, match_id: str | None = None, payload: Any = None) -> int:
    with connect() as con:
        cur = con.execute(
            "INSERT INTO tt_events(ts,event_type,match_id,message,payload_json) VALUES(?,?,?,?,?)",
            (utcnow(), event_type, match_id, message, json.dumps(payload) if payload is not None else None),
        )
        return int(cur.lastrowid)


def add_manual_match(
    *,
    event_name: str,
    player_a: str,
    player_b: str,
    best_of: int = 5,
    sets_a: int = 0,
    sets_b: int = 0,
    points_a: int = 0,
    points_b: int = 0,
) -> dict[str, Any]:
    match_id = f"tt_manual_{uuid.uuid4().hex[:12]}"
    now = utcnow()
    with connect() as con:
        con.execute(
            """INSERT INTO matches(match_id,date,event_name,best_of,player_a_name,player_b_name,source)
               VALUES(?,?,?,?,?,?,?)""",
            (match_id, now, event_name, best_of, player_a, player_b, "manual"),
        )
        con.execute(
            """INSERT INTO live_snapshots(match_id,ts,sets_a,sets_b,points_a,points_b,server,raw_json)
               VALUES(?,?,?,?,?,?,?,?)""",
            (match_id, now, sets_a, sets_b, points_a, points_b, None, None),
        )
    add_event("manual_match", f"Added {player_a} vs {player_b}", match_id)
    return {
        "match_id": match_id,
        "event_name": event_name,
        "player_a": player_a,
        "player_b": player_b,
        "sets_a": sets_a,
        "sets_b": sets_b,
        "points_a": points_a,
        "points_b": points_b,
        "best_of": best_of,
        "status": "watching",
        "prob_2_0": None,
    }


def ensure_match(match_id: str, event_name: str = "Manual / unknown", player_a: str = "Player A", player_b: str = "Player B", best_of: int = 5) -> None:
    with connect() as con:
        row = con.execute("SELECT 1 FROM matches WHERE match_id=?", (match_id,)).fetchone()
        if row is None:
            con.execute(
                """INSERT INTO matches(match_id,date,event_name,best_of,player_a_name,player_b_name,source)
                   VALUES(?,?,?,?,?,?,?)""",
                (match_id, utcnow(), event_name, best_of, player_a, player_b, "panel"),
            )


def upsert_snapshot(match_id: str, *, sets_a: int, sets_b: int, points_a: int, points_b: int, raw_json: Any = None) -> None:
    ensure_match(match_id)
    with connect() as con:
        con.execute(
            """INSERT INTO live_snapshots(match_id,ts,sets_a,sets_b,points_a,points_b,raw_json)
               VALUES(?,?,?,?,?,?,?)""",
            (match_id, utcnow(), sets_a, sets_b, points_a, points_b, json.dumps(raw_json) if raw_json is not None else None),
        )


def list_live_matches(limit: int = 100) -> list[dict[str, Any]]:
    with connect() as con:
        rows = con.execute(
            """
            SELECT m.match_id, m.event_name, m.player_a_name, m.player_b_name, m.best_of,
                   s.sets_a, s.sets_b, s.points_a, s.points_b, s.ts
            FROM matches m
            LEFT JOIN live_snapshots s ON s.id = (
                SELECT s2.id FROM live_snapshots s2
                WHERE s2.match_id=m.match_id ORDER BY s2.ts DESC, s2.id DESC LIMIT 1
            )
            WHERE m.winner_id IS NULL
            ORDER BY COALESCE(s.ts,m.date) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    out = []
    for r in rows:
        out.append({
            "match_id": r["match_id"],
            "event_name": r["event_name"],
            "player_a": r["player_a_name"],
            "player_b": r["player_b_name"],
            "sets_a": int(r["sets_a"] or 0),
            "sets_b": int(r["sets_b"] or 0),
            "points_a": int(r["points_a"] or 0),
            "points_b": int(r["points_b"] or 0),
            "best_of": int(r["best_of"] or 5),
            "status": "watching",
            "prob_2_0": None,
        })
    return out


def log_bet(
    *,
    match_id: str,
    book: str,
    market: str,
    selection: str,
    odds: float,
    stake: float,
    evaluation: dict[str, Any] | None,
) -> dict[str, Any]:
    ensure_match(match_id)
    bet_id = f"bet_{uuid.uuid4().hex[:14]}"
    ev = evaluation or {}
    features = ev.get("features") or {}
    with connect() as con:
        con.execute(
            """INSERT INTO bets(
                bet_id,ts,match_id,book,market,selection,odds,stake,
                hard_pass,soft_score,model_adjust,final_score,decision,features_json,result,pnl
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL)""",
            (
                bet_id, utcnow(), match_id, book, market, selection, odds, stake,
                1 if ev.get("hard_pass") else 0,
                ev.get("soft_score"), ev.get("model_adjust"), ev.get("final_score"),
                ev.get("decision"), json.dumps(features),
            ),
        )
    add_event("bet_logged", f"Logged manual bet {bet_id}: {selection} @ {odds} stake {stake}", match_id, {"bet_id": bet_id})
    return {"bet_id": bet_id, "status": "open"}


def settle_bet(bet_id: str, *, result: str, pnl: float, closing_odds: float | None = None) -> dict[str, Any] | None:
    result = result.lower().strip()
    if result not in {"win", "loss", "void", "cashout"}:
        raise ValueError("result must be win, loss, void, or cashout")
    with connect() as con:
        row = con.execute("SELECT * FROM bets WHERE bet_id=?", (bet_id,)).fetchone()
        if row is None:
            return None
        con.execute(
            "UPDATE bets SET result=?, pnl=?, closing_odds=? WHERE bet_id=?",
            (result, float(pnl), closing_odds, bet_id),
        )
        match_id = row["match_id"]
    add_event("bet_settled", f"Settled {bet_id}: {result}, P/L {float(pnl):+.2f}", match_id, {"bet_id": bet_id, "result": result, "pnl": pnl})
    return {"bet_id": bet_id, "result": result, "pnl": float(pnl)}


def record_arb(match_id: str, arb: dict[str, Any]) -> None:
    ensure_match(match_id)
    with connect() as con:
        con.execute(
            "INSERT INTO arb_alerts(ts,match_id,edge_pct,legs_json) VALUES(?,?,?,?)",
            (utcnow(), match_id, float(arb["edge_pct"]), json.dumps(arb)),
        )
    add_event("arb_alert", f"Arbitrage alert {arb['edge_pct']}%", match_id, arb)


def metrics() -> dict[str, Any]:
    starting = float(os.getenv("DEFEND_TT_BANKROLL", "1000"))
    today = _today_prefix()
    with connect() as con:
        total_pnl = float(con.execute("SELECT COALESCE(SUM(pnl),0) FROM bets WHERE pnl IS NOT NULL").fetchone()[0])
        today_pnl = float(con.execute("SELECT COALESCE(SUM(pnl),0) FROM bets WHERE pnl IS NOT NULL AND ts LIKE ?", (today + "%",)).fetchone()[0])
        open_bets = int(con.execute("SELECT COUNT(*) FROM bets WHERE result IS NULL").fetchone()[0])
        settled = int(con.execute("SELECT COUNT(*) FROM bets WHERE result IS NOT NULL").fetchone()[0])
        wins = int(con.execute("SELECT COUNT(*) FROM bets WHERE result='win'").fetchone()[0])
        hard_total = int(con.execute("SELECT COUNT(*) FROM bets").fetchone()[0])
        hard_pass = int(con.execute("SELECT COUNT(*) FROM bets WHERE hard_pass=1").fetchone()[0])
        arb_today = int(con.execute("SELECT COUNT(*) FROM arb_alerts WHERE ts LIKE ?", (today + "%",)).fetchone()[0])
    return {
        "bankroll": round(starting + total_pnl, 2),
        "total_pnl": round(total_pnl, 2),
        "today_pnl": round(today_pnl, 2),
        "open_bets": open_bets,
        "settled_bets": settled,
        "win_rate": (wins / settled) if settled else None,
        "hard_pass_rate": (hard_pass / hard_total) if hard_total else None,
        "arb_alerts_today": arb_today,
    }


def recent_events(limit: int = 100) -> list[dict[str, Any]]:
    with connect() as con:
        rows = con.execute(
            "SELECT id,ts,event_type,match_id,message,payload_json FROM tt_events ORDER BY id DESC LIMIT ?",
            (max(1, min(limit, 500)),),
        ).fetchall()
    return [dict(r) for r in rows]
