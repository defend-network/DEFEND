"""Unit tests for chronological rating history and time-forward evaluation."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from defend_markets.domain import TTMatchResult
from defend_markets.tt_rating import (
    TTRatingHistoryRow,
    evaluate_time_forward,
    expected_score,
    rebuild_rating_history,
)


def _result(
    event_key: str,
    home: str,
    away: str,
    home_score: int,
    away_score: int,
    day: int,
) -> TTMatchResult:
    return TTMatchResult(
        event_key=event_key,
        league_key="tt",
        home_participant_key=f"table_tennis:{home}",
        away_participant_key=f"table_tennis:{away}",
        home_score=home_score,
        away_score=away_score,
        completed_at=datetime(2026, 1, day, 12, tzinfo=timezone.utc),
        source_provider="odds_api_io",
        raw_ref=f"oaio:{event_key}@hist:202601{day:02d}",
    )


def test_rebuild_rating_history_is_chronological_and_consistent():
    results = [
        _result("e1", "alice", "bob", 3, 1, 1),
        _result("e2", "bob", "alice", 3, 2, 2),
    ]
    rows = rebuild_rating_history(results)
    assert len(rows) == 4
    assert all(isinstance(row, TTRatingHistoryRow) for row in rows)

    alice = [row for row in rows if row.participant_key == "table_tennis:alice"]
    assert [row.event_key for row in alice] == ["e1", "e2"]
    assert alice[0].result == "win"
    assert alice[1].result == "loss"
    assert alice[0].pre_rating == Decimal("1200")
    assert alice[0].post_rating == alice[1].pre_rating
    assert alice[0].expected == expected_score(Decimal("1200"), Decimal("1200"))
    assert alice[1].actual == Decimal("0")

    bob = [row for row in rows if row.participant_key == "table_tennis:bob"]
    assert bob[0].result == "loss"
    assert bob[1].result == "win"
    assert bob[0].pre_rating == Decimal("1200")
    assert bob[0].post_rating == bob[1].pre_rating


def test_rebuild_rating_history_skips_self_matches():
    rows = rebuild_rating_history(
        [
            _result("e1", "alice", "alice", 3, 1, 1),
            _result("e2", "bob", "bob", 3, 0, 2),
        ]
    )
    assert rows == ()


def test_rebuild_rating_history_draws():
    rows = rebuild_rating_history([_result("e1", "alice", "bob", 3, 3, 1)])
    assert len(rows) == 2
    alice = rows[0]
    assert alice.result == "draw"
    assert alice.actual == Decimal("0.5")
    assert alice.post_rating == alice.pre_rating + Decimal("32") * (
        Decimal("0.5") - alice.expected
    )


def test_time_forward_evaluation_never_leaks_future_results():
    results = [
        _result("e1", "alice", "bob", 3, 1, 1),
        _result("e2", "bob", "alice", 3, 2, 2),
        _result("e3", "alice", "bob", 3, 0, 3),
    ]
    evaluation = evaluate_time_forward(results, min_history_games=1)
    matches = {item.event_key: item for item in evaluation.matches}
    assert len(evaluation.matches) == 3
    assert evaluation.n_available == 2
    assert matches["e1"].available is False
    assert matches["e2"].p_home == expected_score(Decimal("1184"), Decimal("1216"))
    assert matches["e3"].p_home != expected_score(
        Decimal("1232"), Decimal("1168")
    )  # not the final ratings


def test_time_forward_evaluation_metrics():
    results = [
        _result("e1", "alice", "bob", 3, 1, 1),
        _result("e2", "bob", "alice", 3, 2, 2),
    ]
    evaluation = evaluate_time_forward(results, min_history_games=1)
    assert evaluation.brier is not None
    assert evaluation.accuracy is not None
    assert evaluation.calibration
    assert evaluation.n_available == 1
    available = next(match for match in evaluation.matches if match.available)
    assert available.p_away == Decimal("1") - available.p_home


def test_time_forward_evaluation_requires_minimum_history():
    results = [_result("e1", "alice", "bob", 3, 1, 1)]
    evaluation = evaluate_time_forward(results, min_history_games=5)
    assert evaluation.n_available == 0
    assert evaluation.brier is None
    assert evaluation.accuracy is None
    assert all(not match.available for match in evaluation.matches)


def test_time_forward_to_dict_shape():
    evaluation = evaluate_time_forward([_result("e1", "alice", "bob", 3, 1, 1)])
    as_dict = evaluation.to_dict()
    assert as_dict["n_matches"] == 1
    assert "brier" in as_dict
    assert "calibration" in as_dict
    assert all("bucket" in row for row in as_dict["calibration"])