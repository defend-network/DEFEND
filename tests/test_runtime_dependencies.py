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


def test_bootstrap_stops_when_venv_creation_command_fails():
    lines = Path("Bootstrap-DEFEND.ps1").read_text("utf-8").splitlines()
    venv_command = '    py -3.14 -m venv (Join-Path $repo ".venv")'
    command_index = lines.index(venv_command)

    assert lines[command_index + 1] == (
        '    if ($LASTEXITCODE -ne 0) { throw "Python virtual environment creation failed" }'
    )
