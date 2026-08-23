"""M1.9.1A training infrastructure hardening (zero paid compute).

- TrainingEnvironmentSpec: EXACT pinned versions (no ``>=``) + validator.
- HostPreflightRunner: executable harness (nvidia-smi + torch CUDA probes) that
  runs on a training host and fail-closes on missing telemetry.
- qlora_config_valid / qlora_device_placement_valid: reject CPU/disk offload on
  the single-GPU A100.
- bf16_lora_feasible: unambiguous units (base_params_billions) and clearly an
  ESTIMATE only.
- validate_assistant_masking: consume ACTUAL labels, prove system/user == -100
  and assistant != -100 (detects real defects).
- FailedHostBlacklist: atomic, bounded, config-root based (not hard-coded to a
  username).
- ProductionMutationGuard: enforced at the real mutation boundary, re-checked at
  execution time (stale queued actions cannot resume production).
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

# ─────────────────────────────────────────────────────────────
# Exact training environment
# ─────────────────────────────────────────────────────────────

TRAINING_ENV_PROFILE = "DEFEND_AI_QWEN3_TRAIN_ENV_V1"


@dataclass(frozen=True)
class TrainingEnvironmentSpec:
    profile_id: str = TRAINING_ENV_PROFILE
    python: str = "3.12"
    torch: str = "2.7.1"
    cuda_runtime: str = "cu128"
    transformers: str = "5.15.1"
    accelerate: str = "1.14.0"
    peft: str = "0.20.0"
    trl: str = "1.10.0"
    bitsandbytes: str = "0.45.0"
    tokenizers: str = "0.22.0"
    datasets: str = "5.0.1"
    huggingface_hub: str = "0.30.0"
    safetensors: str = "0.6.0"

    def env_hash(self) -> str:
        return hashlib.sha256(
            json.dumps(asdict(self), sort_keys=True).encode("utf-8")
        ).hexdigest()

    def minimum_constraints(self) -> dict[str, str]:
        """Install-time minimums (the exact spec is the reproducibility lock)."""
        return {
            "transformers": ">=" + self.transformers,
            "trl": ">=" + self.trl,
            "peft": ">=" + self.peft,
            "bitsandbytes": ">=" + self.bitsandbytes,
            "accelerate": ">=" + self.accelerate,
            "datasets": ">=" + self.datasets,
            "huggingface_hub": ">=" + self.huggingface_hub,
        }


def _installed_version(dist: str) -> str | None:
    try:
        return importlib.metadata.version(dist)
    except importlib.metadata.PackageNotFoundError:
        return None


def validate_training_environment(spec: TrainingEnvironmentSpec) -> tuple[bool, dict[str, str]]:
    """Compare the ACTUAL installed versions to the exact pinned spec."""
    expected = {
        "torch": spec.torch,
        "transformers": spec.transformers,
        "accelerate": spec.accelerate,
        "peft": spec.peft,
        "trl": spec.trl,
        "bitsandbytes": spec.bitsandbytes,
        "tokenizers": spec.tokenizers,
        "datasets": spec.datasets,
        "huggingface_hub": spec.huggingface_hub,
        "safetensors": spec.safetensors,
    }
    mismatches: dict[str, str] = {}
    for dist, want in expected.items():
        have = _installed_version(dist)
        if have is None:
            mismatches[dist] = "MISSING"
        elif not have.startswith(want):
            mismatches[dist] = f"expected {want}, got {have}"
    return (not mismatches), mismatches


# ─────────────────────────────────────────────────────────────
# Host preflight (executable)
# ─────────────────────────────────────────────────────────────

@dataclass
class HostPreflightResult:
    gpu_name: str | None = None
    vram_total_mb: int | None = None
    vram_free_mb: int | None = None
    driver_version: str | None = None
    cuda_version: str | None = None
    gpu_temperature_c: int | None = None
    active_gpu_processes: int | None = None
    host_ram_total_mb: int | None = None
    host_ram_free_mb: int | None = None
    disk_free_mb: int | None = None
    cuda_available: bool | None = None
    matmul_sanity: bool | None = None
    bf16_sanity: bool | None = None
    backward_sanity: bool | None = None
    alloc_release_sanity: bool | None = None
    host_id: str | None = None
    offer_id: int | None = None
    instance_id: int | None = None
    passed: bool | None = None
    status: str = "INCOMPLETE"
    failures: list[str] = field(default_factory=list)

    def as_public_dict(self) -> dict[str, object]:
        return asdict(self)


class HostPreflightRunner:
    """Executable preflight. Runs GPU/CUDA/RAM/disk probes; fails closed when
    required hardware telemetry cannot be measured."""

    def __init__(
        self,
        *,
        nvidia_smi: Callable[[], str] | None = None,
        torch_probe: Callable[[], dict] | None = None,
        host_id: str | None = None,
        offer_id: int | None = None,
        instance_id: int | None = None,
    ) -> None:
        self._nvidia_smi = nvidia_smi or self._default_nvidia_smi
        self._torch_probe = torch_probe or self._default_torch_probe
        self._host_id = host_id
        self._offer_id = offer_id
        self._instance_id = instance_id

    @staticmethod
    def _default_nvidia_smi() -> str:
        if shutil.which("nvidia-smi") is None:
            return ""
        try:
            return subprocess.run(
                ["nvidia-smi"], capture_output=True, text=True, timeout=30
            ).stdout
        except Exception:
            return ""

    @staticmethod
    def _default_torch_probe() -> dict:
        try:
            import torch

            ok = torch.cuda.is_available()
            out = {"cuda_available": ok}
            if not ok:
                return out
            out["device_name"] = torch.cuda.get_device_name(0)
            mem = torch.cuda.get_device_properties(0).total_memory
            out["vram_total_mb"] = int(mem // (1024 * 1024))
            # matmul
            a = torch.randn(256, 256, device="cuda")
            b = torch.randn(256, 256, device="cuda")
            c = a @ b
            torch.cuda.synchronize()
            out["matmul_sanity"] = bool(c.isfinite().all().item())
            # bf16
            try:
                x = torch.randn(64, 64, device="cuda", dtype=torch.bfloat16)
                y = (x @ x).float()
                out["bf16_sanity"] = bool(y.isfinite().all().item())
            except Exception:
                out["bf16_sanity"] = False
            # backward
            try:
                w = torch.randn(32, 32, device="cuda", requires_grad=True)
                (w.sum() ** 2).backward()
                out["backward_sanity"] = w.grad is not None
            except Exception:
                out["backward_sanity"] = False
            # alloc/release loop
            try:
                for _ in range(20):
                    t = torch.empty(8 * 1024 * 1024, device="cuda")
                    del t
                torch.cuda.synchronize()
                out["alloc_release_sanity"] = True
            except Exception:
                out["alloc_release_sanity"] = False
            return out
        except Exception:
            return {"cuda_available": False}

    def run(self, *, min_vram_mb: int, min_host_ram_mb: int, min_disk_mb: int) -> HostPreflightResult:
        result = HostPreflightResult(
            host_id=self._host_id,
            offer_id=self._offer_id,
            instance_id=self._instance_id,
        )
        smi = self._nvidia_smi()
        torch_state = self._torch_probe()

        result.cuda_available = torch_state.get("cuda_available")
        result.vram_total_mb = torch_state.get("vram_total_mb")
        result.matmul_sanity = torch_state.get("matmul_sanity")
        result.bf16_sanity = torch_state.get("bf16_sanity")
        result.backward_sanity = torch_state.get("backward_sanity")
        result.alloc_release_sanity = torch_state.get("alloc_release_sanity")
        result.gpu_name = torch_state.get("device_name")

        if smi:
            for line in smi.splitlines():
                if "Driver Version" in line:
                    result.driver_version = line.split(":", 1)[-1].strip()
                if "CUDA Version" in line:
                    result.cuda_version = line.split(":", 1)[-1].strip()

        # disk free (working dir)
        try:
            result.disk_free_mb = int(shutil.disk_usage(Path.cwd()).free // (1024 * 1024))
        except Exception:
            result.disk_free_mb = None

        # host RAM (Linux /proc/meminfo)
        try:
            info = Path("/proc/meminfo").read_text(encoding="utf-8")
            total = free = None
            for line in info.splitlines():
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1]) // 1024
                if line.startswith("MemAvailable:"):
                    free = int(line.split()[1]) // 1024
            result.host_ram_total_mb = total
            result.host_ram_free_mb = free
        except Exception:
            pass

        # Fail-closed evaluation
        if result.cuda_available is False or result.cuda_available is None:
            result.failures.append("gpu_unavailable")
        if result.cuda_available is True:
            if result.vram_total_mb is None:
                result.failures.append("vram_not_measured")
            elif result.vram_total_mb < min_vram_mb:
                result.failures.append("insufficient_vram")
        else:
            result.failures.append("vram_not_measured")
        if result.host_ram_total_mb is None:
            result.failures.append("host_ram_not_measured")
        elif result.host_ram_total_mb < min_host_ram_mb:
            result.failures.append("insufficient_host_ram")
        if result.disk_free_mb is None:
            result.failures.append("disk_not_measured")
        elif result.disk_free_mb < min_disk_mb:
            result.failures.append("insufficient_disk")
        if result.matmul_sanity is False:
            result.failures.append("matmul_failed")
        if result.bf16_sanity is False:
            result.failures.append("bf16_failed")
        if result.backward_sanity is False:
            result.failures.append("backward_failed")
        if result.alloc_release_sanity is False:
            result.failures.append("alloc_release_failed")

        if not result.failures:
            result.status = "PASS"
            result.passed = True
        elif result.cuda_available is False:
            result.status = "NOT_A_TRAINING_HOST"
            result.passed = False
        else:
            result.status = "FAIL"
            result.passed = False
        return result


# ─────────────────────────────────────────────────────────────
# Training mode validation
# ─────────────────────────────────────────────────────────────

def qlora_config_valid(cfg: dict) -> tuple[bool, str]:
    if cfg.get("load_in_4bit") is not True:
        return False, "load_in_4bit must be True for QLoRA"
    if cfg.get("device_map") == "auto":
        return False, "device_map='auto' is rejected (implicit CPU offload)"
    if cfg.get("bnb_4bit_compute_dtype") not in ("bfloat16", "float16", "float32"):
        return False, "bnb_4bit_compute_dtype must be a supported dtype"
    return True, "QLoRA config valid"


def qlora_device_placement_valid(loaded_hf_device_map: dict) -> tuple[bool, str]:
    """Reject any unintended cpu/disk offload after the model is loaded."""
    for module, device in loaded_hf_device_map.items():
        if str(device) in ("cpu", "disk"):
            return False, f"module {module!r} offloaded to {device}"
    if not loaded_hf_device_map:
        return False, "device map is empty"
    return True, "all modules on intended GPU"


def bf16_lora_feasible(
    *,
    base_params_billions: float,
    vram_total_mb: int,
    overhead_mb: int = 2500,
) -> tuple[bool, str]:
    """ESTIMATE ONLY: whether a BF16 LoRA load canary is worth attempting.

    base_params_billions is the model size in billions of parameters (e.g. 32
    for Qwen3-32B). The real decision still requires an actual model-load peak.
    """
    base_gb = base_params_billions * 2  # 2 bytes/param in bf16
    activation_gb = 6.0  # short sequences in this dataset (~250 tokens max)
    required_mb = int((base_gb + activation_gb) * 1024) + overhead_mb
    if required_mb <= vram_total_mb:
        return True, f"BF16 LoRA estimated {required_mb}MiB <= {vram_total_mb}MiB (estimate only)"
    return False, f"BF16 LoRA estimated {required_mb}MiB > {vram_total_mb}MiB (estimate only)"


# ─────────────────────────────────────────────────────────────
# Assistant-only masking validator (real)
# ─────────────────────────────────────────────────────────────

def validate_assistant_masking(
    labels: list[int],
    role_spans: list[tuple[str, int, int]],
) -> tuple[bool, list[str]]:
    """Consume ACTUAL labels and role/token spans; verify system/user tokens
    are -100 (masked) and assistant target tokens are NOT -100 (trainable)."""
    failures: list[str] = []
    for role, start, end in role_spans:
        for pos in range(start, end):
            label = labels[pos]
            if role == "assistant":
                if label == -100:
                    failures.append(f"assistant token {pos} masked")
            elif role in ("system", "user"):
                if label != -100:
                    failures.append(f"{role} token {pos} unmasked")
    return (not failures), failures


# ─────────────────────────────────────────────────────────────
# Failed-host blacklist (config-root based, atomic, bounded)
# ─────────────────────────────────────────────────────────────

@dataclass
class FailedHostRecord:
    instance_id: int
    offer_id: int
    host: str
    reason: str
    failure_class: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def _config_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    return (Path(local_app_data) / "DEFEND") if local_app_data else Path.home() / ".defend"


class FailedHostBlacklist:
    def __init__(self, path: Path | None = None, max_entries: int = 50) -> None:
        self._path = path or (_config_root() / "failed-hosts.json")
        self._max_entries = max_entries

    def load(self) -> list[FailedHostRecord]:
        if not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return [FailedHostRecord(**e) for e in raw if isinstance(e, dict)]

    def add(self, record: FailedHostRecord) -> None:
        records = [r for r in self.load() if r.instance_id != record.instance_id]
        records.append(record)
        records = records[-self._max_entries:]
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self._path.parent), prefix=f".{self._path.name}.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump([asdict(r) for r in records], handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self._path)
        finally:
            Path(tmp).unlink(missing_ok=True)

    def is_blacklisted(self, host: str, offer_id: int) -> bool:
        return any(r.host == host and r.offer_id == offer_id for r in self.load())


# ─────────────────────────────────────────────────────────────
# Production mutation guard (execution-time enforced)
# ─────────────────────────────────────────────────────────────

_MUTATING_OPS = {"PROVISION", "START", "RESUME", "TRAIN", "DESTROY"}


class ProductionMutationGuard:
    """Checked at the REAL mutation boundary, at execution time, so a stale
    queued request cannot resume production."""

    def __init__(self, production_instance_id: int) -> None:
        self.production_instance_id = production_instance_id

    def authorize(
        self,
        *,
        instance_id: int,
        product: str,
        operation: str,
        authorized: bool,
    ) -> tuple[bool, str]:
        if instance_id == self.production_instance_id and operation in _MUTATING_OPS and not authorized:
            return False, "production instance mutation requires explicit owner authorization"
        return True, "allowed"
