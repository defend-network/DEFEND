from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from defend_markets.domain import DataQualityAssessment
from defend_markets.quality import HealthGate, ProviderHealthState


NOW = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)


def _provider(source: str, status: str = "HEALTHY", age_minutes: int = 1) -> ProviderHealthState:
    return ProviderHealthState(
        source_key=source,
        status=status,
        observed_at=NOW - timedelta(minutes=age_minutes),
    )


def _quality(instrument: str, score: str = "0.9") -> DataQualityAssessment:
    return DataQualityAssessment(
        instrument_key=instrument,
        venue_key="book-a",
        score=Decimal(score),
        freshness_ok=True,
        availability="AVAILABLE",
        as_of=NOW,
    )


def test_healthy_sources_pass_the_gate():
    gate = HealthGate()
    result = gate.evaluate(
        {"book-a": _provider("book-a"), "book-b": _provider("book-b")},
        {},
        now=NOW,
    )
    assert result.ok
    assert result.freshness_ok
    assert result.availability == "AVAILABLE"


def test_unavailable_provider_blocks():
    gate = HealthGate()
    result = gate.evaluate(
        {"book-a": _provider("book-a", status="UNAVAILABLE")}, {}, now=NOW
    )
    assert not result.ok
    assert any(reason.startswith("provider_unhealthy") for reason in result.reasons)
    assert result.availability == "UNAVAILABLE"


def test_stale_observations_block():
    gate = HealthGate(freshness_max_age=timedelta(minutes=5))
    result = gate.evaluate(
        {"book-a": _provider("book-a", age_minutes=10)}, {}, now=NOW
    )
    assert not result.ok
    assert not result.freshness_ok
    assert any(reason.startswith("stale:") for reason in result.reasons)
    assert result.availability == "STALE"


def test_quality_below_threshold_reported():
    gate = HealthGate(min_quality=Decimal("0.5"))
    result = gate.evaluate(
        {"book-a": _provider("book-a")},
        {"sports:tt:market": _quality("sports:tt:market", score="0.3")},
        now=NOW,
    )
    assert not result.ok
    assert any(reason.startswith("quality_below_threshold") for reason in result.reasons)


def test_no_health_observations_is_a_failure_state():
    gate = HealthGate()
    result = gate.evaluate({}, {}, now=NOW)
    assert not result.ok
    assert "no_health_observations" in result.reasons


def test_naive_now_rejected():
    gate = HealthGate()
    import pytest

    with pytest.raises(ValueError, match="timezone-aware"):
        gate.evaluate({"book-a": _provider("book-a")}, {}, now=datetime(2026, 8, 15, 12))