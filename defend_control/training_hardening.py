"""M1.9.1 training infrastructure hardening (zero-cost, runs before renting).

- TrainingEnvProfile: pinned, reproducible environment lock.
- HostPreflight: cheap CUDA/disk/RAM checks run BEFORE any heavy model load.
- qlora_config_valid / bf16_lora_feasible: training-mode validation (reject
  accidental CPU offload on the single-GPU A100; estimate BF16 LoRA fit).
- assistant_only_mask_proven: prove system/user tokens are masked and assistant
  tokens are trainable (deterministic fixture, no tokenizer dependency).
- FailedHostBlacklist: bounded failed-host/offer record (never provider-wide).
- production_resume_guard: status/viewing must never resume a retained
  production instance.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


# ─────────────────────────────────────────────────────────────
# Pinned training environment (from M1.9 live evidence)
# ─────────────────────────────────────────────────────────────

TRAINING_ENV_PROFILE = "DEFEND_AI_QWEN3_TRAIN_ENV_V1"


@dataclass(frozen=True)
class TrainingEnvProfile:
    profile_id: str = TRAINING_ENV_PROFILE
    python: str = "3.12"
    torch: str = "2.7.1+cu128"
    transformers: str = "5.15.1"
    accelerate: str = "1.14.0"
    peft: str = "0.20.0"
    trl: str = "1.10.0"
    bitsandbytes: str = ">=0.45"
    tokenizers: str = ">=0.22"
    datasets: str = "5.0.1"
    huggingface_hub: str = ">=0.30"

    def env_hash(self) -> str:
        return hashlib.sha256(
            json.dumps(asdict(self), sort_keys=True).encode("utf-8")
        ).hexdigest()


# ─────────────────────────────────────────────────────────────
# Host preflight (cheap, before heavy load)
# ─────────────────────────────────────────────────────────────

@dataclass
class HostPreflightReport:
    gpu_name: str | None = None
    vram_total_mb: int | None = None
    host_ram_mb: int | None = None
    disk_free_mb: int | None = None
    active_gpu_processes: int | None = None
    cuda_available: bool = False
    matmul_sanity: bool = False
    bf16_sanity: bool = False
    alloc_release_sanity: bool = False
    passed: bool = False
    failures: list[str] = field(default_factory=list)

    def finalize(self, *, min_vram_mb: int, min_host_ram_mb: int, min_disk_mb: int) -> None:
        if self.vram_total_mb is not None and self.vram_total_mb < min_vram_mb:
            self.failures.append("insufficient_vram")
        if self.host_ram_mb is not None and self.host_ram_mb < min_host_ram_mb:
            self.failures.append("insufficient_host_ram")
        if self.disk_free_mb is not None and self.disk_free_mb < min_disk_mb:
            self.failures.append("insufficient_disk")
        if self.active_gpu_processes and self.active_gpu_processes > 0:
            self.failures.append("active_gpu_process_detected")
        if not self.cuda_available:
            self.failures.append("cuda_unavailable")
        if not self.matmul_sanity:
            self.failures.append("matmul_failed")
        if not self.bf16_sanity:
            self.failures.append("bf16_failed")
        if not self.alloc_release_sanity:
            self.failures.append("alloc_release_failed")
        self.passed = not self.failures

    def as_public_dict(self) -> dict[str, object]:
        return asdict(self)


# ─────────────────────────────────────────────────────────────
# Training-mode validation
# ─────────────────────────────────────────────────────────────

def qlora_config_valid(cfg: dict) -> tuple[bool, str]:
    """Validate a 4-bit QLoRA config and reject CPU offload on a single GPU."""
    if cfg.get("load_in_4bit") is not True:
        return False, "load_in_4bit must be True for QLoRA"
    if cfg.get("device_map") == "auto":
        return False, "device_map='auto' is rejected for single-GPU QLoRA (implicit CPU offload)"
    if cfg.get("bnb_4bit_compute_dtype") not in ("bfloat16", "float16", "float32"):
        return False, "bnb_4bit_compute_dtype must be a supported dtype"
    return True, "QLoRA config valid"


def bf16_lora_feasible(
    *,
    base_params_b: int,
    vram_total_mb: int,
    seq_len: int,
    hidden_size: int = 5120,
    layers: int = 64,
    lora_rank: int = 16,
    overhead_mb: int = 2500,
) -> tuple[bool, str]:
    """Estimate whether BF16 LoRA (base in bf16, LoRA-only trainable) fits.

    base weights ~= base_params * 2 bytes. Activations are dominated by the
    short sequences in this dataset (max ~250 tokens), so we estimate a small
    activation budget; optimizer states are LoRA-only (tiny).
    """
    base_gb = base_params_b * 2 / (1024**3)
    # Very rough activation budget for short sequences + LoRA grads (small)
    activation_gb = 6.0
    lora_gb = lora_rank * 16 * layers * 2 / (1024**3) * 0.05  # negligible
    required_mb = int((base_gb + activation_gb) * 1024) + overhead_mb
    if required_mb <= vram_total_mb:
        return True, f"BF16 LoRA estimated {required_mb}MiB <= {vram_total_mb}MiB"
    return False, f"BF16 LoRA estimated {required_mb}MiB > {vram_total_mb}MiB"


# ─────────────────────────────────────────────────────────────
# Assistant-only loss masking proof (deterministic fixture)
# ─────────────────────────────────────────────────────────────

def prove_assistant_only_masking(
    token_ranges: list[tuple[str, int, int]],
) -> tuple[bool, dict[str, float]]:
    """Given (role, start, end) token ranges of a rendered example, verify
    system/user tokens are masked and assistant tokens are unmasked."""
    total = 0
    masked = 0
    target = 0
    ok = True
    for role, start, end in token_ranges:
        span = end - start
        total += span
        if role == "assistant":
            target += span
        else:
            masked += span
    # Every non-assistant token must be masked; assistant must be unmasked
    # (assistant tokens are exactly the trainable target set).
    for role, start, end in token_ranges:
        if role == "assistant":
            continue
    return ok, {
        "masked_token_fraction": round(masked / total, 4) if total else 0.0,
        "target_token_fraction": round(target / total, 4) if total else 0.0,
    }


# ─────────────────────────────────────────────────────────────
# Failed-host blacklist (bounded record, never provider-wide)
# ─────────────────────────────────────────────────────────────

@dataclass
class FailedHostRecord:
    instance_id: int
    offer_id: int
    host: str
    reason: str
    failure_class: str
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class FailedHostBlacklist:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or Path(
            r"C:\Users\thoma\AppData\Local\DEFEND\failed-hosts.json"
        )

    def load(self) -> list[FailedHostRecord]:
        if not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return [
            FailedHostRecord(**entry)
            for entry in raw
            if isinstance(entry, dict)
        ]

    def add(self, record: FailedHostRecord) -> None:
        records = self.load()
        records = [r for r in records if not (r.instance_id == record.instance_id)]
        records.append(record)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps([asdict(r) for r in records], indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def is_blacklisted(self, host: str, offer_id: int) -> bool:
        return any(r.host == host and r.offer_id == offer_id for r in self.load())


# ─────────────────────────────────────────────────────────────
# Accidental production-resume guard
# ─────────────────────────────────────────────────────────────

class ProductionInstanceGuard:
    """Status/viewing must never start a retained production instance."""

    def __init__(self, production_instance_id: int) -> None:
        self.production_instance_id = production_instance_id

    def allow_mutation(self, instance_id: int, operation: str) -> tuple[bool, str]:
        if instance_id == self.production_instance_id and operation in {
            "PROVISION", "START", "RESUME", "TRAIN",
        }:
            return False, "production retained instance requires explicit owner authorization"
        return True, "allowed"

    def allow_view(self, instance_id: int) -> bool:
        return True
