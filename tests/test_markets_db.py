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