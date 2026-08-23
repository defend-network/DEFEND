"""DEFENDmarkets canonical owner launch (M4.8.2C).

One reproducible owner launch path. Starts/verifies BOTH required services:

* Markets API  — python tools/defend_markets_server.py  (loopback 127.0.0.1:8500)
* Markets UI   — defendmarkets-ui `npm run start`      (127.0.0.1:3500)

The launcher verifies process IDENTITY (PID, command, CWD, worktree, git HEAD,
port), not just port existence. A process on the right port from the wrong
worktree/HEAD is reported as a foreign conflict, never as healthy. Foreign port
owners are never silently terminated. UNKNOWN process identity is never READY.

When this launcher starts a process it persists PID + launch metadata in a
product-owned runtime state file so later STATUS can prove the process was
launched from the intended worktree/HEAD, rather than inferring it from the
current repository state (which may have advanced).

Usage:
    python tools/defend_markets_launch.py start    # launch + verify
    python tools/defend_markets_launch.py status   # read-only report
    python tools/defend_markets_launch.py stop     # stop only Markets-owned children
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Product-owned launch contract: ports/URLs derive from MarketsSettings via
# defend_markets.launch, not from launcher-local constants (single authority).
from defend_markets.launch import build_manifest

_MANIFEST = build_manifest(REPO_ROOT)
FRONTEND_DIR = _MANIFEST.ui_working_directory
API_PORT = _MANIFEST.api_port
UI_PORT = _MANIFEST.ui_port
API_HEALTH = _MANIFEST.api_health_url
UI_HEALTH = _MANIFEST.ui_health_url
WORKSTATION_URL = _MANIFEST.open_url

_STATE_FILE = REPO_ROOT / "defend_markets" / "runtime" / "launch_state.json"


def _listening(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False


def _port_owner(port: int) -> dict | None:
    """Identify the process owning a listening port.

    Returns None only when the port is NOT listening. When the port is listening
    but the owner cannot be identified, returns a sentinel dict with
    ``identity == "UNKNOWN"`` so callers can fail closed instead of treating an
    unobservable owner as healthy.
    """
    try:
        import psutil

        found_listener = False
        for conn in psutil.net_connections(kind="inet"):
            if conn.status == "LISTEN" and conn.laddr and conn.laddr.port == port:
                found_listener = True
                pid = conn.pid
                if pid is None:
                    return {"identity": "UNKNOWN", "pid": None}
                try:
                    proc = psutil.Process(pid)
                    cmdline = " ".join(proc.cmdline()) if proc.cmdline() else ""
                    cwd = proc.cwd()
                    create = int(proc.create_time() * 1000)
                    return {
                        "identity": "KNOWN",
                        "pid": pid,
                        "command": cmdline,
                        "cwd": str(cwd),
                        "create_time_ms": create,
                    }
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    return {"identity": "UNKNOWN", "pid": pid}
        if found_listener:
            return {"identity": "UNKNOWN", "pid": None}
        return None
    except Exception:
        return {"identity": "UNKNOWN", "pid": None} if _listening(port) else None


def _is_intended_worktree(cwd: str) -> bool:
    """True when the process CWD is inside the intended repo/worktree."""
    try:
        resolved = Path(cwd).resolve()
        repo = REPO_ROOT.resolve()
        return resolved == repo or repo in resolved.parents
    except Exception:
        return False


def _is_markets_api_process(owner: dict) -> bool:
    if not owner.get("command"):
        return False
    return "defend_markets_server" in owner["command"]


def _is_markets_ui_process(owner: dict) -> bool:
    """Strict Markets UI identity: CWD must be the dedicated frontend package
    and the command must be that package's Next.js server (dev/start/standalone)."""
    cmd = owner.get("command", "").lower()
    cwd = owner.get("cwd", "")
    if FRONTEND_DIR.name not in cmd and ".next/standalone/server.js" not in cmd:
        return False
    if "next" not in cmd:
        return False
    try:
        cwd_resolved = Path(cwd).resolve()
        expected = FRONTEND_DIR.resolve()
    except Exception:
        return False
    if cwd_resolved != expected and expected not in cwd_resolved.parents:
        return False
    return True


def _git_head(cwd: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(cwd),
            capture_output=True, text=True, timeout=10,
        )
        return out.stdout.strip()
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


