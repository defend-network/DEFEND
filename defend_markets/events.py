"""Minimal real event graph: events, entities, links, impact windows.

Event time (effective), announced time (published) and retrieved time
(ingested) are distinct and optional; providers that cannot supply a
timestamp must leave it None rather than fabricate it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Mapping

from defend_markets.domain import (
    EventEntity,
    EventEntityLink,
    EventImpactWindow,
    EventStatus,
    MarketEvent,
)


@dataclass(frozen=True)
class EventGraphRecord:
    event: MarketEvent
    entities: tuple[EventEntity, ...] = ()
    links: tuple[EventEntityLink, ...] = ()
    impacts: tuple[EventImpactWindow, ...] = ()


def sports_injury_event(
    *,
    event_key: str,
    title: str,
    player_key: str,
    player_name: str,
    team_key: str,
    team_name: str,
    market_instrument_key: str,
    source_key: str,
    announced_at: datetime,
    retrieved_at: datetime,
) -> EventGraphRecord:
    """Real Sports path: injury/news -> player/team -> market -> line movement."""
    return EventGraphRecord(
        event=MarketEvent(
            event_key=event_key,
            event_type="injury_news",
            title=title,
            announced_at=announced_at,
            retrieved_at=retrieved_at,
            source_key=source_key,
            status=EventStatus.OPEN,
            detail={"kind": "injury"},
        ),
        entities=(
            EventEntity(
                entity_key=player_key,
                entity_type="PLAYER",
                display_name=player_name,
            ),
            EventEntity(
                entity_key=team_key,
                entity_type="TEAM",
                display_name=team_name,
            ),
        ),
        links=(
            EventEntityLink(
                event_key=event_key,
                entity_key=player_key,
                role="affected",
                valid_from=announced_at,
            ),
            EventEntityLink(
                event_key=event_key,
                entity_key=team_key,
                role="affected",
                valid_from=announced_at,
            ),
        ),
        impacts=(
            EventImpactWindow(
                event_key=event_key,
                instrument_key=market_instrument_key,
                window_start=announced_at,
                window_end=announced_at + timedelta(days=1),
                direction="NEGATIVE",
                strength=Decimal("0.6"),
                evidence_ref=source_key,
                note="line movement expected after injury disclosure",
            ),
        ),
    )


def macro_release_event(
    *,
    event_key: str,
    title: str,
    indicator: str,
    geography_key: str,
    geography_name: str,
    affected_instrument_keys: tuple[str, ...],
    source_key: str,
    event_time: datetime,
    announced_at: datetime,
    retrieved_at: datetime,
) -> EventGraphRecord:
    """Macro-shaped path: economic release -> geography -> instruments.

    Proves the schema represents non-Sports desks without redesign.
    """
    return EventGraphRecord(
        event=MarketEvent(
            event_key=event_key,
            event_type="economic_release",
            title=title,
            event_time=event_time,
            announced_at=announced_at,
            retrieved_at=retrieved_at,
            source_key=source_key,
            status=EventStatus.OPEN,
            detail={"indicator": indicator},
        ),
        entities=(
            EventEntity(
                entity_key=geography_key,
                entity_type="GEOGRAPHY",
                display_name=geography_name,
                taxonomy={"indicator": indicator},
            ),
        ),
        links=(
            EventEntityLink(
                event_key=event_key,
                entity_key=geography_key,
                role="subject",
                valid_from=announced_at,
            ),
        ),
        impacts=tuple(
            EventImpactWindow(
                event_key=event_key,
                instrument_key=instrument_key,
                window_start=announced_at,
                window_end=announced_at + timedelta(hours=2),
                direction="UNKNOWN",
                strength=Decimal("0"),
                evidence_ref=source_key,
                note="reaction window after release",
            )
            for instrument_key in affected_instrument_keys
        ),
    )


class EventGraphService:
    """Persists event graph records through a caller-supplied repository."""

    def __init__(self, repository: Any) -> None:
        self._repository = repository

    def record(self, graph: EventGraphRecord) -> dict[str, Any]:
        event_id = self._repository.upsert_event(graph.event)
        entity_ids: dict[str, Any] = {}
        for entity in graph.entities:
            entity_ids[entity.entity_key] = self._repository.upsert_entity(entity)
        for link in graph.links:
            self._repository.link_entity(
                link,
                event_id=event_id,
                entity_id=entity_ids[link.entity_key],
            )
        instrument_ids = self._repository.instrument_ids()
        for impact in graph.impacts:
            instrument_id = instrument_ids.get(impact.instrument_key)
            if instrument_id is None:
                raise ValueError(
                    f"impact instrument not registered: {impact.instrument_key}"
                )
            self._repository.upsert_impact(impact, event_id=event_id, instrument_id=instrument_id)
        return {"event_id": event_id, "entities": len(entity_ids), "impacts": len(graph.impacts)}