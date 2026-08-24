"""PHASE A architecture/firewall regression tests.

Proves root excision, the import firewall, legacy-TT removal, and the
supervision contract. Provider-authority negative tests are included; those
still depend on the Control Center orchestration extraction (COMMIT C) and are
marked xfail until that migration lands.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

# Root-level DEFEND-AI runtime modules that must NOT remain at repo root.
ROOT_AI_RUNTIME = {
    "api_server", "control_plane", "registry", "model_client", "model_factory",
    "model_types", "ollama_client", "ollama_embedding_client",
    "openai_compatible_client", "openai_embedding_client", "embedding_client",
    "embedding_provider", "execution_protocol", "tool_sdk", "production_policy",
    "bootstrap_models", "defend_system", "dev_policy", "documents_store",
    "rag_store", "ui_app", "admin_auth", "api_identity_routes",
    "api_batch3_routes", "api_admin_rag_routes", "api_identity_admin_routes",
    "api_setup_integrations_routes",
}


def _defend_ai_imports():
    """Yield (module, imported_name) for every import in defend_ai/*.py."""
    for path in sorted((REPO_ROOT / "defend_ai").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    yield path.name, alias.name
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    yield path.name, node.module


def test_no_active_defend_ai_runtime_at_repo_root():
    remaining = [m for m in ROOT_AI_RUNTIME if (REPO_ROOT / f"{m}.py").exists()]
    assert remaining == [], f"active DEFEND-AI runtime still at root: {remaining}"


def test_root_api_server_no_longer_canonical_entrypoint():
    assert not (REPO_ROOT / "api_server.py").exists()
    assert (REPO_ROOT / "defend_ai" / "api_server.py").exists()


def test_defend_ai_imports_no_defend_control():
    offenders = [m for m, imp in _defend_ai_imports() if imp.startswith("defend_control")]
    assert offenders == [], f"defend_ai imports defend_control: {offenders}"


def test_defend_ai_imports_no_legacy_stack():
    offenders = [m for m, imp in _defend_ai_imports() if imp.startswith("legacy_stack")]
    assert offenders == [], f"defend_ai imports legacy_stack: {offenders}"


def test_defend_ai_imports_no_other_products():
    forbidden = ("defend_markets", "defend_coder", "scs")
    offenders = [
        (m, imp) for m, imp in _defend_ai_imports()
        if any(imp == f or imp.startswith(f + ".") for f in forbidden)
    ]
    assert offenders == [], f"defend_ai imports other products: {offenders}"


def test_no_ai_legacy_tt_runtime_registration():
    src = (REPO_ROOT / "defend_ai" / "api_server.py").read_text(encoding="utf-8")
    assert "admin_tt_router" not in src
    assert "api_admin_tt_routes" not in src


def test_ai_supervision_manifest_launches_package_entrypoint():
    from defend_ai.supervision import supervision_dict

    assert supervision_dict()["api_launch"] == ["python", "-m", "defend_ai.api_server"]


def test_ai_standalone_without_control_center():
    import subprocess
    import sys

    code = (
        "import sys; sys.path.insert(0, r'%s'); "
        "import defend_ai.api_server as a; "
        "assert 'defend_control' not in sys.modules; "
        "print('standalone OK')" % (REPO_ROOT)
    )
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", code],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0, proc.stderr


# --- Provider-authority negative tests (COMMIT C extraction pending) ---------

def _control_ai_mutation_sites():
    hits = {}
    for name in ("orchestrator.py", "controller.py", "local_model.py",
                 "remote_vllm.py", "preflight.py", "model_probe.py", "products.py"):
        path = REPO_ROOT / "defend_control" / name
        if not path.exists():
            continue
        src = path.read_text(encoding="utf-8")
        for token in ("create_instance", "destroy_instance", "set_state",
                      "stop_and_destroy_vast", "search_offers", "VastClient"):
            if token in src:
                hits.setdefault(name, []).append(token)
    return hits


@pytest.mark.xfail(reason="COMMIT C: orchestrator AI extraction still pending")
def test_defend_control_cannot_create_ai_vast_instance():
    assert "create_instance" not in _control_ai_mutation_sites().get("orchestrator.py", [])


@pytest.mark.xfail(reason="COMMIT C: orchestrator AI extraction still pending")
def test_defend_control_cannot_destroy_ai_vast_instance():
    assert "destroy_instance" not in _control_ai_mutation_sites().get("orchestrator.py", [])


@pytest.mark.xfail(reason="COMMIT C: orchestrator AI extraction still pending")
def test_defend_control_cannot_resume_ai_vast_instance():
    assert "set_state" not in _control_ai_mutation_sites().get("orchestrator.py", [])


def test_defend_control_has_no_ai_compat_shims():
    shims = ["eval_runner", "eval_runner_v2", "huggingface", "model_registry",
             "qwen3_canary_executor", "qwen3_candidate", "training_hardening"]
    remaining = [s for s in shims if (REPO_ROOT / "defend_control" / f"{s}.py").exists()]
    assert remaining == [], f"AI compat shims remain: {remaining}"
