"""Versioned risk policy objects and evaluation.

Risk tiers are machine-readable policy objects, not presentation labels.
Every accepted or rejected opportunity references the exact policy version
used to evaluate it.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Mapping

from defend_markets.domain import (
    Opportunity,
    RiskEvaluation,
    RiskPolicy,
    RiskTier,
    horizon_duration,
)


def evaluate(
    opportunity: Opportunity,
    policy: RiskPolicy,
    *,
    desk: str | None = None,
    concentration: Decimal | None = None,
) -> RiskEvaluation:
    """Evaluate an opportunity against one policy version.

    Returns accepted=False with machine-readable reasons on any failure.
    Concentration is checked only when a portfolio exposure is supplied.
    """
    reasons: list[str] = []

    candidate_desk = desk or opportunity.instrument_key.split(":", 1)[0]
    if candidate_desk not in policy.allowed_desks:
        reasons.append(f"desk_not_allowed:{candidate_desk}")

    if opportunity.data_quality < policy.min_data_quality:
        reasons.append(
            f"data_quality:{opportunity.data_quality}<{policy.min_data_quality}"
        )

    if opportunity.confidence < policy.min_confidence:
        reasons.append(
            f"confidence:{opportunity.confidence}<{policy.min_confidence}"
        )

    horizon = horizon_duration(opportunity.horizon)
    if policy.max_horizon is not None and horizon is not None and horizon > policy.max_horizon:
        reasons.append(f"horizon:{opportunity.horizon}>{policy.max_horizon}")

    if opportunity.max_loss is not None and opportunity.max_loss > policy.max_loss_pct:
        reasons.append(
            f"max_loss:{opportunity.max_loss}>{policy.max_loss_pct}"
        )

    if concentration is not None:
        if not isinstance(concentration, Decimal):
            raise ValueError("concentration must be a Decimal")
        if concentration > policy.max_concentration:
            reasons.append(
                f"concentration:{concentration}>{policy.max_concentration}"
            )

    return RiskEvaluation(
        accepted=not reasons,
        reasons=tuple(reasons),
        policy_key=policy.policy_key,
        policy_version=policy.version,
    )


def to_params(policy: RiskPolicy) -> dict[str, object]:
    return {
        "min_data_quality": str(policy.min_data_quality),
        "min_confidence": str(policy.min_confidence),
        "max_concentration": str(policy.max_concentration),
        "allowed_desks": list(policy.allowed_desks),
        "max_horizon_days": (
            policy.max_horizon.days if policy.max_horizon is not None else None
        ),
        "max_loss_pct": str(policy.max_loss_pct),
    }


def from_params(
    policy_key: str,
    version: int,
    tier: RiskTier,
    params: Mapping[str, object],
) -> RiskPolicy:
    def decimal_value(name: str) -> Decimal:
        raw = params.get(name)
        if raw is None:
            raise ValueError(f"policy param {name} is required")
        return Decimal(str(raw))

    max_horizon_days = params.get("max_horizon_days")
    max_horizon = (
        timedelta(days=int(max_horizon_days))
        if max_horizon_days is not None
        else None
    )
    allowed = params.get("allowed_desks")
    desks = tuple(str(item) for item in allowed) if allowed else ("sports",)

    return RiskPolicy(
        policy_key=policy_key,
        version=version,
        tier=tier,
        min_data_quality=decimal_value("min_data_quality"),
        min_confidence=decimal_value("min_confidence"),
        max_concentration=decimal_value("max_concentration"),
        allowed_desks=desks,
        max_horizon=max_horizon,
        max_loss_pct=decimal_value("max_loss_pct"),
    )


def default_risk_policies() -> tuple[RiskPolicy, ...]:
    return (
        RiskPolicy(
            policy_key="markets_conservative",
            version=1,
            tier=RiskTier.CONSERVATIVE,
            min_data_quality=Decimal("0.85"),
            min_confidence=Decimal("0.70"),
            max_concentration=Decimal("0.05"),
            allowed_desks=("sports",),
            max_horizon=timedelta(days=2),
            max_loss_pct=Decimal("0.01"),
        ),
        RiskPolicy(
            policy_key="markets_core",
            version=1,
            tier=RiskTier.CORE,
            min_data_quality=Decimal("0.70"),
            min_confidence=Decimal("0.50"),
            max_concentration=Decimal("0.20"),
            allowed_desks=("sports",),
            max_horizon=timedelta(days=7),
            max_loss_pct=Decimal("0.02"),
        ),
        RiskPolicy(
            policy_key="markets_aggressive",
            version=1,
            tier=RiskTier.AGGRESSIVE,
            min_data_quality=Decimal("0.50"),
            min_confidence=Decimal("0.35"),
            max_concentration=Decimal("0.35"),
            allowed_desks=("sports",),
            max_horizon=timedelta(days=30),
            max_loss_pct=Decimal("0.05"),
        ),
    )