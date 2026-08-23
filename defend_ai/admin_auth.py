"""Server-side admin/owner authentication for DEFEND admin surfaces.

The initial owner is bootstrapped from ``DEFEND_OWNER_USER`` and
``DEFEND_OWNER_PASS``. ``DEFEND_OWNER_EMAIL`` may override the stable owner email
used by the identity store. Admin accounts are created through the invitation
flow rather than environment credentials.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import Header, HTTPException

from defend_data.identity_store import AuthenticationFailed, IdentityStore

AdminRole = Literal["admin", "owner"]


@dataclass(frozen=True)
class AdminPrincipal:
    account_id: str
    username: str
    role: AdminRole
    expires_at: float


_IDENTITY_STORE: IdentityStore | None = None


def _session_seconds() -> int:
    try:
        hours = float(os.getenv("DEFEND_ADMIN_SESSION_HOURS", "12"))
    except ValueError:
        hours = 12.0
    return max(900, min(int(hours * 3600), 7 * 24 * 3600))


def _configured_owner() -> tuple[str, str, str]:
    owner_user = os.getenv("DEFEND_OWNER_USER", "MASSA").strip()
    owner_pass = os.getenv("DEFEND_OWNER_PASS", "")
    owner_email = os.getenv(
        "DEFEND_OWNER_EMAIL", "chairman@defend-network.org"
    ).strip()

    if not owner_user or not owner_pass or not owner_email:
        raise HTTPException(
            status_code=503,
            detail=(
                "Owner credentials are not configured. Set DEFEND_OWNER_USER, "
                "DEFEND_OWNER_PASS, and optionally DEFEND_OWNER_EMAIL in the API "
                "environment."
            ),
        )
    return owner_user, owner_email, owner_pass


def configure_identity_store(store: IdentityStore) -> None:
    """Configure durable admin auth and idempotently bootstrap the owner."""
    if not isinstance(store, IdentityStore):
        raise TypeError("store must be an IdentityStore")
    owner_user, owner_email, owner_pass = _configured_owner()
    try:
        store.bootstrap_owner(
            email=owner_email,
            display_name=owner_user,
            password=owner_pass,
            username=owner_user,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=503,
            detail="Owner identity configuration is invalid",
        ) from exc
    global _IDENTITY_STORE
    _IDENTITY_STORE = store


def _identity_store() -> IdentityStore:
    if _IDENTITY_STORE is None:
        raise HTTPException(
            status_code=503,
            detail="Identity store is not configured",
        )
    return _IDENTITY_STORE


def canonical_admin_login_identifier(identifier: str) -> str:
    """Collapse known account aliases before login rate-limit hashing."""
    cleaned = (identifier or "").strip()
    try:
        account = _identity_store().get_account(cleaned)
    except (TypeError, ValueError):
        account = None
    return account.account_id if account is not None else cleaned


def authenticate(username: str, password: str) -> tuple[str, AdminRole, str, int]:
    store = _identity_store()
    identifier = (username or "").strip()
    try:
        account = store.authenticate_account(identifier, password or "")
    except AuthenticationFailed as exc:
        raise HTTPException(status_code=401, detail="Invalid credentials") from exc
    if account.role not in {"admin", "owner"}:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    ttl = _session_seconds()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
    token = store.create_session(account.account_id, expires_at=expires_at.isoformat())
    owner_user, _, _ = _configured_owner()
    canonical_user = (
        owner_user
        if account.role == "owner" and identifier.casefold() == owner_user.casefold()
        else account.email
    )
    return canonical_user, account.role, token, ttl


def revoke(token: str) -> None:
    _identity_store().revoke_session(token)


def _bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing admin bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing admin bearer token")
    return token


def require_admin(authorization: str | None = Header(default=None)) -> AdminPrincipal:
    token = _bearer_token(authorization)
    account = _identity_store().resolve_session(token)
    if account is None:
        raise HTTPException(status_code=401, detail="Admin session expired or invalid")
    if account.role not in {"admin", "owner"}:
        raise HTTPException(status_code=403, detail="Admin access required")
    return AdminPrincipal(
        account_id=account.account_id,
        username=account.email,
        role=account.role,
        # Authorization always uses the persisted session expiry. This retained
        # field is presentation-only compatibility for existing call sites.
        expires_at=time.time() + _session_seconds(),
    )


def require_owner(authorization: str | None = Header(default=None)) -> AdminPrincipal:
    principal = require_admin(authorization)
    if principal.role != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")
    return principal


def token_from_header(authorization: str | None) -> str:
    """Used only by logout to revoke the caller's token."""
    return _bearer_token(authorization)
