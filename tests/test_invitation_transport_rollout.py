from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from defend_data.identity_mailer import DeliveryResult
from defend_data.identity_security import token_hash
from defend_data.identity_store import (
    IdentityStore,
    InvitationTransportRolloutRequired,
)
from tools import identity_invitation_rollout


def _seed_v3_database(data_paths, *, expires_at: str | None = None) -> str:
    data_paths.ensure()
    database = data_paths.db / "identity.db"
    now = datetime.now(timezone.utc)
    invitation_token = "invite_pre_fragment_secret"
    with sqlite3.connect(database) as conn:
        conn.executescript(
            """
            CREATE TABLE schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            INSERT INTO schema_meta(key,value) VALUES('schema_version','3');

            CREATE TABLE accounts (
                account_id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                username TEXT UNIQUE COLLATE NOCASE,
                display_name TEXT NOT NULL,
                role TEXT NOT NULL,
                status TEXT NOT NULL,
                password_hash TEXT,
                created_by TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_access_at TEXT
            );
            CREATE TABLE invitations (
                invitation_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                email TEXT NOT NULL,
                intended_role TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                consumed_at TEXT,
                revoked_at TEXT,
                delivery_status TEXT NOT NULL DEFAULT 'pending',
                delivery_error TEXT
            );
            CREATE TABLE audit_events (
                event_id TEXT PRIMARY KEY,
                actor_account_id TEXT,
                action TEXT NOT NULL,
                target_type TEXT NOT NULL,
                target_id TEXT,
                outcome TEXT NOT NULL,
                request_id TEXT,
                created_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TRIGGER audit_events_no_update
            BEFORE UPDATE ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'audit_events are append-only');
            END;
            CREATE TRIGGER audit_events_no_delete
            BEFORE DELETE ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'audit_events are append-only');
            END;
            CREATE TRIGGER audit_events_no_duplicate
            BEFORE INSERT ON audit_events
            WHEN EXISTS(
                SELECT 1 FROM audit_events WHERE event_id=NEW.event_id
            )
            BEGIN
                SELECT RAISE(ABORT, 'audit_events are append-only');
            END;
            """
        )
        created_at = now.isoformat()
        conn.execute(
            """
            INSERT INTO accounts(
                account_id,email,username,display_name,role,status,password_hash,
                created_by,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "acct_owner",
                "chairman@defend-network.org",
                "MASSA",
                "Chairman",
                "owner",
                "active",
                "unused-test-hash",
                None,
                created_at,
                created_at,
            ),
        )
        conn.execute(
            """
            INSERT INTO accounts(
                account_id,email,username,display_name,role,status,password_hash,
                created_by,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "acct_pending",
                "pending@example.com",
                None,
                "Pending User",
                "user",
                "pending_activation",
                None,
                "acct_owner",
                created_at,
                created_at,
            ),
        )
        conn.execute(
            """
            INSERT INTO invitations(
                invitation_id,account_id,email,intended_role,token_hash,created_by,
                created_at,expires_at
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                "inv_legacy",
                "acct_pending",
                "pending@example.com",
                "user",
                token_hash(invitation_token),
                "acct_owner",
                created_at,
                expires_at or (now + timedelta(hours=24)).isoformat(),
            ),
        )
    return invitation_token


def test_v3_pending_invitation_is_durably_marked_and_blocks_rollout(data_paths):
    _seed_v3_database(data_paths)
    store = IdentityStore(data_paths)
    try:
        invitation = store.get_invitation("inv_legacy")
        assert invitation is not None
        assert invitation.transport_version == "legacy_path"
        assert store.conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()[0] == "4"

        preflight = store.invitation_transport_preflight()
        assert preflight.ready is False
        assert preflight.legacy_pending_count == 1
        with pytest.raises(InvitationTransportRolloutRequired, match="1"):
            store.assert_invitation_transport_ready()
    finally:
        store.close()


def test_rollout_reissue_revokes_legacy_and_creates_audited_fragment_invitation(
    data_paths,
):
    old_token = _seed_v3_database(data_paths)
    store = IdentityStore(data_paths)
    try:
        replacements = store.reissue_legacy_pending_invitations()

        assert len(replacements) == 1
        replacement, replacement_token = replacements[0]
        assert replacement.transport_version == "fragment_v1"
        assert replacement_token not in {
            old_token,
            replacement.token_hash if hasattr(replacement, "token_hash") else None,
        }
        assert store.invitation_status(old_token)[0] == "revoked"
        assert store.invitation_status(replacement_token)[0] == "pending"
        assert store.invitation_transport_preflight().ready is True
        store.assert_invitation_transport_ready()

        events = store.list_audit_events(limit=10)
        rollout = [
            event for event in events
            if event["action"] == "invitation.transport_reissue"
        ]
        assert len(rollout) == 1
        assert rollout[0]["target_id"] == "inv_legacy"
        assert "token" not in str(rollout[0]).casefold()
    finally:
        store.close()


def test_rollout_reissue_and_required_audit_are_atomic(data_paths):
    old_token = _seed_v3_database(data_paths)
    store = IdentityStore(data_paths)
    try:
        store.conn.executescript(
            """
            CREATE TRIGGER fail_rollout_audit
            BEFORE INSERT ON audit_events
            WHEN NEW.action='invitation.transport_reissue'
            BEGIN
                SELECT RAISE(ABORT, 'simulated rollout audit failure');
            END;
            """
        )

        with pytest.raises(sqlite3.IntegrityError, match="rollout audit failure"):
            store.reissue_legacy_pending_invitations()

        assert store.invitation_status(old_token)[0] == "pending"
        assert store.invitation_transport_preflight().legacy_pending_count == 1
        assert store.conn.execute(
            "SELECT COUNT(*) FROM invitations"
        ).fetchone()[0] == 1
    finally:
        store.close()


def test_new_fragment_invitation_is_not_misclassified(identity, owner):
    account, invitation, _token = identity.create_account_with_invitation(
        email="new-fragment@example.com",
        display_name="New Fragment",
        role="user",
        created_by=owner.account_id,
    )

    assert account.status == "pending_activation"
    assert invitation.transport_version == "fragment_v1"
    assert identity.invitation_transport_preflight().ready is True


def test_expired_legacy_invitation_does_not_block_rollout(data_paths):
    _seed_v3_database(
        data_paths,
        expires_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
    )
    store = IdentityStore(data_paths)
    try:
        assert store.invitation_transport_preflight().ready is True
        store.assert_invitation_transport_ready()
    finally:
        store.close()


def test_rollout_cli_checks_reissues_and_proves_ready_without_printing_secrets(
    data_paths,
):
    old_token = _seed_v3_database(data_paths)
    output: list[str] = []
    delivered_urls: list[str] = []

    class SuccessfulMailer:
        def send_invitation(self, *, recipient, activation_url, expires_at):
            assert recipient == "pending@example.com"
            assert expires_at
            delivered_urls.append(activation_url)
            return DeliveryResult(True, provider_message_id="safe-message-id")

    assert identity_invitation_rollout.run(
        "check", paths=data_paths, output=output.append
    ) == 2
    assert output == ["BLOCKED legacy_pending=1"]

    output.clear()
    assert identity_invitation_rollout.run(
        "reissue",
        paths=data_paths,
        mailer=SuccessfulMailer(),
        output=output.append,
    ) == 0
    assert output == ["REISSUED count=1 delivered=1", "READY legacy_pending=0"]
    assert len(delivered_urls) == 1
    assert "/activate#token=" in delivered_urls[0]
    assert "/activate/" not in delivered_urls[0]

    output.clear()
    assert identity_invitation_rollout.run(
        "check", paths=data_paths, output=output.append
    ) == 0
    assert output == ["READY legacy_pending=0"]

    rendered = "\n".join(output)
    assert old_token not in rendered
    assert "pending@example.com" not in rendered
    assert delivered_urls[0] not in rendered


def test_rollout_cli_delivery_failure_rolls_back_and_never_prints_secrets(
    data_paths,
):
    old_token = _seed_v3_database(data_paths)
    output: list[str] = []

    class FailingMailer:
        def send_invitation(self, *, recipient, activation_url, expires_at):
            return DeliveryResult(
                False,
                error=f"do not print {recipient} {activation_url} {old_token}",
            )

    assert identity_invitation_rollout.run(
        "reissue",
        paths=data_paths,
        mailer=FailingMailer(),
        output=output.append,
    ) == 3
    assert output == ["REISSUE FAILED; no database changes were committed"]
    assert old_token not in output[0]
    assert "pending@example.com" not in output[0]

    store = IdentityStore(data_paths)
    try:
        assert store.invitation_status(old_token)[0] == "pending"
        assert store.invitation_transport_preflight().legacy_pending_count == 1
        assert store.conn.execute(
            "SELECT COUNT(*) FROM invitations"
        ).fetchone()[0] == 1
    finally:
        store.close()
