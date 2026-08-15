"""Deterministic fixture sports provider for DS1 ingestion tests.

No network access. The fixture emits one table-tennis live event and one
non-table-tennis (soccer) event with two sportsbook sources and timestamped
decimal prices. Polls at different observation times produce shifted,
still-deterministic batches.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from defend_sports.domain import (
    CanonicalEvent,
    LiveObservation,
    OddsObservation,
    SourceRef,
)
from defend_sports.providers.base import ProviderBatch, RawProviderEvent, SportsProvider

_BASE_OBSERVED_AT = datetime(2026, 8, 14, 12, 0, 0, tzinfo=timezone.utc)


def _minutes_since(observed_at: datetime, base: datetime) -> int:
    return max(0, int((observed_at - base).total_seconds() // 60))


def _table_tennis_live_state(minutes: int) -> dict[str, object]:
    return {
        "status": "live",
        "sport": "table_tennis",
        "sets": [1, 0],
        "games": [3, 2],
        "points": [2 + minutes, 1 + minutes // 2],
        "server": "home" if minutes % 2 == 0 else "away",
    }


def _soccer_live_state(minutes: int) -> dict[str, object]:
    return {
        "status": "live",
        "sport": "soccer",
        "minute": 63 + minutes,
        "score": {"home": 1, "away": 0},
        "period": "second_half",
    }


def _table_tennis_raw_payload(minutes: int) -> dict[str, object]:
    return {
        "match_id": "tt-live-001",
        "sport": "table_tennis",
        "scoreboard": _table_tennis_live_state(minutes),
        "participants": [
            {"id": "p-1", "name": "Player A"},
            {"id": "p-2", "name": "Player B"},
        ],
        "books": {
            "book-a": {"match_winner": {"home": "1.85", "away": "2.05"}},
            "book-b": {"match_winner": {"home": "1.92", "away": "2.00"}},
        },
    }


def _soccer_raw_payload() -> dict[str, object]:
    return {
        "match_id": "sc-live-001",
        "sport": "soccer",
        "scoreboard": _soccer_live_state(0),
        "participants": [
            {"id": "t-1", "name": "Rovers FC"},
            {"id": "t-2", "name": "United FC"},
        ],
        "books": {
            "book-a": {"match_winner": {"home": "2.10", "away": "3.40"}},
            "book-b": {"match_winner": {"home": "2.05", "away": "3.30"}},
        },
    }


def _table_tennis_home_price(minutes: int, book_key: str) -> Decimal:
    step = minutes // 2
    if book_key == "book-a":
        return Decimal("1.85") - Decimal("0.05") * step
    return Decimal("1.92") + Decimal("0.03") * step


@dataclass(frozen=True)
class FixtureSportsProvider:
    provider_name: str = "fixture"
    base_observed_at: datetime = _BASE_OBSERVED_AT

    def poll(self, observed_at: datetime | None = None) -> ProviderBatch:
        observed_at = observed_at if observed_at is not None else self.base_observed_at
        minutes = _minutes_since(observed_at, self.base_observed_at)

        root = SourceRef(provider=self.provider_name, external_id=self.provider_name)
        book_a = SourceRef(provider=self.provider_name, external_id="book-a")
        book_b = SourceRef(provider=self.provider_name, external_id="book-b")

        table_tennis_ref = f"fixture-tt-live-001@{observed_at.isoformat()}"
        soccer_ref = f"fixture-sc-live-001@{observed_at.isoformat()}"

        raw_events = (
            RawProviderEvent(
                source=root,
                provider_event_id=table_tennis_ref,
                payload=_table_tennis_raw_payload(minutes),
                observed_at=observed_at,
                display_name="Fixture Feed",
            ),
            RawProviderEvent(
                source=root,
                provider_event_id=soccer_ref,
                payload=_soccer_raw_payload(),
                observed_at=observed_at,
                display_name="Fixture Feed",
            ),
        )

        events = (
            CanonicalEvent(
                event_external_id="tt-live-001",
                sport_key="table_tennis",
                league_key="tt_wtt",
                display_name="Player A vs Player B",
                scheduled_at=datetime(2026, 8, 14, 10, 0, tzinfo=timezone.utc),
                raw_event_ref=table_tennis_ref,
            ),
            CanonicalEvent(
                event_external_id="sc-live-001",
                sport_key="soccer",
                league_key="soccer_england",
                display_name="Rovers FC vs United FC",
                scheduled_at=datetime(2026, 8, 14, 11, 0, tzinfo=timezone.utc),
                raw_event_ref=soccer_ref,
            ),
        )

        live = (
            LiveObservation(
                source=book_a,
                event_external_id="tt-live-001",
                state=_table_tennis_live_state(minutes),
                observed_at=observed_at,
                raw_event_ref=table_tennis_ref,
            ),
            LiveObservation(
                source=book_b,
                event_external_id="sc-live-001",
                state=_soccer_live_state(minutes),
                observed_at=observed_at,
                raw_event_ref=soccer_ref,
            ),
        )

        odds = (
            OddsObservation(
                source=book_a,
                event_external_id="tt-live-001",
                market_key="match_winner",
                selection_key="player_a",
                decimal_odds=_table_tennis_home_price(minutes, "book-a"),
                observed_at=observed_at,
                raw_event_ref=table_tennis_ref,
            ),
            OddsObservation(
                source=book_a,
                event_external_id="tt-live-001",
                market_key="match_winner",
                selection_key="player_b",
                decimal_odds=Decimal("2.05"),
                observed_at=observed_at,
                raw_event_ref=table_tennis_ref,
            ),
            OddsObservation(
                source=book_b,
                event_external_id="tt-live-001",
                market_key="match_winner",
                selection_key="player_a",
                decimal_odds=_table_tennis_home_price(minutes, "book-b"),
                observed_at=observed_at,
                raw_event_ref=table_tennis_ref,
            ),
            OddsObservation(
                source=book_b,
                event_external_id="tt-live-001",
                market_key="match_winner",
                selection_key="player_b",
                decimal_odds=Decimal("2.00"),
                observed_at=observed_at,
                raw_event_ref=table_tennis_ref,
            ),
            OddsObservation(
                source=book_a,
                event_external_id="sc-live-001",
                market_key="match_winner",
                selection_key="home",
                decimal_odds=Decimal("2.10"),
                observed_at=observed_at,
                raw_event_ref=soccer_ref,
            ),
            OddsObservation(
                source=book_a,
                event_external_id="sc-live-001",
                market_key="match_winner",
                selection_key="away",
                decimal_odds=Decimal("3.40"),
                observed_at=observed_at,
                raw_event_ref=soccer_ref,
            ),
            OddsObservation(
                source=book_b,
                event_external_id="sc-live-001",
                market_key="match_winner",
                selection_key="home",
                decimal_odds=Decimal("2.05"),
                observed_at=observed_at,
                raw_event_ref=soccer_ref,
            ),
            OddsObservation(
                source=book_b,
                event_external_id="sc-live-001",
                market_key="match_winner",
                selection_key="away",
                decimal_odds=Decimal("3.30"),
                observed_at=observed_at,
                raw_event_ref=soccer_ref,
            ),
        )

        return ProviderBatch(raw_events=raw_events, events=events, live=live, odds=odds)


__all__ = ["FixtureSportsProvider"]