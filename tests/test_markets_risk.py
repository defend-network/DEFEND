from __future__ import annotations

from decimal import Decimal

import pytest

from defend_markets import risk
from defend_markets.domain import Opportunity, RiskEvaluation, RiskTier


def _opportunity(**overrides) -> Opportunity:
    values = dict(
        instrument_key="sports:tt-live-001:match_winner",
        strategy_key="tt_two_way_arb",
        policy_key="markets_core",
        direction="arb",
        horizon="event",
        thesis="t",
        confidence=Decimal("0.9"),
        data_quality=Decimal("0.9"),
        max_loss=Decimal("0.01"),
        invalidation="i",
    )
    values.update(overrides)
    return Opportunity(**values)


def test_core_policy_accepts_high_quality_opportunity():
    policy = risk.default_risk_policies()[1]
    evaluation = risk.evaluate(_opportunity(), policy, desk="sports")
    assert evaluation.accepted
    assert evaluation.policy_key == "markets_core"
    assert evaluation.policy_version == 1


def test_policy_version_is_captured_in_evaluation():
    evaluation = risk.evaluate(_opportunity(), risk.default_risk_policies()[0], desk="sports")
    assert isinstance(evaluation, RiskEvaluation)
    assert evaluation.policy_key == "markets_conservative"
    assert evaluation.policy_version == 1


def test_data_quality_below_policy_minimum_rejects():
    policy = risk.default_risk_policies()[1]
    evaluation = risk.evaluate(
        _opportunity(data_quality=Decimal("0.6")), policy, desk="sports"
    )
    assert not evaluation.accepted
    assert any(reason.startswith("data_quality:") for reason in evaluation.reasons)


def test_confidence_below_policy_minimum_rejects():
    policy = risk.default_risk_policies()[1]
    evaluation = risk.evaluate(
        _opportunity(confidence=Decimal("0.4")), policy, desk="sports"
    )
    assert not evaluation.accepted
    assert any(reason.startswith("confidence:") for reason in evaluation.reasons)


def test_desk_not_allowed_rejects():
    policy = risk.default_risk_policies()[1]
    evaluation = risk.evaluate(_opportunity(), policy, desk="equities")
    assert not evaluation.accepted
    assert any(reason.startswith("desk_not_allowed:") for reason in evaluation.reasons)


def test_max_loss_exceeding_policy_rejects():
    policy = risk.default_risk_policies()[1]
    evaluation = risk.evaluate(
        _opportunity(max_loss=Decimal("0.10")), policy, desk="sports"
    )
    assert not evaluation.accepted
    assert any(reason.startswith("max_loss:") for reason in evaluation.reasons)


def test_horizon_longer_than_policy_maximum_rejects():
    policy = risk.default_risk_policies()[0]
    evaluation = risk.evaluate(
        _opportunity(horizon="positional"), policy, desk="sports"
    )
    assert not evaluation.accepted
    assert any(reason.startswith("horizon:") for reason in evaluation.reasons)


def test_tiers_have_distinct_machine_readable_params():
    conservative, core, aggressive = risk.default_risk_policies()
    assert conservative.tier is RiskTier.CONSERVATIVE
    assert core.tier is RiskTier.CORE
    assert aggressive.tier is RiskTier.AGGRESSIVE
    assert conservative.min_data_quality > core.min_data_quality > aggressive.min_data_quality
    assert conservative.min_confidence > core.min_confidence > aggressive.min_confidence
    assert aggressive.max_loss_pct > core.max_loss_pct > conservative.max_loss_pct


def test_policy_params_roundtrip():
    policy = risk.default_risk_policies()[1]
    restored = risk.from_params(
        policy.policy_key, policy.version, policy.tier, risk.to_params(policy)
    )
    assert restored == policy
    assert restored.allowed_desks == ("sports",)
    assert restored.max_horizon is not None


def test_policy_requires_all_params():
    with pytest.raises(ValueError, match="required"):
        risk.from_params("markets_core", 1, RiskTier.CORE, {})