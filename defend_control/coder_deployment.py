"""DEFENDcoder deployment artifacts — provider-neutral serving configuration.

Separates logical model identity (CoderModelRef) from the deployment
artifact actually served: checkpoint repo/revision, precision/format,
serving runtime requirements, context length, and tool-call parsing.

Generic by design: precision and runtime requirements are data, never
hard-wired "FP8" assumptions scattered through the ControlPlane.

No network, no provider SDK, no secrets in this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .coder_m0 import CODER_MODEL_REGISTRY

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")

# Pinned 2026-08-15 from Hugging Face model info for
# Qwen/Qwen3-Coder-Next-FP8 (public, apache-2.0, F8_E4M3).
_FP8_REVISION = "da6e2ed27304dd39abadd9c82ef50e8de67bdd4c"


@dataclass(frozen=True)
class CoderDeploymentArtifact:
    """The exact checkpoint + runtime configuration to serve for an alias."""

    artifact_id: str
    repo_id: str
    revision: str
    precision: str
    minimum_vllm_version: str
    max_model_len: int
    image_tag: str
    tool_call_parser: str | None = None
    enable_auto_tool_choice: bool = False
    required_min_gpu_ram_mb: int | None = None
    requires_hf_token: bool = False
    notes: str = ""


def is_exact_revision(revision: str) -> bool:
    """True only for a full pinned 40-hex commit SHA (never 'main')."""
    return bool(_FULL_SHA.fullmatch(revision))


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version))


def meets_minimum_vllm_version(version: str, minimum: str) -> bool:
    """Compare dotted vLLM versions numerically, padding to equal width."""
    left = _version_tuple(version)
    right = _version_tuple(minimum)
    width = max(len(left), len(right))
    left = left + (0,) * (width - len(left))
    right = right + (0,) * (width - len(right))
    return left >= right


_DEFAULT_MODEL = CODER_MODEL_REGISTRY["defendcoder-default"]

_CODER_DEFAULT_ARTIFACT = CoderDeploymentArtifact(
    artifact_id="qwen3-coder-30b-a3b-bf16",
    repo_id=_DEFAULT_MODEL.repo_id,
    revision=_DEFAULT_MODEL.revision,
    precision="BF16",
    minimum_vllm_version="0.10.0",
    max_model_len=8192,
    image_tag="v0.10.0",
    tool_call_parser=None,
    enable_auto_tool_choice=False,
    required_min_gpu_ram_mb=None,
    requires_hf_token=False,
    notes="Plain BF16 instruct serving, unchanged from runtime-v1 M0.1",
)

_CODER_HEAVY_ARTIFACT = CoderDeploymentArtifact(
    artifact_id="qwen3-coder-next-fp8",
    repo_id="Qwen/Qwen3-Coder-Next-FP8",
    revision=_FP8_REVISION,
    precision="FP8",
    minimum_vllm_version="0.15.0",
    max_model_len=32_768,
    image_tag="v0.15.0",
    tool_call_parser="qwen3_coder",
    enable_auto_tool_choice=True,
    required_min_gpu_ram_mb=81_920,
    requires_hf_token=False,
    notes=(
        "Official Qwen FP8 checkpoint (F8_E4M3); vLLM >= 0.15.0 with "
        "--enable-auto-tool-choice and --tool-call-parser qwen3_coder; "
        "initial context 32768"
    ),
)

# Deployment artifacts keyed by product alias; fast/eval share the default
# artifact until they are differentiated.
CODER_DEPLOYMENT_REGISTRY: dict[str, CoderDeploymentArtifact] = {
    "defendcoder-fast": _CODER_DEFAULT_ARTIFACT,
    "defendcoder-default": _CODER_DEFAULT_ARTIFACT,
    "defendcoder-heavy": _CODER_HEAVY_ARTIFACT,
    "defendcoder-eval": _CODER_DEFAULT_ARTIFACT,
}


def resolve_deployment(alias: str) -> CoderDeploymentArtifact:
    """Resolve the deployment artifact for a coder alias (frozen registry)."""
    if alias not in CODER_DEPLOYMENT_REGISTRY:
        raise ValueError(
            f"no deployment artifact for coder alias {alias!r}; expected one "
            f"of {sorted(CODER_DEPLOYMENT_REGISTRY)}"
        )
    return CODER_DEPLOYMENT_REGISTRY[alias]