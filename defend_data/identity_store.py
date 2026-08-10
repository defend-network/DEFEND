from __future__ import annotations

import hashlib
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
