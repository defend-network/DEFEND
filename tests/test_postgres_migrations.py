"""Real PostgreSQL migration proofs + provider-integrity negative tests.

Runs ONLY against defendcoder_test (guarded). Resets the schema between
tests by dropping all public tables (owned by the app role after grants).
"""

from __future__ import annotations

import os
import urllib.parse

import pytest

psycopg = pytest.importorskip("psycopg")

from defend_coder.authority_store import (
    PostgresAuthorityStore,
    StartupIntegrityError,
)
from defend_coder.db import CoderDatabase, _MIGRATIONS, _migration_statements
from defend_coder.registry import build_provider_technical_profile

TEST_DB = "defendcoder_test"


def _test_url() -> str:
    url = os.environ.get("CODER_DATABASE_URL", "")
    if not url:
        pytest.skip("CODER_DATABASE_URL is not set")
    p = urllib.parse.urlsplit(url)
    host = p.hostname or "127.0.0.1"
    port = p.port or 5432
    user = p.username or "defendcoder"
    password = p.password or ""
    query = ("?" + p.query) if p.query else ""
    return f"postgresql://{user}:{password}@{host}:{port}/{TEST_DB}{query}"


@pytest.fixture(scope="module")
def db() -> CoderDatabase:
    url = _test_url()
    try:
        conn = psycopg.connect(url, connect_timeout=5)
        conn.close()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"defendcoder_test not reachable: {type(exc).__name__}")
    return CoderDatabase(url)


def _guard(connection) -> None:
    with connection.cursor() as cur:
        cur.execute("SELECT current_database()")
        assert cur.fetchone()[0] == TEST_DB


def _reset(db: CoderDatabase) -> None:
    with db.connect() as connection:
        _guard(connection)
        with connection.cursor() as cur:
            cur.execute(
                """
                DO $$
                DECLARE r record;
                BEGIN
                    FOR r IN SELECT tablename FROM pg_tables
                             WHERE schemaname = 'public'
                    LOOP
                        EXECUTE 'DROP TABLE IF EXISTS public.'
                            || quote_ident(r.tablename) || ' CASCADE';
                    END LOOP;
                END $$;
                """
            )


def _apply_up_to(db: CoderDatabase, upto: int) -> None:
    with db.connect() as connection:
        _guard(connection)
        with connection.cursor() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS coder_schema_migrations ("
                "version INTEGER PRIMARY KEY CHECK (version > 0),"
                "applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            for version, path in _MIGRATIONS:
                if version > upto:
                    break
                for statement in _migration_statements(path):
                    cur.execute(statement)
                cur.execute(
                    "INSERT INTO coder_schema_migrations(version) VALUES (%s)",
                    (version,),
                )


class TestMigrationProofs:
    def test_clean_to_latest(self, db):
        _reset(db)
        version = db.migrate()
        assert version == _MIGRATIONS[-1][0]

    def test_schema9_to_latest(self, db):
        _reset(db)
        _apply_up_to(db, 9)
        version = db.migrate()
        assert version == _MIGRATIONS[-1][0]

    def test_schema10_to_latest(self, db):
        _reset(db)
        _apply_up_to(db, 10)
        version = db.migrate()
        assert version == _MIGRATIONS[-1][0]

    def test_migrate_idempotent(self, db):
        _reset(db)
        first = db.migrate()
        second = db.migrate()
        assert first == second == _MIGRATIONS[-1][0]


class TestProviderIntegrity:
    def test_cross_provider_technical_activation_fails(self, db):
        _reset(db)
        db.migrate()
        store = PostgresAuthorityStore(db)
        from defend_coder.authority_store import hydrate_authority

        hydrate_authority(store)
        openai = build_provider_technical_profile("openai")
        with pytest.raises(StartupIntegrityError):
            store.set_technical_active(
                "deepseek", openai.profile_id, openai.version
            )

    def test_active_technical_backfilled_after_schema10(self, db):
        # Simulate the schema-10 -> 11 upgrade: profiles exist (migration 11
        # just created the still-empty active-pointer table).
        _reset(db)
        _apply_up_to(db, 11)
        store = PostgresAuthorityStore(db)
        for provider in ("deepseek", "qwen3-vllm", "openai"):
            store.save_technical(build_provider_technical_profile(provider))
        assert store.active_technical_for("deepseek") is None
        from defend_coder.authority_store import hydrate_authority

        hydrate_authority(store)
        for provider in ("deepseek", "qwen3-vllm", "openai"):
            assert store.active_technical_for(provider) is not None