def _owner_auth_state() -> dict | None:
    """Read the sanitized owner_auth block from the API health endpoint.

    Returns None when the API is unreachable or the field is absent.
    """
    try:
        req = urllib.request.Request(
            API_HEALTH, headers={"User-Agent": "DEFENDmarkets-launcher"}
        )
        with urllib.request.urlopen(req, timeout=3.0) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data.get("owner_auth")
    except Exception:
        return None


def _read_launch_state() -> dict:
    try:
        if _STATE_FILE.exists():
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _write_launch_state(state: dict) -> None:
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception:
        pass


def _launch_metadata(port: int, pid: int, role: str, head: str) -> dict:
    return {
        "role": role,
        "pid": pid,
        "port": port,
        "head": head,
        "worktree": str(REPO_ROOT),
        "started_at_ms": int(time.time() * 1000),
    }


def _classify(port: int, role: str, owner: dict | None, listening: bool, head: str) -> dict:
    """Classify a single service identity against the intended product."""
    if not listening:
        return {"state": "DOWN"}
    if owner is None or owner.get("identity") != "KNOWN":
        return {"state": "UNKNOWN", "detail": "port owner not observable"}
    cmd = owner.get("command", "")
    cwd = owner.get("cwd", "")
    matches_product = (
        _is_markets_api_process(owner) if role == "api" else _is_markets_ui_process(owner)
    )
    if not matches_product:
        return {"state": "FOREIGN", "detail": f"command is not Markets {role}"}
    if not _is_intended_worktree(cwd):
        return {"state": "WRONG_WORKTREE", "detail": f"CWD outside intended worktree: {cwd}"}
    return {
        "state": "VERIFIED",
        "pid": owner["pid"],
        "command": cmd,
        "cwd": cwd,
        "worktree_head": head,
    }


def status() -> dict:
    repo_head = _git_head(REPO_ROOT)
    api_listening = _listening(API_PORT)
    ui_listening = _listening(UI_PORT)
    api_owner = _port_owner(API_PORT) if api_listening else None
    ui_owner = _port_owner(UI_PORT) if ui_listening else None
    api = _classify(API_PORT, "api", api_owner, api_listening, repo_head)
    ui = _classify(UI_PORT, "ui", ui_owner, ui_listening, repo_head)

    api_ready = api_listening and api.get("state") == "VERIFIED" and _http_get(API_HEALTH) == 200
    ui_ready = (
        ui_listening
        and ui.get("state") == "VERIFIED"
        and _http_get(UI_HEALTH) == 200
    )

    owner_auth = _owner_auth_state()
    auth_ready = bool(owner_auth and owner_auth.get("state") == "READY")

    return {
        "repo_root": str(REPO_ROOT),
        "repo_head": repo_head,
        "api_port": API_PORT,
        "ui_port": UI_PORT,
        "api_listening": api_listening,
        "ui_listening": ui_listening,
        "api_health": _http_get(API_HEALTH),
        "ui_proxy_health": _http_get(UI_HEALTH),
        "api": api,
        "ui": ui,
        "owner_auth": owner_auth,
        "api_ready": api_ready,
        "ui_ready": ui_ready,
        "auth_ready": auth_ready,
        "ready": api_ready and ui_ready,
        "owner_workstation_ready": api_ready and ui_ready and auth_ready,
        "workstation_url": WORKSTATION_URL,
    }


def _start_api() -> None:
    env = dict(os.environ)
    env.setdefault("PYTHONPATH", str(REPO_ROOT))
    env.setdefault("MARKETS_API_PORT", str(API_PORT))
    head = _git_head(REPO_ROOT)
    log = _STATE_FILE.parent / "api_stderr.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "ab") as err:
        proc = subprocess.Popen(
            [sys.executable, str(REPO_ROOT / "tools" / "defend_markets_server.py")],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=err,
            stderr=err,
        )
    state = _read_launch_state()
    state["api"] = _launch_metadata(API_PORT, proc.pid, "api", head)
    _write_launch_state(state)


