from __future__ import annotations

import importlib
import time

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import admin_auth
import api_identity_routes
from admin_auth import AdminPrincipal
from api_admin_tt_routes import router as admin_router
from defend_data.identity_store import IdentityStore, RoleViolation


def _activate_account(identity, owner, *, email: str, role: str):
    account = identity.create_account(
        email=email,
        display_name=email.split("@", 1)[0].title(),
        role=role,
        created_by=owner.account_id,
    )
    _, token = identity.create_invitation(
        account_id=account.account_id,
        created_by=owner.account_id,
    )
    return identity.consume_invitation(token, password=f"valid password for {email}")


def _principal(account, *, claimed_role: str | None = None) -> AdminPrincipal:
    return AdminPrincipal(
        account_id=account.account_id,
        username=account.email,
        role=claimed_role or account.role,
        expires_at=time.time() + 60,
    )


def _admin_login_app(identity, monkeypatch) -> FastAPI:
    monkeypatch.setenv("DEFEND_OWNER_USER", "MASSA")
    monkeypatch.setenv("DEFEND_OWNER_PASS", "valid owner password")
    monkeypatch.setenv("DEFEND_OWNER_EMAIL", "chairman@defend-network.org")
    admin_auth.configure_identity_store(identity)
    app = FastAPI()
    app.include_router(admin_router)
    return app


def test_admin_cannot_manage_admin_even_with_forged_owner_claim(identity, owner):
    actor = _activate_account(
        identity,
        owner,
        email="actor-admin@example.com",
        role="admin",
    )
    target = _activate_account(
        identity,
        owner,
        email="target-admin@example.com",
        role="admin",
    )

    with pytest.raises(RoleViolation, match="owner"):
        identity.disable_account(
            actor=_principal(actor, claimed_role="owner"),
            target_id=target.account_id,
        )

    assert identity.get_account(target.account_id).status == "active"


def test_admin_can_disable_user(identity, owner):
    actor = _activate_account(
        identity,
        owner,
        email="admin@example.com",
        role="admin",
    )
    target = _activate_account(
        identity,
        owner,
        email="user@example.com",
        role="user",
    )

    disabled = identity.disable_account(
        actor=_principal(actor),
        target_id=target.account_id,
    )

    assert disabled.status == "disabled"
    assert identity.get_account(target.account_id).status == "disabled"


def test_owner_can_disable_admin_but_cannot_disable_owner(identity, owner):
    target = _activate_account(
        identity,
        owner,
        email="admin@example.com",
        role="admin",
    )

    disabled = identity.disable_account(
        actor=_principal(owner),
        target_id=target.account_id,
    )

    assert disabled.status == "disabled"
    with pytest.raises(RoleViolation, match="owner account"):
        identity.disable_account(actor=_principal(owner), target_id=owner.account_id)
    assert identity.get_account(owner.account_id).status == "active"


def test_disabled_admin_cannot_disable_user(identity, owner):
    actor = _activate_account(
        identity,
        owner,
        email="admin@example.com",
        role="admin",
    )
    target = _activate_account(
        identity,
        owner,
        email="user@example.com",
        role="user",
    )
    identity.disable_account(actor=_principal(owner), target_id=actor.account_id)

    with pytest.raises(RoleViolation, match="active owner or admin"):
        identity.disable_account(actor=_principal(actor), target_id=target.account_id)

    assert identity.get_account(target.account_id).status == "active"


def test_owner_session_survives_auth_module_restart(data_paths, monkeypatch):
    configured_owner = {"username": "MASSA", "password": "owner password"}
    monkeypatch.setenv("DEFEND_OWNER_USER", configured_owner["username"])
    monkeypatch.setenv("DEFEND_OWNER_PASS", configured_owner["password"])
    monkeypatch.setenv("DEFEND_OWNER_EMAIL", "chairman@defend-network.org")

    first_store = IdentityStore(data_paths)
    admin_auth.configure_identity_store(first_store)
    app = FastAPI()
    app.include_router(admin_router)

    @app.get("/api/admin/system/health")
    def health(_principal: AdminPrincipal = Depends(admin_auth.require_admin)):
        return {"ok": True}

    try:
        with TestClient(app) as client:
            login_response = client.post("/api/admin/login", json=configured_owner)
            assert login_response.status_code == 200
            login = login_response.json()
            assert login["username"] == configured_owner["username"]
            assert login["role"] == "owner"
            assert set(login) == {"username", "role", "token", "expires_in"}
    finally:
        first_store.close()

    importlib.reload(admin_auth)
    restarted_store = IdentityStore(data_paths)
    admin_auth.configure_identity_store(restarted_store)
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/admin/system/health",
                headers={"Authorization": f"Bearer {login['token']}"},
            )
        assert response.status_code == 200
        assert response.json() == {"ok": True}
    finally:
        restarted_store.close()


def test_login_accepts_owner_email_and_logout_revokes_session(
    identity,
    monkeypatch,
):
    monkeypatch.setenv("DEFEND_OWNER_USER", "MASSA")
    monkeypatch.setenv("DEFEND_OWNER_PASS", "owner password")
    monkeypatch.setenv("DEFEND_OWNER_EMAIL", "chairman@defend-network.org")
    admin_auth.configure_identity_store(identity)
    app = FastAPI()
    app.include_router(admin_router)

    with TestClient(app) as client:
        login = client.post(
            "/api/admin/login",
            json={
                "username": "CHAIRMAN@DEFEND-NETWORK.ORG",
                "password": "owner password",
            },
        )
        assert login.status_code == 200
        payload = login.json()
        headers = {"Authorization": f"Bearer {payload['token']}"}
        assert client.post("/api/admin/logout", headers=headers).status_code == 200
        assert client.post("/api/admin/logout", headers=headers).status_code == 401


