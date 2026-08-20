"""DEFEND AI model registry: alias -> repo/revision/adapter resolution.

Mirrors the DEFENDcoder pinned-artifact registry pattern
(`defend_control/coder_m0.py`) for the identity chat lane.

This module centralizes EXISTING metadata only. Every constant below was
previously a duplicated literal in `defend_control/huggingface.py`,
`defend_control/settings.py`, `defend_control/remote_vllm.py`,
`tools/defend_control_center.py`, and
`docs/superpowers/plans/2026-08-10-defend-control-center-vast-vllm-implementation.md`.
It does not introduce new models, adapters, or prompts.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Literal

from .types import ServiceState

# -- Exact identifiers already present in the repository -------------------

# PRODUCTION LoRA adapter repo + pinned revision SHA (owner-provided).
ADAPTER_REPO = "Defend-network/defend-identity-lora-v002"
ADAPTER_REVISION = "46ade1686870210ef0ab4603c32fecb0e563330f"

# Superseded first-generation adapter. NOT production; retained only as
# metadata for rollback/migration history. Nothing in the launch path
# resolves or serves it.
LEGACY_ADAPTER_REPO = "Defend-network/defend-qwen-32b-lora"

# Preserved GGUF sibling repo; never served through the vLLM path
# (huggingface.py:17, plan doc lines 19-20).
GGUF_REPO = "Defend-network/defend-qwen-32b-gguf"

# Served vLLM LoRA module alias (remote_vllm.py:189 `--lora-modules
# defend-ai=...`, model_probe.py:172-173, orchestrator.py:709).
SERVING_ALIAS = "defend-ai"

# Local Ollama served tag (model_factory.py:12, api_server.py:49,
# ui_app.py:22, tools/defend_control_center.py:583).
LOCAL_ALIAS = "defend-ai:latest"

# Embedding lane (embedding_provider.py:85-87, defend_data/admin_rag.py:99).
EMBEDDING_MODEL = "qwen3-embedding:0.6b"
EMBEDDING_REPO = "Qwen/Qwen3-Embedding-0.6B"

# Optional deploy-time pin override. Validated strict SHA; absent/empty uses
# the production pin above. Secrets never belong here; this is metadata only.
_ADAPTER_REVISION_ENV = "DEFEND_ADAPTER_REVISION"

_REVISION = re.compile(r"^[0-9a-fA-F]{40,64}$")
_REPOSITORY = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$"
)

DefendModelRole = Literal["identity-adapter", "local", "embedding"]


class ModelRegistryError(ValueError):
    """Strict alias-resolution failure; never carries secrets or outputs."""


@dataclass(frozen=True)
class DefendModelRef:
    alias: str
    role: DefendModelRole
    backend: str
    repo_id: str
    serving_alias: str
    revision: str | None = None
    notes: str = ""


# Registry: DEFEND AI lane aliases -> concrete checkpoints.
DEFEND_MODEL_REGISTRY: dict[str, DefendModelRef] = {
    SERVING_ALIAS: DefendModelRef(
        alias=SERVING_ALIAS,
        role="identity-adapter",
        backend="openai_compatible",
        repo_id=ADAPTER_REPO,
        serving_alias=SERVING_ALIAS,
        revision=ADAPTER_REVISION,
        notes=(
            "Trained DEFEND LoRA served through vLLM; base model and base "
            "revision are derived from adapter_config.json at deploy time"
        ),
    ),
    LOCAL_ALIAS: DefendModelRef(
        alias=LOCAL_ALIAS,
        role="local",
        backend="ollama",
        repo_id=LOCAL_ALIAS,
        serving_alias=LOCAL_ALIAS,
        notes="Local Ollama tag built from the repository Modelfile",
    ),
    EMBEDDING_MODEL: DefendModelRef(
        alias=EMBEDDING_MODEL,
        role="embedding",
        backend="ollama",
        repo_id=EMBEDDING_MODEL,
        serving_alias=EMBEDDING_MODEL,
        notes="Embedding lane; 1024-dim vectors (rag_store.py:14)",
    ),
}


def adapter_revision_pin() -> str | None:
    """Return the production pin SHA, or a validated exact-SHA override.

    Defaults to the owner-pinned ADAPTER_REVISION. DEFEND_ADAPTER_REVISION
    may override it for a specific deployment; invalid values fail loudly
    instead of silently falling back.
    """
    raw = os.environ.get(_ADAPTER_REVISION_ENV, "").strip()
    if not raw:
        return ADAPTER_REVISION
    if not _REVISION.fullmatch(raw):
        raise ModelRegistryError(
            f"{_ADAPTER_REVISION_ENV} must be an immutable SHA "
            "(40-64 lowercase/uppercase hex characters)"
        )
    return raw.lower()


def resolve_defend_alias(alias: str) -> DefendModelRef:
    if alias not in DEFEND_MODEL_REGISTRY:
        raise ModelRegistryError(
            f"unknown DEFEND AI model alias {alias!r}; expected one of "
            f"{sorted(DEFEND_MODEL_REGISTRY)}"
        )
    return DEFEND_MODEL_REGISTRY[alias]


@dataclass(frozen=True)
class DefendModelStatus:
    """Observation payload for the DEFEND AI model lane.

    Intentionally mirrors `CoderSessionStatus`; never includes API keys,
    tokens, prompts, or generated outputs.
    """

    state: ServiceState
    alias: str
    serving_alias: str
    backend: str
    adapter_repo: str
    adapter_revision: str | None
    base_repo: str | None
    base_revision: str | None
    provider: str
    message: str | None = None

    def as_public_dict(self) -> dict[str, object]:
        return {
            "service": "DEFEND AI",
            "state": self.state,
            "alias": self.alias,
            "serving_alias": self.serving_alias,
            "backend": self.backend,
            "adapter_repo": self.adapter_repo,
            "adapter_revision": self.adapter_revision,
            "base_repo": self.base_repo,
            "base_revision": self.base_revision,
            "provider": self.provider,
            "message": self.message,
        }