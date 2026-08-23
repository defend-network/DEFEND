"""Versioned Vast runtime-template profiles.

A Vast template is infrastructure configuration ("what kind of machine /
environment is this?"). It is separate from a DeploymentProfile ("which exact
model runs?") and from a job/run ("what operation?").

Templates NEVER contain secrets or model identity as mutable truth.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import os
from pathlib import Path


class TemplateStatus(str, Enum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class StartupMode(str, Enum):
    SSH_BOOTSTRAP = "ssh_bootstrap"
    IMAGE_CMD = "image_cmd"
    CLOUD_INIT = "cloud_init"


@dataclass(frozen=True)
class VastTemplateProfile:
    template_profile_id: str
    product_id: str
    purpose: str
    version: str
    provider: str = "vast"
    vast_template_id: str | None = None
    template_name: str = ""
    image: str | None = None
    disk_gb: int = 160
    min_gpu_ram_gb: int = 80
    preferred_gpu_families: tuple[str, ...] = ("A100",)
    minimum_reliability: float = 0.97
    ports: tuple[int, ...] = (8000,)
    startup_mode: StartupMode = StartupMode.SSH_BOOTSTRAP
    runtime_packages: dict[str, str] = field(default_factory=dict)
    deployment_profile_ids: tuple[str, ...] = ()
    status: TemplateStatus = TemplateStatus.ACTIVE
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    deprecated_at: str | None = None
    migration_reason: str | None = None

    def as_public_dict(self) -> dict[str, object]:
        return {k: v for k, v in asdict(self).items()}


class VastTemplateRegistry:
    def __init__(self, path: Path | None = None) -> None:
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) / "DEFEND" if local_app_data else Path.cwd()
        self._path = path or (base / "vast-templates.json")

    def load(self) -> dict[str, VastTemplateProfile]:
        if not self._path.exists():
            return default_templates()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default_templates()
        templates = default_templates()
        for tid, entry in (raw.items() if isinstance(raw, dict) else {}):
            if isinstance(entry, dict):
                templates[tid] = _template_from_mapping(tid, entry)
        return templates

    def save(self, templates: dict[str, VastTemplateProfile]) -> None:
        payload = {tid: asdict(t) for tid, t in templates.items()}
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

    def get(self, template_profile_id: str) -> VastTemplateProfile:
        templates = self.load()
        if template_profile_id not in templates:
            raise KeyError(f"unknown template profile {template_profile_id!r}")
        return templates[template_profile_id]


def _template_from_mapping(tid: str, entry: dict) -> VastTemplateProfile:
    return VastTemplateProfile(
        template_profile_id=tid,
        product_id=entry.get("product_id", "defend-ai"),
        purpose=entry.get("purpose", "inference"),
        version=entry.get("version", "1"),
        provider=entry.get("provider", "vast"),
        vast_template_id=entry.get("vast_template_id"),
        template_name=entry.get("template_name", tid),
        image=entry.get("image"),
        disk_gb=int(entry.get("disk_gb", 160)),
        min_gpu_ram_gb=int(entry.get("min_gpu_ram_gb", 80)),
        preferred_gpu_families=tuple(entry.get("preferred_gpu_families", ("A100",))),
        minimum_reliability=float(entry.get("minimum_reliability", 0.97)),
        ports=tuple(int(p) for p in entry.get("ports", (8000,))),
        startup_mode=StartupMode(entry.get("startup_mode", StartupMode.SSH_BOOTSTRAP.value)),
        runtime_packages=dict(entry.get("runtime_packages", {})),
        deployment_profile_ids=tuple(entry.get("deployment_profile_ids", ())),
        status=TemplateStatus(entry.get("status", TemplateStatus.ACTIVE.value)),
        created_at=entry.get("created_at", datetime.now(timezone.utc).isoformat()),
        deprecated_at=entry.get("deprecated_at"),
        migration_reason=entry.get("migration_reason"),
    )


def default_templates() -> dict[str, VastTemplateProfile]:
    # v002 production inference recipe (TRL SFT, PEFT 0.20.0, transformers
    # 5.15.0, PyTorch 2.12.0+cu130) is the runtime stack reference for the
    # inference template; Qwen3 compatibility is pending audit.
    return {
        "defend-ai-prod-inference-a10080-v1": VastTemplateProfile(
            template_profile_id="defend-ai-prod-inference-a10080-v1",
            product_id="defend-ai",
            purpose="PRODUCTION_INFERENCE",
            version="1",
            template_name="defend-ai-prod-inference-a10080-v1",
            image="vllm/vllm-openai:v0.10.0",
            disk_gb=160,
            min_gpu_ram_gb=80,
            preferred_gpu_families=("A100",),
            minimum_reliability=0.97,
            ports=(8000,),
            startup_mode=StartupMode.SSH_BOOTSTRAP,
            runtime_packages={
                "vllm": ">=0.10.0",
                "peft": "0.20.0",
            },
            deployment_profile_ids=("defend-ai-production-qwen25-v002",),
        ),
        "defend-ai-qwen3-eval-a10080-v1": VastTemplateProfile(
            template_profile_id="defend-ai-qwen3-eval-a10080-v1",
            product_id="defend-ai",
            purpose="CANDIDATE_INFERENCE_EVAL",
            version="1",
            template_name="defend-ai-qwen3-eval-a10080-v1",
            image="vllm/vllm-openai:v0.10.0",
            disk_gb=160,
            min_gpu_ram_gb=80,
            preferred_gpu_families=("A100",),
            minimum_reliability=0.97,
            ports=(8000,),
            startup_mode=StartupMode.SSH_BOOTSTRAP,
            runtime_packages={"vllm": ">=0.10.0", "peft": "0.20.0"},
            deployment_profile_ids=("defend-ai-candidate-qwen3-v001",),
        ),
        "defend-ai-qwen3-training-qlora-a10080-v1": VastTemplateProfile(
            template_profile_id="defend-ai-qwen3-training-qlora-a10080-v1",
            product_id="defend-ai",
            purpose="QWEN3_TRAINING_QLORA",
            version="1",
            template_name="defend-ai-qwen3-training-qlora-a10080-v1",
            image=None,
            disk_gb=200,
            min_gpu_ram_gb=80,
            preferred_gpu_families=("A100",),
            minimum_reliability=0.97,
            ports=(8000,),
            startup_mode=StartupMode.SSH_BOOTSTRAP,
            runtime_packages={
                # v002 recipe stack; Qwen3 compatibility pending audit before pinning.
                "transformers": ">=5.15.0",
                "trl": ">=1.10.0",
                "peft": ">=0.20.0",
                "torch": ">=2.12.0",
                "bitsandbytes": ">=0.45",
                "accelerate": ">=1.0",
                "huggingface_hub": ">=0.30",
            },
            deployment_profile_ids=("defend-ai-qwen3-training-qlora-v001",),
        ),
    }


def template_compatible_with_offer(
    template: VastTemplateProfile,
    *,
    offer_gpu_ram_mb: int,
    offer_gpu_name: str,
    offer_reliability: float,
    offer_disk_gb: float,
    profile_min_vram_gb: int,
) -> tuple[bool, str]:
    """Fail-before-rental template compatibility check."""
    required_mb = max(template.min_gpu_ram_gb, profile_min_vram_gb) * 1024
    if offer_gpu_ram_mb < required_mb:
        return (
            False,
            f"offer VRAM {offer_gpu_ram_mb}MiB below requirement {required_mb}MiB",
        )
    family = offer_gpu_name.split()[0].upper() if offer_gpu_name else ""
    families = {f.upper() for f in template.preferred_gpu_families}
    if families and family not in families:
        return False, f"offer GPU {offer_gpu_name!r} not in {sorted(families)}"
    if offer_reliability < template.minimum_reliability:
        return False, "offer reliability below template policy"
    if offer_disk_gb < template.disk_gb:
        return False, "offer disk below template requirement"
    return True, "offer compatible with template and profile"
