import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import socket

import pytest

from defend_sports.db import SportsDatabase
from defend_sports.domain import CanonicalEvent, LiveObservation, OddsObservation
from defend_sports.ingestion import IngestionService
from defend_sports.providers.base import ProviderBatch, RawProviderEvent, SportsProvider
from defend_sports.providers.fixture import FixtureSportsProvider
from defend_sports.repositories import SportsRepository

requires_database = pytest.mark.skipif(
    not os.environ.get("SPORTS_TEST_DATABASE_URL"),
    reason="SPORTS_TEST_DATABASE_URL is required for PostgreSQL integration tests",
)

_TWO_MINUTES = timedelta(minutes=2)


@pytest.fixture(scope="session")
def database():
    url = os.environ.get("SPORTS_TEST_DATABASE_URL")
    if not url:
        return None
    database = SportsDatabase(url)
    database.migrate()
    return database


@pytest.fixture(autouse=True)
def _clean_shared_tables(database):
    if database is None:
        yield
        return
    with database.connect() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    TRUNCATE odds_snapshots, live_observations, raw_provider_events,
                             provider_health, selections, markets, sport_events,
                             leagues, participants, sports, provider_sources
                    RESTART IDENTITY CASCADE
                    """
                )
    yield


def _count(connection, table, where=None, params=()):
    sql = f"SELECT count(*) FROM {table}"
    if where:
        sql += f" WHERE {where}"
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return int(cursor.fetchone()[0])


def _rows(connection, sql, params=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


class TestProviderInterface:
    def test_fixture_provider_conforms_to_sports_provider_protocol(self):
        provider = FixtureSportsProvider()
        assert isinstance(provider, SportsProvider)
        assert provider.provider_name == "fixture"

    def test_fixture_provider_poll_is_deterministic(self):
        provider = FixtureSportsProvider()
        assert provider.poll() == provider.poll()

    def test_fixture_provider_poll_makes_no_network_calls(self, monkeypatch):
        def forbidden(*args, **kwargs):
            raise AssertionError("fixture provider attempted a network call")

        with monkeypatch.context() as context:
            context.setattr(socket, "socket", forbidden)
            batch = FixtureSportsProvider().poll()

        assert batch.raw_events
        assert batch.events

    def test_fixture_batch_carries_only_canonical_models(self):
        batch = FixtureSportsProvider().poll()
        assert isinstance(batch, ProviderBatch)
        assert all(isinstance(item, RawProviderEvent) for item in batch.raw_events)
        assert all(isinstance(item, CanonicalEvent) for item in batch.events)
        assert all(isinstance(item, LiveObservation) for item in batch.live)
        assert all(isinstance(item, OddsObservation) for item in batch.odds)
        assert all(item.raw_event_ref for item in batch.live)
        assert all(item.raw_event_ref for item in batch.odds)

    def test_fixture_batch_has_two_books_and_timestamped_decimal_odds(self):
        batch = FixtureSportsProvider().poll()
        sources = {item.source.external_id for item in batch.odds}
        assert sources == {"book-a", "book-b"}
        assert all(item.observed_at is not None for item in batch.odds)
        assert all(item.observed_at.tzinfo is not None for item in batch.odds)
        assert all(isinstance(item.decimal_odds, Decimal) for item in batch.odds)
        assert all(item.decimal_odds > Decimal("1") for item in batch.odds)

    def test_table_tennis_live_state_carries_point_set_server_state(self):
        batch = FixtureSportsProvider().poll()
        table_tennis_live = [item for item in batch.live if item.event_external_id == "tt-live-001"]
        assert table_tennis_live
        state = table_tennis_live[0].state
        assert state["sets"] == [1, 0]
        assert state["games"] == [3, 2]
        assert state["points"] == [2, 1]
        assert state["server"] == "home"

    def test_non_table_tennis_event_is_represented(self):
        batch = FixtureSportsProvider().poll()
        events = {item.event_external_id: item for item in batch.events}
        assert set(events) == {"tt-live-001", "sc-live-001"}
        assert events["sc-live-001"].sport_key == "soccer"
        assert any(item.event_external_id == "sc-live-001" for item in batch.live)
        assert any(item.event_external_id == "sc-live-001" for item in batch.odds)


@requires_database
class TestIngestionPipeline:
    def test_ingest_result_reports_counts(self, database):
        service = IngestionService(database)
        result = service.ingest(FixtureSportsProvider().poll())

        assert result.provider == "fixture"
        assert result.raw_events_created == 2
        assert result.events == 2
        assert result.live_observations == 2
        assert result.odds_snapshots == 8
        assert result.markets == 2
        assert result.selections == 4
        assert result.health == "HEALTHY"

    def test_provider_source_recorded_once(self, database):
        service = IngestionService(database)
        provider = FixtureSportsProvider()

        service.ingest(provider.poll())
        with database.connect() as connection:
            assert _count(connection, "provider_sources") == 3
            rows = _rows(connection, "SELECT provider_name, source_key FROM provider_sources ORDER BY source_key")
            assert rows == [
                ("fixture", "book-a"),
                ("fixture", "book-b"),
                ("fixture", "fixture"),
            ]

        service.ingest(provider.poll())
        with database.connect() as connection:
            assert _count(connection, "provider_sources") == 3

    def test_canonical_event_identity_stored(self, database):
        service = IngestionService(database)
        service.ingest(FixtureSportsProvider().poll())

        with database.connect() as connection:
            row = _rows(
                connection,
                """
                SELECT e.event_key, e.display_name, e.scheduled_at, s.sport_key, l.league_key
                FROM sport_events e
                JOIN sports s ON s.sport_id = e.sport_id
                LEFT JOIN leagues l ON l.league_id = e.league_id
                WHERE e.event_key = %s
                """,
                ("tt-live-001",),
            )[0]

        assert row[0] == "tt-live-001"
        assert row[1] == "Player A vs Player B"
        assert row[2] == datetime(2026, 8, 14, 10, 0, tzinfo=timezone.utc)
        assert row[3] == "table_tennis"
        assert row[4] == "tt_wtt"

    def test_duplicate_provider_event_ingestion_is_idempotent(self, database):
        service = IngestionService(database)
        batch = FixtureSportsProvider().poll()

        service.ingest(batch)
        with database.connect() as connection:
            before = {
                "raw": _count(connection, "raw_provider_events"),
                "odds": _count(connection, "odds_snapshots"),
                "live": _count(connection, "live_observations"),
                "events": _count(connection, "sport_events"),
                "sources": _count(connection, "provider_sources"),
            }

        service.ingest(batch)
        with database.connect() as connection:
            after = {
                "raw": _count(connection, "raw_provider_events"),
                "odds": _count(connection, "odds_snapshots"),
                "live": _count(connection, "live_observations"),
                "events": _count(connection, "sport_events"),
                "sources": _count(connection, "provider_sources"),
            }

        assert before == after

    def test_odds_history_appends_never_overwrites(self, database):
        service = IngestionService(database)
        provider = FixtureSportsProvider()

        service.ingest(provider.poll())
        service.ingest(provider.poll(observed_at=provider.base_observed_at + _TWO_MINUTES))

        with database.connect() as connection:
            rows = _rows(
                connection,
                """
                SELECT o.decimal_odds, p.source_key, o.observed_at
                FROM odds_snapshots o
                JOIN provider_sources p ON p.source_id = o.source_id
                JOIN selections s ON s.selection_id = o.selection_id
                JOIN markets m ON m.market_id = s.market_id
                JOIN sport_events e ON e.event_id = m.event_id
                WHERE e.event_key = 'tt-live-001'
                  AND m.market_key = 'match_winner'
                  AND s.selection_key = 'player_a'
                ORDER BY o.observed_at, p.source_key
                """,
            )

        assert len(rows) == 4
        prices = [row[0] for row in rows]
        assert prices == [
            Decimal("1.85"),
            Decimal("1.92"),
            Decimal("1.80"),
            Decimal("1.95"),
        ]
        assert Decimal("1.85") in prices
        assert Decimal("1.80") in prices

    def test_live_state_appends_historically(self, database):
        service = IngestionService(database)
        provider = FixtureSportsProvider()

        service.ingest(provider.poll())
        service.ingest(provider.poll(observed_at=provider.base_observed_at + _TWO_MINUTES))

        with database.connect() as connection:
            rows = _rows(
                connection,
                """
                SELECT o.state_json, o.observed_at
                FROM live_observations o
                JOIN sport_events e ON e.event_id = o.event_id
                WHERE e.event_key = 'tt-live-001'
                ORDER BY o.observed_at
                """,
            )

        assert len(rows) == 2
        assert rows[0][0]["sets"] == [1, 0]
        assert rows[0][0]["points"] == [2, 1]
        assert rows[1][0]["points"] == [4, 2]
        assert rows[1][0]["server"] in {"home", "away"}
        assert rows[0][1] != rows[1][1]

    def test_raw_provenance_retained(self, database):
        service = IngestionService(database)
        service.ingest(FixtureSportsProvider().poll())

        with database.connect() as connection:
            raw_rows = _rows(
                connection,
                "SELECT provider_event_id, payload FROM raw_provider_events ORDER BY provider_event_id",
            )
            assert len(raw_rows) == 2

            payloads = {provider_event_id: payload for provider_event_id, payload in raw_rows}
            table_tennis_payload = next(
                payload for key, payload in payloads.items() if "tt-live-001" in key
            )
            assert table_tennis_payload["match_id"] == "tt-live-001"
            assert set(table_tennis_payload["books"]) == {"book-a", "book-b"}
            assert isinstance(
                table_tennis_payload["books"]["book-a"]["match_winner"]["home"], str
            )

            linked_odds = _rows(
                connection,
                """
                SELECT DISTINCT rp.provider_event_id
                FROM odds_snapshots o
                JOIN raw_provider_events rp ON rp.raw_event_id = o.raw_event_id
                """,
            )
            assert len(linked_odds) == 2

            live_links = _rows(connection, "SELECT raw_event_id FROM live_observations")
            assert live_links
            assert all(row[0] is not None for row in live_links)

    def test_observed_at_and_received_at_remain_distinct(self, database):
        service = IngestionService(database)
        provider = FixtureSportsProvider()
        service.ingest(provider.poll())

        with database.connect() as connection:
            row = _rows(
                connection,
                """
                SELECT o.observed_at, o.received_at
                FROM odds_snapshots o
                JOIN selections s ON s.selection_id = o.selection_id
                WHERE s.selection_key = 'player_a'
                ORDER BY o.observed_at
                LIMIT 1
                """,
            )[0]

        observed_at, received_at = row
        assert observed_at.tzinfo is not None
        assert received_at.tzinfo is not None
        assert observed_at == provider.base_observed_at
        assert received_at > observed_at

    def test_provider_health_tracks_success_and_failure(self, database, monkeypatch):
        provider = FixtureSportsProvider()
        service = IngestionService(database)
        service.ingest(provider.poll())

        with database.connect() as connection:
            latest = _rows(
                connection,
                "SELECT status FROM provider_health ORDER BY provider_health_id DESC LIMIT 1",
            )[0][0]
        assert latest == "HEALTHY"

        repository = SportsRepository()

        def failing_append_odds_snapshot(*args, **kwargs):
            raise RuntimeError("simulated provider failure")

        monkeypatch.setattr(repository, "append_odds_snapshot", failing_append_odds_snapshot)
        failing_service = IngestionService(database, repository=repository)

        with pytest.raises(RuntimeError, match="simulated provider failure"):
            failing_service.ingest(provider.poll(observed_at=provider.base_observed_at + _TWO_MINUTES))

        with database.connect() as connection:
            assert _count(connection, "raw_provider_events") == 2
            assert _count(connection, "odds_snapshots") == 8
            assert _count(connection, "live_observations") == 2
            latest = _rows(
                connection,
                "SELECT status, detail_json FROM provider_health ORDER BY provider_health_id DESC LIMIT 1",
            )[0]

        assert latest[0] == "UNAVAILABLE"
        assert "simulated provider failure" in latest[1]["error"]

    def test_table_tennis_and_other_sport_ingest_through_same_pipeline(self, database):
        service = IngestionService(database)
        service.ingest(FixtureSportsProvider().poll())

        with database.connect() as connection:
            sport_keys = _rows(
                connection,
                """
                SELECT DISTINCT s.sport_key
                FROM sport_events e
                JOIN sports s ON s.sport_id = e.sport_id
                ORDER BY s.sport_key
                """,
            )
            assert [row[0] for row in sport_keys] == ["soccer", "table_tennis"]

            per_event_odds = _rows(
                connection,
                """
                SELECT e.event_key, count(*)
                FROM odds_snapshots o
                JOIN selections s ON s.selection_id = o.selection_id
                JOIN markets m ON m.market_id = s.market_id
                JOIN sport_events e ON e.event_id = m.event_id
                GROUP BY e.event_key
                ORDER BY e.event_key
                """,
            )
            assert [row[0] for row in per_event_odds] == ["sc-live-001", "tt-live-001"]
            assert all(row[1] >= 1 for row in per_event_odds)

    def test_canonical_tables_carry_no_vendor_field_names(self, database):
        service = IngestionService(database)
        service.ingest(FixtureSportsProvider().poll())

        with database.connect() as connection:
            columns = _rows(
                connection,
                """
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name IN ('sport_events', 'live_observations', 'markets',
                                     'selections', 'odds_snapshots')
                """,
            )

        names = {column for _, column in columns}
        for vendor_field in ("match_id", "moneyline", "scoreboard", "spread", "gameid"):
            assert vendor_field not in names