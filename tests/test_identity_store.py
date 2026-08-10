from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from defend_data.data_core import DataCore
from defend_data.identity_security import token_hash
from defend_data.identity_store import AuthenticationFailed, InvitationInvalid, RoleViolation


def test_schema_version_one_creates_identity_tables(identity):
    tables = {
        row["name"]
        for row in identity.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {
        "accounts",
        "invitations",
        "account_sessions",
        "account_visitor_links",
        "login_events",
        "audit_events",
    } <= tables
    version = identity.conn.execute(
        "SELECT value FROM schema_meta WHERE key='schema_version'"
    ).fetchone()
    assert version["value"] == "1"


def test_only_one_owner(identity):
    first = identity.bootstrap_owner(
        email="chairman@defend-network.org",
        display_name="Chairman",
        password="valid-password",
    )
    second = identity.bootstrap_owner(
        email="chairman@defend-network.org",
        display_name="Chairman",
        password="valid-password",
    )
    assert first.account_id == second.account_id
    with pytest.raises(RoleViolation):
        identity.create_account(
            email="other@example.com",
            display_name="Other",
            role="owner",
            created_by=first.account_id,
        )


def test_normalized_email_is_unique(identity, owner):
    identity.create_account(
        email="member@example.com",
        display_name="Member",
        role="user",
        created_by=owner.account_id,
    )
    with pytest.raises(ValueError, match="email already exists"):
        identity.create_account(
            email=" MEMBER@EXAMPLE.COM ",
            display_name="Duplicate",
            role="user",
            created_by=owner.account_id,
        )


def test_invitation_activation_and_authentication_are_single_use(identity, owner):
    account = identity.create_account(
        email="member@example.com",
        display_name="Member",
        role="user",
        created_by=owner.account_id,
    )
    invitation, token = identity.create_invitation(
        account_id=account.account_id,
        created_by=owner.account_id,
    )

    stored = identity.conn.execute(
        "SELECT token_hash FROM invitations WHERE invitation_id=?",
        (invitation.invitation_id,),
    ).fetchone()
    assert stored["token_hash"] == token_hash(token)

    activated = identity.consume_invitation(token, password="a sufficiently long password")
    assert activated.status == "active"
    authenticated = identity.authenticate_account(
        " MEMBER@EXAMPLE.COM ", "a sufficiently long password"
    )
    assert authenticated.account_id == activated.account_id
    assert authenticated.last_access_at is not None
    with pytest.raises(AuthenticationFailed):
        identity.authenticate_account("member@example.com", "wrong password")
    with pytest.raises(InvitationInvalid):
        identity.consume_invitation(token, password="another sufficiently long password")


def test_session_resolve_and_revoke_without_storing_raw_token(identity, owner):
    token = identity.create_session(owner.account_id)
    stored = identity.conn.execute("SELECT session_hash FROM account_sessions").fetchone()
    assert stored["session_hash"] == token_hash(token)

    resolved = identity.resolve_session(token)
    assert resolved is not None
    assert resolved.account_id == owner.account_id
    assert identity.revoke_session(token)
    assert identity.resolve_session(token) is None


def test_authentication_hides_malformed_identifiers(identity):
    with pytest.raises(AuthenticationFailed, match="invalid credentials"):
        identity.authenticate_account("not@a@valid@email", "wrong password")


def test_shared_store_resolves_sessions_concurrently(identity, owner):
    token = identity.create_session(owner.account_id)

    with ThreadPoolExecutor(max_workers=16) as pool:
        resolved = list(pool.map(lambda _: identity.resolve_session(token), range(100)))

    assert all(account is not None for account in resolved)
    assert {account.account_id for account in resolved if account is not None} == {
        owner.account_id
    }


def test_newer_identity_schema_is_rejected(data_paths):
    db_path = data_paths.db / "identity.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO schema_meta(key,value) VALUES('schema_version','99')")
    conn.commit()
    conn.close()

    from defend_data.identity_store import IdentityStore

    with pytest.raises(RuntimeError, match="newer identity schema version"):
        IdentityStore(data_paths)


def test_data_core_reports_identity_health_and_stats(tmp_path):
    core = DataCore(tmp_path / "DEFEND_DATA")
    try:
        assert core.stats()["identity"]["accounts"] == 0
        health = core.health()
        assert health["ok"]
        assert health["databases"]["identity"]["exists"]
    finally:
        core.close()

    with pytest.raises(sqlite3.ProgrammingError):
        core.identity.conn.execute("SELECT 1")