def _start_ui() -> None:
    import shutil

    ui = FRONTEND_DIR
    standalone = ui / ".next" / "standalone"
    server = standalone / "server.js"
    if not server.is_file():
        raise RuntimeError(
            "standalone Markets web build missing; run 'npm run build' in defendmarkets-ui"
        )
    for relative in ("public", ".next/static"):
        source = ui / relative
        destination = standalone / relative
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)
    head = _git_head(REPO_ROOT)
    env = dict(os.environ)
    env.setdefault("HOSTNAME", "127.0.0.1")
    env.setdefault("PORT", str(UI_PORT))
    env.setdefault("MARKETS_INTERNAL_API_ORIGIN", f"http://127.0.0.1:{API_PORT}")
    proc = subprocess.Popen(
        ["node", ".next/standalone/server.js"],
        cwd=str(ui),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    state = _read_launch_state()
    state["ui"] = _launch_metadata(UI_PORT, proc.pid, "ui", head)
    _write_launch_state(state)


def _wait_health(url: str, timeout: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _http_get(url) == 200:
            return True
        time.sleep(0.5)
    return False


def _stop_owned(role: str) -> bool:
    """Stop a Markets-owned child by PID recorded in the launch state.

    Never terminates a process not recorded as launched by this launcher. Uses
    terminate() (graceful) first, then confirms exit.
    """
    state = _read_launch_state()
    entry = state.get(role)
    if not entry or not isinstance(entry.get("pid"), int):
        return False
    try:
        import psutil

        proc = psutil.Process(entry["pid"])
        cmd = " ".join(proc.cmdline()) if proc.cmdline() else ""
        matches = (
            "defend_markets_server" in cmd
            if role == "api"
            else "next" in cmd.lower()
        )
        if not matches:
            return False
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except psutil.TimeoutExpired:
            return False
        state.pop(role, None)
        _write_launch_state(state)
        return True
    except psutil.NoSuchProcess:
        state.pop(role, None)
        _write_launch_state(state)
        return True
    except Exception:
        return False


def _launch() -> dict:
    report = {"started_api": False, "started_ui": False, "ready": False}

    api_listening = _listening(API_PORT)
    ui_listening = _listening(UI_PORT)
    api_owner = _port_owner(API_PORT) if api_listening else None
    ui_owner = _port_owner(UI_PORT) if ui_listening else None

    # Fail closed on FOREIGN/UNKNOWN/conflicting occupants (never kill).
    if api_listening and api_owner is not None and api_owner.get("identity") != "KNOWN":
        report["error"] = f"API port {API_PORT} occupied by unidentifiable process; refusing to adopt"
        return {**report, **status()}
    if api_listening and api_owner is not None and not _is_markets_api_process(api_owner):
        report["error"] = f"foreign process owns API port {API_PORT}: {api_owner}"
        return {**report, **status()}
    if api_listening and api_owner is not None and not _is_intended_worktree(api_owner.get("cwd", "")):
        report["error"] = f"API port {API_PORT} owned by wrong-worktree process: {api_owner}"
        return {**report, **status()}

    if ui_listening and ui_owner is not None and ui_owner.get("identity") != "KNOWN":
        report["error"] = f"UI port {UI_PORT} occupied by unidentifiable process; refusing to adopt"
        return {**report, **status()}
    if ui_listening and ui_owner is not None and not _is_markets_ui_process(ui_owner):
        report["error"] = f"foreign process owns UI port {UI_PORT}: {ui_owner}"
        return {**report, **status()}
    if ui_listening and ui_owner is not None and not _is_intended_worktree(ui_owner.get("cwd", "")):
        report["error"] = f"UI port {UI_PORT} owned by wrong-worktree process: {ui_owner}"
        return {**report, **status()}

    if not api_listening:
        _start_api()
        report["started_api"] = True
    if not _wait_health(API_HEALTH):
        report["error"] = "Markets API failed to become healthy"
        return {**report, **status()}

    if not ui_listening:
        _start_ui()
        report["started_ui"] = True
    if not _wait_health(UI_HEALTH):
        report["error"] = "Markets UI failed to become healthy"
        return {**report, **status()}

    final = status()
    report.update(final)
    report["ready"] = final["ready"]
    return report


def _stop() -> dict:
    api_stopped = _stop_owned("api") if _listening(API_PORT) else True
    ui_stopped = _stop_owned("ui") if _listening(UI_PORT) else True
    report = {
        "api_stopped": api_stopped,
        "ui_stopped": ui_stopped,
    }
    report.update(status())
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="DEFENDmarkets canonical owner launch")
    parser.add_argument("command", nargs="?", default="start", choices=["start", "status", "stop"])
    args = parser.parse_args()

    if args.command == "status":
        print(json.dumps(status(), indent=2))
        return
    if args.command == "stop":
        print(json.dumps(_stop(), indent=2))
        return

    result = _launch()
    print(json.dumps(result, indent=2))
    if result.get("ready"):
        print(f"\n[DEFENDmarkets] ready: {WORKSTATION_URL}")


if __name__ == "__main__":
    main()
