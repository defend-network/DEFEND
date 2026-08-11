from __future__ import annotations

import base64
import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest

from defend_data.data_core import DataCore
from defend_data.identity_security import token_hash, verify_password
from defend_data.identity_store import (
    AuthenticationFailed,
    IdentityStore,
    InvitationInvalid,
    RoleViolation,
)


def test_schema_version_four_creates_identity_tables(identity):
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
    assert version["value"] == "4"


def _insert_audit_event(identity, owner, event_id="audit_test"):
    identity.conn.execute(
        """
        INSERT INTO audit_events(
            event_id,actor_account_id,action,target_type,target_id,outcome,
            request_id,created_at,metadata_json
        ) VALUES(?,?,?,?,?,?,?,?,?)
        """,
        (
            event_id,
            owner.account_id,
            "view",
            "conversation",
            "c1",
            "success",
            "req1",
            "2026-08-10T12:00:00+00:00",
            "{}",
        ),
    )
    identity.conn.commit()


def test_audit_events_cannot_be_updated(identity, owner):
    _insert_audit_event(identity, owner)

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        identity.conn.execute(
            "UPDATE audit_events SET outcome='failure' WHERE event_id='audit_test'"
        )


def test_audit_events_cannot_be_deleted(identity, owner):
    _insert_audit_event(identity, owner)

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        identity.conn.execute("DELETE FROM audit_events WHERE event_id='audit_test'")


def test_audit_events_cannot_be_replaced(identity, owner):
    _insert_audit_event(identity, owner)

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        identity.conn.execute(
            """
            INSERT OR REPLACE INTO audit_events(
                event_id,actor_account_id,action,target_type,target_id,outcome,
                request_id,created_at,metadata_json
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                "audit_test",
                owner.account_id,
                "view",
                "conversation",
                "c1",
                "failure",
                "req2",
                "2026-08-10T13:00:00+00:00",
                "{}",
            ),
        )

    row = identity.conn.execute(
        "SELECT outcome,request_id FROM audit_events WHERE event_id='audit_test'"
    ).fetchone()
    assert dict(row) == {"outcome": "success", "request_id": "req1"}


def test_audit_event_preserves_actor_id_after_account_deletion(identity, owner):
    _insert_audit_event(identity, owner)

    identity.conn.execute("DELETE FROM accounts WHERE account_id=?", (owner.account_id,))
    identity.conn.commit()

    row = identity.conn.execute(
        "SELECT actor_account_id FROM audit_events WHERE event_id='audit_test'"
    ).fetchone()
    assert row["actor_account_id"] == owner.account_id


def test_populated_v1_audit_events_migrate_to_append_only_v4(data_paths):
    seed = IdentityStore(data_paths)
    owner = seed.bootstrap_owner(
        email="chairman@defend-network.org",
        display_name="Chairman",
        password="valid owner password",
    )
    seed.close()

    conn = sqlite3.connect(data_paths.db / "identity.db")
    conn.executescript(
        """
        PRAGMA foreign_keys=ON;
        DROP TRIGGER audit_events_no_update;
        DROP TRIGGER audit_events_no_delete;
        DROP TABLE audit_events;
        CREATE TABLE audit_events (
            event_id TEXT PRIMARY KEY,
            actor_account_id TEXT REFERENCES accounts(account_id) ON DELETE SET NULL,
            action TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id TEXT,
            outcome TEXT NOT NULL,
            request_id TEXT,
            created_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX idx_audit_events_created ON audit_events(created_at DESC);
        UPDATE schema_meta SET value='1' WHERE key='schema_version';
        """
    )
    conn.execute(
        """
        INSERT INTO audit_events(
            event_id,actor_account_id,action,target_type,target_id,outcome,
            request_id,created_at,metadata_json
        ) VALUES(?,?,?,?,?,?,?,?,?)
        """,
        (
            "audit_legacy",
            owner.account_id,
            "view",
            "conversation",
            "legacy-c1",
            "success",
            "legacy-req",
            "2026-08-10T12:00:00+00:00",
            "{}",
        ),
    )
    conn.commit()
    conn.close()

    migrated = IdentityStore(data_paths)
    try:
        version = migrated.conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()
        assert version["value"] == "4"
        migrated.conn.execute("DELETE FROM accounts WHERE account_id=?", (owner.account_id,))
        migrated.conn.commit()
        row = migrated.conn.execute(
            "SELECT actor_account_id FROM audit_events WHERE event_id='audit_legacy'"
        ).fetchone()
        assert row["actor_account_id"] == owner.account_id
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            migrated.conn.execute(
                "UPDATE audit_events SET outcome='failure' WHERE event_id='audit_legacy'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            migrated.conn.execute("DELETE FROM audit_events WHERE event_id='audit_legacy'")
    finally:
        migrated.close()


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


def test_invitation_expiry_is_fixed_at_exactly_48_hours(identity, owner):
    account = identity.create_account(
        email="fixed-expiry@example.com",
        display_name="Fixed Expiry",
        role="user",
        created_by=owner.account_id,
    )
    invitation, _ = identity.create_invitation(
        account_id=account.account_id,
        created_by=owner.account_id,
    )

    created = datetime.fromisoformat(invitation.created_at)
    expires = datetime.fromisoformat(invitation.expires_at)
    assert (expires - created).total_seconds() == 48 * 60 * 60
    with pytest.raises(TypeError):
        identity.create_invitation(
            account_id=account.account_id,
            created_by=owner.account_id,
            expires_at="2030-01-01T00:00:00+00:00",
        )


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


def test_successful_login_upgrades_legacy_password_hash(identity, owner):
    password = "legacy owner password"
    salt = b"0123456789abcdef"
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=1 << 14,
        r=8,
        p=1,
        maxmem=128 * 1024 * 1024,
        dklen=64,
    )

    def encode(value):
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    legacy = f"scrypt$n=16384,r=8,p=1,dklen=64${encode(salt)}${encode(digest)}"
    identity.conn.execute(
        "UPDATE accounts SET password_hash=? WHERE account_id=?",
        (legacy, owner.account_id),
    )
    identity.conn.commit()

    authenticated = identity.authenticate_account(owner.email, password)
    stored = identity.conn.execute(
        "SELECT password_hash FROM accounts WHERE account_id=?", (owner.account_id,)
    ).fetchone()["password_hash"]
    assert authenticated.account_id == owner.account_id
    assert stored.startswith("scrypt$v=2$")
    assert verify_password(password, stored)


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
