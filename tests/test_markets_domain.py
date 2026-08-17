from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from defend_markets.domain import (
    CostModel,
    DecisionRecord,
    DecisionType,
    NoActionReason,
    Opportunity,
    PitAvailability,
    ProvenanceStamp,
    RiskTier,
)


class TestProvenancePit:
    def test_provenance_requires_aware_timestamps(self):
        with pytest.raises(ValueError, match="timezone-aware"):
            ProvenanceStamp(
                source_key="book-a",
                observed_at=datetime(2026, 8, 15, 10, 0),
                received_at=None,
            )

    def test_provenance_allows_unknown_timestamps(self):
        stamp = ProvenanceStamp(source_key="book-a")
        assert stamp.observed_at is None
        assert stamp.received_at is None
        assert stamp.normalization_version is None

    def test_pit_availability_marks_missing_fields(self):
        availability = PitAvailability(
            provided=frozenset({"observed_at", "received_at"}),
            limitations=("announced_at is not modeled",),
        )
        assert availability.has("observed_at")
        assert not availability.has("announced_at")
        assert availability.limitations


class TestCostsBeforeEdge:
    def test_cost_model_unknown_components_are_none_not_zero(self):
        costs = CostModel()
        assert costs.vig is None
        assert costs.spread is None
        assert costs.total() is None

    def test_cost_model_total_sums_known_components(self):
        costs = CostModel(fees=Decimal("0.001"), slippage=Decimal("0.0005"))
        assert costs.total() == Decimal("0.0015")

    def test_opportunity_preserves_gross_and_net_separately(self):
        opportunity = Opportunity(
            instrument_key="sports:tt-live-001:match_winner",
            strategy_key="tt_two_way_arb",
            policy_key="markets_core",
            direction="arb",
            horizon="event",
            thesis="t",
            gross_edge=Decimal("0.01"),
            net_edge=None,
            costs=CostModel(),
            confidence=Decimal("0.9"),
            data_quality=Decimal("0.8"),
            risk_tier=RiskTier.CORE,
            invalidation="i",
        )
        assert opportunity.gross_edge == Decimal("0.01")
        assert opportunity.net_edge is None
        assert opportunity.cost_estimate is None

    def test_confidence_and_expected_value_are_distinct(self):
        opportunity = Opportunity(
            instrument_key="k",
            strategy_key="s",
            policy_key="p",
            direction="long",
            horizon="event",
            thesis="t",
            confidence=Decimal("0.7"),
            expected_value=None,
            data_quality=Decimal("0.8"),
            invalidation="i",
        )
        assert opportunity.confidence == Decimal("0.7")
        assert opportunity.expected_value is None


class TestDecisionContract:
    def test_opportunity_decisions_cannot_carry_no_action_codes(self):
        with pytest.raises(ValueError, match="reason codes"):
            DecisionRecord(
                strategy_key="s",
                policy_key="p",
                thesis="t",
                decision_type=DecisionType.OPPORTUNITY,
                reason_codes=(NoActionReason.STALE_DATA,),
            )

    def test_no_action_carries_machine_readable_codes(self):
        record = DecisionRecord(
            strategy_key="s",
            policy_key="p",
            thesis="t",
            decision_type=DecisionType.NO_ACTION,
            reason_codes=(NoActionReason.COSTS_UNACCOUNTED, NoActionReason.STALE_DATA),
        )
        assert record.is_no_action
        assert [code.value for code in record.reason_codes] == [
            "costs_unaccounted",
            "stale_data",
        ]

    def test_outcome_is_null_until_resolved(self):
        record = DecisionRecord(
            strategy_key="s",
            policy_key="p",
            thesis="t",
            decision_type=DecisionType.NO_ACTION,
            reason_codes=(NoActionReason.NO_ELIGIBLE_DATA,),
        )
        assert record.outcome is None

    def test_reason_codes_are_all_first_class(self):
        codes = {code.value for code in NoActionReason}
        assert {
            "insufficient_edge",
            "stale_data",
            "below_risk_policy",
            "missing_provenance",
            "insufficient_liquidity",
            "costs_exceed_edge",
            "costs_unaccounted",
            "provider_unhealthy",
            "no_eligible_data",
            "strategy_not_eligible",
        } <= codes