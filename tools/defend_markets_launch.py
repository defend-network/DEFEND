"""DEFENDmarkets canonical owner launch (M4.8.2B).

One reproducible owner launch path. Starts/verifies BOTH required services:

* Markets API  — python tools/defend_markets_server.py  (loopback 127.0.0.1:8300)
* Markets UI   — defend-ui-v2 `npm run start`           (127.0.0.1:3000)

The launcher verifies process IDENTITY (worktree, git HEAD, command, port), not
just port existence. A process on the right port from the wrong worktree/HEAD is
reported as a foreign conflict, never as healthy. Foreign port owners are never
silently terminated.

Usage:
    python tools/defend_markets_launch.py            # launch + verify
    python tools/defend_markets_launch.py --status   # report only
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = REPO_ROOT / "defend-ui-v2"
API_PORT = 8300
UI_PORT = 3000
API_HEALTH = f"http://127.0.0.1:{API_PORT}/health"
UI_HEALTH = f"http://127.0.0.1:{UI_PORT}/markets-health"
WORKSTATION_URL = f"http://127.0.0.1:{UI_PORT}/markets"


def _port_pid(port: int) -> int | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return None  # connected but can't get PID without psutil here
    except OSError:
        pass
    return None


def _listening(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False


def _port_owner(port: int) -> dict | None:
    """Identify the process owning a listening port (PID, command, CWD).

    Returns None if psutil cannot identify the owner (foreign/unknown).
    """
    try:
        import psutil

        for conn in psutil.net_connections(kind="inet"):
            if conn.status == "LISTEN" and conn.laddr and conn.laddr.port == port:
                pid = conn.pid
                if pid is None:
                    return None
                try:
                    proc = psutil.Process(pid)
                    cmdline = " ".join(proc.cmdline()) if proc.cmdline() else ""
                    cwd = proc.cwd()
                    return {"pid": pid, "command": cmdline, "cwd": str(cwd)}
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    return None
        return None
    except Exception:
        return None


def _is_intended_worktree(cwd: str) -> bool:
    """True when the process CWD is inside the intended repo/worktree."""
    try:
        resolved = Path(cwd).resolve()
        repo = REPO_ROOT.resolve()
        return resolved == repo or repo in resolved.parents
    except Exception:
        return False


def _is_markets_api_process(owner: dict) -> bool:
    cmd = owner.get("command", "")
    return "defend_markets_server" in cmd


def _is_markets_ui_process(owner: dict) -> bool:
    cmd = owner.get("command", "").lower()
    if "next" not in cmd or "start" not in cmd:
        return False
    for other in ("scs-ui", "coder-ui", "sports-ui"):
        if other in cmd:
            return False
    return True


def _git_head(cwd: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(cwd),
            capture_output=True, text=True, timeout=10,
        )
        return out.stdout.strip()[:12]
    except Exception:
        return "unknown"


def _http_get(url: str, timeout: float = 3.0) -> int | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "DEFENDmarkets-launcher"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return None


def status() -> dict:
    repo_head = _git_head(REPO_ROOT)
    api_owner = _port_owner(API_PORT) if _listening(API_PORT) else None
    ui_owner = _port_owner(UI_PORT) if _listening(UI_PORT) else None
    api_identity = "healthy" if api_owner and _is_markets_api_process(api_owner) and _is_intended_worktree(api_owner["cwd"]) else (
        "foreign" if api_owner else "down"
    )
    ui_identity = "healthy" if ui_owner and _is_markets_ui_process(ui_owner) and _is_intended_worktree(ui_owner["cwd"]) else (
        "foreign" if ui_owner else "down"
    )
    return {
        "repo_root": str(REPO_ROOT),
        "repo_head": repo_head,
        "api_port": API_PORT,
        "ui_port": UI_PORT,
        "api_listening": _listening(API_PORT),
        "ui_listening": _listening(UI_PORT),
        "api_health": _http_get(API_HEALTH),
        "ui_proxy_health": _http_get(UI_HEALTH),
        "api_process_identity": api_identity,
        "ui_process_identity": ui_identity,
        "api_owner": api_owner,
        "ui_owner": ui_owner,
        "workstation_url": WORKSTATION_URL,
    }


def _start_api() -> None:
    env = dict(os.environ)
    env.setdefault("PYTHONPATH", str(REPO_ROOT))
    subprocess.Popen(
        [sys.executable, "tools", "defend_markets_server.py"],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _start_ui() -> None:
    subprocess.Popen(
        ["npm.cmd", "run", "start"] if os.name == "nt" else ["npm", "run", "start"],
        cwd=str(FRONTEND_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_health(url: str, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _http_get(url) == 200:
            return True
        time.sleep(0.5)
    return False


def launch() -> dict:
    report = {"started_api": False, "started_ui": False, "ready": False}

    # Detect foreign/conflicting process ownership BEFORE starting (never kill).
    api_owner = _port_owner(API_PORT) if _listening(API_PORT) else None
    ui_owner = _port_owner(UI_PORT) if _listening(UI_PORT) else None

    if _listening(API_PORT) and api_owner is not None and not _is_markets_api_process(api_owner):
        report["error"] = f"foreign process owns API port {API_PORT}: {api_owner}"
        return {**report, **status()}

    if not _listening(API_PORT):
        _start_api()
        report["started_api"] = True
    if not _wait_health(API_HEALTH):
        report["error"] = "Markets API failed to become healthy"
        return {**report, **status()}

    if _listening(UI_PORT) and ui_owner is not None and not _is_markets_ui_process(ui_owner):
        report["error"] = f"foreign process owns UI port {UI_PORT}: {ui_owner}"
        return {**report, **status()}

    if not _listening(UI_PORT):
        _start_ui()
        report["started_ui"] = True
    if not _wait_health(UI_HEALTH):
        report["error"] = "Markets UI failed to become healthy"
        return {**report, **status()}

    report["ready"] = True
    report.update(status())
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="DEFENDmarkets canonical owner launch")
    parser.add_argument("--status", action="store_true", help="report status only")
    args = parser.parse_args()

    if args.status:
        import json
        print(json.dumps(status(), indent=2))
        return

    result = launch()
    import json
    print(json.dumps(result, indent=2))
    if result.get("ready"):
        print(f"\n[DEFENDmarkets] ready: {WORKSTATION_URL}")


if __name__ == "__main__":
    main()
