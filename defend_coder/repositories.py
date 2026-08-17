from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from .db import CoderDatabase


@dataclass(frozen=True)
class AccountRecord:
    account_id: UUID
    username: str
    email: str | None
    password_hash: str
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class SessionRecord:
    session_id: UUID
    account_id: UUID
    token_hash: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    last_seen_at: datetime


@dataclass(frozen=True)
class WorkspaceRecord:
    workspace_id: UUID
    owner_account_id: UUID
    name: str
    workspace_root: str
    repository_url: str | None
    default_branch: str | None
    created_at: datetime
    updated_at: datetime


class CoderRepository:
    def __init__(self, db: CoderDatabase) -> None:
        self._db = db

    def create_account(
        self,
        *,
        username: str,
        email: str | None,
        password_hash: str,
        role: str,
    ) -> AccountRecord:
        if role not in {"admin", "consumer"}:
            raise ValueError("role must be admin or consumer")

        account_id = uuid4()

        with self._db.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO coder_accounts(
                        account_id,
                        username,
                        email,
                        password_hash,
                        role
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING
                        account_id,
                        username,
                        email,
                        password_hash,
                        role,
                        is_active,
                        created_at,
                        updated_at
                    """,
                    (
                        account_id,
                        username,
                        email,
                        password_hash,
                        role,
                    ),
                )
                return _account(cursor.fetchone())

    def get_account_by_username(
        self,
        username: str,
    ) -> AccountRecord | None:
        with self._db.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        account_id,
                        username,
                        email,
                        password_hash,
                        role,
                        is_active,
                        created_at,
                        updated_at
                    FROM coder_accounts
                    WHERE username = %s
                    """,
                    (username,),
                )
                row = cursor.fetchone()

        return _account(row) if row else None

    def get_account(
        self,
        account_id: UUID,
    ) -> AccountRecord | None:
        with self._db.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        account_id,
                        username,
                        email,
                        password_hash,
                        role,
                        is_active,
                        created_at,
                        updated_at
                    FROM coder_accounts
                    WHERE account_id = %s
                    """,
                    (account_id,),
                )
                row = cursor.fetchone()

        return _account(row) if row else None

    def create_session(
        self,
        *,
        account_id: UUID,
        token_hash: str,
        expires_at: datetime,
    ) -> SessionRecord:
        if len(token_hash) != 64:
            raise ValueError(
                "session token hash must be a 64-character SHA-256 hex digest"
            )

        session_id = uuid4()

        with self._db.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO coder_sessions(
                        session_id,
                        account_id,
                        token_hash,
                        expires_at
                    )
                    VALUES (%s, %s, %s, %s)
                    RETURNING
                        session_id,
                        account_id,
                        token_hash,
                        created_at,
                        expires_at,
                        revoked_at,
                        last_seen_at
                    """,
                    (
                        session_id,
                        account_id,
                        token_hash,
                        expires_at,
                    ),
                )
                return _session(cursor.fetchone())

    def get_session_by_hash(
        self,
        token_hash: str,
    ) -> SessionRecord | None:
        with self._db.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        session_id,
                        account_id,
                        token_hash,
                        created_at,
                        expires_at,
                        revoked_at,
                        last_seen_at
                    FROM coder_sessions
                    WHERE token_hash = %s
                    """,
                    (token_hash,),
                )
                row = cursor.fetchone()

        return _session(row) if row else None

    def revoke_session(
        self,
        session_id: UUID,
    ) -> None:
        with self._db.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE coder_sessions
                    SET revoked_at = COALESCE(revoked_at, now())
                    WHERE session_id = %s
                    """,
                    (session_id,),
                )

    def touch_session_last_seen(
        self,
        session_id: UUID,
    ) -> None:
        with self._db.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE coder_sessions
                    SET last_seen_at = now()
                    WHERE session_id = %s
                        AND revoked_at IS NULL
                    """,
                    (session_id,),
                )

    def list_expired_idle_sessions(
        self,
        threshold: datetime,
    ) -> tuple[SessionRecord, ...]:
        with self._db.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        s.session_id,
                        s.account_id,
                        s.token_hash,
                        s.created_at,
                        s.expires_at,
                        s.revoked_at,
                        s.last_seen_at
                    FROM coder_sessions AS s
                    JOIN coder_accounts AS a
                        ON a.account_id = s.account_id
                    WHERE s.revoked_at IS NULL
                        AND s.expires_at > now()
                        AND s.last_seen_at < %s
                        AND a.role = 'consumer'
                        AND a.is_active = TRUE
                    """,
                    (threshold,),
                )
                return tuple(_session(row) for row in cursor.fetchall())

    def create_workspace(
        self,
        *,
        owner_account_id: UUID,
        name: str,
        workspace_root: str,
        repository_url: str | None = None,
        default_branch: str | None = None,
    ) -> WorkspaceRecord:
        workspace_id = uuid4()

        with self._db.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO coder_workspaces(
                        workspace_id,
                        owner_account_id,
                        name,
                        workspace_root,
                        repository_url,
                        default_branch
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING
                        workspace_id,
                        owner_account_id,
                        name,
                        workspace_root,
                        repository_url,
                        default_branch,
                        created_at,
                        updated_at
                    """,
                    (
                        workspace_id,
                        owner_account_id,
                        name,
                        workspace_root,
                        repository_url,
                        default_branch,
                    ),
                )
                return _workspace(cursor.fetchone())

    def list_workspaces_for_owner(
        self,
        owner_account_id: UUID,
    ) -> tuple[WorkspaceRecord, ...]:
        with self._db.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        workspace_id,
                        owner_account_id,
                        name,
                        workspace_root,
                        repository_url,
                        default_branch,
                        created_at,
                        updated_at
                    FROM coder_workspaces
                    WHERE owner_account_id = %s
                    ORDER BY created_at, workspace_id
                    """,
                    (owner_account_id,),
                )
                rows = cursor.fetchall()

        return tuple(_workspace(row) for row in rows)

    def append_audit_event(
        self,
        *,
        actor_account_id: UUID | None,
        event_type: str,
        target_type: str,
        target_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        with self._db.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO coder_audit_events(
                        actor_account_id,
                        event_type,
                        target_type,
                        target_id,
                        detail_json
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        actor_account_id,
                        event_type,
                        target_type,
                        target_id,
                        Jsonb(detail or {}),
                    ),
                )


def _account(row) -> AccountRecord:
    return AccountRecord(*row)


def _session(row) -> SessionRecord:
    return SessionRecord(*row)


def _workspace(row) -> WorkspaceRecord:
    return WorkspaceRecord(*row)
