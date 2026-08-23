"""M4.8.2C-R owner auth bootstrap state + AUTH_BACKEND_UNAVAILABLE tests."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _reset_admin_auth():
    import defend_ai.admin_auth

    admin_auth._IDENTITY_STORE = None
    yield
    admin_auth._IDENTITY_STORE = None


def _build_app(monkeypatch, tmp_path, with_owner: bool):
    import defend_ai.admin_auth
    from defend_data.data_core import DataCore
    from defend_markets.app import build_markets_app, MarketsDependencies
    from defend_markets.config import MarketsSettings
    from defend_markets.db import MarketsDatabase
    from defend_markets.quant.orchestrator import MarketsIntelligenceOrchestrator
    from defend_markets.quant.owner_routes import build_owner_router

    if with_owner:
        monkeypatch.setenv("DEFEND_OWNER_USER", "MASSA")
        monkeypatch.setenv("DEFEND_OWNER_PASS", "isolated-test-password")
        monkeypatch.setenv("DEFEND_OWNER_EMAIL", "chairman@defend-network.org")
        monkeypatch.setenv("DEFEND_DATA_ROOT", str(tmp_path / "data"))
    else:
        for key in ("DEFEND_OWNER_USER", "DEFEND_OWNER_PASS", "DEFEND_OWNER_EMAIL"):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("DEFEND_DATA_ROOT", str(tmp_path / "data"))
        # no DPAPI store present
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "nolocal"))

    db = MarketsDatabase("postgresql://x:x@127.0.0.1:5432/x")
    deps = MarketsDependencies(
        settings=MarketsSettings(data_root=tmp_path, database_url=db.database_url),
        database=db,
    )
    app = build_markets_app(deps)
    return app


def test_health_exposes_owner_auth_state_ready(monkeypatch, tmp_path):
    app = _build_app(monkeypatch, tmp_path, with_owner=True)
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    owner_auth = r.json().get("owner_auth")
    assert owner_auth is not None
    assert owner_auth["state"] == "READY"
    assert owner_auth["identity_store"] == "legacy_shared_owner_identity"
    assert owner_auth["credentials_configured"] is True
    # no secret leakage
    assert "isolated-test-password" not in r.text


def test_health_exposes_owner_auth_state_not_configured(monkeypatch, tmp_path):
    app = _build_app(monkeypatch, tmp_path, with_owner=False)
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    owner_auth = r.json().get("owner_auth")
    assert owner_auth is not None
    assert owner_auth["state"] == "NOT_CONFIGURED"
    assert owner_auth["credentials_configured"] is False


def test_login_returns_structured_auth_backend_unavailable(monkeypatch, tmp_path):
    app = _build_app(monkeypatch, tmp_path, with_owner=False)
    client = TestClient(app)
    r = client.post("/api/markets/owner/login", json={"username": "MASSA", "password": "x"})
    assert r.status_code == 503
    body = r.json()
    assert body.get("detail", {}).get("error") == "AUTH_BACKEND_UNAVAILABLE"


def test_login_wrong_password_is_401_not_503(monkeypatch, tmp_path):
    app = _build_app(monkeypatch, tmp_path, with_owner=True)
    client = TestClient(app)
    r = client.post("/api/markets/owner/login", json={"username": "MASSA", "password": "wrong"})
    assert r.status_code == 401
