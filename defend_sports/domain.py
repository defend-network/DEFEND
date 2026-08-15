from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Mapping


def _require_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be blank")
    return value


def _require_aware_datetime(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    return value


def _require_optional_datetime(name: str, value: object) -> datetime | None:
    if value is None:
        return None
    return _require_aware_datetime(name, value)


def _require_decimal_odds(name: str, value: object) -> Decimal:
    if not isinstance(value, Decimal):
        raise ValueError(f"{name} must be a Decimal")
    try:
        if not value.is_finite() or value <= Decimal("1"):
            raise ValueError(f"{name} must be a finite decimal odds value above 1")
    except (ValueError, TypeError):
        raise ValueError(f"{name} must be a finite decimal odds value above 1") from None
    return value


def _require_optional_raw_event_ref(value: object) -> str | None:
    if value is None:
        return None
    return _require_text("raw_event_ref", value)


def _require_state(value: object) -> Mapping[str, object]:
    if value is None or not isinstance(value, Mapping):
        raise ValueError("state must be a mapping")
    return value


@dataclass(frozen=True)
class SourceRef:
    """Provider-side identity of a data source (feed, book, or provider)."""

    provider: str = field(default="")
    external_id: str = field(default="")

    def __post_init__(self) -> None:
        _require_text("provider", self.provider)
        _require_text("external_id", self.external_id)


@dataclass(frozen=True)
class CanonicalEvent:
    """Provider-neutral sports event identity."""

    event_external_id: str = field(default="")
    sport_key: str = field(default="")
    league_key: str = field(default="")
    display_name: str = field(default="")
    scheduled_at: datetime | None = field(default=None)
    raw_event_ref: str | None = field(default=None)

    def __post_init__(self) -> None:
        _require_text("event_external_id", self.event_external_id)
        _require_text("sport_key", self.sport_key)
        _require_text("league_key", self.league_key)
        _require_text("display_name", self.display_name)
        object.__setattr__(self, "scheduled_at", _require_optional_datetime("scheduled_at", self.scheduled_at))
        object.__setattr__(self, "raw_event_ref", _require_optional_raw_event_ref(self.raw_event_ref))


@dataclass(frozen=True)
class LiveObservation:
    """Provider-neutral live-state snapshot for a canonical event."""

    source: SourceRef = field(default_factory=SourceRef)
    event_external_id: str = field(default="")
    state: Mapping[str, object] = field(default_factory=dict)
    observed_at: datetime | None = field(default=None)
    received_at: datetime | None = field(default=None)
    raw_event_ref: str | None = field(default=None)

    def __post_init__(self) -> None:
        if not isinstance(self.source, SourceRef):
            raise ValueError("source must be a SourceRef")
        _require_text("event_external_id", self.event_external_id)
        object.__setattr__(self, "state", _require_state(self.state))
        object.__setattr__(self, "observed_at", _require_aware_datetime("observed_at", self.observed_at))
        object.__setattr__(self, "received_at", _require_optional_datetime("received_at", self.received_at))
        object.__setattr__(self, "raw_event_ref", _require_optional_raw_event_ref(self.raw_event_ref))


@dataclass(frozen=True)
class CanonicalMarket:
    """Provider-neutral market attached to a canonical event."""

    event_external_id: str = field(default="")
    market_key: str = field(default="")
    display_name: str = field(default="")

    def __post_init__(self) -> None:
        _require_text("event_external_id", self.event_external_id)
        _require_text("market_key", self.market_key)
        _require_text("display_name", self.display_name)


@dataclass(frozen=True)
class CanonicalSelection:
    """Provider-neutral selection/outcome within a canonical market."""

    market_key: str = field(default="")
    selection_key: str = field(default="")
    display_name: str = field(default="")

    def __post_init__(self) -> None:
        _require_text("market_key", self.market_key)
        _require_text("selection_key", self.selection_key)
        _require_text("display_name", self.display_name)


@dataclass(frozen=True)
class OddsObservation:
    """Provider-neutral append-only odds snapshot for a canonical selection."""

    source: SourceRef = field(default_factory=SourceRef)
    event_external_id: str = field(default="")
    market_key: str = field(default="")
    selection_key: str = field(default="")
    decimal_odds: Decimal | None = field(default=None)
    observed_at: datetime | None = field(default=None)
    received_at: datetime | None = field(default=None)
    raw_event_ref: str | None = field(default=None)

    def __post_init__(self) -> None:
        if not isinstance(self.source, SourceRef):
            raise ValueError("source must be a SourceRef")
        _require_text("event_external_id", self.event_external_id)
        _require_text("market_key", self.market_key)
        _require_text("selection_key", self.selection_key)
        object.__setattr__(self, "decimal_odds", _require_decimal_odds("decimal_odds", self.decimal_odds))
        object.__setattr__(self, "observed_at", _require_aware_datetime("observed_at", self.observed_at))
        object.__setattr__(self, "received_at", _require_optional_datetime("received_at", self.received_at))
        object.__setattr__(self, "raw_event_ref", _require_optional_raw_event_ref(self.raw_event_ref))