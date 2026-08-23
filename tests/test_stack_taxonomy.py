"""Stack taxonomy tests (P0.3R).

Machine-enforced classification: every runtime-relevant top-level package is
registered, no status is UNKNOWN, the registry does not drift from the
filesystem, and there are NO legacy compatibility shims left inside
defend_control.
"""

from __future__ import annotations

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
    assert _registry(), "stack registry must not be empty"


def test_no_unknown_statuses():
    for entry in _registry():
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
    for entry in _registry():
        path = ROOT / entry["path"]
        assert path.exists(), f"registry drift: {entry['path']} missing on disk"


def test_no_duplicate_implementation_authority():
    paths = [entry["path"] for entry in _registry()]
    assert len(paths) == len(set(paths)), "duplicate registry entries"


def test_no_legacy_compatibility_shims_in_defend_control():
    """P0.3R: canonical defend_control must contain ZERO legacy shims."""
    shims = [
        e for e in _registry()
        if e["status"] == "LEGACY_COMPATIBILITY_SHIM"
        and e["path"].startswith("defend_control/")
    ]
    assert shims == [], f"defend_control still has legacy shims: {shims}"


def test_every_transitional_entry_has_removal_condition():
    transitional = [
        e for e in _registry() if e["status"] == "LEGACY_ACTIVE_TRANSITIONAL"
    ]
    assert transitional
    for entry in transitional:
        assert entry["removal_condition"], entry["path"]


def test_legacy_modules_carry_header():
    for entry in _registry():
        if entry["status"] != "LEGACY_ACTIVE_TRANSITIONAL":
            continue
        path = ROOT / entry["path"]
        if path.is_dir():
            for py in sorted(path.rglob("*.py")):
                if py.name == "__init__.py":
                    continue
                assert "LEGACY / NON-CANONICAL" in py.read_text(encoding="utf-8"), py
        else:
            assert "LEGACY / NON-CANONICAL" in path.read_text(encoding="utf-8"), path


def test_tabletennis_not_at_repo_root():
    assert not (ROOT / "TableTennis").exists()
    assert (ROOT / "legacy_stack" / "table_tennis").exists()


def test_legacy_tools_not_in_tools_root():
    assert not (ROOT / "tools" / "defend_tt_backfill.py").exists()
    assert not (ROOT / "tools" / "defend_sports_ingest.py").exists()
    assert (ROOT / "legacy_stack" / "tools" / "defend_tt_backfill.py").exists()
