from __future__ import annotations

import importlib
import time

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import admin_auth
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
