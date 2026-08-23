"""M4.8.2C frontdoor (same-origin proxy) owner auth test (C-09).

The M4.8.2B transport test hit the raw FastAPI origin. This test proves the
full chain the browser actually uses:

    HTTP client -> Markets Next frontend origin -> same-origin rewrite/BFF
        -> loopback Markets API -> login/protected/logout

It launches the PRODUCTION standalone Next server (`.next/standalone/server.js`)
with its rewrites pointed at a loopback Markets API on a free port, using an
isolated owner identity. If the standalone build is absent the test skips
rather than silently relabelling a raw-API check as proxy certification.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path

import pytest


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _listening(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False


def _wait_http(url: str, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status in (200, 401, 404, 503):
                    return True
        except Exception:
            time.sleep(0.25)
    return False


def _start_api(monkeypatch, tmp_path, port: int) -> None:
    import uvicorn

    monkeypatch.setenv("DEFEND_OWNER_USER", "MASSA")
    monkeypatch.setenv("DEFEND_OWNER_EMAIL", "chairman@defend-network.org")
    monkeypatch.setenv("DEFEND_OWNER_PASS", "isolated-test-password")
    monkeypatch.setenv("DEFEND_DATA_ROOT", str(tmp_path / "data"))

    from defend_markets.app import build_markets_app
    from defend_markets.app import MarketsDependencies
    from defend_markets.config import MarketsSettings
    from defend_markets.db import MarketsDatabase

    db = MarketsDatabase(os.environ.get("MARKETS_DATABASE_URL", "postgresql://x:x@127.0.0.1:5432/x"))
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


def test_frontdoor_proxy_auth_chain(monkeypatch, tmp_path):
    repo = Path(__file__).resolve().parents[1]
    standalone = repo / "defendmarkets-ui" / ".next" / "standalone" / "server.js"
    if not standalone.is_file():
        pytest.skip("standalone Markets UI build absent; run 'npm run build' in defendmarkets-ui")

    # The standalone build bakes the rewrite target at build time (default
    # 8500). To exercise the real frontdoor proxy, run the isolated API on the
    # canonical port 8500 (skip if a real API already occupies it).
    api_port = 8500
    if _listening(api_port):
        pytest.skip("canonical Markets API port 8500 already in use")

    ui_port = _free_port()

    _start_api(monkeypatch, tmp_path, api_port)
    if not _wait_http(f"http://127.0.0.1:{api_port}/health"):
        pytest.fail("isolated Markets API did not become healthy")

    ui_dir = repo / "defendmarkets-ui"
    standalone_dir = ui_dir / ".next" / "standalone"
    for relative in ("public", ".next/static"):
        source = ui_dir / relative
        destination = standalone_dir / relative
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)

    env = dict(os.environ)
    env["HOSTNAME"] = "127.0.0.1"
    env["PORT"] = str(ui_port)
    proc = subprocess.Popen(
        ["node", ".next/standalone/server.js"],
        cwd=str(ui_dir),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        frontdoor = f"http://127.0.0.1:{ui_port}"
        assert _wait_http(f"{frontdoor}/markets-health")

        # 1. wrong password through the FRONTDOOR proxy -> 401 (not transport error)
        status, _ = _http("POST", f"{frontdoor}/api/markets/owner/login", body={"username": "MASSA", "password": "wrong"})
        assert status == 401

        # 2. valid isolated owner through the FRONTDOOR proxy -> 200 + token
        status, body = _http("POST", f"{frontdoor}/api/markets/owner/login", body={"username": "MASSA", "password": "isolated-test-password"})
        assert status == 200
        data = json.loads(body)
        assert data["role"] == "owner"
        token = data["token"]

        # 3. protected owner endpoint through the FRONTDOOR proxy -> 200
        status, _ = _http("GET", f"{frontdoor}/api/markets/owner/overview", token=token)
        assert status == 200

        # 4. logout through the FRONTDOOR proxy -> 200
        status, _ = _http("POST", f"{frontdoor}/api/markets/owner/logout", token=token)
        assert status == 200

        # 5. revoked token through the FRONTDOOR proxy -> 401
        status, _ = _http("GET", f"{frontdoor}/api/markets/owner/overview", token=token)
        assert status == 401
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
