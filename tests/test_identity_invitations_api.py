from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import admin_auth
import api_identity_routes
import defend_data.identity_store as identity_store_module
from admin_auth import AdminPrincipal
from api_identity_routes import router
from defend_data.identity_mailer import DeliveryResult, GmailInvitationMailer


FROZEN_NOW = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return FROZEN_NOW.replace(tzinfo=None)
        return FROZEN_NOW.astimezone(tz)


@pytest.fixture
def client(identity, owner, monkeypatch):
    monkeypatch.setenv("DEFEND_OWNER_USER", "MASSA")
    monkeypatch.setenv("DEFEND_OWNER_PASS", "valid owner password")
    monkeypatch.setenv("DEFEND_OWNER_EMAIL", owner.email)
    monkeypatch.setenv("DEFEND_PUBLIC_WEB_ORIGIN", "https://ai.defend-network.org")
    admin_auth.configure_identity_store(identity)
    monkeypatch.setattr(identity_store_module, "datetime", FrozenDateTime)
    monkeypatch.setattr(
        GmailInvitationMailer,
        "send_invitation",
        lambda self, **kwargs: DeliveryResult(
            delivered=True, provider_message_id="<message@example.com>"
        ),
    )
    app = FastAPI()
    app.state.defend_data = SimpleNamespace(identity=identity)
    app.include_router(router)
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client


@pytest.fixture
def admin_headers(identity, owner):
    token = identity.create_session(owner.account_id)
    return {"Authorization": f"Bearer {token}"}


