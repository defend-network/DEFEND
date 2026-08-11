from __future__ import annotations

import hashlib
import os
import threading
import time
from collections import OrderedDict, deque
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from admin_auth import AdminPrincipal, require_admin
from defend_data.identity_mailer import (
    DeliveryResult,
    GmailInvitationMailer,
    activation_url,
)
from defend_data.identity_security import normalize_email
from defend_data.identity_store import (
    AccountRecord,
    AuthenticationFailed,
    IdentityStore,
    InvitationExpired,
    InvitationInvalid,
    InvitationRecord,
    RoleViolation,
)
from defend_data.visitor_store import client_ip


router = APIRouter()

_ACCOUNT_COOKIE = "defend_account_session"
_RATE_LIMIT_ATTEMPTS = 5
_RATE_LIMIT_WINDOW_SECONDS = 60.0


class SensitivePathRedactionMiddleware:
    """Remove raw activation tokens before outer server access logging."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        path = scope.get("path", "") if scope.get("type") == "http" else ""
        sensitive = (
            path.startswith("/api/activate/")
            and path.rstrip("/") != "/api/activate/status"
        )

        def redact() -> None:
            if not sensitive:
                return
            suffix = "/status" if path.endswith("/status") else ""
            redacted = f"/api/activate/[redacted]{suffix}"
            scope["path"] = redacted
            scope["raw_path"] = redacted.encode("ascii")

        async def redact_before_response(message) -> None:
            if message.get("type") == "http.response.start":
                redact()
            await send(message)

        try:
            await self.app(scope, receive, redact_before_response)
        except Exception:
            # Starlette's outer error middleware may generate the response;
            # redact before control returns to that logging boundary as well.
            redact()
            raise


class _BoundedRateLimiter:
    def __init__(self, *, max_keys: int = 4096) -> None:
        self._max_keys = max_keys
        self._events: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()
        self._clock = time.monotonic

    def allow(self, key: str) -> bool:
        return self.allow_many((key,))

    def allow_many(self, keys: tuple[str, ...]) -> bool:
        unique_keys = tuple(dict.fromkeys(keys))
        now = self._clock()
        cutoff = now - _RATE_LIMIT_WINDOW_SECONDS
        with self._lock:
            existing: dict[str, deque[float]] = {}
            for key in unique_keys:
                attempts = self._events.get(key)
                if attempts is None:
                    continue
                while attempts and attempts[0] <= cutoff:
                    attempts.popleft()
                self._events.move_to_end(key)
                existing[key] = attempts
            if any(
                len(existing.get(key, ())) >= _RATE_LIMIT_ATTEMPTS
                for key in unique_keys
            ):
                return False
            for key in unique_keys:
                attempts = existing.get(key)
                if attempts is None:
                    while len(self._events) >= self._max_keys:
                        self._events.popitem(last=False)
                    attempts = deque()
                    self._events[key] = attempts
                attempts.append(now)
            return True

    def reset(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)


class CreateAccountIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=160)
    role: Literal["admin", "user"]


class ActivateIn(BaseModel):
    token: str
    password: str


class ActivationStatusIn(BaseModel):
    token: str


class AccountLoginIn(BaseModel):
    email: str
    password: str


def _identity_store(request: Request) -> IdentityStore:
    data = getattr(request.app.state, "defend_data", None)
    store = getattr(data, "identity", None)
    if not isinstance(store, IdentityStore):
        raise HTTPException(status_code=503, detail="Identity service is unavailable")
    return store


def _mailer() -> GmailInvitationMailer:
    return GmailInvitationMailer()


def _limiter(request: Request, name: str) -> _BoundedRateLimiter:
    attribute = f"identity_{name}_rate_limiter"
    limiter = getattr(request.app.state, attribute, None)
    if limiter is None:
        limiter = _BoundedRateLimiter()
        setattr(request.app.state, attribute, limiter)
    return limiter


def _client_ip(request: Request) -> str:
    headers = {key.lower(): value for key, value in request.headers.items()}
    observed = request.client.host if request.client is not None else None
    trust_cloudflare = os.getenv("DEFEND_TRUST_CLOUDFLARE", "false").strip().lower()
    return client_ip(
        headers,
        observed,
        trust_cloudflare=trust_cloudflare == "true",
    )


def _admin_audit(
    store: IdentityStore,
    request: Request,
    principal: AdminPrincipal,
    *,
    action: str,
    target_type: str,
    target_id: str | None,
    outcome: Literal["success", "failure"],
    metadata: dict | None = None,
) -> None:
    context = _admin_audit_context(request, metadata=metadata)
    store.record_audit(
        actor_account_id=principal.account_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        outcome=outcome,
        request_id=context["request_id"],
        client_context=context["client_context"],
        metadata=context["metadata"],
    )


def _admin_audit_context(
    request: Request,
    *,
    metadata: dict | None = None,
) -> dict[str, object]:
    return {
        "request_id": (request.headers.get("x-request-id") or "")[:200] or None,
        "client_context": {
            "ip_address": _client_ip(request),
            "user_agent": request.headers.get("user-agent", "")[:512],
        },
        "metadata": metadata or {},
    }


def _rate_key(request: Request, identifier: str) -> str:
    digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()
    return f"{_client_ip(request)}:{digest}"


def _admin_login_rate_keys(request: Request, identifier: str) -> tuple[str, str]:
    normalized = _email_rate_identifier(identifier)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return (f"ip:{_client_ip(request)}", f"identifier:{digest}")


def _email_rate_identifier(value: str) -> str:
    try:
        return normalize_email(value)
    except (TypeError, ValueError):
        return (value or "").strip().casefold()[:320]


def _session_seconds() -> int:
    try:
        hours = float(os.getenv("DEFEND_ACCOUNT_SESSION_HOURS", "12"))
    except ValueError:
        hours = 12.0
    return max(900, min(int(hours * 3600), 7 * 24 * 3600))


def _account_payload(account: AccountRecord) -> dict[str, str | None]:
    return {
        "account_id": account.account_id,
        "email": account.email,
        "display_name": account.display_name,
        "role": account.role,
        "status": account.status,
        "created_at": account.created_at,
        "last_access_at": account.last_access_at,
    }


def _invitation_state(invitation: InvitationRecord) -> str:
    if invitation.consumed_at is not None:
        return "consumed"
    if invitation.revoked_at is not None:
        return "revoked"
    expires_at = datetime.fromisoformat(invitation.expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        return "expired"
    return "pending"


def _invitation_payload(
    invitation: InvitationRecord,
    *,
    token: str | None = None,
    delivery: DeliveryResult | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "invitation_id": invitation.invitation_id,
        "account_id": invitation.account_id,
        "email": invitation.email,
        "intended_role": invitation.intended_role,
        "created_at": invitation.created_at,
        "expires_at": invitation.expires_at,
        "status": _invitation_state(invitation),
        "delivery_status": invitation.delivery_status,
        "delivery_error": invitation.delivery_error,
    }
    if token is not None:
        payload["token"] = token
        payload["activation_url"] = activation_url(token)
    if delivery is not None:
        payload["delivery"] = {
            "delivered": delivery.delivered,
            "provider_message_id": delivery.provider_message_id,
            "error": invitation.delivery_error,
        }
    return payload


def _safe_delivery_error(error: str | None) -> str | None:
    if not error:
        return None
    cleaned = " ".join(error.split())
    for name in ("DEFEND_GMAIL_APP_PASSWORD", "DEFEND_GMAIL_SMTP_USERNAME"):
        secret = os.getenv(name, "")
        if secret:
            cleaned = cleaned.replace(secret, "[redacted]")
    return cleaned[:240]


def _deliver_invitation(
    store: IdentityStore,
    invitation: InvitationRecord,
    token: str,
) -> tuple[InvitationRecord, DeliveryResult]:
    result = _mailer().send_invitation(
        recipient=invitation.email,
        activation_url=activation_url(token),
        expires_at=invitation.expires_at,
    )
    safe_result = DeliveryResult(
        delivered=result.delivered,
        provider_message_id=(result.provider_message_id or "")[:240] or None,
        error=_safe_delivery_error(result.error),
    )
    updated = store.record_invitation_delivery(
        invitation.invitation_id,
        delivered=safe_result.delivered,
        error=safe_result.error,
    )
    return updated, safe_result


@router.post("/api/admin/accounts", status_code=201)
def create_account(
    body: CreateAccountIn,
    request: Request,
    principal: AdminPrincipal = Depends(require_admin),
) -> dict[str, object]:
    store = _identity_store(request)
    try:
        account, invitation, token = store.create_account_with_invitation(
            email=body.email,
            display_name=body.display_name,
            role=body.role,
            created_by=principal.account_id,
            audit_context=_admin_audit_context(request),
        )
    except RoleViolation as exc:
        _admin_audit(
            store,
            request,
            principal,
            action="account.create",
            target_type="account",
            target_id=None,
            outcome="failure",
            metadata={"reason": "forbidden", "intended_role": body.role},
        )
        raise HTTPException(status_code=403, detail="Account role is not permitted") from exc
    except ValueError as exc:
        _admin_audit(
            store,
            request,
            principal,
            action="account.create",
            target_type="account",
            target_id=None,
            outcome="failure",
            metadata={"reason": "duplicate" if str(exc) == "email already exists" else "invalid", "intended_role": body.role},
        )
        status_code = 409 if str(exc) == "email already exists" else 400
        detail = "Email already exists" if status_code == 409 else "Invalid account request"
        raise HTTPException(status_code=status_code, detail=detail) from exc
    invitation, delivery = _deliver_invitation(store, invitation, token)
    return {
        "account": _account_payload(account),
        "invitation": _invitation_payload(
            invitation,
            token=token,
            delivery=delivery,
        ),
    }


@router.post("/api/admin/invitations/{invitation_id}/resend")
def resend_invitation(
    invitation_id: str,
    request: Request,
    principal: AdminPrincipal = Depends(require_admin),
) -> dict[str, object]:
    store = _identity_store(request)
    existing = store.get_invitation(invitation_id)
    if existing is None:
        _admin_audit(
            store,
            request,
            principal,
            action="invitation.resend",
            target_type="invitation",
            target_id=invitation_id,
            outcome="failure",
            metadata={"reason": "not_found"},
        )
        raise HTTPException(status_code=404, detail="Invitation not found")
    try:
        invitation, token = store.create_invitation(
            account_id=existing.account_id,
            created_by=principal.account_id,
            replaces_invitation_id=invitation_id,
            audit_context=_admin_audit_context(request),
        )
    except RoleViolation as exc:
        _admin_audit(
            store,
            request,
            principal,
            action="invitation.resend",
            target_type="invitation",
            target_id=invitation_id,
            outcome="failure",
            metadata={"reason": "forbidden"},
        )
        raise HTTPException(status_code=403, detail="Invitation action is not permitted") from exc
    except InvitationInvalid as exc:
        _admin_audit(
            store,
            request,
            principal,
            action="invitation.resend",
            target_type="invitation",
            target_id=invitation_id,
            outcome="failure",
            metadata={"reason": "invalid_state"},
        )
        raise HTTPException(status_code=409, detail="Invitation cannot be resent") from exc
    invitation, delivery = _deliver_invitation(store, invitation, token)
    return {
        "invitation": _invitation_payload(
            invitation,
            token=token,
            delivery=delivery,
        )
    }


@router.post("/api/admin/invitations/{invitation_id}/revoke")
def revoke_invitation(
    invitation_id: str,
    request: Request,
    principal: AdminPrincipal = Depends(require_admin),
) -> dict[str, object]:
    store = _identity_store(request)
    try:
        invitation = store.revoke_invitation(
            invitation_id,
            revoked_by=principal.account_id,
            audit_context=_admin_audit_context(request),
        )
    except KeyError as exc:
        _admin_audit(
            store,
            request,
            principal,
            action="invitation.revoke",
            target_type="invitation",
            target_id=invitation_id,
            outcome="failure",
            metadata={"reason": "not_found"},
        )
        raise HTTPException(status_code=404, detail="Invitation not found") from exc
    except RoleViolation as exc:
        _admin_audit(
            store,
            request,
            principal,
            action="invitation.revoke",
            target_type="invitation",
            target_id=invitation_id,
            outcome="failure",
            metadata={"reason": "forbidden"},
        )
        raise HTTPException(status_code=403, detail="Invitation action is not permitted") from exc
    except InvitationInvalid as exc:
        _admin_audit(
            store,
            request,
            principal,
            action="invitation.revoke",
            target_type="invitation",
            target_id=invitation_id,
            outcome="failure",
            metadata={"reason": "invalid_state"},
        )
        raise HTTPException(status_code=409, detail="Invitation cannot be revoked") from exc
    return {"invitation": _invitation_payload(invitation)}


@router.post("/api/activate/status")
def activation_status(body: ActivationStatusIn, request: Request) -> dict[str, object]:
    token = body.token
    if len(token) > 512:
        return {"status": "invalid"}
    store = _identity_store(request)
    status, invitation = store.invitation_status(token)
    if invitation is None:
        return {"status": status}
    account = store.get_account(invitation.account_id)
    return {
        "status": status,
        "expires_at": invitation.expires_at,
        "email": invitation.email,
        "display_name": account.display_name if account is not None else None,
    }


@router.post("/api/activate")
def activate_account(body: ActivateIn, request: Request) -> dict[str, object]:
    token = body.token
    limiter = _limiter(request, "activation")
    key = _rate_key(request, token[:512])
    if not limiter.allow(key):
        raise HTTPException(status_code=429, detail="Too many authentication attempts")
    if len(token) > 512 or not 12 <= len(body.password) <= 512:
        raise HTTPException(status_code=410, detail="Invitation is unavailable")
    store = _identity_store(request)
    try:
        account = store.consume_invitation(token, password=body.password)
    except (InvitationExpired, InvitationInvalid, TypeError, ValueError) as exc:
        raise HTTPException(status_code=410, detail="Invitation is unavailable") from exc
    limiter.reset(key)
    return {"account": _account_payload(account)}


@router.post("/api/account/login")
def account_login(
    body: AccountLoginIn,
    request: Request,
    response: Response,
) -> dict[str, object]:
    limiter = _limiter(request, "login")
    key = _rate_key(request, _email_rate_identifier(body.email))
    if not limiter.allow(key):
        raise HTTPException(status_code=429, detail="Too many authentication attempts")
    if len(body.email) > 320 or len(body.password) > 512:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    store = _identity_store(request)
    try:
        account = store.authenticate_account(body.email, body.password)
    except AuthenticationFailed as exc:
        raise HTTPException(status_code=401, detail="Invalid credentials") from exc
    ttl = _session_seconds()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
    token = store.create_session(account.account_id, expires_at=expires_at.isoformat())
    response.set_cookie(
        _ACCOUNT_COOKIE,
        token,
        max_age=ttl,
        expires=ttl,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )
    limiter.reset(key)
    return {"account": _account_payload(account), "expires_in": ttl}


@router.post("/api/account/logout")
def account_logout(
    request: Request,
    response: Response,
    authorization: str | None = Header(default=None),
) -> dict[str, bool]:
    token = request.cookies.get(_ACCOUNT_COOKIE)
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
    store = _identity_store(request)
    if not token or store.resolve_session(token) is None:
        raise HTTPException(status_code=401, detail="Account session is invalid")
    store.revoke_session(token)
    response.delete_cookie(
        _ACCOUNT_COOKIE,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )
    return {"ok": True}
