"""Server-side admin/owner authentication for DEFEND admin surfaces.

No usable credential defaults are shipped. Configure:
  DEFEND_ADMIN_USER
  DEFEND_ADMIN_PASS
  DEFEND_OWNER_USER
  DEFEND_OWNER_PASS

Tokens are in-memory, expire automatically, and are invalidated by API restart.
This is intentionally small and dependency-free so it can later be replaced by a
real identity provider without changing the TableTennis routes.
"""
from __future__ import annotations

import os
import secrets
import time
from dataclasses import dataclass
from typing import Literal

from fastapi import Header, HTTPException

AdminRole = Literal["admin", "owner"]


@dataclass(frozen=True)
class AdminPrincipal:
    username: str
    role: AdminRole
    expires_at: float


# token -> principal
_TOKENS: dict[str, AdminPrincipal] = {}


def _session_seconds() -> int:
    try:
        hours = float(os.getenv("DEFEND_ADMIN_SESSION_HOURS", "12"))
    except ValueError:
        hours = 12.0
    return max(900, min(int(hours * 3600), 7 * 24 * 3600))


def _configured_credentials() -> tuple[str, str, str, str]:
    admin_user = os.getenv("DEFEND_ADMIN_USER", "admin").strip()
    owner_user = os.getenv("DEFEND_OWNER_USER", "MASSA").strip()
    admin_pass = os.getenv("DEFEND_ADMIN_PASS", "")
    owner_pass = os.getenv("DEFEND_OWNER_PASS", "")

    # Usernames may have harmless defaults; passwords may not.
    if not admin_pass or not owner_pass:
        raise HTTPException(
            status_code=503,
            detail=(
                "Admin credentials are not configured. Set DEFEND_ADMIN_PASS "
                "and DEFEND_OWNER_PASS in the API environment."
            ),
        )
    if admin_user == owner_user:
        raise HTTPException(status_code=503, detail="Admin and owner usernames must differ")
    if secrets.compare_digest(admin_pass, owner_pass):
        raise HTTPException(status_code=503, detail="Admin and owner passwords must differ")
    return admin_user, admin_pass, owner_user, owner_pass


def authenticate(username: str, password: str) -> tuple[str, AdminRole, str, int]:
    admin_user, admin_pass, owner_user, owner_pass = _configured_credentials()
    u = (username or "").strip()
    p = password or ""

    role: AdminRole | None = None
    canonical_user = u
    if secrets.compare_digest(u, owner_user) and secrets.compare_digest(p, owner_pass):
        role = "owner"
        canonical_user = owner_user
    elif secrets.compare_digest(u, admin_user) and secrets.compare_digest(p, admin_pass):
        role = "admin"
        canonical_user = admin_user
    if role is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    ttl = _session_seconds()
    expires_at = time.time() + ttl
    token = secrets.token_urlsafe(32)
    _TOKENS[token] = AdminPrincipal(canonical_user, role, expires_at)
    _purge_expired()
    return canonical_user, role, token, ttl


def revoke(token: str) -> None:
    _TOKENS.pop(token, None)


def _purge_expired() -> None:
    now = time.time()
    for token, principal in list(_TOKENS.items()):
        if principal.expires_at <= now:
            _TOKENS.pop(token, None)


def _bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing admin bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing admin bearer token")
    return token


def require_admin(authorization: str | None = Header(default=None)) -> AdminPrincipal:
    _purge_expired()
    token = _bearer_token(authorization)
    principal = _TOKENS.get(token)
    if principal is None:
        raise HTTPException(status_code=401, detail="Admin session expired or invalid")
    return principal


def require_owner(authorization: str | None = Header(default=None)) -> AdminPrincipal:
    principal = require_admin(authorization)
    if principal.role != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")
    return principal


def token_from_header(authorization: str | None) -> str:
    """Used only by logout to revoke the caller's token."""
    return _bearer_token(authorization)
