from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Literal

from .config import DataPaths
from .identity_security import (
    hash_password,
    new_token,
    normalize_email,
    password_needs_rehash,
    token_hash,
    verify_password,
)
from .sqlite_utils import connect_sqlite, transaction


AccountRole = Literal["owner", "admin", "user"]
AccountStatus = Literal["pending_activation", "active", "disabled", "anonymized"]


class IdentityError(ValueError):
    pass


class RoleViolation(IdentityError):
    pass


class AuthenticationFailed(IdentityError):
    pass


class InvitationInvalid(IdentityError):
    pass


class InvitationExpired(InvitationInvalid):
    pass


@dataclass(frozen=True)
class AccountRecord:
    account_id: str
    email: str
    display_name: str
    role: AccountRole
    status: AccountStatus
    created_at: str
    last_access_at: str | None


@dataclass(frozen=True)
class InvitationRecord:
    invitation_id: str
    account_id: str
    email: str
    intended_role: AccountRole
    created_by: str
    created_at: str
    expires_at: str
    consumed_at: str | None
    revoked_at: str | None
    delivery_status: str
    delivery_error: str | None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _serialized(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapped


class IdentityStore:
    """Durable identity, invitation, session, and audit persistence."""

    VALID_ROLES = {"owner", "admin", "user"}
    VALID_STATUSES = {"pending_activation", "active", "disabled", "anonymized"}
    _AUDIT_SENSITIVE_KEYS = {
        "password",
        "token",
        "cookie",
        "authorization",
        "secret",
    }
    _AUDIT_PAYLOAD_FORMAT = "identity_audit_v1"
    _MAX_AUDIT_PAYLOAD_BYTES = 16 * 1024

    def __init__(self, paths: DataPaths):
        self._lock = threading.RLock()
        self.paths = paths.ensure()
        self.db_path = self.paths.db / "identity.db"
        self.conn = connect_sqlite(self.db_path)
        try:
            self._migrate()
        except Exception:
            self.conn.close()
            raise
        # Used to equalize the expensive password check for unknown accounts.
        self._dummy_password_hash = hash_password("DEFEND invalid credential sentinel")

    @_serialized
    def close(self) -> None:
        self.conn.close()

    def _migrate(self) -> None:
        has_schema_meta = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_meta'"
        ).fetchone()
        if has_schema_meta is None:
            current_version = 0
        else:
            row = self.conn.execute(
                "SELECT value FROM schema_meta WHERE key='schema_version'"
            ).fetchone()
            try:
                current_version = int(row["value"]) if row is not None else 0
            except (TypeError, ValueError) as exc:
                raise RuntimeError("invalid identity schema version") from exc
        if current_version > 3:
            raise RuntimeError(
                f"newer identity schema version {current_version} is not supported"
            )
        if current_version < 0:
            raise RuntimeError("invalid identity schema version")
        if current_version == 3:
            return

        try:
            if current_version == 0:
                self.conn.executescript(
                    """
            BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS accounts (
                account_id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                username TEXT UNIQUE COLLATE NOCASE,
                display_name TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('owner','admin','user')),
                status TEXT NOT NULL CHECK(status IN ('pending_activation','active','disabled','anonymized')),
                password_hash TEXT,
                created_by TEXT REFERENCES accounts(account_id),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_access_at TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_single_owner
                ON accounts(role) WHERE role='owner';
            CREATE INDEX IF NOT EXISTS idx_accounts_status_role
                ON accounts(status, role);

            CREATE TABLE IF NOT EXISTS invitations (
                invitation_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
                email TEXT NOT NULL,
                intended_role TEXT NOT NULL CHECK(intended_role IN ('admin','user')),
                token_hash TEXT NOT NULL UNIQUE,
                created_by TEXT NOT NULL REFERENCES accounts(account_id),
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                consumed_at TEXT,
                revoked_at TEXT,
                delivery_status TEXT NOT NULL DEFAULT 'pending',
                delivery_error TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_invitations_account_created
                ON invitations(account_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS account_sessions (
                session_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
                session_hash TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                revoked_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_account_sessions_account
                ON account_sessions(account_id, expires_at DESC);

            CREATE TABLE IF NOT EXISTS account_visitor_links (
                account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
                visitor_id TEXT NOT NULL,
                linked_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                PRIMARY KEY(account_id, visitor_id)
            );

            CREATE TABLE IF NOT EXISTS login_events (
                event_id TEXT PRIMARY KEY,
                account_id TEXT REFERENCES accounts(account_id) ON DELETE SET NULL,
                identifier_hash TEXT NOT NULL,
                outcome TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_login_events_account_created
                ON login_events(account_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS audit_events (
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
            CREATE INDEX IF NOT EXISTS idx_audit_events_created
                ON audit_events(created_at DESC);
            INSERT OR REPLACE INTO schema_meta(key,value) VALUES('schema_version','1');
            COMMIT;
                    """
                )
                current_version = 1

            if current_version == 1:
                self.conn.executescript(
                    """
            BEGIN IMMEDIATE;
            CREATE TABLE audit_events_v2 (
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
            INSERT INTO audit_events_v2(
                event_id,actor_account_id,action,target_type,target_id,outcome,
                request_id,created_at,metadata_json
            )
            SELECT
                event_id,actor_account_id,action,target_type,target_id,outcome,
                request_id,created_at,metadata_json
            FROM audit_events;
            DROP TABLE audit_events;
            ALTER TABLE audit_events_v2 RENAME TO audit_events;
            CREATE INDEX idx_audit_events_created
                ON audit_events(created_at DESC);
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
            INSERT OR REPLACE INTO schema_meta(key,value) VALUES('schema_version','2');
            COMMIT;
                    """
                )
                current_version = 2

            if current_version == 2:
                self.conn.executescript(
                    """
            BEGIN IMMEDIATE;
            CREATE TRIGGER audit_events_no_duplicate
            BEFORE INSERT ON audit_events
            WHEN EXISTS(
                SELECT 1 FROM audit_events WHERE event_id=NEW.event_id
            )
            BEGIN
                SELECT RAISE(ABORT, 'audit_events are append-only');
            END;
            INSERT OR REPLACE INTO schema_meta(key,value) VALUES('schema_version','3');
            COMMIT;
                    """
                )
        except Exception:
            if self.conn.in_transaction:
                self.conn.rollback()
            raise

    @staticmethod
    def _account_from_row(row: sqlite3.Row) -> AccountRecord:
        return AccountRecord(
            account_id=row["account_id"],
            email=row["email"],
            display_name=row["display_name"],
            role=row["role"],
            status=row["status"],
            created_at=row["created_at"],
            last_access_at=row["last_access_at"],
        )

    @staticmethod
    def _invitation_from_row(row: sqlite3.Row) -> InvitationRecord:
        return InvitationRecord(
            invitation_id=row["invitation_id"],
            account_id=row["account_id"],
            email=row["email"],
            intended_role=row["intended_role"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            consumed_at=row["consumed_at"],
            revoked_at=row["revoked_at"],
            delivery_status=row["delivery_status"],
            delivery_error=row["delivery_error"],
        )

    @staticmethod
    def _clean_display_name(value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("display_name must not be empty")
        return cleaned[:160]

    @_serialized
    def get_account(self, account_id_or_email: str) -> AccountRecord | None:
        identifier = (account_id_or_email or "").strip()
        if not identifier:
            return None
        if identifier.startswith("acct_"):
            row = self.conn.execute(
                "SELECT * FROM accounts WHERE account_id=?", (identifier,)
            ).fetchone()
        elif "@" in identifier:
            row = self.conn.execute(
                "SELECT * FROM accounts WHERE email=?", (normalize_email(identifier),)
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT * FROM accounts WHERE username=? COLLATE NOCASE", (identifier,)
            ).fetchone()
        return self._account_from_row(row) if row is not None else None

    def _authorized_creator(self, created_by: str, role: AccountRole) -> AccountRecord:
        actor = self.get_account(created_by)
        if actor is None or actor.status != "active" or actor.role not in {"owner", "admin"}:
            raise RoleViolation("active owner or admin account required")
        if role == "owner":
            raise RoleViolation("owner accounts can only be bootstrapped")
        if role == "admin" and actor.role != "owner":
            raise RoleViolation("only the owner may create administrators")
        return actor

    @_serialized
    def create_account(
        self,
        *,
        email: str,
        display_name: str,
        role: AccountRole,
        created_by: str,
        username: str | None = None,
    ) -> AccountRecord:
        if role not in self.VALID_ROLES:
            raise ValueError("invalid account role")
        normalized = normalize_email(email)
        clean_name = self._clean_display_name(display_name)
        clean_username = (username or "").strip() or None
        now = utc_now()
        account_id = f"acct_{uuid.uuid4().hex}"
        try:
            with transaction(self.conn, immediate=True):
                self._authorized_creator(created_by, role)
                self.conn.execute(
                    """
                    INSERT INTO accounts(
                        account_id,email,username,display_name,role,status,password_hash,
                        created_by,created_at,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        account_id,
                        normalized,
                        clean_username,
                        clean_name,
                        role,
                        "pending_activation",
                        None,
                        created_by,
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            message = str(exc).lower()
            if "accounts.email" in message:
                raise ValueError("email already exists") from exc
            if "accounts.username" in message:
                raise ValueError("username already exists") from exc
            raise
        account = self.get_account(account_id)
        assert account is not None
        return account

    @_serialized
    def create_account_with_invitation(
        self,
        *,
        email: str,
        display_name: str,
        role: AccountRole,
        created_by: str,
    ) -> tuple[AccountRecord, InvitationRecord, str]:
        """Atomically create a pending account and its initial invitation."""
        if role not in self.VALID_ROLES:
            raise ValueError("invalid account role")
        normalized = normalize_email(email)
        clean_name = self._clean_display_name(display_name)
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        account_id = f"acct_{uuid.uuid4().hex}"
        invitation_id = f"inv_{uuid.uuid4().hex}"
        token, stored_hash = new_token("invite")
        try:
            with transaction(self.conn, immediate=True):
                self._authorized_creator(created_by, role)
                self.conn.execute(
                    """
                    INSERT INTO accounts(
                        account_id,email,username,display_name,role,status,password_hash,
                        created_by,created_at,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        account_id,
                        normalized,
                        None,
                        clean_name,
                        role,
                        "pending_activation",
                        None,
                        created_by,
                        now,
                        now,
                    ),
                )
                self.conn.execute(
                    """
                    INSERT INTO invitations(
                        invitation_id,account_id,email,intended_role,token_hash,created_by,
                        created_at,expires_at
                    ) VALUES(?,?,?,?,?,?,?,?)
                    """,
                    (
                        invitation_id,
                        account_id,
                        normalized,
                        role,
                        stored_hash,
                        created_by,
                        now,
                        (now_dt + timedelta(hours=48)).isoformat(),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            message = str(exc).lower()
            if "accounts.email" in message:
                raise ValueError("email already exists") from exc
            raise
        account_row = self.conn.execute(
            "SELECT * FROM accounts WHERE account_id=?", (account_id,)
        ).fetchone()
        invitation_row = self.conn.execute(
            "SELECT * FROM invitations WHERE invitation_id=?", (invitation_id,)
        ).fetchone()
        assert account_row is not None and invitation_row is not None
        return (
            self._account_from_row(account_row),
            self._invitation_from_row(invitation_row),
            token,
        )

    @_serialized
    def disable_account(self, *, actor: object, target_id: str) -> AccountRecord:
        """Disable a user/admin while enforcing authority from persisted roles."""
        actor_id = (
            actor if isinstance(actor, str) else getattr(actor, "account_id", None)
        )
        if not isinstance(actor_id, str) or not actor_id:
            raise RoleViolation("active owner or admin account required")
        clean_target_id = (target_id or "").strip()
        if not clean_target_id:
            raise KeyError(target_id)

        with transaction(self.conn, immediate=True):
            actor_row = self.conn.execute(
                "SELECT * FROM accounts WHERE account_id=?", (actor_id,)
            ).fetchone()
            target_row = self.conn.execute(
                "SELECT * FROM accounts WHERE account_id=?", (clean_target_id,)
            ).fetchone()
            if (
                actor_row is None
                or actor_row["status"] != "active"
                or actor_row["role"] not in {"owner", "admin"}
            ):
                raise RoleViolation("active owner or admin account required")
            if target_row is None:
                raise KeyError(clean_target_id)
            if target_row["role"] == "owner":
                raise RoleViolation("the owner account cannot be disabled")
            if actor_id == clean_target_id:
                raise RoleViolation("accounts cannot disable themselves")
            if target_row["role"] == "admin" and actor_row["role"] != "owner":
                raise RoleViolation("only the owner may disable administrators")
            if target_row["status"] == "anonymized":
                raise RoleViolation("anonymized accounts cannot be disabled")
            if target_row["status"] != "disabled":
                self.conn.execute(
                    "UPDATE accounts SET status='disabled',updated_at=? WHERE account_id=?",
                    (utc_now(), clean_target_id),
                )
            refreshed = self.conn.execute(
                "SELECT * FROM accounts WHERE account_id=?", (clean_target_id,)
            ).fetchone()
            assert refreshed is not None
            disabled = self._account_from_row(refreshed)
        return disabled

    @_serialized
    def list_accounts(
        self, *, query: str = "", limit: int = 50, offset: int = 0
    ) -> dict[str, object]:
        if not 1 <= int(limit) <= 100:
            raise ValueError("limit must be between 1 and 100")
        if not 0 <= int(offset) <= 1_000_000:
            raise ValueError("offset must be between 0 and 1000000")
        cleaned = (query or "").strip()[:200]
        like = f"%{cleaned}%"
        where = """WHERE ?='' OR account_id LIKE ? OR email LIKE ? OR
                           COALESCE(username,'') LIKE ? OR display_name LIKE ? OR
                           role LIKE ? OR status LIKE ?"""
        params = (cleaned, like, like, like, like, like, like)
        total = int(
            self.conn.execute(
                f"SELECT COUNT(*) FROM accounts {where}", params
            ).fetchone()[0]
        )
        rows = self.conn.execute(
            f"""
            SELECT a.account_id,a.email,a.display_name,a.role,a.status,
                   a.created_at,a.last_access_at,
                   COUNT(DISTINCT l.visitor_id) AS visitor_count,
                   COUNT(DISTINCT CASE
                       WHEN s.revoked_at IS NULL AND s.expires_at > ? THEN s.session_id
                   END) AS active_session_count
            FROM accounts a
            LEFT JOIN account_visitor_links l ON l.account_id=a.account_id
            LEFT JOIN account_sessions s ON s.account_id=a.account_id
            {where.replace('account_id', 'a.account_id').replace('email', 'a.email').replace('username', 'a.username').replace('display_name', 'a.display_name').replace('role', 'a.role').replace('status', 'a.status')}
            GROUP BY a.account_id
            ORDER BY a.created_at DESC,a.account_id ASC
            LIMIT ? OFFSET ?
            """,
            (utc_now(), *params, int(limit), int(offset)),
        ).fetchall()
        return {"items": [dict(row) for row in rows], "total": total}

    @_serialized
    def account_admin_detail(
        self,
        account_id: str,
        *,
        nested_limit: int = 200,
        linked_visitor_limit: int = 25,
        linked_visitor_offset: int = 0,
    ) -> dict[str, object] | None:
        cap = max(1, min(int(nested_limit), 200))
        link_limit = max(1, min(int(linked_visitor_limit), 50))
        link_offset = max(0, min(int(linked_visitor_offset), 1_000_000))
        row = self.conn.execute(
            """
            SELECT account_id,email,display_name,role,status,created_at,updated_at,last_access_at
            FROM accounts WHERE account_id=?
            """,
            ((account_id or "").strip(),),
        ).fetchone()
        if row is None:
            return None
        sessions = self.conn.execute(
            """
            SELECT session_id,created_at,last_seen_at,expires_at,revoked_at
            FROM account_sessions WHERE account_id=?
            ORDER BY last_seen_at DESC LIMIT ?
            """,
            (account_id, cap),
        ).fetchall()
        logins = self.conn.execute(
            """
            SELECT event_id,outcome,created_at
            FROM login_events WHERE account_id=?
            ORDER BY created_at DESC LIMIT ?
            """,
            (account_id, cap),
        ).fetchall()
        invitations = self.conn.execute(
            """
            SELECT invitation_id,account_id,email,intended_role,created_by,created_at,
                   expires_at,consumed_at,revoked_at,delivery_status,delivery_error
            FROM invitations WHERE account_id=?
            ORDER BY created_at DESC LIMIT ?
            """,
            (account_id, cap),
        ).fetchall()
        link_total = int(
            self.conn.execute(
                "SELECT COUNT(*) FROM account_visitor_links WHERE account_id=?",
                (account_id,),
            ).fetchone()[0]
        )
        links = self.conn.execute(
            """
            SELECT visitor_id,linked_at,last_seen_at FROM account_visitor_links
            WHERE account_id=? ORDER BY last_seen_at DESC,visitor_id ASC LIMIT ? OFFSET ?
            """,
            (account_id, link_limit, link_offset),
        ).fetchall()
        return {
            "account": dict(row),
            "sessions": [dict(item) for item in sessions],
            "login_events": [dict(item) for item in logins],
            "invitations": [dict(item) for item in invitations],
            "visitor_links": [dict(item) for item in links],
            "visitor_links_page": {
                "total": link_total,
                "limit": link_limit,
                "offset": link_offset,
            },
        }

    def _administrative_actor_and_target(self, actor_id: str, target_id: str):
        actor = self.conn.execute(
            "SELECT * FROM accounts WHERE account_id=?", (actor_id,)
        ).fetchone()
        target = self.conn.execute(
            "SELECT * FROM accounts WHERE account_id=?", (target_id,)
        ).fetchone()
        if actor is None or actor["status"] != "active" or actor["role"] not in {"owner", "admin"}:
            raise RoleViolation("active owner or admin account required")
        if target is None:
            raise KeyError(target_id)
        return actor, target

    @_serialized
    def update_account_admin(
        self,
        *,
        actor_id: str,
        target_id: str,
        display_name: str | None = None,
        role: AccountRole | None = None,
        status: str | None = None,
        audit_context: dict[str, object] | None = None,
    ) -> AccountRecord:
        if role is not None and role not in {"admin", "user"}:
            raise ValueError("invalid account role")
        if status is not None and status not in {"active", "disabled"}:
            raise ValueError("invalid account status")
        with transaction(self.conn, immediate=True):
            actor, target = self._administrative_actor_and_target(actor_id, target_id)
            if target["role"] == "owner":
                raise RoleViolation("the owner account cannot be managed")
            if target["role"] == "admin" and actor["role"] != "owner":
                raise RoleViolation("only the owner may manage administrators")
            if role == "admin" and actor["role"] != "owner":
                raise RoleViolation("only the owner may promote administrators")
            if actor_id == target_id and (role is not None or status is not None):
                raise RoleViolation("accounts cannot change their own role or status")
            if status == "active" and target["password_hash"] is None:
                raise RoleViolation("pending accounts must activate by invitation")
            next_name = (
                self._clean_display_name(display_name)
                if display_name is not None
                else target["display_name"]
            )
            self.conn.execute(
                """
                UPDATE accounts SET display_name=?,role=?,status=?,updated_at=?
                WHERE account_id=?
                """,
                (
                    next_name,
                    role or target["role"],
                    status or target["status"],
                    utc_now(),
                    target_id,
                ),
            )
            if status == "disabled":
                self.conn.execute(
                    "UPDATE account_sessions SET revoked_at=COALESCE(revoked_at,?) WHERE account_id=?",
                    (utc_now(), target_id),
                )
            if audit_context is not None:
                self._insert_account_mutation_audit(
                    actor_id=actor_id,
                    action="account.update",
                    target_id=target_id,
                    audit_context=audit_context,
                )
        refreshed = self.get_account(target_id)
        assert refreshed is not None
        return refreshed

    @_serialized
    def anonymize_account(
        self,
        *,
        actor_id: str,
        target_id: str,
        audit_context: dict[str, object] | None = None,
    ) -> AccountRecord:
        with transaction(self.conn, immediate=True):
            actor, target = self._administrative_actor_and_target(actor_id, target_id)
            if actor["role"] != "owner":
                raise RoleViolation("only the owner may anonymize accounts")
            if target["role"] == "owner" or actor_id == target_id:
                raise RoleViolation("the owner account cannot be anonymized")
            now = utc_now()
            anonymous_email = f"anonymized+{target_id}@invalid.local"
            self.conn.execute(
                """
                UPDATE accounts SET email=?,username=NULL,display_name='Anonymized account',
                    role='user',status='anonymized',password_hash=NULL,updated_at=?,last_access_at=NULL
                WHERE account_id=?
                """,
                (anonymous_email, now, target_id),
            )
            self.conn.execute(
                "UPDATE account_sessions SET revoked_at=COALESCE(revoked_at,?) WHERE account_id=?",
                (now, target_id),
            )
            self.conn.execute("DELETE FROM account_visitor_links WHERE account_id=?", (target_id,))
            self.conn.execute("DELETE FROM invitations WHERE account_id=?", (target_id,))
            self.conn.execute("UPDATE login_events SET account_id=NULL WHERE account_id=?", (target_id,))
            if audit_context is not None:
                self._insert_account_mutation_audit(
                    actor_id=actor_id,
                    action="account.anonymize",
                    target_id=target_id,
                    audit_context=audit_context,
                )
        refreshed = self.get_account(target_id)
        assert refreshed is not None
        return refreshed

    @_serialized
    def delete_account_admin(
        self,
        *,
        actor_id: str,
        target_id: str,
        audit_context: dict[str, object] | None = None,
    ) -> None:
        with transaction(self.conn, immediate=True):
            actor, target = self._administrative_actor_and_target(actor_id, target_id)
            if actor["role"] != "owner":
                raise RoleViolation("only the owner may delete accounts")
            if target["role"] == "owner" or actor_id == target_id:
                raise RoleViolation("the owner account cannot be deleted")
            self.conn.execute(
                "UPDATE accounts SET created_by=? WHERE created_by=?", (actor_id, target_id)
            )
            self.conn.execute(
                "UPDATE invitations SET created_by=? WHERE created_by=?", (actor_id, target_id)
            )
            self.conn.execute("DELETE FROM accounts WHERE account_id=?", (target_id,))
            if audit_context is not None:
                self._insert_account_mutation_audit(
                    actor_id=actor_id,
                    action="account.delete",
                    target_id=target_id,
                    audit_context=audit_context,
                )

    @_serialized
    def linked_accounts_for_visitors(self, visitor_ids: list[str]) -> dict[str, dict[str, object]]:
        clean_ids = list(dict.fromkeys(value for value in visitor_ids if value))[:1000]
        if not clean_ids:
            return {}
        placeholders = ",".join("?" for _ in clean_ids)
        rows = self.conn.execute(
            f"""
            SELECT l.visitor_id,a.account_id,a.email,a.display_name,a.role,a.status
            FROM account_visitor_links l JOIN accounts a ON a.account_id=l.account_id
            WHERE l.visitor_id IN ({placeholders})
            ORDER BY l.last_seen_at DESC
            """,
            tuple(clean_ids),
        ).fetchall()
        return {row["visitor_id"]: {key: row[key] for key in row.keys() if key != "visitor_id"} for row in rows}

    @_serialized
    def visitor_ids_matching_account(self, query: str, *, limit: int = 1000) -> list[str]:
        cleaned = (query or "").strip()
        if not cleaned:
            return []
        like = f"%{cleaned[:200]}%"
        rows = self.conn.execute(
            """
            SELECT DISTINCT l.visitor_id
            FROM account_visitor_links l JOIN accounts a ON a.account_id=l.account_id
            WHERE a.account_id LIKE ? OR a.email LIKE ? OR a.display_name LIKE ?
            ORDER BY l.visitor_id LIMIT ?
            """,
            (like, like, like, max(1, min(int(limit), 1000))),
        ).fetchall()
        return [str(row["visitor_id"]) for row in rows]

    @_serialized
    def list_invitations_admin(
        self, *, query: str = "", limit: int = 50, offset: int = 0
    ) -> dict[str, object]:
        if not 1 <= int(limit) <= 100 or not 0 <= int(offset) <= 1_000_000:
            raise ValueError("invalid pagination")
        cleaned = (query or "").strip()[:200]
        like = f"%{cleaned}%"
        status_expr = """CASE WHEN i.consumed_at IS NOT NULL THEN 'consumed'
                            WHEN i.revoked_at IS NOT NULL THEN 'revoked'
                            WHEN i.expires_at <= ? THEN 'expired' ELSE 'pending' END"""
        where = f"""WHERE ?='' OR i.invitation_id LIKE ? OR i.email LIKE ? OR
                    i.intended_role LIKE ? OR i.delivery_status LIKE ? OR
                    c.account_id LIKE ? OR c.email LIKE ? OR c.display_name LIKE ? OR
                    ({status_expr}) LIKE ?"""
        now = utc_now()
        params = (cleaned, like, like, like, like, like, like, like, now, like)
        total = int(self.conn.execute(
            f"SELECT COUNT(*) FROM invitations i JOIN accounts c ON c.account_id=i.created_by {where}",
            params,
        ).fetchone()[0])
        rows = self.conn.execute(
            f"""
            SELECT i.invitation_id,i.account_id,i.email,i.intended_role,i.created_at,
                   i.expires_at,i.consumed_at,i.revoked_at,i.delivery_status,i.delivery_error,
                   {status_expr} AS status,
                   c.account_id AS creator_account_id,c.email AS creator_email,
                   c.display_name AS creator_display_name
            FROM invitations i JOIN accounts c ON c.account_id=i.created_by
            {where}
            ORDER BY i.created_at DESC,i.invitation_id ASC LIMIT ? OFFSET ?
            """,
            (now, *params, int(limit), int(offset)),
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["creator"] = {
                "account_id": item.pop("creator_account_id"),
                "email": item.pop("creator_email"),
                "display_name": item.pop("creator_display_name"),
            }
            items.append(item)
        return {"items": items, "total": total}

    @_serialized
    def count_audit_events(self, *, query: str = "") -> int:
        cleaned = (query or "").strip()[:200]
        like = f"%{cleaned}%"
        return int(self.conn.execute(
            """
            SELECT COUNT(*) FROM audit_events
            WHERE ?='' OR event_id LIKE ? OR COALESCE(actor_account_id,'') LIKE ?
                OR action LIKE ? OR target_type LIKE ? OR COALESCE(target_id,'') LIKE ?
                OR outcome LIKE ? OR COALESCE(request_id,'') LIKE ?
            """,
            (cleaned, like, like, like, like, like, like, like),
        ).fetchone()[0])

    @_serialized
    def link_visitor(
        self,
        *,
        account_id: str,
        visitor_id: str,
        linked_at: str | None = None,
    ) -> None:
        clean_account_id = (account_id or "").strip()
        clean_visitor_id = (visitor_id or "").strip()
        if not clean_account_id:
            raise ValueError("account_id must not be empty")
        if not clean_visitor_id:
            raise ValueError("visitor_id must not be empty")
        observed_at = linked_at or utc_now()
        with transaction(self.conn, immediate=True):
            self.conn.execute(
                """
                INSERT OR IGNORE INTO account_visitor_links(
                    account_id,visitor_id,linked_at,last_seen_at
                ) VALUES(?,?,?,?)
                """,
                (
                    clean_account_id,
                    clean_visitor_id,
                    observed_at,
                    observed_at,
                ),
            )

    @_serialized
    def list_linked_visitors(self, account_id: str) -> list[str]:
        rows = self.conn.execute(
            """
            SELECT visitor_id
            FROM account_visitor_links
            WHERE account_id=?
            ORDER BY linked_at DESC,visitor_id ASC
            """,
            ((account_id or "").strip(),),
        ).fetchall()
        return [str(row["visitor_id"]) for row in rows]

    @classmethod
    def _validate_audit_payload(cls, value: object) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                normalized_key = str(key).casefold()
                if any(secret in normalized_key for secret in cls._AUDIT_SENSITIVE_KEYS):
                    raise ValueError("audit payload contains a sensitive key")
                cls._validate_audit_payload(nested)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                cls._validate_audit_payload(nested)

    @staticmethod
    def _required_audit_text(name: str, value: object) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError(f"{name} must not be empty")
        return cleaned

    def _insert_account_mutation_audit(
        self,
        *,
        actor_id: str,
        action: str,
        target_id: str,
        audit_context: dict[str, object],
    ) -> str:
        unexpected = set(audit_context) - {"request_id", "client_context", "metadata"}
        if unexpected:
            raise ValueError("invalid account mutation audit context")
        return self._insert_audit(
            actor_account_id=actor_id,
            action=action,
            target_type="account",
            target_id=target_id,
            outcome="success",
            request_id=audit_context.get("request_id"),
            client_context=audit_context.get("client_context"),
            metadata=audit_context.get("metadata"),
        )

    def _insert_audit(
        self,
        *,
        actor_account_id: str | None,
        action: str,
        target_type: str,
        target_id: str | None,
        outcome: str,
        request_id: object = None,
        client_context: object = None,
        metadata: object = None,
    ) -> str:
        if client_context is not None and not isinstance(client_context, dict):
            raise ValueError("client_context must be an object")
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")
        safe_client_context = client_context or {}
        safe_metadata = metadata or {}
        self._validate_audit_payload(safe_client_context)
        self._validate_audit_payload(safe_metadata)
        payload = {
            "_format": self._AUDIT_PAYLOAD_FORMAT,
            "client_context": safe_client_context,
            "metadata": safe_metadata,
        }
        try:
            encoded_payload = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("audit payload must be JSON serializable") from exc
        if len(encoded_payload.encode("utf-8")) > self._MAX_AUDIT_PAYLOAD_BYTES:
            raise ValueError("audit payload is too large")
        event_id = f"audit_{uuid.uuid4().hex}"
        actor_id = (actor_account_id or "").strip() or None
        clean_target_id = None if target_id is None else str(target_id).strip() or None
        clean_request_id = None if request_id is None else str(request_id).strip() or None
        self.conn.execute(
            """
            INSERT INTO audit_events(
                event_id,actor_account_id,action,target_type,target_id,outcome,
                request_id,created_at,metadata_json
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                event_id,
                actor_id,
                self._required_audit_text("action", action),
                self._required_audit_text("target_type", target_type),
                clean_target_id,
                self._required_audit_text("outcome", outcome),
                clean_request_id,
                utc_now(),
                encoded_payload,
            ),
        )
        return event_id

    @_serialized
    def record_audit(
        self,
        *,
        actor_account_id: str | None,
        action: str,
        target_type: str,
        target_id: str | None,
        outcome: str,
        request_id: str | None = None,
        client_context: dict | None = None,
        metadata: dict | None = None,
    ) -> str:
        with transaction(self.conn, immediate=True):
            return self._insert_audit(
                actor_account_id=actor_account_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                outcome=outcome,
                request_id=request_id,
                client_context=client_context,
                metadata=metadata,
            )

    @_serialized
    def list_audit_events(
        self,
        *,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= 100
        ):
            raise ValueError("limit must be between 1 and 100")
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise ValueError("offset must be zero or greater")

        clean_query = (query or "").strip().casefold()
        parameters: list[object] = []
        where = ""
        if clean_query:
            pattern = f"%{clean_query}%"
            where = """
                WHERE lower(coalesce(actor_account_id,'')) LIKE ?
                   OR lower(action) LIKE ?
                   OR lower(target_type) LIKE ?
                   OR lower(coalesce(target_id,'')) LIKE ?
                   OR lower(outcome) LIKE ?
                   OR lower(coalesce(request_id,'')) LIKE ?
            """
            parameters.extend([pattern] * 6)
        parameters.extend([limit, offset])
        rows = self.conn.execute(
            f"""
            SELECT * FROM audit_events
            {where}
            ORDER BY created_at DESC,rowid DESC
            LIMIT ? OFFSET ?
            """,
            parameters,
        ).fetchall()

        events: list[dict] = []
        for row in rows:
            try:
                stored_payload = json.loads(row["metadata_json"])
            except (TypeError, ValueError):
                stored_payload = {}
            if (
                isinstance(stored_payload, dict)
                and stored_payload.get("_format") == self._AUDIT_PAYLOAD_FORMAT
            ):
                stored_context = stored_payload.get("client_context", {})
                stored_metadata = stored_payload.get("metadata", {})
            else:
                stored_context = {}
                stored_metadata = stored_payload if isinstance(stored_payload, dict) else {}
            events.append(
                {
                    "event_id": row["event_id"],
                    "actor_account_id": row["actor_account_id"],
                    "action": row["action"],
                    "target_type": row["target_type"],
                    "target_id": row["target_id"],
                    "outcome": row["outcome"],
                    "request_id": row["request_id"],
                    "created_at": row["created_at"],
                    "client_context": stored_context,
                    "metadata": stored_metadata,
                }
            )
        return events

    @_serialized
    def bootstrap_owner(
        self,
        *,
        email: str,
        display_name: str,
        password: str,
        username: str | None = None,
    ) -> AccountRecord:
        normalized = normalize_email(email)
        clean_name = self._clean_display_name(display_name)
        clean_username = (username or "").strip() or None
        with transaction(self.conn, immediate=True):
            existing = self.conn.execute(
                "SELECT * FROM accounts WHERE role='owner'"
            ).fetchone()
            if existing is not None:
                if existing["email"] != normalized:
                    raise RoleViolation("a different owner is already bootstrapped")
                return self._account_from_row(existing)
            if self.conn.execute("SELECT 1 FROM accounts WHERE email=?", (normalized,)).fetchone():
                raise RoleViolation("owner email belongs to another account")
            now = utc_now()
            account_id = f"acct_{uuid.uuid4().hex}"
            self.conn.execute(
                """
                INSERT INTO accounts(
                    account_id,email,username,display_name,role,status,password_hash,
                    created_by,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    account_id,
                    normalized,
                    clean_username,
                    clean_name,
                    "owner",
                    "active",
                    hash_password(password),
                    None,
                    now,
                    now,
                ),
            )
        owner = self.get_account(account_id)
        assert owner is not None
        return owner

    def _record_login(self, identifier: str, account_id: str | None, outcome: str) -> None:
        identifier_digest = hashlib.sha256(identifier.casefold().encode("utf-8")).hexdigest()
        self.conn.execute(
            "INSERT INTO login_events(event_id,account_id,identifier_hash,outcome,created_at) VALUES(?,?,?,?,?)",
            (f"login_{uuid.uuid4().hex}", account_id, identifier_digest, outcome, utc_now()),
        )

    @_serialized
    def authenticate_account(self, email_or_username: str, password: str) -> AccountRecord:
        identifier = (email_or_username or "").strip()
        authenticated: AccountRecord | None = None
        with transaction(self.conn, immediate=True):
            try:
                account = self.get_account(identifier)
            except (TypeError, ValueError):
                account = None
            row = None
            if account is not None:
                row = self.conn.execute(
                    "SELECT password_hash,status FROM accounts WHERE account_id=?",
                    (account.account_id,),
                ).fetchone()
            encoded = (
                row["password_hash"]
                if row is not None and row["password_hash"]
                else self._dummy_password_hash
            )
            valid = verify_password(password or "", encoded)
            if account is None or row is None or row["status"] != "active" or not valid:
                self._record_login(
                    identifier,
                    account.account_id if account else None,
                    "failure",
                )
            else:
                now = utc_now()
                next_password_hash = (
                    hash_password(password) if password_needs_rehash(encoded) else encoded
                )
                self.conn.execute(
                    """
                    UPDATE accounts
                    SET password_hash=?,last_access_at=?,updated_at=?
                    WHERE account_id=?
                    """,
                    (next_password_hash, now, now, account.account_id),
                )
                self._record_login(identifier, account.account_id, "success")
                refreshed = self.conn.execute(
                    "SELECT * FROM accounts WHERE account_id=?", (account.account_id,)
                ).fetchone()
                assert refreshed is not None
                authenticated = self._account_from_row(refreshed)
        if authenticated is None:
            raise AuthenticationFailed("invalid credentials")
        return authenticated

    @_serialized
    def create_invitation(
        self,
        *,
        account_id: str,
        created_by: str,
    ) -> tuple[InvitationRecord, str]:
        now_dt = datetime.now(timezone.utc)
        expiry = now_dt + timedelta(hours=48)
        token, stored_hash = new_token("invite")
        invitation_id = f"inv_{uuid.uuid4().hex}"
        now = now_dt.isoformat()
        with transaction(self.conn, immediate=True):
            account = self.get_account(account_id)
            if account is None:
                raise KeyError(account_id)
            self._authorized_creator(created_by, account.role)
            if account.status != "pending_activation":
                raise InvitationInvalid("account is not pending activation")
            self.conn.execute(
                """
                UPDATE invitations SET revoked_at=?
                WHERE account_id=? AND consumed_at IS NULL AND revoked_at IS NULL
                """,
                (now, account.account_id),
            )
            self.conn.execute(
                """
                INSERT INTO invitations(
                    invitation_id,account_id,email,intended_role,token_hash,created_by,
                    created_at,expires_at
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    invitation_id,
                    account.account_id,
                    account.email,
                    account.role,
                    stored_hash,
                    created_by,
                    now,
                    expiry.isoformat(),
                ),
            )
        row = self.conn.execute(
            "SELECT * FROM invitations WHERE invitation_id=?", (invitation_id,)
        ).fetchone()
        assert row is not None
        return self._invitation_from_row(row), token

    @_serialized
    def get_invitation(self, invitation_id: str) -> InvitationRecord | None:
        clean_id = (invitation_id or "").strip()
        if not clean_id:
            return None
        row = self.conn.execute(
            "SELECT * FROM invitations WHERE invitation_id=?", (clean_id,)
        ).fetchone()
        return self._invitation_from_row(row) if row is not None else None

    @_serialized
    def invitation_status(
        self, token: str
    ) -> tuple[str, InvitationRecord | None]:
        try:
            stored_hash = token_hash(token)
        except TypeError:
            return "invalid", None
        row = self.conn.execute(
            "SELECT * FROM invitations WHERE token_hash=?", (stored_hash,)
        ).fetchone()
        if row is None:
            return "invalid", None
        invitation = self._invitation_from_row(row)
        if invitation.consumed_at is not None:
            return "consumed", invitation
        if invitation.revoked_at is not None:
            return "revoked", invitation
        if _parse_time(invitation.expires_at) <= datetime.now(timezone.utc):
            return "expired", invitation
        return "pending", invitation

    @_serialized
    def record_invitation_delivery(
        self,
        invitation_id: str,
        *,
        delivered: bool,
        error: str | None = None,
    ) -> InvitationRecord:
        clean_error = None
        if not delivered:
            clean_error = " ".join((error or "Email delivery failed").split())[:240]
        with transaction(self.conn, immediate=True):
            changed = self.conn.execute(
                """
                UPDATE invitations SET delivery_status=?,delivery_error=?
                WHERE invitation_id=?
                """,
                (
                    "delivered" if delivered else "failed",
                    clean_error,
                    invitation_id,
                ),
            )
            if changed.rowcount != 1:
                raise KeyError(invitation_id)
            row = self.conn.execute(
                "SELECT * FROM invitations WHERE invitation_id=?", (invitation_id,)
            ).fetchone()
            assert row is not None
            invitation = self._invitation_from_row(row)
        return invitation

    @_serialized
    def revoke_invitation(
        self,
        invitation_id: str,
        *,
        revoked_by: str,
    ) -> InvitationRecord:
        with transaction(self.conn, immediate=True):
            row = self.conn.execute(
                "SELECT * FROM invitations WHERE invitation_id=?", (invitation_id,)
            ).fetchone()
            if row is None:
                raise KeyError(invitation_id)
            invitation = self._invitation_from_row(row)
            self._authorized_creator(revoked_by, invitation.intended_role)
            if invitation.consumed_at is not None:
                raise InvitationInvalid("consumed invitations cannot be revoked")
            if invitation.revoked_at is None:
                self.conn.execute(
                    "UPDATE invitations SET revoked_at=? WHERE invitation_id=?",
                    (utc_now(), invitation_id),
                )
            refreshed = self.conn.execute(
                "SELECT * FROM invitations WHERE invitation_id=?", (invitation_id,)
            ).fetchone()
            assert refreshed is not None
            revoked = self._invitation_from_row(refreshed)
        return revoked

    @_serialized
    def consume_invitation(self, token: str, *, password: str) -> AccountRecord:
        stored_hash = token_hash(token)
        row = self.conn.execute(
            "SELECT * FROM invitations WHERE token_hash=?", (stored_hash,)
        ).fetchone()
        if row is None:
            raise InvitationInvalid("invitation is invalid")
        if row["consumed_at"] is not None or row["revoked_at"] is not None:
            raise InvitationInvalid("invitation is no longer available")
        if _parse_time(row["expires_at"]) <= datetime.now(timezone.utc):
            raise InvitationExpired("invitation has expired")
        encoded_password = hash_password(password)
        now = utc_now()
        with transaction(self.conn, immediate=True):
            current = self.conn.execute(
                "SELECT * FROM invitations WHERE token_hash=?", (stored_hash,)
            ).fetchone()
            if current is None or current["consumed_at"] is not None or current["revoked_at"] is not None:
                raise InvitationInvalid("invitation is no longer available")
            if _parse_time(current["expires_at"]) <= datetime.now(timezone.utc):
                raise InvitationExpired("invitation has expired")
            changed = self.conn.execute(
                """
                UPDATE accounts SET password_hash=?,status='active',updated_at=?
                WHERE account_id=? AND status='pending_activation'
                """,
                (encoded_password, now, current["account_id"]),
            )
            if changed.rowcount != 1:
                raise InvitationInvalid("account cannot be activated")
            self.conn.execute(
                "UPDATE invitations SET consumed_at=? WHERE invitation_id=?",
                (now, current["invitation_id"]),
            )
        account = self.get_account(row["account_id"])
        assert account is not None
        return account

    @_serialized
    def create_session(
        self,
        account_id: str,
        *,
        expires_at: str | None = None,
    ) -> str:
        now_dt = datetime.now(timezone.utc)
        expiry = _parse_time(expires_at) if expires_at is not None else now_dt + timedelta(hours=12)
        if expiry <= now_dt:
            raise ValueError("session expiry must be in the future")
        token, stored_hash = new_token("session")
        with transaction(self.conn, immediate=True):
            account = self.get_account(account_id)
            if account is None or account.status != "active":
                raise AuthenticationFailed("account cannot create a session")
            self.conn.execute(
                """
                INSERT INTO account_sessions(
                    session_id,account_id,session_hash,created_at,last_seen_at,expires_at
                ) VALUES(?,?,?,?,?,?)
                """,
                (
                    f"asess_{uuid.uuid4().hex}",
                    account.account_id,
                    stored_hash,
                    now_dt.isoformat(),
                    now_dt.isoformat(),
                    expiry.isoformat(),
                ),
            )
        return token

    @_serialized
    def resolve_session(self, token: str) -> AccountRecord | None:
        with transaction(self.conn, immediate=True):
            row = self.conn.execute(
                """
                SELECT s.*,a.*
                FROM account_sessions s
                JOIN accounts a ON a.account_id=s.account_id
                WHERE s.session_hash=?
                """,
                (token_hash(token),),
            ).fetchone()
            if (
                row is None
                or row["revoked_at"] is not None
                or row["status"] != "active"
                or _parse_time(row["expires_at"]) <= datetime.now(timezone.utc)
            ):
                return None
            now = utc_now()
            self.conn.execute(
                "UPDATE account_sessions SET last_seen_at=? WHERE session_id=?",
                (now, row["session_id"]),
            )
            self.conn.execute(
                "UPDATE accounts SET last_access_at=?,updated_at=? WHERE account_id=?",
                (now, now, row["account_id"]),
            )
            refreshed = self.conn.execute(
                "SELECT * FROM accounts WHERE account_id=?", (row["account_id"],)
            ).fetchone()
            assert refreshed is not None
            resolved = self._account_from_row(refreshed)
        return resolved

    @_serialized
    def revoke_session(self, token: str) -> bool:
        changed = self.conn.execute(
            """
            UPDATE account_sessions SET revoked_at=?
            WHERE session_hash=? AND revoked_at IS NULL
            """,
            (utc_now(), token_hash(token)),
        )
        self.conn.commit()
        return changed.rowcount == 1

    @_serialized
    def stats(self) -> dict[str, int]:
        return {
            "accounts": int(self.conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]),
            "invitations": int(self.conn.execute("SELECT COUNT(*) FROM invitations").fetchone()[0]),
            "sessions": int(self.conn.execute("SELECT COUNT(*) FROM account_sessions").fetchone()[0]),
        }
