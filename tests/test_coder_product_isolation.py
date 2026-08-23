"""DEFENDcoder product isolation architecture tests.

defend_coder is the canonical DEFENDcoder product boundary. It must not import
Control Center (defend_control) or any sibling product (defend_markets,
defend_sports, SCS, etc.). Neutral shared primitives (shared_platform) are the
only permitted cross-boundary imports.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from defend_coder import runtime_status as _rt  # noqa: F401


PACKAGE_DIR = Path(__file__).parent.parent / "defend_coder"

FORBIDDEN = (
    "defend_control",
    "defend_markets",
    "defend_sports",
    "scs_",
    "defend_ai",
)

_IMPORT_RE = re.compile(
    r"^\s*(?:from|import)\s+([A-Za-z_][A-Za-z0-9_]*)"
)


def _top_level_imports(source: str) -> set[str]:
    result: set[str] = set()
    for line in source.splitlines():
        match = _IMPORT_RE.match(line)
        if match:
            result.add(match.group(1))
    return result


def _coder_modules() -> list[Path]:
    return sorted(PACKAGE_DIR.glob("*.py"))


class TestProductIsolation:
    def test_defend_coder_imports_no_control_or_sibling_products(self):
        offenders: list[str] = []
        for module in _coder_modules():
            top_level = _top_level_imports(module.read_text(encoding="utf-8"))
            for name in top_level:
                if any(name == f or name.startswith(f) for f in FORBIDDEN):
                    offenders.append(f"{module.name}: imports {name}")
        assert offenders == [], offenders

    def test_recursive_isolation_includes_subpackages(self):
        offenders: list[str] = []
        for module in sorted(PACKAGE_DIR.rglob("*.py")):
            top_level = _top_level_imports(module.read_text(encoding="utf-8"))
            for name in top_level:
                if any(name == f or name.startswith(f) for f in FORBIDDEN):
                    offenders.append(
                        f"{module.relative_to(PACKAGE_DIR)}: imports {name}"
                    )
        assert offenders == [], offenders

    def test_transitive_clean_process_has_no_defend_control(self):
        import subprocess
        import sys

        probe = (
            "import sys; "
            "from tools import defend_coder_server; "
            "from defend_coder.app import build_coder_app; "
            "loaded = [m for m in sys.modules "
            "if m == 'defend_control' or m.startswith('defend_control.')]; "
            "print('CONTROL_LOADED', loaded); "
            "sys.exit(1 if loaded else 0)"
        )
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert completed.returncode == 0, (
            f"canonical startup transitively loaded defend_control: "
            f"{completed.stdout} {completed.stderr}"
        )

    def test_standalone_server_imports_no_control_center(self):
        server = (
            Path(__file__).parent.parent / "tools" / "defend_coder_server.py"
        )
        source = server.read_text(encoding="utf-8")
        top_level = _top_level_imports(source)
        assert "defend_control" not in top_level
        assert "defend_markets" not in top_level

    def test_runtime_status_is_product_owned(self):
        from defend_coder.runtime_status import coder_runtime_status

        class _Creds:
            def configured(self, provider):
                return provider == "deepseek"

        status = coder_runtime_status(_Creds())
        assert status["state"] == "ready"
        assert status["provider"] == "deepseek"
        assert status["next_state"] == "ABSENT"

    def test_dpapi_primitive_moved_to_shared_platform(self):
        import shared_platform.dpapi as dpapi
        from defend_control.secrets import DpapiSecretStore as Shim

        assert dpapi.DpapiSecretStore is Shim
        assert hasattr(dpapi, "restrict_to_current_user")

    def test_launch_manifest_is_product_owned(self):
        from defend_coder.launch import (
            API_PORT,
            MODEL_FORWARD_PORT,
            UI_PORT,
            build_launch_manifest,
        )

        manifest = build_launch_manifest()
        assert manifest.api_port == API_PORT == 8301
        assert manifest.ui_port == UI_PORT == 3301
        assert manifest.model_forward_port == MODEL_FORWARD_PORT == 8403
        assert manifest.health_url == "http://127.0.0.1:8301/health"
        assert "tools.defend_coder_server" in manifest.api_command

    def test_production_runtime_manager_is_concrete_not_fake(self):
        import inspect

        import defend_coder.app as app_module

        source = inspect.getsource(app_module)
        # Production default must be the concrete manager, never the fake
        # boundary as the fallback authority.
        assert "CoderRuntimeManager()" in source
        assert "ProductRuntimeAdapterBoundary()" not in source
