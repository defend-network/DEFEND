"""M4.8.2C launcher identity tests (START/STATUS/STOP, strict identity)."""

from __future__ import annotations

from pathlib import Path

from tools.defend_markets_launch import (
    API_PORT,
    FRONTEND_DIR,
    REPO_ROOT,
    UI_PORT,
    WORKSTATION_URL,
    _is_intended_worktree,
    _is_markets_api_process,
    _is_markets_ui_process,
)


def test_intended_worktree_detection():
    assert _is_intended_worktree(str(REPO_ROOT)) is True
    assert _is_intended_worktree(str(REPO_ROOT / "defendmarkets-ui")) is True


def test_foreign_worktree_rejected():
    assert _is_intended_worktree(r"C:\other\worktree") is False
    assert _is_intended_worktree(r"C:\Windows") is False


def test_api_process_identity():
    assert _is_markets_api_process({"command": "python tools/defend_markets_server.py"}) is True
    assert _is_markets_api_process({"command": "python tools/defend_sports_server.py"}) is False


def test_ui_process_identity_strict():
    # Correct: dedicated Markets frontend dir, next start
    assert _is_markets_ui_process({
        "command": f"node {FRONTEND_DIR}\\node_modules\\next\\dist\\bin\\next start",
        "cwd": str(FRONTEND_DIR),
    }) is True
    # Correct: standalone production server
    assert _is_markets_ui_process({
        "command": "node .next/standalone/server.js",
        "cwd": str(FRONTEND_DIR),
    }) is True
    # Generic Next server on the port (wrong package) must NOT satisfy identity
    assert _is_markets_ui_process({
        "command": "node /somewhere/else/next start",
        "cwd": "/somewhere/else",
    }) is False
    # SCS UI (different package dir) must NOT satisfy identity
    assert _is_markets_ui_process({
        "command": "node .../scs-ui/next start -p 3100",
        "cwd": "/repo/scs-ui",
    }) is False


def test_launcher_reports_canonical_ports():
    assert API_PORT == 8500
    assert UI_PORT == 3500
    assert WORKSTATION_URL == "http://127.0.0.1:3500/markets"
    assert FRONTEND_DIR.name == "defendmarkets-ui"
