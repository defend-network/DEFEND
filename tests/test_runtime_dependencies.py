import json
from pathlib import Path


RUNTIME_IMPORTS = {
    "bs4": "beautifulsoup4",
    "ddgs": "ddgs",
    "fastapi": "fastapi",
    "httpx": "httpx",
    "lancedb": "lancedb",
    "openpyxl": "openpyxl",
    "pdfplumber": "pdfplumber",
    "PIL": "pillow",
    "pymupdf": "pymupdf",
    "uvicorn": "uvicorn",
    "yaml": "pyyaml",
}


def test_runtime_manifest_covers_registered_tool_imports():
    text = Path("requirements-runtime.txt").read_text("utf-8").casefold()
    missing = sorted(package for package in RUNTIME_IMPORTS.values() if package not in text)
    assert missing == []


def test_legacy_start_script_contains_no_literal_key_assignment():
    text = Path("start_api.ps1").read_text("utf-8")
    assert "tvly-" not in text
    assert "DEFEND_OWNER_PASS=" not in text


def test_all_legacy_run_instructions_contain_no_literal_search_key():
    for path in (Path("RUN.txt"), Path("RUN_DEFEND.txt"), Path("start_api.TXT")):
        text = path.read_text("utf-8")
        assert "tvly-" not in text, f"literal search credential found in {path}"


def test_bootstrap_stops_when_venv_creation_command_fails():
    lines = Path("Bootstrap-DEFEND.ps1").read_text("utf-8").splitlines()
    venv_command = '    py -3.14 -m venv (Join-Path $repo ".venv")'
    command_index = lines.index(venv_command)

    assert lines[command_index + 1] == (
        '    if ($LASTEXITCODE -ne 0) { throw "Python virtual environment creation failed" }'
    )


def test_bootstrap_cmd_works_with_machine_script_policy_unchanged():
    text = Path("Bootstrap-DEFEND.cmd").read_text("utf-8")
    assert "powershell.exe" in text
    assert "-NoProfile" in text
    assert "-ExecutionPolicy Bypass" in text
    assert '"%~dp0Bootstrap-DEFEND.ps1"' in text
    assert "Set-ExecutionPolicy" not in text


def test_bootstrap_uses_repository_local_npm_cache():
    text = Path("Bootstrap-DEFEND.ps1").read_text("utf-8")
    assert '"--cache" (Join-Path $repo "defend-ui-v2\\.npm-cache")' in text


def test_bootstrap_has_desktop_fallback_for_restricted_windows_profiles():
    text = Path("Bootstrap-DEFEND.ps1").read_text("utf-8")
    assert "$env:OneDrive" in text
    assert "$env:USERPROFILE" in text
    assert "[System.IO.Directory]::CreateDirectory($desktop)" in text


def test_start_button_opens_gui_and_exposes_non_billable_check():
    text = Path("Start-DEFEND.cmd").read_text("utf-8")
    assert "pythonw.exe\" -m tools.defend_control_center" in text
    assert "python.exe\" -m tools.defend_control_center --check" in text


def test_frontend_uses_maintained_patched_next_release():
    package = json.loads(Path("defend-ui-v2/package.json").read_text("utf-8"))
    assert package["dependencies"]["next"] == "16.3.0"
