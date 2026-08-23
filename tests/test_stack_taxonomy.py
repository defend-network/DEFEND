"""Stack taxonomy tests (P0.3).

Machine-enforced classification: every runtime-relevant top-level package is
registered in ``docs/platform/stack-registry.json``, no status is UNKNOWN, the
registry does not drift from the filesystem, and every compatibility shim is
logic-free (AST) with the required metadata.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "docs" / "platform" / "stack-registry.json"

_RUNTIME_TOP_LEVEL_PACKAGES = {
    "defend_ai",
    "defend_coder",
    "defend_markets",
    "defendmarkets-ui",
    "defendcoder-ui",
    "defend-ui-v2",
    "defend_data",
    "scs_api",
    "scs_data",
    "scs_copilot",
    "scs_knowledge",
    "scs_reports",
    "scs_ai",
    "scs_diagnostics",
    "scs_engineering",
    "scs_equipment",
    "scs_procedures",
    "scs-ui",
    "shared_platform",
    "defend_integrations",
    "defend_control",
    "legacy_stack",
    "TableTennis",
    "tools",
    "evals",
    "bench",
}

_ALLOWED_STATUSES = {
    "CANONICAL_PRODUCT",
    "CANONICAL_CONTROL_CENTER",
    "NEUTRAL_SHARED",
    "LEGACY_ACTIVE_TRANSITIONAL",
    "LEGACY_COMPATIBILITY_SHIM",
    "ARCHIVED_NONEXECUTABLE",
    "HISTORICAL_REQUIRED",
}


def _registry() -> list[dict]:
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    return data["entries"]


def test_registry_exists_and_has_entries():
    entries = _registry()
    assert entries, "stack registry must not be empty"


def test_no_unknown_statuses():
    entries = _registry()
    for entry in entries:
        assert entry["status"] in _ALLOWED_STATUSES, entry["path"]
        assert entry["status"] != "UNKNOWN"


def test_every_runtime_top_level_package_is_registered():
    registered = {entry["path"] for entry in _registry()}
    for package in _RUNTIME_TOP_LEVEL_PACKAGES:
        covered = any(
            path == package or path.startswith(package + "/")
            for path in registered
        )
        assert covered, f"unregistered runtime package: {package}"


def test_registry_paths_do_not_drift_from_filesystem():
    # Every registered package/file path must exist (or be a documented
    # container). File entries must exist; directory entries must exist too.
    for entry in _registry():
        path = ROOT / entry["path"]
        assert path.exists(), f"registry drift: {entry['path']} missing on disk"


def test_no_duplicate_implementation_authority():
    # Each status has exactly one entry per canonical package; no path is
    # registered twice.
    paths = [entry["path"] for entry in _registry()]
    assert len(paths) == len(set(paths)), "duplicate registry entries"


def test_every_shim_is_registered_and_has_canonical_target():
    shims = [e for e in _registry() if e["status"] == "LEGACY_COMPATIBILITY_SHIM"]
    assert shims
    for shim in shims:
        assert shim["canonical_target"], shim["path"]


def test_every_transitional_entry_has_removal_condition():
    transitional = [
        e for e in _registry() if e["status"] == "LEGACY_ACTIVE_TRANSITIONAL"
    ]
    assert transitional
    for entry in transitional:
        assert entry["removal_condition"], entry["path"]


def test_shim_files_are_logic_free():
    """AST: a LEGACY_COMPATIBILITY_SHIM must not define functions/classes."""
    shims = [e for e in _registry() if e["status"] == "LEGACY_COMPATIBILITY_SHIM"]
    for shim in shims:
        path = ROOT / shim["path"]
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            assert not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)), (
                f"{shim['path']} contains {type(node).__name__} - shims must be logic-free"
            )


def test_shim_files_carry_machine_readable_metadata():
    shims = [e for e in _registry() if e["status"] == "LEGACY_COMPATIBILITY_SHIM"]
    for shim in shims:
        text = (ROOT / shim["path"]).read_text(encoding="utf-8")
        assert "LEGACY_COMPATIBILITY_SHIM_ONLY" in text, shim["path"]
        assert "CANONICAL_TARGET" in text, shim["path"]
        assert "LEGACY / NON-CANONICAL" in text, shim["path"]


def test_legacy_modules_carry_header():
    for entry in _registry():
        if entry["status"] != "LEGACY_ACTIVE_TRANSITIONAL":
            continue
        path = ROOT / entry["path"]
        if path.is_dir():
            for py in sorted(path.rglob("*.py")):
                assert "LEGACY / NON-CANONICAL" in py.read_text(encoding="utf-8"), py
        else:
            assert "LEGACY / NON-CANONICAL" in path.read_text(encoding="utf-8"), path
