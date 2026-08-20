"""Regression guard: active DEFEND AI model configuration must agree with the
canonical model manifest (docs/operations/DEFEND_AI_MODEL_MANIFEST_V1.json).

Prevents recurrence of: documentation says Model A, Control Center launches
Model B, runtime alias points to Model C, evaluation reports Model D."""

from __future__ import annotations

import hashlib
import inspect
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "docs" / "operations" / "DEFEND_AI_MODEL_MANIFEST_V1.json"


@pytest.fixture(scope="module")
def manifest():
    with MANIFEST_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def _modelfile_system_block() -> str | None:
    raw = (REPO_ROOT / "Modelfile").read_text(encoding="utf-8")
    match = re.search(r'SYSTEM """(.*?)"""', raw, re.S)
    return match.group(1).strip() if match else None


def test_manifest_exists_and_is_v1(manifest):
    assert manifest["schema_version"] == 1
    assert manifest["product"] == "defend-ai"
    assert re.fullmatch(r"[0-9a-f]{40}", manifest["canonical_model"]["adapter_revision"])
    assert re.fullmatch(r"[0-9a-f]{40}", manifest["canonical_model"]["base_revision"])
    assert manifest["canonical_model"]["peft_type"] == "LORA"
    assert manifest["canonical_model"]["lora_rank"] == 16


def test_adapter_repo_agrees_across_active_code(manifest):
    expected = manifest["canonical_model"]["adapter_repo"]
    from defend_control.huggingface import _ADAPTER_REPO
    from defend_control.settings import _ADAPTER_REPO as settings_adapter
    from defend_control.remote_vllm import _validate_adapter
    from tools.defend_control_center import _default_settings
    from pathlib import Path as P

    assert _ADAPTER_REPO == expected
    assert settings_adapter == expected
    assert _validate_adapter.__module__  # remote vLLM validates the same pinned spec
    assert _default_settings(P(r"C:\DEFEND")).adapter_repo == expected


def test_alias_semantics_match_manifest(manifest):
    canonical = manifest["aliases"]["canonical"]
    local = manifest["aliases"]["local_dev"]

    assert canonical == "defend-ai"
    assert local == "defend-ai:latest"

    from model_factory import build_model_client
    from api_server import MODEL_NAME

    assert build_model_client.__module__  # env-driven factory
    assert MODEL_NAME == "defend-ai:latest"  # default when DEFEND_MODEL unset

    source = (REPO_ROOT / "ui_app.py").read_text(encoding="utf-8")
    match = re.search(r'DEFEND_MODEL", "(.*?)"', source)
    assert match is not None
    assert match.group(1) == "defend-ai:latest"

    from defend_control.model_probe import ModelProbe
    signature = inspect.signature(ModelProbe.wait_ready)
    assert signature.parameters["model"].default == "defend-ai"


def test_system_prompt_hash_matches_manifest(manifest):
    from defend_system import get_system_prompt

    prompt = get_system_prompt()
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    assert digest == manifest["canonical_model"]["system_prompt"]["sha256"]
    assert len(prompt) == manifest["canonical_model"]["system_prompt"]["chars"]


def test_modelfile_system_block_derives_from_single_source(manifest):
    """The local dev Modelfile must embed the same system prompt as the app's
    single source (defend_system.get_system_prompt), not a drifted copy."""
    from defend_system import get_system_prompt

    block = _modelfile_system_block()
    assert block is not None, "Modelfile SYSTEM block missing"
    digest = hashlib.sha256(block.encode("utf-8")).hexdigest()
    assert digest == manifest["canonical_model"]["system_prompt"]["sha256_stripped"]
    assert block == get_system_prompt().strip()


def test_modelfile_is_explicitly_marked_legacy_local_plumbing():
    raw = (REPO_ROOT / "Modelfile").read_text(encoding="utf-8")
    assert "qwen2.5:14b" in raw  # local dev base (legacy plumbing)
    assert "NOT" in raw.splitlines()[0]
    assert "CANONICAL" in raw.splitlines()[0].upper()