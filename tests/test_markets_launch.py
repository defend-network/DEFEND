"""M4.8.2B launcher identity tests (Phase 4/5, 6.5/6.6)."""

from __future__ import annotations

from pathlib import Path

from tools.defend_markets_launch import (
    REPO_ROOT,
    _is_intended_worktree,
    _is_markets_api_process,
    _is_markets_ui_process,
)


def test_intended_worktree_detection():
    assert _is_intended_worktree(str(REPO_ROOT)) is True
    assert _is_intended_worktree(str(REPO_ROOT / "defend-ui-v2")) is True


def test_foreign_worktree_rejected():
    assert _is_intended_worktree(r"C:\other\worktree") is False
    assert _is_intended_worktree(r"C:\Windows") is False


def test_api_process_identity():
    assert _is_markets_api_process({"command": "python tools/defend_markets_server.py"}) is True
    assert _is_markets_api_process({"command": "python tools/defend_sports_server.py"}) is False


def test_ui_process_identity():
    assert _is_markets_ui_process({"command": "node .../next/dist/bin/next start"}) is True
    assert _is_markets_ui_process({"command": "node .../scs-ui/next start -p 3100"}) is False


def test_launcher_reports_canonical_ports():
    from tools.defend_markets_launch import API_PORT, UI_PORT, WORKSTATION_URL

    assert API_PORT == 8300
    assert UI_PORT == 3000
    assert WORKSTATION_URL == "http://127.0.0.1:3000/markets"
