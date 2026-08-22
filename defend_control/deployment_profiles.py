"""Explicit immutable DEFEND AI deployment profiles.

A deployment profile selects the EXACT base model, adapter, tokenizer and
runtime for a workload. It is separate from a Vast template ("what kind of
machine") and from a job/run ("what operation"). Model identity lives here;
templates prepare the environment.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import os
from pathlib import Path

from .huggingface import adapter_runtime_base_compatible


class ProfileStatus(str, Enum):
    PRODUCTION = "PRODUCTION"
    CANDIDATE = "CANDIDATE"
    NOT_TRAINED = "NOT_TRAINED"
    ACCEPTED_CANDIDATE = "ACCEPTED_CANDIDATE"
    DEPRECATED = "DEPRECATED"


class ProfilePurpose(str, Enum):
    PRODUCTION_INFERENCE = "PRODUCTION_INFERENCE"
    CANDIDATE_INFERENCE_EVAL = "CANDIDATE_INFERENCE_EVAL"
    TRAINING = "TRAINING"


@dataclass(frozen=True)
class DeploymentProfile:
    profile_id: str
    product_id: str
    purpose: ProfilePurpose
    status: ProfileStatus
    base_repo: str
    base_revision: str
    adapter_repo: str | None
    adapter_revision: str | None
    tokenizer_repo: str | None
    tokenizer_revision: str | None
    serving_alias: str
    runtime_engine: str
    dtype: str
    quantization: str | None = None
    max_model_len: int = 8192
    expected_min_vram_gb: int = 80
    expected_gpu_class: str = "A100 80GB"
    concurrency_profile: str = "LOW_CONCURRENCY_8K"
    vast_template_ref: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    profile_version: str = "1.0"
    promotion_provenance: str | None = None

    def as_public_dict(self) -> dict[str, object]:
        return {k: v for k, v in asdict(self).items()}


class DeploymentProfileRegistry:
    def __init__(self, path: Path | None = None) -> None:
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) / "DEFEND" if local_app_data else Path.cwd()
        self._path = path or (base / "deployment-profiles.json")

    def load(self) -> dict[str, DeploymentProfile]:
        if not self._path.exists():
            return default_profiles()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default_profiles()
        profiles = default_profiles()
        for profile_id, entry in (raw.items() if isinstance(raw, dict) else {}):
            if isinstance(entry, dict):
                profiles[profile_id] = _from_mapping(profile_id, entry)
        return profiles

    def save(self, profiles: dict[str, DeploymentProfile]) -> None:
        payload = {pid: asdict(p) for pid, p in profiles.items()}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = __import__("tempfile").mkstemp(
            dir=self._path.parent, prefix=f".{self._path.name}.", suffix=".tmp"
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self._path)
        finally:
            temporary_path.unlink(missing_ok=True)

    def get(self, profile_id: str) -> DeploymentProfile:
        profiles = self.load()
        if profile_id not in profiles:
            raise KeyError(f"unknown deployment profile {profile_id!r}")
        return profiles[profile_id]


def _from_mapping(profile_id: str, entry: dict) -> DeploymentProfile:
    purpose = entry.get("purpose", ProfilePurpose.PRODUCTION_INFERENCE.value)
    status = entry.get("status", ProfileStatus.CANDIDATE.value)
    return DeploymentProfile(
        profile_id=profile_id,
        product_id=entry.get("product_id", "defend-ai"),
        purpose=ProfilePurpose(purpose),
        status=ProfileStatus(status),
        base_repo=entry["base_repo"],
        base_revision=entry["base_revision"],
        adapter_repo=entry.get("adapter_repo"),
        adapter_revision=entry.get("adapter_revision"),
        tokenizer_repo=entry.get("tokenizer_repo"),
        tokenizer_revision=entry.get("tokenizer_revision"),
        serving_alias=entry.get("serving_alias", "defend-ai"),
        runtime_engine=entry.get("runtime_engine", "vllm"),
        dtype=entry.get("dtype", "bfloat16"),
        quantization=entry.get("quantization"),
        max_model_len=int(entry.get("max_model_len", 8192)),
        expected_min_vram_gb=int(entry.get("expected_min_vram_gb", 80)),
        expected_gpu_class=entry.get("expected_gpu_class", "A100 80GB"),
        concurrency_profile=entry.get("concurrency_profile", "LOW_CONCURRENCY_8K"),
        vast_template_ref=entry.get("vast_template_ref"),
        created_at=entry.get("created_at", datetime.now(timezone.utc).isoformat()),
        profile_version=entry.get("profile_version", "1.0"),
        promotion_provenance=entry.get("promotion_provenance"),
    )


def default_profiles() -> dict[str, DeploymentProfile]:
    return {
        # Verified current production: Qwen2.5-32B-Instruct + identity-lora-v002.
        # This is the rollback baseline. Do not alter.
        "defend-ai-production-qwen25-v002": DeploymentProfile(
            profile_id="defend-ai-production-qwen25-v002",
            product_id="defend-ai",
            purpose=ProfilePurpose.PRODUCTION_INFERENCE,
            status=ProfileStatus.PRODUCTION,
            base_repo="Qwen/Qwen2.5-32B-Instruct",
            base_revision="5ede1c97bbab6ce5cda5812749b4c0bdf79b18dd",
            adapter_repo="Defend-network/defend-identity-lora-v002",
            adapter_revision="46ade1686870210ef0ab4603c32fecb0e563330f",
            tokenizer_repo="Qwen/Qwen2.5-32B-Instruct",
            tokenizer_revision="5ede1c97bbab6ce5cda5812749b4c0bdf79b18dd",
            serving_alias="defend-ai",
            runtime_engine="vllm",
            dtype="bfloat16",
            quantization=None,
            max_model_len=8192,
            expected_min_vram_gb=80,
            expected_gpu_class="A100 80GB",
            concurrency_profile="LOW_CONCURRENCY_8K",
            vast_template_ref="defend-ai-prod-inference-a10080-v1",
            promotion_provenance="M1.7 live acceptance (instance 48416143, 75125/81920 MiB @ 8K)",
        ),
        # Qwen3 candidate: adapter NOT_TRAINED until a Qwen3 identity LoRA exists.
        "defend-ai-candidate-qwen3-v001": DeploymentProfile(
            profile_id="defend-ai-candidate-qwen3-v001",
            product_id="defend-ai",
            purpose=ProfilePurpose.CANDIDATE_INFERENCE_EVAL,
            status=ProfileStatus.NOT_TRAINED,
            base_repo="Qwen/Qwen3-32B",
            base_revision="9216db5781bf21249d130ec9da846c4624c16137",
            adapter_repo="Defend-network/defend-qwen3-32b-identity-lora-v001",
            adapter_revision=None,
            tokenizer_repo="Qwen/Qwen3-32B",
            tokenizer_revision="9216db5781bf21249d130ec9da846c4624c16137",
            serving_alias="defend-ai",
            runtime_engine="vllm",
            dtype="bfloat16",
            quantization=None,
            max_model_len=8192,
            expected_min_vram_gb=80,
            expected_gpu_class="A100 80GB",
            concurrency_profile="LOW_CONCURRENCY_8K",
            vast_template_ref="defend-ai-qwen3-eval-a10080-v1",
            promotion_provenance="planned; requires trained Qwen3 identity adapter",
        ),
        # Qwen3 QLoRA training profile.
        "defend-ai-qwen3-training-qlora-v001": DeploymentProfile(
            profile_id="defend-ai-qwen3-training-qlora-v001",
            product_id="defend-ai",
            purpose=ProfilePurpose.TRAINING,
            status=ProfileStatus.NOT_TRAINED,
            base_repo="Qwen/Qwen3-32B",
            base_revision="9216db5781bf21249d130ec9da846c4624c16137",
            adapter_repo="Defend-network/defend-qwen3-32b-identity-lora-v001",
            adapter_revision=None,
            tokenizer_repo="Qwen/Qwen3-32B",
            tokenizer_revision="9216db5781bf21249d130ec9da846c4624c16137",
            serving_alias="defend-ai",
            runtime_engine="trl-sft-qlora",
            dtype="bfloat16",
            quantization="nf4",
            max_model_len=8192,
            expected_min_vram_gb=80,
            expected_gpu_class="A100 80GB",
            concurrency_profile="TRAINING",
            vast_template_ref="defend-ai-qwen3-training-qlora-a10080-v1",
            promotion_provenance=None,
        ),
    }


def profile_adapter_base_compatible(
    profile: DeploymentProfile,
    adapter_base_model_name_or_path: str | None,
    adapter_architecture: str | None,
    profile_base_config: dict,
) -> tuple[bool, str]:
    """TRUE independent guard: the PROFILE-selected base is authoritative.

    The adapter is validated INDEPENDENTLY against the profile base config
    (model family + architecture class). A Qwen2.5 adapter on a Qwen3 profile
    (or vice versa) fails closed even though the repository names differ.
    """
    if not adapter_base_model_name_or_path:
        return False, "adapter declares no base_model_name_or_path"
    ok, reason = adapter_runtime_base_compatible(
        adapter_base_repo=adapter_base_model_name_or_path,
        adapter_architecture=adapter_architecture,
        runtime_base_config=profile_base_config,
    )
    if not ok:
        return False, reason
    return True, "profile base and adapter base agree"
