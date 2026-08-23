"""Legacy firewall + negative import graph tests (P0.3).

Enforces the canonical boundaries:

- canonical product packages and shared_platform must NOT import legacy_stack
  (except the exactly enumerated transitional read-only Markets->legacy-sports
  relationship, Section 13).
- canonical product packages must NOT import defend_control compatibility
  shims (they use shared_platform or their own canonical modules).
- shared_platform must NOT import any product or Control Center.
- legacy Sports must not register/masquerade as Markets.
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

# Section 13: Markets has a transitional READ-ONLY relationship to legacy
# sports data. This is the ONLY canonical->legacy import allowed.
_MARKETS_LEGACY_SPORTS_EXCEPTION = {"defend_markets/collector.py"}

_SHIM_PATHS = (
    "defend_control/coder_control_plane.py",
    "defend_control/coder_deployment.py",
    "defend_control/coder_m0.py",
    "defend_control/coder_provisioning.py",
    "defend_control/coder_remote_vllm.py",
    "defend_control/coder_vast_backend.py",
    "defend_control/secrets.py",
    "defend_control/redaction.py",
    "defend_control/processes.py",
    "defend_control/windows_job.py",
    "defend_control/vast.py",
    "defend_control/ssh_tunnel.py",
    "defend_control/deployment_profiles.py",
)


def _py_files(*dirs: str):
    for d in dirs:
        base = ROOT / d
        if base.is_dir():
            yield from base.rglob("*.py")


def _import_module_roots(path: Path):
    """Extract the top-level module root of each import statement."""
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("from "):
            # from X.Y import Z  -> root X
            target = stripped[len("from "):].split(" import ")[0].strip()
            if target.startswith("."):
                continue  # relative import
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
            if root == "legacy_stack" and rel not in _MARKETS_LEGACY_SPORTS_EXCEPTION:
                offenders.append(f"{rel}: {root}")
    assert offenders == [], (
        "canonical product imports legacy_stack: " + "; ".join(offenders)
    )


def test_markets_legacy_sports_relationship_is_read_only_and_enumerated():
    # The single allowed canonical->legacy import is the Markets collector's
    # read-only legacy-sports data access (Section 13).
    collector = ROOT / "defend_markets" / "collector.py"
    text = collector.read_text(encoding="utf-8")
    assert "legacy_stack.defend_sports" in text


def test_canonical_products_do_not_import_defend_control_shims():
    offenders = []
    for path in _py_files(*_CANONICAL_PRODUCT_DIRS):
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        for root in _import_module_roots(path):
            if root == "defend_control":
                offenders.append(f"{rel}: defend_control")
    assert offenders == [], (
        "canonical product imports defend_control: " + "; ".join(offenders)
    )


def test_shared_platform_imports_no_product_or_control_center():
    forbidden = {
        "defend_ai",
        "defend_coder",
        "defend_markets",
        "defend_control",
        "defend_data",
        "legacy_stack",
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
    # No code may use application_id "markets" for legacy Sports.
    sports_service = (ROOT / "defend_control" / "products.py").read_text(encoding="utf-8")
    m = re.search(r"class SportsService.*?application_id = \"(\w+)\"", sports_service, re.DOTALL)
    assert m is not None
    assert m.group(1) == "sports", "legacy Sports must keep application_id 'sports'"


def test_legacy_stack_readme_has_required_notice():
    readme = (ROOT / "legacy_stack" / "README.md").read_text(encoding="utf-8")
    assert "LEGACY STACK — NOT CANONICAL RUNTIME" in readme
    assert "Canonical product code may not import from" in readme
