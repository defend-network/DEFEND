"""Provider adapter interfaces for DEFEND Sports."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping, Protocol, runtime_checkable

from defend_sports.domain import CanonicalEvent, LiveObservation, OddsObservation, SourceRef


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


@dataclass(frozen=True)
class RawProviderEvent:
    """Raw provider payload plus provenance for a single provider event.

    Stored verbatim so normalization bugs can be reproduced. Raw/vendor
    field names never leave this model; canonical consumers reference it
    only through ``raw_event_ref``.
    """

    source: SourceRef = field(default_factory=SourceRef)
    provider_event_id: str = field(default="")
    payload: Mapping[str, object] = field(default_factory=dict)
    observed_at: datetime | None = field(default=None)
    received_at: datetime | None = field(default=None)
    display_name: str | None = field(default=None)

    def __post_init__(self) -> None:
        if not isinstance(self.source, SourceRef):
            raise ValueError("source must be a SourceRef")
        _require_text("provider_event_id", self.provider_event_id)
        if not isinstance(self.payload, Mapping):
            raise ValueError("payload must be a mapping")
        object.__setattr__(self, "observed_at", _require_aware_datetime("observed_at", self.observed_at))
        object.__setattr__(self, "received_at", _require_optional_datetime("received_at", self.received_at))
        if self.display_name is not None:
            object.__setattr__(self, "display_name", _require_text("display_name", self.display_name))


@dataclass(frozen=True)
class ProviderBatch:
    """One poll of a sports provider, expressed entirely in canonical models."""

    raw_events: tuple[RawProviderEvent, ...] = ()
    events: tuple[CanonicalEvent, ...] = ()
    live: tuple[LiveObservation, ...] = ()
    odds: tuple[OddsObservation, ...] = ()


@runtime_checkable
class SportsProvider(Protocol):
    """Narrow provider abstraction: name plus a poll that yields a batch."""

    @property
    def provider_name(self) -> str: ...

    def poll(self) -> ProviderBatch: ...