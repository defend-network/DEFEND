from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import os

import pytest

from defend_coder.auth import AuthError, AuthService
from defend_coder.db import CoderDatabase
from defend_coder.repositories import CoderRepository


pytestmark = pytest.mark.skipif(
    not os.environ.get("CODER_TEST_DATABASE_URL"),
    reason="CODER_TEST_DATABASE_URL is not configured",
)


@pytest.fixture
def repo():
    db = CoderDatabase(os.environ["CODER_TEST_DATABASE_URL"])
    db.migrate()

    with db.connect() as connection:
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

    return CoderRepository(db)


@pytest.fixture
def auth(repo):
    return AuthService(repo, session_ttl=timedelta(hours=8))


def test_password_hash_uses_argon2id_and_verifies(auth):
    password = "correct horse battery staple"
    encoded = auth.hash_password(password)

    assert encoded != password
    assert encoded.startswith("$argon2id$")
    assert auth.verify_password(encoded, password) is True
    assert auth.verify_password(encoded, "wrong password") is False


def test_create_account_never_persists_plaintext_password(auth, repo):
    password = "NeverStoreThisPlaintext!"

    created = auth.create_account(
        username="admin",
        email="admin@example.test",
        password=password,
        role="admin",
    )

    stored = repo.get_account(created.account_id)

    assert stored is not None
    assert stored.password_hash != password
    assert stored.password_hash.startswith("$argon2id$")


def test_same_login_service_supports_admin_and_consumer(auth):
    auth.create_account(
        username="admin",
        email=None,
        password="admin-password",
        role="admin",
    )
    auth.create_account(
        username="consumer",
        email=None,
        password="consumer-password",
        role="consumer",
    )

    admin = auth.login("admin", "admin-password")
    consumer = auth.login("consumer", "consumer-password")

    assert admin.account.role == "admin"
    assert consumer.account.role == "consumer"


def test_wrong_username_and_wrong_password_are_same_public_error(auth):
    auth.create_account(
        username="real-user",
        email=None,
        password="correct-password",
        role="consumer",
    )

    with pytest.raises(AuthError) as missing:
        auth.login("missing-user", "anything")

    with pytest.raises(AuthError) as wrong:
        auth.login("real-user", "wrong-password")

    assert str(missing.value) == "invalid credentials"
    assert str(wrong.value) == "invalid credentials"


def test_login_returns_raw_token_once_and_only_hash_is_stored(auth, repo):
    auth.create_account(
        username="session-user",
        email=None,
        password="correct-password",
        role="consumer",
    )

    login = auth.login("session-user", "correct-password")

    assert login.token
    assert len(login.token) >= 32

    expected_hash = hashlib.sha256(login.token.encode("utf-8")).hexdigest()
    stored = repo.get_session_by_hash(expected_hash)

    assert stored is not None
    assert stored.token_hash == expected_hash
    assert stored.token_hash != login.token


def test_authenticate_session_rejects_unknown_token(auth):
    with pytest.raises(AuthError, match="invalid session"):
        auth.authenticate_session("not-a-real-session")


def test_revoked_session_is_rejected(auth):
    auth.create_account(
        username="revoke-user",
        email=None,
        password="correct-password",
        role="consumer",
    )

    login = auth.login("revoke-user", "correct-password")
    auth.logout(login.token)

    with pytest.raises(AuthError, match="invalid session"):
        auth.authenticate_session(login.token)


def test_expired_session_is_rejected(repo):
    auth = AuthService(repo, session_ttl=timedelta(seconds=-1))

    auth.create_account(
        username="expired-user",
        email=None,
        password="correct-password",
        role="consumer",
    )

    login = auth.login("expired-user", "correct-password")

    with pytest.raises(AuthError, match="invalid session"):
        auth.authenticate_session(login.token)


def test_inactive_account_cannot_login(auth, repo):
    account = auth.create_account(
        username="inactive-user",
        email=None,
        password="correct-password",
        role="consumer",
    )

    with repo._db.connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE coder_accounts
                SET is_active = FALSE
                WHERE account_id = %s
                """,
                (account.account_id,),
            )

    with pytest.raises(AuthError) as error:
        auth.login("inactive-user", "correct-password")

    assert str(error.value) == "invalid credentials"


def test_require_role_enforces_admin_boundary(auth):
    auth.create_account(
        username="admin",
        email=None,
        password="admin-password",
        role="admin",
    )
    auth.create_account(
        username="consumer",
        email=None,
        password="consumer-password",
        role="consumer",
    )

    admin = auth.login("admin", "admin-password")
    consumer = auth.login("consumer", "consumer-password")

    assert auth.require_role(admin.account, "admin").role == "admin"

    with pytest.raises(AuthError, match="forbidden"):
        auth.require_role(consumer.account, "admin")
