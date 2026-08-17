from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os

import pytest

from defend_coder.db import CoderDatabase
from defend_coder.repositories import CoderRepository


pytestmark = pytest.mark.skipif(
    not os.environ.get("CODER_TEST_DATABASE_URL"),
    reason="CODER_TEST_DATABASE_URL is not configured",
)


@pytest.fixture
def db():
    database = CoderDatabase(os.environ["CODER_TEST_DATABASE_URL"])
    database.migrate()

    with database.connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                TRUNCATE
                    coder_audit_events,
                    coder_sessions,
                    coder_workspaces,
                    coder_accounts
                RESTART IDENTITY CASCADE
                """
            )

    return database


@pytest.fixture
def repo(db):
    return CoderRepository(db)


def test_migrate_is_idempotent(db):
    assert db.migrate() == 1
    assert db.migrate() == 1


def test_health_reports_ready_after_migration(db):
    health = db.health()

    assert health == {
        "ok": True,
        "application_id": "coder",
        "schema_version": 1,
        "database": "ready",
    }


def test_account_role_is_constrained(repo):
    with pytest.raises(ValueError, match="role"):
        repo.create_account(
            username="bad-role",
            email=None,
            password_hash="synthetic-hash",
            role="owner",
        )


def test_accounts_enforce_unique_username(repo):
    repo.create_account(
        username="admin",
        email="admin@example.test",
        password_hash="synthetic-hash-1",
        role="admin",
    )

    with pytest.raises(Exception):
        repo.create_account(
            username="admin",
            email="different@example.test",
            password_hash="synthetic-hash-2",
            role="consumer",
        )


def test_admin_and_consumer_roles_round_trip(repo):
    admin = repo.create_account(
        username="admin",
        email="admin@example.test",
        password_hash="synthetic-admin-hash",
        role="admin",
    )

    consumer = repo.create_account(
        username="consumer",
        email="consumer@example.test",
        password_hash="synthetic-consumer-hash",
        role="consumer",
    )

    assert admin.role == "admin"
    assert consumer.role == "consumer"


def test_session_persists_only_hash(repo):
    account = repo.create_account(
        username="session-user",
        email=None,
        password_hash="synthetic-password-hash",
        role="consumer",
    )

    raw_token = "never-store-this-raw-session-token"
    token_hash = "a" * 64

    session = repo.create_session(
        account_id=account.account_id,
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=8),
    )

    assert session.token_hash == token_hash

    with repo._db.connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'coder_sessions'
                """
            )
            columns = {row[0] for row in cursor.fetchall()}

            cursor.execute(
                """
                SELECT token_hash
                FROM coder_sessions
                WHERE session_id = %s
                """,
                (session.session_id,),
            )
            stored = cursor.fetchone()[0]

    assert stored == token_hash
    assert raw_token != stored
    assert "token" not in columns
    assert "raw_token" not in columns


def test_session_has_expiry_and_revocation(repo):
    account = repo.create_account(
        username="revoke-user",
        email=None,
        password_hash="synthetic-password-hash",
        role="consumer",
    )

    session = repo.create_session(
        account_id=account.account_id,
        token_hash="b" * 64,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )

    assert session.expires_at is not None
    assert session.revoked_at is None

    repo.revoke_session(session.session_id)

    updated = repo.get_session_by_hash("b" * 64)
    assert updated is not None
    assert updated.revoked_at is not None


def test_workspace_requires_real_owner(db, repo):
    with pytest.raises(Exception):
        repo.create_workspace(
            owner_account_id=__import__("uuid").uuid4(),
            name="orphan",
            workspace_root=r"C:\DEFEND_CODER_DATA\orphan",
        )


def test_workspace_round_trip_is_owner_scoped(repo):
    first = repo.create_account(
        username="first-user",
        email=None,
        password_hash="hash-first",
        role="consumer",
    )

    second = repo.create_account(
        username="second-user",
        email=None,
        password_hash="hash-second",
        role="consumer",
    )

    created = repo.create_workspace(
        owner_account_id=first.account_id,
        name="my-project",
        workspace_root=r"C:\DEFEND_CODER_DATA\first\my-project",
        repository_url="https://github.com/example/project.git",
        default_branch="main",
    )

    first_rows = repo.list_workspaces_for_owner(first.account_id)
    second_rows = repo.list_workspaces_for_owner(second.account_id)

    assert first_rows == (created,)
    assert second_rows == ()


def test_audit_schema_has_no_password_columns(db):
    with db.connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'coder_audit_events'
                """
            )
            columns = {row[0] for row in cursor.fetchall()}

    assert "password" not in columns
    assert "password_hash" not in columns


def test_database_repr_does_not_leak_url():
    url = "postgresql://coder:super-secret@example.test/coder"
    db = CoderDatabase(url)

    assert "super-secret" not in repr(db)
    assert url not in repr(db)
