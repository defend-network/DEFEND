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
