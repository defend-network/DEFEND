from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from defend_markets.domain import EventStatus, EventImpactWindow
from defend_markets.events import (
    EventGraphRecord,
    EventGraphService,
    macro_release_event,
    sports_injury_event,
)

NOW = datetime(2026, 8, 15, 10, 0, tzinfo=timezone.utc)


class FakeGraphRepository:
    def __init__(self, instruments: dict[str, str] | None = None) -> None:
        self.instruments = dict(instruments or {})
        self.events: list[object] = []
        self.entities: list[object] = []
        self.links: list[tuple[object, object, object]] = []
        self.impacts: list[tuple[object, object, object]] = []

    def upsert_event(self, event) -> str:
        self.events.append(event)
        return f"event-{len(self.events)}"

    def upsert_entity(self, entity) -> str:
        self.entities.append(entity)
        return f"entity-{entity.entity_key}"

    def link_entity(self, link, *, event_id: str, entity_id: str) -> None:
        self.links.append((link, event_id, entity_id))

    def instrument_ids(self) -> dict[str, str]:
        return dict(self.instruments)

    def upsert_impact(self, impact, *, event_id: str, instrument_id: str) -> None:
        self.impacts.append((impact, event_id, instrument_id))


class TestSportsInjuryGraph:
    def test_shape_matches_real_sports_path(self):
        graph = sports_injury_event(
            event_key="inj-20260815-p1",
            title="Player A injured at practice",
            player_key="tt:player:a",
            player_name="Player A",
            team_key="tt:team:x",
            team_name="Team X",
            market_instrument_key="sports:tt-live-001:match_winner",
            source_key="book-a",
            announced_at=NOW,
            retrieved_at=NOW,
        )
        assert graph.event.event_type == "injury_news"
        assert graph.event.status is EventStatus.OPEN
        assert {entity.entity_type for entity in graph.entities} == {"PLAYER", "TEAM"}
        assert len(graph.links) == 2
        assert len(graph.impacts) == 1
        impact = graph.impacts[0]
        assert impact.direction == "NEGATIVE"
        assert impact.strength == Decimal("0.6")
        assert impact.instrument_key == "sports:tt-live-001:match_winner"
        assert impact.window_end > impact.window_start

    def test_service_persists_graph(self):
        repository = FakeGraphRepository(
            instruments={"sports:tt-live-001:match_winner": str(uuid4())}
        )
        service = EventGraphService(repository)
        graph = sports_injury_event(
            event_key="inj-1",
            title="Injury",
            player_key="tt:player:a",
            player_name="Player A",
            team_key="tt:team:x",
            team_name="Team X",
            market_instrument_key="sports:tt-live-001:match_winner",
            source_key="book-a",
            announced_at=NOW,
            retrieved_at=NOW,
        )
        result = service.record(graph)
        assert result["event_id"] == "event-1"
        assert result["entities"] == 2
        assert result["impacts"] == 1
        assert len(repository.links) == 2
        assert len(repository.impacts) == 1

    def test_service_rejects_unknown_instrument(self):
        repository = FakeGraphRepository(instruments={})
        service = EventGraphService(repository)
        graph = sports_injury_event(
            event_key="inj-2",
            title="Injury",
            player_key="tt:player:a",
            player_name="Player A",
            team_key="tt:team:x",
            team_name="Team X",
            market_instrument_key="sports:tt-live-001:match_winner",
            source_key="book-a",
            announced_at=NOW,
            retrieved_at=NOW,
        )
        with pytest.raises(ValueError, match="impact instrument not registered"):
            service.record(graph)


class TestMacroGraph:
    def test_non_sports_desk_uses_same_schema(self):
        graph = macro_release_event(
            event_key="cpi-2026-08",
            title="US CPI release",
            indicator="cpi_yoy",
            geography_key="geo:us",
            geography_name="United States",
            affected_instrument_keys=("macro:us:cpi_yoy", "fx:usd:index"),
            source_key="bls",
            event_time=NOW,
            announced_at=NOW,
            retrieved_at=NOW,
        )
        assert graph.event.event_type == "economic_release"
        assert graph.event.detail == {"indicator": "cpi_yoy"}
        assert len(graph.impacts) == 2
        for impact in graph.impacts:
            assert impact.window_end > impact.window_start

    def test_macro_graph_persists(self):
        repository = FakeGraphRepository(
            instruments={
                "macro:us:cpi_yoy": str(uuid4()),
                "fx:usd:index": str(uuid4()),
            }
        )
        service = EventGraphService(repository)
        graph = macro_release_event(
            event_key="cpi-2026-08",
            title="US CPI release",
            indicator="cpi_yoy",
            geography_key="geo:us",
            geography_name="United States",
            affected_instrument_keys=("macro:us:cpi_yoy", "fx:usd:index"),
            source_key="bls",
            event_time=NOW,
            announced_at=NOW,
            retrieved_at=NOW,
        )
        result = service.record(graph)
        assert result["impacts"] == 2
        assert result["entities"] == 1


def test_impact_window_requires_end_after_start():
    with pytest.raises(ValueError, match="window_end"):
        EventImpactWindow(
            event_key="e",
            instrument_key="i",
            window_start=NOW,
            window_end=NOW,
        )