def _create_invitation(client, admin_headers, **overrides):
    body = {
        "email": "user@example.com",
        "display_name": "User",
        "role": "user",
        **overrides,
    }
    response = client.post("/api/admin/accounts", headers=admin_headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_invitation_is_single_use_and_expires_in_exactly_48_hours(
    client, admin_headers
):
    created = _create_invitation(client, admin_headers)
    invitation = created["invitation"]
    token = invitation["token"]

    assert invitation["expires_at"] == (FROZEN_NOW + timedelta(hours=48)).isoformat()
    assert invitation["activation_url"] == (
        f"https://ai.defend-network.org/activate/{token}"
    )
    assert invitation["delivery"] == {
        "delivered": True,
        "provider_message_id": "<message@example.com>",
        "error": None,
    }
    activated = client.post(
        f"/api/activate/{token}",
        json={"password": "a sufficiently long password"},
    )
    assert activated.status_code == 200
    assert activated.json()["account"]["status"] == "active"

    reused = client.post(
        f"/api/activate/{token}",
        json={"password": "another sufficiently long password"},
    )
    assert reused.status_code == 410
    assert reused.json() == {"detail": "Invitation is unavailable"}


def test_initial_account_and_invitation_are_created_atomically(
    client, admin_headers, identity
):
    identity.conn.executescript(
        """
        CREATE TRIGGER fail_test_initial_invitation
        BEFORE INSERT ON invitations
        WHEN NEW.email='atomic-failure@example.com'
        BEGIN
            SELECT RAISE(ABORT, 'simulated invitation insert failure');
        END;
        """
    )

    with pytest.raises(sqlite3.IntegrityError, match="simulated invitation"):
        client.post(
            "/api/admin/accounts",
            headers=admin_headers,
            json={
                "email": "atomic-failure@example.com",
                "display_name": "Atomic Failure",
                "role": "user",
            },
        )

    assert identity.get_account("atomic-failure@example.com") is None


def test_resend_revokes_the_old_token_and_revoke_blocks_the_new_token(
    client, admin_headers
):
    created = _create_invitation(client, admin_headers)
    old_token = created["invitation"]["token"]
    invitation_id = created["invitation"]["invitation_id"]

    resent_response = client.post(
        f"/api/admin/invitations/{invitation_id}/resend",
        headers=admin_headers,
    )
    assert resent_response.status_code == 200, resent_response.text
    resent = resent_response.json()["invitation"]
    assert resent["token"] != old_token
    assert client.get(f"/api/activate/{old_token}/status").json()["status"] == "revoked"
    assert (
        client.post(
            f"/api/activate/{old_token}",
            json={"password": "a sufficiently long password"},
        ).status_code
        == 410
    )

    revoked = client.post(
        f"/api/admin/invitations/{resent['invitation_id']}/revoke",
        headers=admin_headers,
    )
    assert revoked.status_code == 200
    assert revoked.json()["invitation"]["status"] == "revoked"
    assert client.get(f"/api/activate/{resent['token']}/status").json()["status"] == "revoked"


def test_creation_requires_admin_auth_and_persists_bounded_delivery_failure(
    client, admin_headers, identity, monkeypatch
):
    unauthorized = client.post(
        "/api/admin/accounts",
        json={"email": "blocked@example.com", "display_name": "Blocked", "role": "user"},
    )
    assert unauthorized.status_code == 401

    monkeypatch.setattr(
        GmailInvitationMailer,
        "send_invitation",
        lambda self, **kwargs: DeliveryResult(delivered=False, error="e" * 1000),
    )
    created = _create_invitation(
        client,
        admin_headers,
        email="delivery-failure@example.com",
        display_name="Delivery Failure",
    )

    stored = identity.conn.execute(
        "SELECT delivery_status,delivery_error FROM invitations WHERE invitation_id=?",
        (created["invitation"]["invitation_id"],),
    ).fetchone()
    assert stored["delivery_status"] == "failed"
    assert 0 < len(stored["delivery_error"]) <= 240
    assert created["account"]["status"] == "pending_activation"
    assert created["invitation"]["token"]


def test_account_login_errors_are_generic_and_rate_limited_by_ip_and_email(
    client, admin_headers
):
    created = _create_invitation(client, admin_headers)
    token = created["invitation"]["token"]
    password = "a sufficiently long password"
    assert client.post(f"/api/activate/{token}", json={"password": password}).status_code == 200

    unknown = client.post(
        "/api/account/login",
        json={"email": "unknown@example.com", "password": "wrong password"},
    )
    wrong = client.post(
        "/api/account/login",
        json={"email": "user@example.com", "password": "wrong password"},
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json() == {"detail": "Invalid credentials"}

    for _ in range(4):
        response = client.post(
            "/api/account/login",
            json={"email": "user@example.com", "password": "wrong password"},
        )
        assert response.status_code == 401
    limited = client.post(
        "/api/account/login",
        json={"email": "user@example.com", "password": password},
    )
    assert limited.status_code == 429
    assert limited.json() == {"detail": "Too many authentication attempts"}


def test_account_login_sets_http_only_cookie_and_logout_revokes_it(
    client, admin_headers
):
    created = _create_invitation(
        client,
        admin_headers,
        email="session@example.com",
        display_name="Session User",
    )
    password = "a sufficiently long password"
    assert (
        client.post(
            f"/api/activate/{created['invitation']['token']}",
            json={"password": password},
        ).status_code
        == 200
    )

    login = client.post(
        "/api/account/login",
        json={"email": "SESSION@EXAMPLE.COM", "password": password},
    )
    assert login.status_code == 200
    assert login.json()["account"]["email"] == "session@example.com"
    assert "token" not in login.json()
    cookie = login.headers["set-cookie"]
    assert "defend_account_session=" in cookie
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=lax" in cookie

    logout = client.post("/api/account/logout")
    assert logout.status_code == 200
    assert logout.json() == {"ok": True}
    assert "Max-Age=0" in logout.headers["set-cookie"]
    assert client.post("/api/account/logout").status_code == 401


def test_activation_failures_are_generic_and_rate_limited(client):
    for _ in range(5):
        response = client.post(
            "/api/activate/invite_unknown",
            json={"password": "a sufficiently long password"},
        )
        assert response.status_code == 410
        assert response.json() == {"detail": "Invitation is unavailable"}

    limited = client.post(
        "/api/activate/invite_unknown",
        json={"password": "a sufficiently long password"},
    )
    assert limited.status_code == 429
    assert limited.json() == {"detail": "Too many authentication attempts"}


def test_activation_rate_limit_uses_trusted_cloudflare_client_ip(client, monkeypatch):
    monkeypatch.setenv("DEFEND_TRUST_CLOUDFLARE", "true")
    token = "invite_cloudflare_rate_limit"
    for _ in range(5):
        response = client.post(
            f"/api/activate/{token}",
            headers={"CF-Connecting-IP": "203.0.113.10"},
            json={"password": "a sufficiently long password"},
        )
        assert response.status_code == 410

    different_client = client.post(
        f"/api/activate/{token}",
        headers={"CF-Connecting-IP": "203.0.113.11"},
        json={"password": "a sufficiently long password"},
    )
    assert different_client.status_code == 410


def test_sensitive_activation_path_is_redacted_before_outer_access_logging():
    middleware = getattr(
        api_identity_routes,
        "SensitivePathRedactionMiddleware",
        None,
    )
    assert middleware is not None

    inner = FastAPI()
    inner.add_middleware(middleware)

    @inner.get("/api/activate/{token}/status")
    def status(token: str):
        return {"received": bool(token)}

    class CaptureScopeAfterResponse:
        def __init__(self, app):
            self.app = app
            self.path = None
            self.raw_path = None

        async def __call__(self, scope, receive, send):
            async def capture_at_response_start(message):
                if message.get("type") == "http.response.start":
                    self.path = scope.get("path")
                    self.raw_path = scope.get("raw_path")
                await send(message)

            await self.app(scope, receive, capture_at_response_start)

    captured = CaptureScopeAfterResponse(inner)
    raw_token = "invite_raw-secret-token"
    with TestClient(captured) as redaction_client:
        response = redaction_client.get(f"/api/activate/{raw_token}/status")

    assert response.status_code == 200
    assert captured.path == "/api/activate/[redacted]/status"
    assert captured.raw_path == b"/api/activate/[redacted]/status"
    assert raw_token not in captured.path


def test_admin_cannot_invite_an_admin_account(client, identity, owner):
    admin = identity.create_account(
        email="admin@example.com",
        display_name="Admin",
        role="admin",
        created_by=owner.account_id,
    )
    _, invitation_token = identity.create_invitation(
        account_id=admin.account_id,
        created_by=owner.account_id,
    )
    admin = identity.consume_invitation(
        invitation_token,
        password="a sufficiently long admin password",
    )
    principal = AdminPrincipal(
        account_id=admin.account_id,
        username=admin.email,
        role="admin",
        expires_at=FROZEN_NOW.timestamp() + 3600,
    )
    token = identity.create_session(principal.account_id)

    response = client.post(
        "/api/admin/accounts",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": "new-admin@example.com", "display_name": "New Admin", "role": "admin"},
    )

    assert response.status_code == 403
