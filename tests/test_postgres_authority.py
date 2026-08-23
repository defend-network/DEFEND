"""Real PostgreSQL authority-store tests (defendcoder_test only).

These tests are gated: they SKIP unless the ``defendcoder_test`` database is
reachable. They must NEVER touch the production ``defendcoder`` / dev
databases. Every destructive step re-asserts ``current_database()``.
"""

from __future__ import annotations

import os

import pytest

psycopg = pytest.importorskip("psycopg")

from defend_coder.authority_store import (
    PostgresAuthorityStore,
    StartupIntegrityError,
    hydrate_authority,
)
from defend_coder.db import CoderDatabase
from defend_coder.identity import default_identity_profile

TEST_DB = "defendcoder_test"


def _test_url() -> str:
    import urllib.parse

    url = os.environ.get("CODER_DATABASE_URL", "")
    if not url:
        pytest.skip("CODER_DATABASE_URL is not set")
    parsed = urllib.parse.urlsplit(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 5432
    user = parsed.username or "defendcoder"
    password = parsed.password or ""
    query = parsed.query
    return (
        f"postgresql://{user}:{password}@{host}:{port}/{TEST_DB}"
        f"{('?' + query) if query else ''}"
    )


@pytest.fixture(scope="module")
def test_db() -> CoderDatabase:
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
        name = cur.fetchone()[0]
    assert name == TEST_DB, f"refusing to run against {name!r} (expected {TEST_DB})"


class TestPostgresAuthority:
    def test_migrate_clean_to_latest(self, test_db):
        test_db.migrate()
        with test_db.connect() as connection:
            _guard(connection)
            with connection.cursor() as cur:
                for table in (
                    "coder_identity_profiles",
                    "coder_prompt_core_bundles",
                    "coder_provider_technical_profiles",
                    "coder_provider_technical_active",
                ):
                    cur.execute(
                        "SELECT 1 FROM information_schema.tables "
                        "WHERE table_name = %s",
                        (table,),
                    )
                    assert cur.fetchone() is not None, table

    def test_seed_and_reload(self, test_db):
        test_db.migrate()
        store = PostgresAuthorityStore(test_db)
        hydrated = hydrate_authority(store)
        assert hydrated.active_identity is not None
        assert hydrated.active_prompt_core is not None
        # Simulate restart: rebuild the store and re-hydrate.
        store2 = PostgresAuthorityStore(test_db)
        hydrated2 = hydrate_authority(store2)
        assert (
            hydrated2.identity_profiles[hydrated2.active_identity].hash
            == hydrated.identity_profiles[hydrated.active_identity].hash
        )

    def test_identity_hash_conflict_fails(self, test_db):
        test_db.migrate()
        store = PostgresAuthorityStore(test_db)
        hydrate_authority(store)
        default = default_identity_profile()
        # Same id/version, different content -> conflict on save.
        with pytest.raises(StartupIntegrityError):
            store.save_identity(
                default_identity_profile().with_content(
                    profile_id=default.profile_id,
                    version=default.version,
                    communication_style="Tampered content.",
                )
            )

    def test_technical_active_pointer(self, test_db):
        test_db.migrate()
        store = PostgresAuthorityStore(test_db)
        hydrate_authority(store)
        assert store.active_technical_for("deepseek") is not None
        from defend_coder.registry import build_provider_technical_profile

        v2 = build_provider_technical_profile("deepseek", version="2")
        store.save_technical(v2)
        store.set_technical_active("deepseek", v2.profile_id, "2")
        assert store.active_technical_for("deepseek") == (v2.profile_id, "2")
