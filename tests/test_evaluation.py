from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from defend_markets.evaluation import CalibrationEvaluator

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)


def test_empty_sample_reports_nothing():
    card = CalibrationEvaluator().score(probabilities=[], outcomes=[])
    assert card.sample_size == 0
    assert card.brier is None
    assert card.log_loss is None
    assert card.accuracy is None


def test_brier_perfect_predictions_is_zero():
    evaluator = CalibrationEvaluator(min_sample=2)
    card = evaluator.score(
        probabilities=[Decimal("1"), Decimal("1"), Decimal("0"), Decimal("0")],
        outcomes=[True, True, False, False],
    )
    assert card.brier == Decimal("0")


def test_brier_worst_case_is_one():
    evaluator = CalibrationEvaluator(min_sample=2)
    card = evaluator.score(
        probabilities=[Decimal("1"), Decimal("0")],
        outcomes=[False, True],
    )
    assert card.brier == Decimal("1")


def test_brier_known_value():
    evaluator = CalibrationEvaluator(min_sample=2)
    card = evaluator.score(
        probabilities=[Decimal("0.5")] * 4,
        outcomes=[True, True, False, False],
    )
    assert card.brier == pytest.approx(Decimal("0.25"))


def test_log_loss_finite_for_certain_predictions():
    evaluator = CalibrationEvaluator(min_sample=2)
    card = evaluator.score(
        probabilities=[Decimal("1"), Decimal("0")],
        outcomes=[True, False],
    )
    assert card.log_loss is not None
    assert card.log_loss >= Decimal("0")


def test_small_sample_suppresses_metrics_but_reports_size():
    evaluator = CalibrationEvaluator()
    card = evaluator.score(
        probabilities=[Decimal("0.6"), Decimal("0.4")],
        outcomes=[True, False],
    )
    assert card.sample_size == 2
    assert card.brier is None
    assert not card.calibrated


def test_calibration_buckets_built_at_threshold():
    evaluator = CalibrationEvaluator()
    probabilities = [Decimal("0.1"), Decimal("0.9")] * 20
    outcomes = [False, True] * 20
    card = evaluator.score(probabilities=probabilities, outcomes=outcomes)
    assert card.sample_size == 40
    assert card.calibrated
    assert card.buckets
    assert card.accuracy == Decimal("1")


def test_model_vs_baselines_wiring():
    evaluator = CalibrationEvaluator()
    prediction_id = uuid4()
    predictions = [
        {
            "prediction_id": prediction_id,
            "model_p_a": Decimal("0.7"),
            "consensus_p_a": Decimal("0.55"),
        }
    ]
    settlements = [
        {
            "prediction_id": prediction_id,
            "settlement_ts": NOW,
            "correct": True,
        }
    ]
    cards = evaluator.model_vs_baselines(
        predictions=predictions, settlements=settlements
    )
    assert "model" in cards
    assert "elo_baseline" in cards
    assert "market_baseline" in cards
    assert cards["model"].sample_size == 1


def test_model_vs_baselines_skips_unsettled():
    evaluator = CalibrationEvaluator()
    cards = evaluator.model_vs_baselines(
        predictions=[{"prediction_id": uuid4(), "model_p_a": Decimal("0.7")}],
        settlements=[],
    )
    assert cards["model"].sample_size == 0