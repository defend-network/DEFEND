"""Legacy firewall + negative import graph tests (P0.3R).

Enforces canonical boundaries with NO exceptions:
- canonical product packages and shared_platform must NOT import legacy_stack
  (Section 12: zero exceptions, including Markets).
- shared_platform must NOT import any product or Control Center.
- legacy Sports must not masquerade as Markets.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_CANONICAL_PRODUCT_DIRS = (
    "defend_ai",
    "defend_coder",
    "defend_markets",
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
)


def _py_files(*dirs: str):
    for d in dirs:
        base = ROOT / d
        if base.is_dir():
            yield from base.rglob("*.py")


def _import_module_roots(path: Path):
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("from "):
            target = stripped[len("from "):].split(" import ")[0].strip()
            if target.startswith("."):
                continue
            yield target.split(".")[0]
        elif stripped.startswith("import "):
            for part in stripped[len("import "):].split(","):
                name = part.strip().split(" as ")[0].strip()
                yield name.split(".")[0]


def test_canonical_products_do_not_import_legacy_stack():
    offenders = []
    for path in _py_files(*_CANONICAL_PRODUCT_DIRS):
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        for root in _import_module_roots(path):
            if root == "legacy_stack":
                offenders.append(f"{rel}: legacy_stack")
    assert offenders == [], (
        "canonical product imports legacy_stack: " + "; ".join(offenders)
    )


def test_shared_platform_imports_no_product_or_control_center():
    forbidden = {
        "defend_ai", "defend_coder", "defend_markets", "defend_control",
        "defend_data", "legacy_stack",
    }
    offenders = []
    for path in _py_files("shared_platform"):
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        for root in _import_module_roots(path):
            if root in forbidden or root.startswith("scs_"):
                offenders.append(f"{rel}: {root}")
    assert offenders == [], "shared_platform import leak: " + "; ".join(offenders)


def test_legacy_sports_display_name_includes_legacy():
    products = (ROOT / "defend_control" / "products.py").read_text(encoding="utf-8")
    assert "DEFEND Sports (Legacy)" in products
    ui = (ROOT / "defend_control" / "ui.py").read_text(encoding="utf-8")
    assert "DEFEND Sports (Legacy)" in ui


def test_legacy_sports_cannot_register_as_markets():
    sports_service = (ROOT / "defend_control" / "products.py").read_text(encoding="utf-8")
    m = re.search(r"class SportsService.*?application_id = \"(\w+)\"", sports_service, re.DOTALL)
    assert m is not None
    assert m.group(1) == "sports", "legacy Sports must keep application_id 'sports'"


def test_legacy_stack_readme_has_required_notice():
    readme = (ROOT / "legacy_stack" / "README.md").read_text(encoding="utf-8")
    assert "LEGACY STACK — NOT CANONICAL RUNTIME" in readme
    assert "Canonical product code may not import from" in readme
