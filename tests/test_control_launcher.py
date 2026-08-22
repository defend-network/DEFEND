from __future__ import annotations

from pathlib import Path


def test_worktree_launcher_falls_back_to_canonical_virtualenv():
    launcher = (Path(__file__).resolve().parents[1] / "Start-DEFEND.cmd").read_text(
        encoding="utf-8"
    )

    assert 'set "DEFEND_VENV=%DEFEND_REPO%.venv"' in launcher
    assert 'set "DEFEND_VENV=%DEFEND_REPO%..\\..\\.venv"' in launcher
    assert 'if not exist "%DEFEND_VENV%\\Scripts\\python.exe"' in launcher
    assert 'exit /b 9009' in launcher
