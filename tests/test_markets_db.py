from __future__ import annotations

import os

import pytest

HAS_DATABASE_URL = bool(os.environ.get("MARKETS_TEST_DATABASE_URL"))

pytestmark = pytest.mark.skipif(
    not HAS_DATABASE_URL,
    reason="MARKETS_TEST_DATABASE_URL not configured; DB-gated tests skipped",
)


def _database():
    from defend_markets.db import MarketsDatabase

    return MarketsDatabase(os.environ["MARKETS_TEST_DATABASE_URL"])


def test_migration_is_idempotent_and_repeatable():
    database = _database()
    database.migrate()
    database.migrate()
    database.migrate()


def test_expected_tables_exist_after_migration():
    database = _database()
    database.migrate()
    expected = {
        "market_schema_migrations",
        "market_instruments",
        "market_instrument_links",
        "market_events",
        "market_event_entities",
        "market_event_entity_links",
        "market_event_impacts",
        "market_strategies",
        "market_strategy_runs",
        "market_strategy_results",
        "market_risk_policies",
        "market_outcomes",
        "market_decisions",
        "market_opportunities",
        "market_data_quality",
        "tt_participants",
        "tt_participant_aliases",
        "tt_collector_state",
        "tt_feature_snapshots",
        "tt_predictions",
        "tt_prediction_amendments",
        "tt_settlements",
        "tt_shadow_predictions",
        "tt_research_ledger",
        "tt_rating_history",
    }
    with database.connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
            )
            tables = {row[0] for row in cursor.fetchall()}
    assert expected <= tables


def test_seed_defaults_is_idempotent():
    database = _database()
    database.migrate()
    from defend_markets.repositories import MarketsRepository

    repository = MarketsRepository()
    with database.connect() as connection:
        with connection.transaction():
            repository.seed_defaults(connection)
            strategy_count_before = len(repository.list_strategies(connection))
            policy_count_before = len(repository.list_policies(connection))
            repository.seed_defaults(connection)
            assert len(repository.list_strategies(connection)) == strategy_count_before
            assert len(repository.list_policies(connection)) == policy_count_before


def test_seeded_defaults_are_versioned():
    database = _database()
    database.migrate()
    from defend_markets.repositories import MarketsRepository

    repository = MarketsRepository()
    with database.connect() as connection:
        with connection.transaction():
            repository.seed_defaults(connection)
            strategies = {item["strategy_key"]: item for item in repository.list_strategies(connection)}
            policies = {item["policy_key"]: item for item in repository.list_policies(connection)}
    assert strategies["tt_two_way_arb"]["lifecycle"] == "EXPERIMENTAL"
    assert strategies["tt_clv"]["lifecycle"] == "PLANNED"
    assert policies["markets_core"]["version"] == 1


def test_identity_alias_resolution_round_trip():
    database = _database()
    database.migrate()
    from datetime import datetime, timezone

    from defend_markets.forecast_store import PostgresForecastStore
    from defend_markets.identity import IDENTITY_CONFIRMED, IdentityService

    store = PostgresForecastStore(database)
    service = IdentityService(
        store, clock=lambda: datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    )
    with database.connect() as connection, connection.cursor() as cursor:
        cursor.execute("DELETE FROM tt_participant_aliases")
        cursor.execute("DELETE FROM tt_participants")
    primary = service.resolve("Havel, Ladislav", provider="odds_api_io", raw_ref="899515")
    service.confirm_alias(
        int(primary["participant_id"]),
        alias_name="Havel, Ladislav (1956)",
        provider="odds_api_io",
        raw_ref="899515",
    )
    variant = service.resolve(
        "Havel, Ladislav (1956)", provider="odds_api_io", raw_ref="899515"
    )
    assert variant["participant_id"] == primary["participant_id"]
    assert variant["identity_state"] == IDENTITY_CONFIRMED
    rows = store.participant_by_normalized("havel ladislav 1956")
    assert len(rows) == 1
    assert rows[0]["participant_id"] == primary["participant_id"]


def test_rating_history_store_round_trip():
    database = _database()
    database.migrate()
    from datetime import datetime, timezone

    from defend_markets.domain import TTMatchResult
    from defend_markets.forecast_store import PostgresForecastStore
    from defend_markets.tt_rating import TTRatingHistoryRow, rebuild_rating_history

    with database.connect() as connection, connection.cursor() as cursor:
        cursor.execute("DELETE FROM tt_rating_history WHERE participant_key LIKE %s", ("table_tennis:%",))

    rows = rebuild_rating_history(
        [
            TTMatchResult(
                event_key="e1",
                league_key="tt",
                home_participant_key="table_tennis:alice",
                away_participant_key="table_tennis:bob",
                home_score=3,
                away_score=1,
                completed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                source_provider="odds_api_io",
                raw_ref="oaio:e1@hist:20260101",
            ),
        ]
    )
    assert len(rows) == 2
    assert all(isinstance(row, TTRatingHistoryRow) for row in rows)
    store = PostgresForecastStore(database)
    first = store.insert_rating_history(rows)
    second = store.insert_rating_history(rows)
    assert first == 2
    assert second == 0
    catalog = store.catalog_rating_history("table_tennis:alice")
    assert len(catalog) == 1
    assert catalog[0]["result"] == "win"
    assert catalog[0]["source_provider"] == "odds_api_io"
    assert float(catalog[0]["pre_rating"]) == 1200.0
    assert float(catalog[0]["post_rating"]) > 1200.0