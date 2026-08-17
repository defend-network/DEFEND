from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from .repositories import AccountRecord, CoderRepository


class AuthError(RuntimeError):
    """Public-safe authentication/authorization failure."""


@dataclass(frozen=True)
class AuthenticatedAccount:
    account_id: UUID
    username: str
    email: str | None
    role: str
    is_active: bool

    @classmethod
    def from_record(cls, record: AccountRecord) -> "AuthenticatedAccount":
        return cls(
            account_id=record.account_id,
            username=record.username,
            email=record.email,
            role=record.role,
            is_active=record.is_active,
        )


@dataclass(frozen=True)
class SessionToken:
    token: str
    account: AuthenticatedAccount
    expires_at: datetime


class AuthService:
    """Unified DEFENDcoder authentication for admin and consumer accounts.

    Passwords use Argon2id. Session tokens are opaque random values returned
    only to the caller; PostgreSQL stores only their SHA-256 digest.
    """

    def __init__(
        self,
        repository: CoderRepository,
        *,
        session_ttl: timedelta = timedelta(hours=8),
        password_hasher: PasswordHasher | None = None,
    ) -> None:
        self._repository = repository
        self._session_ttl = session_ttl
        self._password_hasher = password_hasher or PasswordHasher()

        # Used when a username does not exist so the public login path still
        # performs a real Argon2 verification rather than returning early.
        self._dummy_password_hash = self._password_hasher.hash(
            "DEFENDcoder-dummy-password-never-used-for-login"
        )

    def hash_password(self, password: str) -> str:
        if not isinstance(password, str) or not password:
            raise ValueError("password must not be empty")

        return self._password_hasher.hash(password)

    def verify_password(
        self,
        password_hash: str,
        password: str,
    ) -> bool:
        try:
            return self._password_hasher.verify(
                password_hash,
                password,
            )
        except (VerifyMismatchError, InvalidHashError):
            return False

    def create_account(
        self,
        *,
        username: str,
        email: str | None,
        password: str,
        role: str,
    ) -> AuthenticatedAccount:
        if role not in {"admin", "consumer"}:
            raise ValueError("role must be admin or consumer")

        username = username.strip()

        if not username:
            raise ValueError("username must not be empty")

        if email is not None:
            email = email.strip() or None

        record = self._repository.create_account(
            username=username,
            email=email,
            password_hash=self.hash_password(password),
            role=role,
        )

        self._repository.append_audit_event(
            actor_account_id=record.account_id,
            event_type="account.created",
            target_type="coder_account",
            target_id=str(record.account_id),
            detail={"role": record.role},
        )

        return AuthenticatedAccount.from_record(record)

    def login(
        self,
        username: str,
        password: str,
    ) -> SessionToken:
        record = self._repository.get_account_by_username(
            username.strip()
        )

        if record is None:
            # Avoid an immediate username-enumeration timing shortcut.
            self.verify_password(
                self._dummy_password_hash,
                password,
            )
            raise AuthError("invalid credentials")

        if not record.is_active:
            # Still verify the supplied password before returning the same
            # public error used for invalid credentials.
            self.verify_password(
                record.password_hash,
                password,
            )
            raise AuthError("invalid credentials")

        if not self.verify_password(
            record.password_hash,
            password,
        ):
            raise AuthError("invalid credentials")

        raw_token = secrets.token_urlsafe(32)
        token_hash = _hash_session_token(raw_token)
        expires_at = (
            datetime.now(timezone.utc)
            + self._session_ttl
        )

        self._repository.create_session(
            account_id=record.account_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )

        self._repository.append_audit_event(
            actor_account_id=record.account_id,
            event_type="auth.login",
            target_type="coder_session",
            detail={"role": record.role},
        )

        return SessionToken(
            token=raw_token,
            account=AuthenticatedAccount.from_record(record),
            expires_at=expires_at,
        )

    def authenticate_session(
        self,
        raw_token: str,
    ) -> AuthenticatedAccount:
        if not isinstance(raw_token, str) or not raw_token:
            raise AuthError("invalid session")

        token_hash = _hash_session_token(raw_token)

        session = self._repository.get_session_by_hash(
            token_hash
        )

        if session is None:
            raise AuthError("invalid session")

        now = datetime.now(timezone.utc)

        if session.revoked_at is not None:
            raise AuthError("invalid session")

        if session.expires_at <= now:
            raise AuthError("invalid session")

        account = self._repository.get_account(
            session.account_id
        )

        if account is None or not account.is_active:
            raise AuthError("invalid session")

        return AuthenticatedAccount.from_record(account)

    def logout(self, raw_token: str) -> None:
        if not isinstance(raw_token, str) or not raw_token:
            raise AuthError("invalid session")

        token_hash = _hash_session_token(raw_token)

        session = self._repository.get_session_by_hash(
            token_hash
        )

        if session is None:
            raise AuthError("invalid session")

        self._repository.revoke_session(
            session.session_id
        )

        self._repository.append_audit_event(
            actor_account_id=session.account_id,
            event_type="auth.logout",
            target_type="coder_session",
            target_id=str(session.session_id),
        )

    def touch_session(self, raw_token: str) -> None:
        """Record genuine activity for a live session (advisory; never raises).

        Heartbeat calls must NOT use this — the idle policy requires that
        heartbeats never extend the inactivity window.
        """
        if not isinstance(raw_token, str) or not raw_token:
            return

        token_hash = _hash_session_token(raw_token)

        try:
            session = self._repository.get_session_by_hash(token_hash)
        except Exception:
            return

        if session is None or session.revoked_at is not None:
            return

        try:
            self._repository.touch_session_last_seen(session.session_id)
        except Exception:
            return

    def revoke_idle_sessions(
        self,
        *,
        now: datetime | None = None,
        idle_timeout: timedelta | None = None,
    ) -> tuple[tuple[UUID, UUID], ...]:
        """Revoke consumer sessions idle past the timeout (server-authoritative).

        Heartbeats never count as activity; only genuine API activity resets
        ``last_seen_at``. Admin sessions are exempt. Returns the
        (session_id, account_id) pairs revoked and records one
        ``session.idle_timeout`` audit event per session.
        """
        if idle_timeout is None:
            idle_timeout = self._session_ttl

        if idle_timeout.total_seconds() <= 0:
            return ()

        effective_now = now or datetime.now(timezone.utc)
        threshold = effective_now - idle_timeout

        expired = self._repository.list_expired_idle_sessions(
            threshold
        )

        revoked: list[tuple[UUID, UUID]] = []

        for session in expired:
            self._repository.revoke_session(session.session_id)
            self._repository.append_audit_event(
                actor_account_id=session.account_id,
                event_type="session.idle_timeout",
                target_type="coder_session",
                target_id=str(session.session_id),
                detail={
                    "account_id": str(session.account_id),
                    "timeout_seconds": int(idle_timeout.total_seconds()),
                },
            )
            revoked.append(
                (session.session_id, session.account_id)
            )

        return tuple(revoked)

    def require_role(
        self,
        account: AuthenticatedAccount,
        required_role: str,
    ) -> AuthenticatedAccount:
        if account.role != required_role:
            raise AuthError("forbidden")

        return account


def _hash_session_token(raw_token: str) -> str:
    return hashlib.sha256(
        raw_token.encode("utf-8")
    ).hexdigest()
