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
_ALL_MIGRATED_TABLES = _REQUIRED_TABLES | {
    "provider_discovery",
    "provider_quota",
    "backfill_checkpoints",
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
_MIGRATION_V2_PATH = (
    Path(__file__).resolve().parents[1]
    / "defend_sports"
    / "migrations"
    / "0002_quota_discovery.sql"
)
_MIGRATION_V3_PATH = (
    Path(__file__).resolve().parents[1]
    / "defend_sports"
    / "migrations"
    / "0003_backfill.sql"
)
_MIGRATION_V4_PATH = (
    Path(__file__).resolve().parents[1]
    / "defend_sports"
    / "migrations"
    / "0004_raw_provider_uniqueness.sql"
)
_RAW_PROVIDER_UNIQUENESS_INDEX = "raw_provider_events_sport_key_unique"


def test_raw_provider_uniqueness_migration_defines_the_approved_invariant():
    migration = _MIGRATION_V4_PATH.read_text(encoding="utf-8")
    assert "CREATE UNIQUE INDEX IF NOT EXISTS" in migration
    assert _RAW_PROVIDER_UNIQUENESS_INDEX in migration
    assert "source_id, COALESCE(payload->'sport'->>'slug', ''), provider_event_id" in migration
    assert "DROP" not in migration.casefold()
    assert "DELETE" not in migration.casefold()
    assert "TRUNCATE" not in migration.casefold()


def test_backfill_migration_defines_expected_schema():
    migration = _MIGRATION_V3_PATH.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS backfill_checkpoints" in migration
    assert "UNIQUE (provider, sport, league, window_from, window_to)" in migration
    assert "cursor_value TEXT NOT NULL DEFAULT ''" in migration
    assert "status TEXT NOT NULL DEFAULT 'RUNNING'" in migration
    assert "requests_used BIGINT NOT NULL DEFAULT 0" in migration


def test_quota_discovery_migration_defines_expected_schema():
    migration = _MIGRATION_V2_PATH.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS provider_discovery" in migration
    assert "CREATE TABLE IF NOT EXISTS provider_quota" in migration
    assert "source_id UUID NOT NULL REFERENCES provider_sources(source_id)" in migration
    assert "requests_remaining BIGINT" in migration
    assert "status TEXT NOT NULL" in migration
    assert "observed_at TIMESTAMPTZ NOT NULL" in migration


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
def test_migration_is_idempotent_and_health_reports_version_four():
    database = SportsDatabase(os.environ["SPORTS_TEST_DATABASE_URL"])

    assert database.migrate() == 4
    assert database.migrate() == 4
    assert database.health() == {
        "ok": True,
        "application_id": "sports",
        "schema_version": 4,
        "database": "ready",
    }


@pytest.mark.skipif(
    not os.environ.get("SPORTS_TEST_DATABASE_URL"),
    reason="SPORTS_TEST_DATABASE_URL is required for PostgreSQL integration tests",
)
def test_raw_provider_uniqueness_index_is_applied_and_enforces_the_invariant():
    database = SportsDatabase(os.environ["SPORTS_TEST_DATABASE_URL"])

    assert database.migrate() == 4
    assert database.migrate() == 4

    with database.connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT indexdef FROM pg_indexes
                WHERE schemaname = current_schema()
                  AND indexname = %s
                """,
                (_RAW_PROVIDER_UNIQUENESS_INDEX,),
            )
            indexdef = cursor.fetchone()
            assert indexdef is not None
            assert "COALESCE" in indexdef[0]
            assert "source_id" in indexdef[0]
            assert "provider_event_id" in indexdef[0]
            assert "payload -> 'sport'" in indexdef[0]

            cursor.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT source_id,
                           COALESCE(payload->'sport'->>'slug', ''),
                           provider_event_id,
                           COUNT(*)
                    FROM raw_provider_events
                    GROUP BY 1, 2, 3
                    HAVING COUNT(*) > 1
                ) violations
                """
            )
            assert cursor.fetchone()[0] == 0

    with database.connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = ANY(%s)
                """,
                (list(_ALL_MIGRATED_TABLES),),
            )
            columns_by_table: dict[str, set[str]] = {}
            for table_name, column_name in cursor.fetchall():
                columns_by_table.setdefault(table_name, set()).add(column_name)

    assert set(columns_by_table) == _ALL_MIGRATED_TABLES
    for table in _SHARED_MARKET_TABLES:
        assert "user_id" not in columns_by_table[table]
