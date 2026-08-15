import os
from pathlib import Path
import re

import pytest

from defend_sports.db import SportsDatabase


_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "defend_sports"
    / "migrations"
    / "0001_foundation.sql"
)
_REQUIRED_TABLES = {
    "sports_schema_migrations",
    "sports_users",
    "sports_user_risk",
    "sportsbooks",
    "sports",
    "leagues",
    "participants",
    "sport_events",
    "live_observations",
    "markets",
    "selections",
    "odds_snapshots",
    "provider_sources",
    "provider_health",
    "raw_provider_events",
    "audit_events",
}
_SHARED_MARKET_TABLES = {
    "sportsbooks",
    "sports",
    "leagues",
    "participants",
    "sport_events",
    "live_observations",
    "markets",
    "selections",
    "odds_snapshots",
    "provider_sources",
    "provider_health",
    "raw_provider_events",
}


def test_foundation_migration_defines_the_required_neutral_schema():
    migration = _MIGRATION_PATH.read_text(encoding="utf-8")

    for table in _REQUIRED_TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in migration

    assert "role TEXT NOT NULL CHECK (role IN ('OWNER', 'ADMIN', 'ANALYST', 'MEMBER'))" in migration
    assert "bankroll NUMERIC(18,4) NOT NULL CHECK (bankroll >= 0)" in migration
    assert "user_max_stake_pct NUMERIC(8,6) NOT NULL CHECK" in migration
    assert "state_json JSONB NOT NULL" in migration
    assert "decimal_odds NUMERIC(18,6) NOT NULL CHECK (decimal_odds > 1)" in migration
    assert "raw_event_id UUID NOT NULL REFERENCES raw_provider_events(raw_event_id)" in migration
    assert "qwen" not in migration.casefold()
    assert "huggingface" not in migration.casefold()

    for table in _SHARED_MARKET_TABLES:
        table_definition = re.search(
            rf"CREATE TABLE IF NOT EXISTS {table} \((.*?)\n\);",
            migration,
            flags=re.DOTALL,
        )
        assert table_definition is not None
        assert "user_id" not in table_definition.group(1)


def test_database_representation_never_exposes_its_connection_url():
    database = SportsDatabase("postgresql://sports:secret@db.example/sports")

    assert "secret" not in repr(database)
    assert "database_url" not in repr(database)


@pytest.mark.skipif(
    not os.environ.get("SPORTS_TEST_DATABASE_URL"),
    reason="SPORTS_TEST_DATABASE_URL is required for PostgreSQL integration tests",
)
def test_migration_is_idempotent_and_health_reports_version_one():
    database = SportsDatabase(os.environ["SPORTS_TEST_DATABASE_URL"])

    assert database.migrate() == 1
    assert database.migrate() == 1
    assert database.health() == {
        "ok": True,
        "application_id": "sports",
        "schema_version": 1,
        "database": "ready",
    }

    with database.connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = ANY(%s)
                """,
                (list(_REQUIRED_TABLES),),
            )
            columns_by_table: dict[str, set[str]] = {}
            for table_name, column_name in cursor.fetchall():
                columns_by_table.setdefault(table_name, set()).add(column_name)

    assert set(columns_by_table) == _REQUIRED_TABLES
    for table in _SHARED_MARKET_TABLES:
        assert "user_id" not in columns_by_table[table]
