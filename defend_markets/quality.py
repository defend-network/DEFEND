"""Data health gate.

Provider freshness, availability and quality gate recommendation
eligibility. A gate failure must degrade confidence, reject, or force
NO_ACTION depending on policy — never silently pass stale data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Mapping

from defend_markets.domain import DataQualityAssessment, HealthGateResult


@dataclass(frozen=True)
class ProviderHealthState:
    source_key: str = ""
    status: str = "UNAVAILABLE"
    observed_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.status not in ("HEALTHY", "DEGRADED", "UNAVAILABLE"):
            raise ValueError("status must be HEALTHY, DEGRADED, or UNAVAILABLE")
        if self.observed_at is not None and self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")


class HealthGate:
    def __init__(
        self,
        *,
        freshness_max_age: timedelta = timedelta(minutes=5),
        min_quality: Decimal = Decimal("0.5"),
    ) -> None:
        self._freshness_max_age = freshness_max_age
        self._min_quality = min_quality

    def evaluate(
        self,
        provider_states: Mapping[str, ProviderHealthState],
        quality: Mapping[str, DataQualityAssessment],
        *,
        now: datetime | None = None,
    ) -> HealthGateResult:
        current = now if now is not None else datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")

        reasons: list[str] = []
        availability = "AVAILABLE"
        freshness_ok = True
        worst_score = Decimal("1")

        for source_key, state in provider_states.items():
            if state.status == "UNAVAILABLE":
                reasons.append(f"provider_unhealthy:{source_key}")
                availability = "UNAVAILABLE"
            elif state.status == "DEGRADED":
                reasons.append(f"provider_degraded:{source_key}")
                availability = "STALE" if availability == "AVAILABLE" else availability
            if state.observed_at is not None and current - state.observed_at > self._freshness_max_age:
                reasons.append(f"stale:{source_key}")
                freshness_ok = False
                if availability == "AVAILABLE":
                    availability = "STALE"

        for instrument_key, assessment in quality.items():
            worst_score = min(worst_score, assessment.score)
            if assessment.availability == "UNAVAILABLE":
                reasons.append(f"quality_unavailable:{instrument_key}")
                availability = "UNAVAILABLE"
            elif assessment.availability == "STALE":
                reasons.append(f"quality_stale:{instrument_key}")
                freshness_ok = False
                if availability == "AVAILABLE":
                    availability = "STALE"
            if assessment.score < self._min_quality:
                reasons.append(
                    f"quality_below_threshold:{instrument_key}:{assessment.score}"
                )

        if not provider_states and not quality:
            reasons.append("no_health_observations")

        return HealthGateResult(
            ok=not reasons,
            freshness_ok=freshness_ok,
            availability=availability,
            reasons=tuple(reasons),
            score=worst_score,
        )