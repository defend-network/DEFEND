"""Product-isolation boundary tests: canonical DEFEND AI imports no Control
Center or other product package. Neutral shared_platform imports are allowed."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

FORBIDDEN_PREFIXES = (
    "defend_control",
    "defend_coder",
    "defend_markets",
    "defend_sports",
    "scs_ai", "scs_api", "scs_copilot", "scs_data", "scs_diagnostics",
    "scs_engineering", "scs_equipment", "scs_knowledge", "scs_procedures", "scs_reports",
)

_IMPORT_RE = re.compile(r"^\s*(?:import|from)\s+([A-Za-z_][A-Za-z0-9_]*)")


def _defend_ai_files() -> list[Path]:
    root = Path(__file__).resolve().parent.parent / "defend_ai"
    return sorted(root.glob("*.py"))


def test_defend_ai_imports_no_control_center_or_other_products():
    for path in _defend_ai_files():
        hits = []
        for line in path.read_text(encoding="utf-8").splitlines():
            m = _IMPORT_RE.match(line)
            if not m:
                continue
            module = m.group(1)
            for prefix in FORBIDDEN_PREFIXES:
                if module == prefix or module.startswith(prefix + "."):
                    hits.append(module)
        assert not hits, f"{path.name} imports forbidden module(s): {hits}"


def test_transitive_runtime_isolation():
    """In a clean subprocess, importing the canonical DEFEND AI product and
    neutral shared infra must not transitively load Control Center or other
    product packages."""
    root = Path(__file__).resolve().parent.parent
    code = (
        "import sys\n"
        "import defend_ai.qwen3_canary_executor\n"
        "import shared_platform.vast\n"
        "import shared_platform.secure_store\n"
        "cc = sorted(m for m in sys.modules if m.startswith('defend_control'))\n"
        "other = sorted(m for m in sys.modules if m.startswith(('defend_coder','defend_markets','defend_sports')) or m.startswith('scs_'))\n"
        "print('CC=' + repr(cc))\n"
        "print('OTHER=' + repr(other))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=str(root), timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert "CC=[]" in proc.stdout, f"Control Center modules loaded transitively: {proc.stdout}"
    assert "OTHER=[]" in proc.stdout, f"Other product modules loaded transitively: {proc.stdout}"
