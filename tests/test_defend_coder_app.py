from __future__ import annotations

from datetime import timedelta
import os

import pytest
from fastapi.testclient import TestClient

from defend_coder.app import build_coder_app
from defend_coder.auth import AuthService
from defend_coder.config import CoderSettings
from defend_coder.db import CoderDatabase
from defend_coder.repositories import CoderRepository


pytestmark = pytest.mark.skipif(
    not os.environ.get("CODER_TEST_DATABASE_URL"),
    reason="CODER_TEST_DATABASE_URL is not configured",
)


@pytest.fixture
def db():
    database = CoderDatabase(os.environ["CODER_TEST_DATABASE_URL"])
    database.migrate()

    with database.connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                TRUNCATE
                    coder_audit_events,
                    coder_sessions,
                    coder_workspaces,
                    coder_accounts
                RESTART IDENTITY CASCADE
                """
            )

    return database


@pytest.fixture
def repo(db):
    return CoderRepository(db)


@pytest.fixture
def auth(repo):
    service = AuthService(repo, session_ttl=timedelta(hours=8))
    service.create_account(
        username="admin",
        email="admin@example.test",
        password="admin-password",
        role="admin",
    )
    service.create_account(
        username="consumer",
        email="consumer@example.test",
        password="consumer-password",
        role="consumer",
    )
    return service


@pytest.fixture
def settings():
    return CoderSettings(
        database_url="postgresql://redacted",
        host="127.0.0.1",
        port=8301,
        public_https=True,
        workspace_root=r"C:\DEFEND_CODER_DATA",
    )


@pytest.fixture
def client(db, auth, settings):
    app = build_coder_app(
        settings=settings,
        db=db,
        auth=auth,
        runtime_status=lambda: {
            "state": "ready",
            "model": "Qwen/Qwen3-Coder-30B-A3B-Instruct",
        },
    )
    return TestClient(
        app,
        base_url="https://testserver",
    )


def _login(client, username, password, role):
    response = client.post(
        "/v1/auth/login",
        json={
            "username": username,
            "password": password,
            "role": role,
        },
    )
    return response


def test_health_is_public_safe(client):
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["application_id"] == "coder"

    blob = str(body).lower()
    for banned in ("password", "secret", "token", "postgresql://"):
        assert banned not in blob


def test_admin_login_sets_secure_http_only_cookie(client):
    response = _login(
        client,
        "admin",
        "admin-password",
        "admin",
    )

    assert response.status_code == 200
    assert response.json()["account"]["role"] == "admin"

    cookie = response.headers["set-cookie"].lower()
    assert "defendcoder_session=" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "secure" in cookie


def test_consumer_login_uses_same_endpoint(client):
    response = _login(
        client,
        "consumer",
        "consumer-password",
        "consumer",
    )

    assert response.status_code == 200
    assert response.json()["account"]["role"] == "consumer"


def test_role_mismatch_is_generic_login_failure(client):
    response = _login(
        client,
        "consumer",
        "consumer-password",
        "admin",
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid credentials"


def test_wrong_username_and_password_are_generic(client):
    missing = _login(client, "missing", "anything", "consumer")
    wrong = _login(client, "consumer", "wrong", "consumer")

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert missing.json()["detail"] == "invalid credentials"
    assert wrong.json()["detail"] == "invalid credentials"


def test_session_endpoint_returns_current_account(client):
    login = _login(
        client,
        "consumer",
        "consumer-password",
        "consumer",
    )
    assert login.status_code == 200

    response = client.get("/v1/auth/session")

    assert response.status_code == 200
    assert response.json()["account"]["username"] == "consumer"
    assert response.json()["account"]["role"] == "consumer"


def test_admin_status_rejects_consumer(client):
    _login(
        client,
        "consumer",
        "consumer-password",
        "consumer",
    )

    response = client.get("/v1/admin/status")

    assert response.status_code == 403


def test_admin_status_returns_safe_runtime_status(client):
    _login(
        client,
        "admin",
        "admin-password",
        "admin",
    )

    response = client.get("/v1/admin/status")

    assert response.status_code == 200
    body = response.json()
    assert body["runtime"]["state"] == "ready"

    blob = str(body).lower()
    for banned in ("password", "secret", "token"):
        assert banned not in blob


def test_workspace_list_is_owner_scoped(client):
    _login(
        client,
        "consumer",
        "consumer-password",
        "consumer",
    )

    response = client.get("/v1/workspaces")

    assert response.status_code == 200
    assert response.json()["workspaces"] == []


def test_workspace_create_requires_csrf(client):
    _login(
        client,
        "consumer",
        "consumer-password",
        "consumer",
    )

    response = client.post(
        "/v1/workspaces",
        json={
            "name": "project",
            "workspace_root": r"C:\DEFEND_CODER_DATA\consumer\project",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "csrf validation failed"


def test_workspace_create_with_csrf(client):
    login = _login(
        client,
        "consumer",
        "consumer-password",
        "consumer",
    )

    csrf = login.json()["csrf_token"]

    response = client.post(
        "/v1/workspaces",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": "project",
            "workspace_root": r"C:\DEFEND_CODER_DATA\consumer\project",
            "repository_url": "https://github.com/example/project.git",
            "default_branch": "main",
        },
    )

    assert response.status_code == 201
    body = response.json()["workspace"]
    assert body["name"] == "project"
    assert body["repository_url"] == "https://github.com/example/project.git"


def test_logout_requires_csrf(client):
    login = _login(
        client,
        "consumer",
        "consumer-password",
        "consumer",
    )

    without = client.post("/v1/auth/logout")
    assert without.status_code == 403

    csrf = login.json()["csrf_token"]
    response = client.post(
        "/v1/auth/logout",
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 204

    after = client.get("/v1/auth/session")
    assert after.status_code == 401
