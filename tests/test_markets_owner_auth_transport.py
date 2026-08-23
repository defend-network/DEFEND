"""M4.8.2B owner auth transport tests (P3/P6.9).

Proves the full owner auth chain through REAL HTTP transport (not just
TestClient) using an ISOLATED test identity store with a known password:
login -> session -> protected endpoint -> logout -> revoked token rejected.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
import urllib.request
import urllib.error

import pytest


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _start_server(monkeypatch, tmp_path) -> int:
    import uvicorn

    # isolated identity store
    monkeypatch.setenv("DEFEND_OWNER_USER", "MASSA")
    monkeypatch.setenv("DEFEND_OWNER_EMAIL", "chairman@defend-network.org")
    monkeypatch.setenv("DEFEND_OWNER_PASS", "isolated-test-password")
    monkeypatch.setenv("DEFEND_DATA_ROOT", str(tmp_path / "data"))

    from defend_markets.app import build_markets_app
    from defend_markets.config import MarketsSettings
    from defend_markets.db import MarketsDatabase
    from defend_markets.app import MarketsDependencies

    db = MarketsDatabase(os.environ.get("MARKETS_DATABASE_URL", "postgresql://x:x@127.0.0.1:5432/x"))
    port = _free_port()
    # Build app with a real DB (read-only health/auth endpoints don't need DB writes).
    deps = MarketsDependencies(
        settings=MarketsSettings(data_root=tmp_path, database_url=db.database_url),
        database=db,
    )
    app = build_markets_app(deps)

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)

    def run():
        server.run()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    for _ in range(50):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
                if r.status == 200:
                    break
        except Exception:
            time.sleep(0.1)
    return port


def _http(method, url, body=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def test_owner_auth_transport_chain(monkeypatch, tmp_path):
    port = _start_server(monkeypatch, tmp_path)
    base = f"http://127.0.0.1:{port}"

    # 1. wrong password -> 401 (NOT transport failure)
    status, body = _http("POST", f"{base}/api/markets/owner/login", body={"username": "MASSA", "password": "wrong"})
    assert status == 401

    # 2. valid isolated owner login -> token
    status, body = _http("POST", f"{base}/api/markets/owner/login", body={"username": "MASSA", "password": "isolated-test-password"})
    assert status == 200
    data = json.loads(body)
    assert data["role"] == "owner"
    token = data["token"]
    assert token

    # 3. protected endpoint with token -> 200
    status, _ = _http("GET", f"{base}/api/markets/owner/overview", token=token)
    assert status == 200

    # 4. missing token -> 401
    status, _ = _http("GET", f"{base}/api/markets/owner/overview")
    assert status == 401

    # 5. invalid token -> 401
    status, _ = _http("GET", f"{base}/api/markets/owner/overview", token="invalid-token")
    assert status == 401

    # 6. logout -> 200
    status, _ = _http("POST", f"{base}/api/markets/owner/logout", token=token)
    assert status == 200

    # 7. post-logout token -> rejected (401)
    status, _ = _http("GET", f"{base}/api/markets/owner/overview", token=token)
    assert status == 401
