from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

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
    activation_url = urlsplit(invitation["activation_url"])
    assert activation_url.scheme == "https"
    assert activation_url.netloc == "ai.defend-network.org"
    assert activation_url.path == "/activate"
    assert activation_url.query == ""
    assert parse_qs(activation_url.fragment) == {"token": [token]}
    assert token not in f"{activation_url.path}?{activation_url.query}"
    assert invitation["delivery"] == {
        "delivered": True,
        "provider_message_id": "<message@example.com>",
        "error": None,
    }
    activated = client.post(
        "/api/activate",
        json={"token": token, "password": "a sufficiently long password"},
    )
    assert activated.status_code == 200
    assert activated.json()["account"]["status"] == "active"

    reused = client.post(
        "/api/activate",
        json={"token": token, "password": "another sufficiently long password"},
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


def test_initial_account_and_invitation_roll_back_when_required_audit_fails(
    client,
    admin_headers,
    identity,
):
    identity.conn.executescript(
        """
        CREATE TRIGGER fail_test_account_create_audit
        BEFORE INSERT ON audit_events
        WHEN NEW.action='account.create'
        BEGIN
            SELECT RAISE(ABORT, 'simulated account create audit failure');
        END;
        """
    )

    with pytest.raises(sqlite3.IntegrityError, match="simulated account create audit"):
        client.post(
            "/api/admin/accounts",
            headers=admin_headers,
            json={
                "email": "audit-atomic-create@example.com",
                "display_name": "Audit Atomic Create",
                "role": "user",
            },
        )

    assert identity.get_account("audit-atomic-create@example.com") is None
    assert identity.conn.execute(
        "SELECT COUNT(*) FROM invitations WHERE email=?",
        ("audit-atomic-create@example.com",),
    ).fetchone()[0] == 0


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
    assert client.post(
        "/api/activate/status", json={"token": old_token}
    ).json()["status"] == "revoked"
    assert (
        client.post(
            "/api/activate",
            json={"token": old_token, "password": "a sufficiently long password"},
        ).status_code
        == 410
    )

    revoked = client.post(
        f"/api/admin/invitations/{resent['invitation_id']}/revoke",
        headers=admin_headers,
    )
    assert revoked.status_code == 200
    assert revoked.json()["invitation"]["status"] == "revoked"
    assert client.post(
        "/api/activate/status", json={"token": resent["token"]}
    ).json()["status"] == "revoked"


def test_resend_replacement_rolls_back_when_required_audit_fails(
    client,
    admin_headers,
    identity,
):
    created = _create_invitation(
        client,
        admin_headers,
        email="audit-atomic-resend@example.com",
    )
    original = created["invitation"]
    original_token = original["token"]
    identity.conn.executescript(
        """
        CREATE TRIGGER fail_test_invitation_resend_audit
        BEFORE INSERT ON audit_events
        WHEN NEW.action='invitation.resend'
        BEGIN
            SELECT RAISE(ABORT, 'simulated invitation resend audit failure');
        END;
        """
    )

    with pytest.raises(sqlite3.IntegrityError, match="simulated invitation resend audit"):
        client.post(
            f"/api/admin/invitations/{original['invitation_id']}/resend",
            headers=admin_headers,
        )

    stored = identity.get_invitation(original["invitation_id"])
    assert stored is not None
    assert stored.revoked_at is None
    assert identity.conn.execute(
        "SELECT COUNT(*) FROM invitations WHERE account_id=?",
        (original["account_id"],),
    ).fetchone()[0] == 1
    assert client.post(
        "/api/activate/status", json={"token": original_token}
    ).json()["status"] == "pending"


def test_revoke_rolls_back_when_required_audit_fails(
    client,
    admin_headers,
    identity,
):
    created = _create_invitation(
        client,
        admin_headers,
        email="audit-atomic-revoke@example.com",
    )
    invitation = created["invitation"]
    identity.conn.executescript(
        """
        CREATE TRIGGER fail_test_invitation_revoke_audit
        BEFORE INSERT ON audit_events
        WHEN NEW.action='invitation.revoke'
        BEGIN
            SELECT RAISE(ABORT, 'simulated invitation revoke audit failure');
        END;
        """
    )

    with pytest.raises(sqlite3.IntegrityError, match="simulated invitation revoke audit"):
        client.post(
            f"/api/admin/invitations/{invitation['invitation_id']}/revoke",
            headers=admin_headers,
        )

    stored = identity.get_invitation(invitation["invitation_id"])
    assert stored is not None
    assert stored.revoked_at is None
    assert client.post(
        "/api/activate/status", json={"token": invitation["token"]}
    ).json()["status"] == "pending"


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
    assert client.post(
        "/api/activate", json={"token": token, "password": password}
    ).status_code == 200

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
            "/api/activate",
            json={"token": created["invitation"]["token"], "password": password},
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
            "/api/activate",
            json={"token": "invite_unknown", "password": "a sufficiently long password"},
        )
        assert response.status_code == 410
        assert response.json() == {"detail": "Invitation is unavailable"}

    limited = client.post(
        "/api/activate",
        json={"token": "invite_unknown", "password": "a sufficiently long password"},
    )
    assert limited.status_code == 429
    assert limited.json() == {"detail": "Too many authentication attempts"}


