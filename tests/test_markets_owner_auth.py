"""M4.8.1 owner auth + owner-facing Markets API tests (P15/P16/P34)."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


def _build_owner_app():
    import admin_auth
    from defend_data.data_core import DataCore
    from defend_markets.quant.orchestrator import MarketsIntelligenceOrchestrator
    from defend_markets.quant.owner_routes import build_owner_router
    from defend_markets.quant.store import InMemoryQuantStore

    # fresh identity store for the test (isolated, not the real owner DB)
    import tempfile
    from pathlib import Path

    from defend_data.config import DataPaths
    from defend_data.identity_store import IdentityStore

    tmp = Path(tempfile.mkdtemp(prefix="m481-identity-"))
    paths = DataPaths.from_env(root=tmp).ensure()
    store = IdentityStore(paths)
    admin_auth.configure_identity_store(store)

    # fake orchestrator: owner router only needs health/arbitrage/scheduler/store
    class _FakeOrchestrator:
        def __init__(self):
            self._store = InMemoryQuantStore()

        def markets_health_snapshot(self):
            return {"postgres": {"schema_version": 24}, "m5": {"champion": "M5_REGULARIZED_LOGISTIC"}}

        def arbitrage_status(self):
            return {"current_active_arbs": 0}

        def scheduler_status(self):
            return {"hardrock_capture": {"status": "IDLE"}}

    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(build_owner_router(_FakeOrchestrator()))
    return app


@pytest.fixture(autouse=True)
def _owner_env(monkeypatch):
    monkeypatch.setenv("DEFEND_OWNER_USER", "MASSA")
    monkeypatch.setenv("DEFEND_OWNER_PASS", "test-owner-pass-123")
    monkeypatch.setenv("DEFEND_OWNER_EMAIL", "chairman@defend-network.org")


def test_owner_login_and_protected_route():
    app = _build_owner_app()
    client = TestClient(app)
    # unauthenticated protected request -> 401
    assert client.get("/api/markets/owner/overview").status_code == 401
    # wrong password -> 401
    r = client.post("/api/markets/owner/login", json={"username": "MASSA", "password": "wrong"})
    assert r.status_code == 401
    # correct owner login
    r = client.post("/api/markets/owner/login", json={"username": "MASSA", "password": "test-owner-pass-123"})
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "owner"
    assert body["token"]
    token = body["token"]
    # protected route with token -> 200
    r = client.get("/api/markets/owner/overview", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["postgres"]["schema_version"] == 24


def test_owner_logout_invalidates_session():
    app = _build_owner_app()
    client = TestClient(app)
    r = client.post("/api/markets/owner/login", json={"username": "MASSA", "password": "test-owner-pass-123"})
    token = r.json()["token"]
    # logout
    r = client.post("/api/markets/owner/logout", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    # token now invalid
    r = client.get("/api/markets/owner/overview", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_no_secret_in_overview_payload():
    app = _build_owner_app()
    client = TestClient(app)
    r = client.post("/api/markets/owner/login", json={"username": "MASSA", "password": "test-owner-pass-123"})
    token = r.json()["token"]
    for path in ("/api/markets/owner/overview", "/api/markets/owner/data-health", "/api/markets/owner/model"):
        r = client.get(path, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        text = r.text
        assert "test-owner-pass-123" not in text
        assert "Bearer" not in text
