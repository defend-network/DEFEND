from datetime import datetime, timezone
from decimal import Decimal

import pytest

from defend_markets.domain import TTMatchResult
from defend_markets.tt_rating import (
    TTEloModel,
    build_ratings,
    calibration_bucket,
    expected_score,
    update_rating,
)


def _result(event_key: str, home: str, away: str, home_score: int, away_score: int) -> TTMatchResult:
    return TTMatchResult(
        event_key=event_key,
        league_key="tt_test",
        home_participant_key=home,
        away_participant_key=away,
        home_score=home_score,
        away_score=away_score,
        completed_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        source_provider="test",
        raw_ref=f"ref-{event_key}",
    )


def _row(**kwargs: object) -> dict[str, object]:
    base: dict[str, object] = {
        "event_key": "evt",
        "league_key": "tt_test",
        "home_participant_key": "home",
        "away_participant_key": "away",
        "home_score": 3,
        "away_score": 1,
        "completed_at": datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        "source_provider": "test",
        "raw_ref": "ref",
    }
    base.update(kwargs)
    return base


def test_expected_score_symmetric_and_bounded() -> None:
    p = expected_score(Decimal("1200"), Decimal("1200"))
    assert p == Decimal("0.5")
    assert Decimal("0") < expected_score(Decimal("1600"), Decimal("1200")) < Decimal("1")
    p2 = expected_score(Decimal("1200"), Decimal("1600"))
    assert expected_score(Decimal("1600"), Decimal("1200")) + p2 == pytest.approx(Decimal("1"))


def test_update_rating_favorite_loss() -> None:
    rating = Decimal("1600")
    expected = expected_score(Decimal("1600"), Decimal("1200"))
    updated = update_rating(rating, expected, Decimal("0"))
    assert updated < rating
    assert updated == rating + Decimal("32") * (Decimal("0") - expected)


def test_calibration_bucket_bounds() -> None:
    assert calibration_bucket(Decimal("0.55")) == "0.50-0.60"
    assert calibration_bucket(Decimal("0.60")) == "0.60-0.70"
    assert calibration_bucket(Decimal("0.95")) == "0.90-1.00"
    assert calibration_bucket(Decimal("1.5")) is None
    assert calibration_bucket(Decimal("-0.1")) is None


def test_build_ratings_counts_games_wins_and_recent_form() -> None:
    results = [
        _result("e1", "alice", "bob", 3, 1),
        _result("e2", "bob", "alice", 3, 2),
        _result("e3", "alice", "bob", 3, 0),
        _result("e4", "bob", "alice", 3, 1),
        _result("e5", "alice", "bob", 3, 2),
        _result("e6", "bob", "alice", 3, 0),
        _result("e7", "alice", "bob", 3, 1),
    ]
    profiles = build_ratings(results)
    alice = profiles["alice"]
    bob = profiles["bob"]
    assert alice.games == 7 and bob.games == 7
    assert alice.wins == 4 and bob.wins == 3
    assert alice.recent_games == 5
    assert alice.recent_form == Decimal("3") / Decimal("5")
    # Alice won more often, so her rating must exceed Bob's.
    assert alice.rating > bob.rating


def test_build_ratings_skips_self_matches() -> None:
    profiles = build_ratings(
        [
            _result("e1", "x", "y", 3, 1),
            _result("e2", "x", "x", 3, 1),
        ]
    )
    assert "x" in profiles and "y" in profiles
    assert profiles["x"].games == 1 and profiles["y"].games == 1


def test_evaluate_unavailable_without_history() -> None:
    model = TTEloModel.from_history_rows([])
    evaluation = model.evaluate("alice", "bob")
    assert evaluation.available is False
    assert "no history" in evaluation.reason
    assert evaluation.p_home is None


def test_evaluate_unavailable_below_minimum_games() -> None:
    model = TTEloModel.from_history_rows([_row(event_key="e1"), _row(event_key="e2")])
    evaluation = model.evaluate("home", "away")
    assert evaluation.available is False
    assert "insufficient history" in evaluation.reason


def test_evaluate_available_with_history_and_calibration() -> None:
    rows = [_row(event_key=f"e{i}", home_score=3, away_score=1) for i in range(6)]
    model = TTEloModel.from_history_rows(rows)
    evaluation = model.evaluate("home", "away")
    assert evaluation.available is True
    assert evaluation.p_home is not None
    assert Decimal("0") < evaluation.p_home < Decimal("1")
    assert evaluation.p_away == Decimal("1") - evaluation.p_home
    assert evaluation.home_games == 6 and evaluation.away_games == 6
    assert evaluation.home_rating is not None and evaluation.away_rating is not None
    assert evaluation.home_form is not None
    assert evaluation.calibration_bucket is not None
    assert evaluation.reason is None


def test_from_history_rows_tolerates_missing_optional_fields() -> None:
    model = TTEloModel.from_history_rows(
        [
            {
                "event_key": "e1",
                "league_key": "tt",
                "home_participant_key": "home",
                "away_participant_key": "away",
                "home_score": 3,
                "away_score": 1,
            }
        ]
    )
    assert "home" in model.profiles()