def test_admin_login_throttles_by_observed_ip_before_more_password_hashes(
    identity,
    monkeypatch,
):
    app = _admin_login_app(identity, monkeypatch)
    with TestClient(app) as client:
        for index in range(5):
            response = client.post(
                "/api/admin/login",
                json={"username": f"unknown-{index}", "password": "wrong password"},
            )
            assert response.status_code == 401

        limited = client.post(
            "/api/admin/login",
            json={"username": "MASSA", "password": "valid owner password"},
        )

    assert limited.status_code == 429
    assert limited.json() == {"detail": "Too many authentication attempts"}
    assert identity.conn.execute("SELECT COUNT(*) FROM login_events").fetchone()[0] == 5


def test_admin_login_throttles_normalized_identifier_across_cloudflare_ips(
    identity,
    monkeypatch,
):
    app = _admin_login_app(identity, monkeypatch)
    monkeypatch.setenv("DEFEND_TRUST_CLOUDFLARE", "true")
    with TestClient(app) as client:
        for index, identifier in enumerate(
            [
                "CHAIRMAN@DEFEND-NETWORK.ORG",
                "chairman@defend-network.org",
                " Chairman@Defend-Network.Org ",
                "CHAIRMAN@defend-network.org",
                "chairman@DEFEND-NETWORK.ORG",
            ]
        ):
            response = client.post(
                "/api/admin/login",
                headers={"CF-Connecting-IP": f"203.0.113.{index + 1}"},
                json={"username": identifier, "password": "wrong password"},
            )
            assert response.status_code == 401

        limited = client.post(
            "/api/admin/login",
            headers={"CF-Connecting-IP": "203.0.113.99"},
            json={
                "username": "chairman@defend-network.org",
                "password": "valid owner password",
            },
        )

    assert limited.status_code == 429
    assert limited.json() == {"detail": "Too many authentication attempts"}


def test_admin_login_throttles_all_known_account_aliases_in_one_identifier_bucket(
    identity,
    owner,
    monkeypatch,
):
    identity.conn.execute(
        "UPDATE accounts SET username=? WHERE account_id=?",
        ("MASSA", owner.account_id),
    )
    identity.conn.commit()
    app = _admin_login_app(identity, monkeypatch)
    monkeypatch.setenv("DEFEND_TRUST_CLOUDFLARE", "true")
    aliases = [
        "MASSA",
        owner.email,
        owner.account_id,
        "massa",
        owner.email.upper(),
    ]
    with TestClient(app) as client:
        for index, identifier in enumerate(aliases):
            response = client.post(
                "/api/admin/login",
                headers={"CF-Connecting-IP": f"198.51.100.{index + 1}"},
                json={"username": identifier, "password": "wrong password"},
            )
            assert response.status_code == 401

        limited = client.post(
            "/api/admin/login",
            headers={"CF-Connecting-IP": "198.51.100.99"},
            json={
                "username": owner.account_id,
                "password": "valid owner password",
            },
        )

    assert limited.status_code == 429
    assert limited.json() == {"detail": "Too many authentication attempts"}
    assert identity.conn.execute("SELECT COUNT(*) FROM login_events").fetchone()[0] == 5


def test_oversized_admin_password_is_generic_not_reflected_and_counts_toward_throttle(
    identity,
    monkeypatch,
):
    app = _admin_login_app(identity, monkeypatch)
    oversized_secret = "oversized-secret-" + ("x" * 600)

    with TestClient(app) as client:
        for _ in range(5):
            response = client.post(
                "/api/admin/login",
                json={"username": "MASSA", "password": oversized_secret},
            )
            assert response.status_code == 401
            assert response.json() == {"detail": "Invalid credentials"}
            assert oversized_secret not in response.text

        limited = client.post(
            "/api/admin/login",
            json={"username": "MASSA", "password": "valid owner password"},
        )

    assert limited.status_code == 429
    assert limited.json() == {"detail": "Too many authentication attempts"}
    assert identity.conn.execute("SELECT COUNT(*) FROM login_events").fetchone()[0] == 0


def test_admin_login_rate_limit_recovers_after_the_window(identity, monkeypatch):
    app = _admin_login_app(identity, monkeypatch)
    now = [1_000.0]
    limiter = api_identity_routes._BoundedRateLimiter()
    limiter._clock = lambda: now[0]
    app.state.identity_admin_login_rate_limiter = limiter

    with TestClient(app) as client:
        for _ in range(5):
            assert client.post(
                "/api/admin/login",
                json={"username": "MASSA", "password": "wrong password"},
            ).status_code == 401
        assert client.post(
            "/api/admin/login",
            json={"username": "MASSA", "password": "valid owner password"},
        ).status_code == 429

        now[0] += 61
        recovered = client.post(
            "/api/admin/login",
            json={"username": "MASSA", "password": "valid owner password"},
        )

    assert recovered.status_code == 200


def test_admin_login_does_not_enumerate_valid_non_admin_accounts(
    identity,
    owner,
    monkeypatch,
):
    user = _activate_account(
        identity,
        owner,
        email="member@example.com",
        role="user",
    )
    app = _admin_login_app(identity, monkeypatch)
    with TestClient(app) as client:
        unknown = client.post(
            "/api/admin/login",
            json={"username": "unknown@example.com", "password": "wrong password"},
        )
        wrong = client.post(
            "/api/admin/login",
            json={"username": "MASSA", "password": "wrong password"},
        )
        non_admin = client.post(
            "/api/admin/login",
            json={
                "username": user.email,
                "password": f"valid password for {user.email}",
            },
        )

    assert unknown.status_code == wrong.status_code == non_admin.status_code == 401
    assert unknown.json() == wrong.json() == non_admin.json() == {
        "detail": "Invalid credentials"
    }
