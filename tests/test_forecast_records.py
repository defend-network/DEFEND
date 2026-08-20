from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from defend_markets.forecast import (
    PredictionRecord,
    ResearchEntry,
    SettlementRecord,
    ShadowRecord,
)

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)


def prediction(**overrides) -> PredictionRecord:
    fields = dict(
        prediction_id=uuid4(),
        created_ts=NOW,
        event_key="tt-1",
        sport_key="table_tennis",
        player_a_name_at_prediction="Alice",
        player_b_name_at_prediction="Bob",
        decision="OPPORTUNITY",
    )
    fields.update(overrides)
    return PredictionRecord(**fields)


def test_prediction_rejects_unknown_decision():
    with pytest.raises(ValueError):
        prediction(decision="HOLD")


def test_prediction_rejects_blank_event_key():
    with pytest.raises(ValueError):
        prediction(event_key="  ")


def test_prediction_rejects_naive_timestamps():
    with pytest.raises(ValueError):
        prediction(created_ts=datetime(2026, 8, 15, 12, 0))


def test_prediction_rejects_probabilities_outside_unit_interval():
    with pytest.raises(ValueError):
        prediction(model_p_a=Decimal("1.2"))
    with pytest.raises(ValueError):
        prediction(model_p_a=Decimal("-0.1"))


def test_prediction_requires_model_probabilities_sum_to_one():
    with pytest.raises(ValueError):
        prediction(model_p_a=Decimal("0.6"), model_p_b=Decimal("0.5"))


def test_prediction_accepts_model_p_a_only():
    record = prediction(model_p_a=Decimal("0.55"))
    assert record.model_p_a == Decimal("0.55")


def test_settlement_rejects_blank_source_ref():
    with pytest.raises(ValueError):
        SettlementRecord(
            prediction_id=uuid4(),
            source_raw_ref=" ",
            settlement_ts=NOW,
            winner_participant_key="table_tennis:alice",
            correct=True,
            settled_by="tt_settlement_service.v1",
        )


def test_settlement_rejects_blank_winner():
    with pytest.raises(ValueError):
        SettlementRecord(
            prediction_id=uuid4(),
            source_raw_ref="tt-1:1",
            settlement_ts=NOW,
            winner_participant_key="",
            correct=True,
            settled_by="tt_settlement_service.v1",
        )


def test_settlement_requires_aware_timestamp():
    with pytest.raises(ValueError):
        SettlementRecord(
            prediction_id=uuid4(),
            source_raw_ref="tt-1:1",
            settlement_ts=datetime(2026, 8, 15, 12, 0),
            winner_participant_key="table_tennis:alice",
            correct=True,
            settled_by="tt_settlement_service.v1",
        )


def test_shadow_record_defaults():
    shadow = ShadowRecord(
        event_key="tt-1",
        created_ts=NOW,
        model_id="tt_elo",
        model_version="0.0.1",
        strategy_id="tt_elo_arb",
        strategy_version=1,
    )
    assert shadow.market_p_a is None
    assert shadow.elo_p_a is None


def test_research_entry_requires_valid_decision():
    with pytest.raises(ValueError):
        ResearchEntry(
            hypothesis="h",
            change="c",
            expected_mechanism="m",
            decision="UNKNOWN",
        )
    entry = ResearchEntry(
        hypothesis="h",
        change="c",
        expected_mechanism="m",
        decision="KEEP",
    )
    assert entry.decision == "KEEP"