def test_activation_rate_limit_uses_trusted_cloudflare_client_ip(client, monkeypatch):
    monkeypatch.setenv("DEFEND_TRUST_CLOUDFLARE", "true")
    token = "invite_cloudflare_rate_limit"
    for _ in range(5):
        response = client.post(
            "/api/activate",
            headers={"CF-Connecting-IP": "203.0.113.10"},
            json={"token": token, "password": "a sufficiently long password"},
        )
        assert response.status_code == 410

    different_client = client.post(
        "/api/activate",
        headers={"CF-Connecting-IP": "203.0.113.11"},
        json={"token": token, "password": "a sufficiently long password"},
    )
    assert different_client.status_code == 410


def test_activation_api_uses_only_fixed_paths_and_disables_legacy_token_routes(client):
    registered_paths = {route.path for route in router.routes}
    assert "/api/activate/status" in registered_paths
    assert "/api/activate" in registered_paths
    assert not any("{token}" in path for path in registered_paths)

    raw_token = "invite_raw-secret-token"
    legacy_status = client.get(f"/api/activate/{raw_token}/status")
    legacy_activation = client.post(
        f"/api/activate/{raw_token}",
        json={"password": "a sufficiently long password"},
    )
    assert legacy_status.status_code == 404
    assert legacy_activation.status_code == 404


def test_activation_requests_never_put_the_token_in_path_or_query(client):
    raw_token = "invite_body-only-secret"
    status = client.post("/api/activate/status", json={"token": raw_token})
    activation = client.post(
        "/api/activate",
        json={"token": raw_token, "password": "a sufficiently long password"},
    )

    assert status.status_code == 200
    assert status.json() == {"status": "invalid"}
    assert activation.status_code == 410
    for response in (status, activation):
        assert raw_token not in response.request.url.path
        assert raw_token not in response.request.url.query.decode()


def test_only_legacy_activation_paths_are_redacted_at_the_outer_logging_boundary(
    identity,
):
    inner = FastAPI()
    inner.state.defend_data = SimpleNamespace(identity=identity)
    inner.add_middleware(api_identity_routes.SensitivePathRedactionMiddleware)
    inner.include_router(router)

    class CaptureScopeAfterResponse:
        def __init__(self, app):
            self.app = app
            self.paths = []

        async def __call__(self, scope, receive, send):
            async def capture_at_response_start(message):
                if message.get("type") == "http.response.start":
                    self.paths.append(scope.get("path"))
                await send(message)

            await self.app(scope, receive, capture_at_response_start)

    captured = CaptureScopeAfterResponse(inner)
    raw_token = "invite_stale-legacy-secret"
    with TestClient(captured) as redaction_client:
        fixed = redaction_client.post(
            "/api/activate/status", json={"token": "invite_unknown"}
        )
        legacy = redaction_client.get(f"/api/activate/{raw_token}/status")

    assert fixed.status_code == 200
    assert legacy.status_code == 404
    assert captured.paths == [
        "/api/activate/status",
        "/api/activate/[redacted]/status",
    ]
    assert raw_token not in repr(captured.paths)


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


def test_account_and_invitation_admin_mutations_are_audited_without_secrets(
    client, admin_headers, identity
):
    created = _create_invitation(
        client,
        admin_headers,
        email="audited-user@example.com",
        display_name="Audited User",
    )
    original = created["invitation"]
    resent = client.post(
        f"/api/admin/invitations/{original['invitation_id']}/resend",
        headers=admin_headers,
    )
    assert resent.status_code == 200
    replacement = resent.json()["invitation"]
    revoked = client.post(
        f"/api/admin/invitations/{replacement['invitation_id']}/revoke",
        headers=admin_headers,
    )
    assert revoked.status_code == 200

    events = identity.list_audit_events(limit=100)
    by_action = {event["action"]: event for event in events}
    assert by_action["account.create"]["target_id"] == created["account"]["account_id"]
    assert by_action["invitation.resend"]["target_id"] == original["invitation_id"]
    assert by_action["invitation.revoke"]["target_id"] == replacement["invitation_id"]
    assert all(by_action[action]["outcome"] == "success" for action in by_action)
    serialized = repr(events)
    assert original["token"] not in serialized
    assert replacement["token"] not in serialized
    assert "activation_url" not in serialized


def test_known_admin_mutation_failures_are_audited(client, admin_headers, identity):
    _create_invitation(
        client,
        admin_headers,
        email="duplicate-audit@example.com",
        display_name="Duplicate Audit",
    )
    duplicate = client.post(
        "/api/admin/accounts",
        headers=admin_headers,
        json={
            "email": "duplicate-audit@example.com",
            "display_name": "Duplicate Audit Again",
            "role": "user",
        },
    )
    missing = client.post(
        "/api/admin/invitations/inv_missing/resend", headers=admin_headers
    )

    assert duplicate.status_code == 409
    assert missing.status_code == 404
    failures = [
        event
        for event in identity.list_audit_events(limit=100)
        if event["outcome"] == "failure"
    ]
    assert {(event["action"], event["target_id"]) for event in failures} >= {
        ("account.create", None),
        ("invitation.resend", "inv_missing"),
    }
