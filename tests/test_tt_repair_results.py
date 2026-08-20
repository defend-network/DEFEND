"""Regression tests for the TT label repair flow (P1).

Locks the exact bug class that occurred in production: the repair step once
built TTMatchResult rows keyed by the raw provider_event_id (which carries an
@hist:<date> suffix) instead of the canonical stored event_key, inserting a
second duplicate row per repaired event while leaving the original wrong
label in place.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

from defend_markets.domain import TTMatchResult
from defend_sports.providers.odds_api_io import parse_tt_final_result
from tools.defend_tt_repair_results import build_plan, collect_repair_results

CANONICAL_KEY = "oaio:123"
RAW_KEY = "oaio:123@hist:20260213"
LEAGUE = "czech-republic-czech-liga-pro"
HOME = "table_tennis:homeplayer"
AWAY = "table_tennis:awayplayer"
COMPLETED_AT = datetime(2026, 2, 13, 12, 0, 0, tzinfo=timezone.utc)


def _payload() -> dict[str, object]:
    return {
        "id": 123,
        "home": "Home Player",
        "away": "Away Player",
        "status": "settled",
        "scores": {
            "home": 11,
            "away": 8,
            "periods": {
                "ft": {"home": 3, "away": 1},
                "p1": {"home": 11, "away": 6},
                "p2": {"home": 9, "away": 11},
                "p3": {"home": 11, "away": 8},
                "p4": {"home": 11, "away": 5},
            },
        },
    }


def _stored_row(home_score: int = 8, away_score: int = 11) -> tuple:
    return (
        CANONICAL_KEY,
        LEAGUE,
        HOME,
        AWAY,
        home_score,
        away_score,
        COMPLETED_AT,
        "odds_api_io",
        RAW_KEY,
    )


def _raw_rows() -> list[tuple[str, object]]:
    return [(RAW_KEY, _payload())]


def test_plan_targets_the_canonical_existing_result():
    report = build_plan(_raw_rows(), [_stored_row()])
    assert report["OLD_LABELS_CHANGED"] == 1
    (change,) = report["changes"]
    assert change["event_key"] == RAW_KEY
    assert (change["old_home_score"], change["old_away_score"]) == (8, 11)
    assert (change["new_home_score"], change["new_away_score"]) == (3, 1)
    assert change["new_winner"] == "HOME"
    assert change["old_winner"] == "AWAY"


def test_repair_updates_intended_canonical_result():
    results = collect_repair_results(build_plan(_raw_rows(), [_stored_row()]), [_stored_row()], _raw_rows())
    assert len(results) == 1
    result = results[0]
    assert result.event_key == CANONICAL_KEY
    assert result.raw_ref == RAW_KEY
    assert result.league_key == LEAGUE
    assert result.home_participant_key == HOME
    assert result.away_participant_key == AWAY
    assert result.source_provider == "odds_api_io"
    assert result.completed_at == COMPLETED_AT


def test_repair_does_not_create_a_second_event():
    stored = [_stored_row()]
    results = collect_repair_results(build_plan(_raw_rows(), stored), stored, _raw_rows())
    assert len(results) == 1
    assert results[0].event_key == CANONICAL_KEY
    assert not results[0].event_key.endswith("@hist:")


def test_repaired_label_equals_canonical_parser_output():
    parsed = parse_tt_final_result(_payload())
    results = collect_repair_results(build_plan(_raw_rows(), [_stored_row()]), [_stored_row()], _raw_rows())
    assert (results[0].home_score, results[0].away_score) == (parsed.home_score, parsed.away_score)
    assert (results[0].home_score, results[0].away_score) == (3, 1)


def test_repeated_repair_is_idempotent():
    stored = [_stored_row()]
    first = collect_repair_results(build_plan(_raw_rows(), stored), stored, _raw_rows())
    corrected = [_stored_row(home_score=first[0].home_score, away_score=first[0].away_score)]
    report = build_plan(_raw_rows(), corrected)
    assert report["OLD_LABELS_CHANGED"] == 0
    assert report["ROWS_UNCHANGED"] == 1
    assert report["changes"] == []


def test_repair_row_count_never_increases():
    stored = [_stored_row()]
    results = collect_repair_results(build_plan(_raw_rows(), stored), stored, _raw_rows())
    assert len(results) <= len(stored)


def test_repair_skips_unresolved_rows():
    payload = {
        "id": 999,
        "home": "A",
        "away": "B",
        "status": "settled",
        "scores": {"home": 9, "away": 6},
    }
    stored = [
        _stored_row(),
        ("oaio:999", LEAGUE, HOME, AWAY, 0, 0, COMPLETED_AT, "odds_api_io", "oaio:999@hist:20260213"),
    ]
    raw = _raw_rows() + [("oaio:999@hist:20260213", payload)]
    report = build_plan(raw, stored)
    assert report["UNRESOLVED"] == 1
    results = collect_repair_results(report, stored, raw)
    assert all(r.event_key != "oaio:999" for r in results)
    assert len(results) == 1


def test_repair_preserves_void_rows():
    payload = {
        "id": 777,
        "home": "A",
        "away": "B",
        "status": "settled",
        "scores": {"home": 3, "away": 3,
                   "periods": {"ft": {"home": 3, "away": 3}}},
    }
    stored = [
        _stored_row(),
        ("oaio:777", LEAGUE, HOME, AWAY, 3, 3, COMPLETED_AT, "odds_api_io", "oaio:777@hist:20260213"),
    ]
    raw = _raw_rows() + [("oaio:777@hist:20260213", payload)]
    results = collect_repair_results(build_plan(raw, stored), stored, raw)
    assert all(r.event_key != "oaio:777" for r in results)


HAS_DATABASE_URL = bool(os.environ.get("MARKETS_TEST_DATABASE_URL"))

pytestmark = pytest.mark.skipif(
    not HAS_DATABASE_URL,
    reason="MARKETS_TEST_DATABASE_URL not configured; DB-gated tests skipped",
)


def test_db_repair_row_count_does_not_increase():
    from defend_markets.db import MarketsDatabase
    from defend_markets.repositories import MarketsRepository
    from defend_markets.store import PostgresMarketsStore

    database = MarketsDatabase(os.environ["MARKETS_TEST_DATABASE_URL"])
    database.migrate()
    with database.connect() as connection, connection.transaction():
        connection.execute("DELETE FROM tt_match_results WHERE event_key = %s", (CANONICAL_KEY,))
        connection.execute(
            "INSERT INTO tt_match_results (event_key, league_key, home_participant_key, "
            "away_participant_key, home_score, away_score, completed_at, source_provider, raw_ref) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (CANONICAL_KEY, LEAGUE, HOME, AWAY, 8, 11, COMPLETED_AT, "odds_api_io", RAW_KEY),
        )
    try:
        stored = [(CANONICAL_KEY, LEAGUE, HOME, AWAY, 8, 11, COMPLETED_AT, "odds_api_io", RAW_KEY)]
        results = collect_repair_results(build_plan(_raw_rows(), stored), stored, _raw_rows())
        store = PostgresMarketsStore(database, MarketsRepository())
        store.record_tt_results(results)
        with database.connect() as connection:
            rows = connection.execute(
                "SELECT event_key, home_score, away_score, raw_ref FROM tt_match_results "
                "WHERE event_key = %s", (CANONICAL_KEY,)
            ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == CANONICAL_KEY
        assert (rows[0][1], rows[0][2]) == (3, 1)
        assert rows[0][3] == RAW_KEY
    finally:
        with database.connect() as connection, connection.transaction():
            connection.execute("DELETE FROM tt_match_results WHERE event_key = %s", (CANONICAL_KEY,))