"""M1.9.1C training-infrastructure hardening (zero paid compute).

Last-mile corrections on top of M1.9.1B:

- CUDA identity is truthful: GPU_DRIVER_VERSION, TORCH_VERSION, TORCH_CUDA_BUILD,
  CUDA_RUNTIME_VERSION (only where measurable) and CUDA_AVAILABLE are tracked
  separately. No invented nvidia-smi field. Required telemetry fails closed.
- GPU compute-process telemetry is explicit MEASURED / UNSUPPORTED / ERROR; an
  ERROR can no longer masquerade as "zero active processes".
- HF model-cache disk is mandatory: the real cache path is resolved
  (HF_HOME / HF_HUB_CACHE / TRANSFORMERS_CACHE / explicit cache_dir), created,
  and measured. Unknown/unmeasurable fails.
- Python version is an explicit policy (python_policy major.minor, or optional
  python_exact patch), never falsely labelled exact equality.
- env_lock_resolution is renamed/relabelled PYPI_METADATA_COMPATIBILITY (a
  useful zero-cost precheck, not a full resolver proof); host install remains
  final authority.
- Failed-host blacklist fails closed on corruption via immutable required
  campaign blocks, and add() is concurrency-safe.
- PaidCanaryReadiness is derived from real gates and reports READY_TO_RENT
  (not HOST_ALREADY_PASSED), requiring a non-empty pinned candidate revision.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

# ─────────────────────────────────────────────────────────────
# Training environment (exact, resolvable)
# ─────────────────────────────────────────────────────────────

TRAINING_ENV_PROFILE = "DEFEND_AI_QWEN3_TRAIN_ENV_V1"
TRAINING_ENV_PROFILE_V2 = "DEFEND_AI_QWEN3_TRAIN_ENV_V2"

#: Preflight policy governing required host telemetry.
PREFLIGHT_POLICY_VERSION = "DEFEND_AI_PREFLIGHT_POLICY_V2"


@dataclass(frozen=True)
class TrainingEnvironmentSpec:
    profile_id: str = TRAINING_ENV_PROFILE
    python_policy: str = "3.12"          # major.minor compatibility policy
    python_exact: str | None = None       # optional exact patch override
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
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode("utf-8")).hexdigest()


def training_env_v2() -> TrainingEnvironmentSpec:
    """V2 fixes V1's unresolvable pins:
    - safetensors 0.6.0 does not exist; transformers 5.15.1 requires >=0.8.0.
    - transformers 5.15.1 requires huggingface-hub<2.0,>=1.5.0, but tokenizers
      0.22.0 requires huggingface-hub<1.0 (unresolvable together); tokenizers
      0.22.1 widens to <2.0. V1 is preserved, not mutated."""
    return TrainingEnvironmentSpec(
        profile_id=TRAINING_ENV_PROFILE_V2,
        safetensors="0.8.0",
        huggingface_hub="1.28.0",
        tokenizers="0.22.1",
    )


def _version_components(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", version.split("+")[0]))


def _exact_eq(actual: str, expected: str) -> bool:
    return _version_components(actual) == _version_components(expected)


def parse_torch_build(torch_version: str) -> tuple[str, str | None]:
    """Split '2.7.1+cu128' into (version '2.7.1', cuda 'cu128')."""
    if "+" in torch_version:
        base, suffix = torch_version.split("+", 1)
        return base, suffix
    return torch_version, None


def python_policy_accepts(spec: TrainingEnvironmentSpec, major: int, minor: int, patch: int) -> tuple[bool, str]:
    if spec.python_exact:
        exp = _version_components(spec.python_exact)
        actual = (major, minor, patch)
        if len(exp) >= 3:
            return actual[:3] == exp[:3], f"expected exact {spec.python_exact}, got {major}.{minor}.{patch}"
        return actual[:len(exp)] == exp, f"expected exact {spec.python_exact}, got {major}.{minor}.{patch}"
    pol = _version_components(spec.python_policy)
    if len(pol) >= 2:
        return (major, minor) == (pol[0], pol[1]), f"policy {spec.python_policy} (actual patch {patch} recorded)"
    return False, f"invalid python_policy {spec.python_policy!r}"


def _installed_version(dist: str) -> str | None:
    try:
        return importlib.metadata.version(dist)
    except importlib.metadata.PackageNotFoundError:
        return None


def validate_training_environment(spec: TrainingEnvironmentSpec) -> tuple[bool, dict[str, str]]:
    mismatches: dict[str, str] = {}

    py_ok, py_msg = python_policy_accepts(spec, sys.version_info.major, sys.version_info.minor, sys.version_info.micro)
    if not py_ok:
        mismatches["python_policy"] = py_msg

    torch_v = _installed_version("torch")
    if torch_v is None:
        mismatches["torch"] = "MISSING"
    else:
        base, cuda = parse_torch_build(torch_v)
        if not _exact_eq(base, spec.torch):
            mismatches["torch"] = f"expected {spec.torch}, got {base}"
        if cuda != spec.cuda_runtime:
            mismatches["cuda_runtime"] = f"expected {spec.cuda_runtime}, got {cuda or 'none'}"

    exact_pkgs = {
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
    for dist, want in exact_pkgs.items():
        have = _installed_version(dist)
        if have is None:
            mismatches[dist] = "MISSING"
        elif not _exact_eq(have, want):
            mismatches[dist] = f"expected {want}, got {have}"

    return (not mismatches), mismatches


def torch_cuda_build_validated(spec: TrainingEnvironmentSpec) -> tuple[bool, str]:
    torch_v = _installed_version("torch")
    if torch_v is None:
        return False, "torch not installed"
    base, cuda = parse_torch_build(torch_v)
    if cuda != spec.cuda_runtime:
        return False, f"torch build cuda {cuda!r} != expected {spec.cuda_runtime!r}"
    return True, f"torch {base} built for {cuda}"


# ─────────────────────────────────────────────────────────────
# Dependency compatibility (PYPI metadata precheck — not a full resolver)
# ─────────────────────────────────────────────────────────────

def _normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.lower())


def _spec_satisfies(version: str, spec: str) -> bool:
    v = _version_components(version)
    for part in spec.split(","):
        part = part.strip()
        m = re.match(r"(>=|<=|==|!=|>|<)\s*([0-9][0-9.]*)", part)
        if not m:
            continue
        op, target = m.group(1), _version_components(m.group(2))
        if op == ">=" and not v >= target:
            return False
        if op == "<=" and not v <= target:
            return False
        if op == "==" and v != target:
            return False
        if op == "!=" and v == target:
            return False
        if op == ">" and not v > target:
            return False
        if op == "<" and not v < target:
            return False
    return True


def _pypi_package_info(name: str, version: str) -> tuple[bool, list[str]]:
    """(exact version exists, requires_dist). Network read, zero-cost."""
    import urllib.request

    try:
        with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{version}/json", timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return True, data.get("info", {}).get("requires_dist") or []
    except Exception:
        return False, []


@dataclass(frozen=True)
class PyPIMetadataCompatibility:
    kind: str = "PYPI_METADATA_COMPATIBILITY"
    status: str = "PASS"  # PASS | FAIL
    missing: list[str] = field(default_factory=list)
    incompatible: list[str] = field(default_factory=list)


def pypi_metadata_compatibility(spec: TrainingEnvironmentSpec, package_info=None) -> PyPIMetadataCompatibility:
    """Zero-cost precheck only: direct base-requirement compatibility against
    PyPI metadata. It skips environment-marked/extras and transitive deps, so it
    is NOT a full resolver proof (FULL_RESOLVER_PROOF=NO; host install is final
    authority)."""
    package_info = package_info or _pypi_package_info
    pins = {
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
    pins_norm = {_normalize_name(k): (k, v) for k, v in pins.items()}
    missing: list[str] = []
    incompatible: list[str] = []
    for name, ver in pins.items():
        exists, requires = package_info(name, ver)
        if not exists:
            missing.append(f"{name}=={ver}")
            continue
        for req_str in requires:
            if ";" in req_str:
                continue  # extra / environment-marked, not a base dependency
            m = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)", req_str)
            if not m:
                continue
            req_name = _normalize_name(m.group(1))
            spec_part = req_str[m.end():].strip()
            if req_name in pins_norm:
                pinned_key, pinned_ver = pins_norm[req_name]
                if not _spec_satisfies(pinned_ver, spec_part):
                    incompatible.append(f"{name} {req_str} conflicts with {pinned_key}=={pinned_ver}")
    status = "PASS" if not missing and not incompatible else "FAIL"
    return PyPIMetadataCompatibility(status=status, missing=missing, incompatible=incompatible)


#: Backward-compatible alias (M1.9.1B name).
env_lock_resolution = pypi_metadata_compatibility

#: No full pip dry-run resolver proof is claimed here.
FULL_RESOLVER_PROOF = False
HOST_INSTALL_REQUIRED = True


# ─────────────────────────────────────────────────────────────
# Host preflight (executable, fail-closed, truthful CUDA telemetry)
# ─────────────────────────────────────────────────────────────

GPU_PROCESS_MEASURED = "MEASURED"
GPU_PROCESS_UNSUPPORTED = "UNSUPPORTED"
GPU_PROCESS_ERROR = "ERROR"


@dataclass
class HostPreflightResult:
    gpu_name: str | None = None
    vram_total_mb: int | None = None
    vram_free_mb: int | None = None
    vram_used_mb: int | None = None
    free_vram_percent: float | None = None
    driver_version: str | None = None
    torch_version: str | None = None
    torch_cuda_build: str | None = None
    cuda_runtime_version: str | None = None
    cuda_available: bool | None = None
    gpu_temperature_c: int | None = None
    ecc_mode: str | None = None
    gpu_process_telemetry_status: str = "INCOMPLETE"
    active_gpu_processes: list[dict] = field(default_factory=list)
    host_ram_total_mb: int | None = None
    host_ram_available_mb: int | None = None
    work_disk_free_mb: int | None = None
    hf_cache_path: str | None = None
    hf_cache_path_resolved: bool = False
    hf_cache_disk_free_mb: int | None = None
    matmul_sanity: bool | None = None
    bf16_sanity: bool | None = None
    backward_sanity: bool | None = None
    alloc_release_sanity: bool | None = None
    alloc_release_detail: str | None = None
    host_id: str | None = None
    offer_id: int | None = None
    instance_id: int | None = None
    passed: bool | None = None
    status: str = "INCOMPLETE"
    failures: list[str] = field(default_factory=list)

    def as_public_dict(self) -> dict[str, object]:
        return asdict(self)


def _parse_nvidia_query(csv: str) -> dict[str, str | None]:
    """Parse nvidia-smi --query-gpu=... --format=csv,noheader (fixed column order)."""
    line = next((l for l in csv.strip().splitlines() if l.strip()), None)
    if not line:
        return {}
    keys = ["name", "memory.total", "memory.free", "memory.used", "driver_version", "temperature.gpu", "ecc.mode.current"]
    values = [v.strip() for v in line.split(",")]
    return dict(zip(keys, values))


def _parse_compute_processes(csv: str) -> list[dict]:
    out = []
    for line in csv.strip().splitlines():
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 3:
            out.append({"pid": parts[0], "name": parts[1], "used_mb": parts[2]})
    return out


def resolve_hf_cache_path(cache_dir: str | None = None) -> str | None:
    """Resolve the exact HF model-cache path that download/load will use."""
    if cache_dir:
        candidate = cache_dir
    else:
        candidate = (
            os.environ.get("HF_HUB_CACHE")
            or os.environ.get("TRANSFORMERS_CACHE")
            or os.environ.get("HUGGINGFACE_HUB_CACHE")
            or (os.path.join(os.environ["HF_HOME"], "hub") if os.environ.get("HF_HOME") else None)
            or os.path.join(str(Path.home()), ".cache", "huggingface", "hub")
        )
    try:
        path = Path(candidate).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        return str(path)
    except Exception:
        return None


class HostPreflightRunner:
    def __init__(
        self,
        *,
        nvidia_query: Callable[[], str] | None = None,
        nvidia_processes: Callable[[], tuple[str, str]] | None = None,
        torch_probe: Callable[[], dict] | None = None,
        meminfo: Callable[[], str] | None = None,
        disk_usage: Callable[[str], int] | None = None,
        host_id: str | None = None,
        offer_id: int | None = None,
        instance_id: int | None = None,
    ) -> None:
        self._nvidia_query = nvidia_query or self._default_nvidia_query
        self._nvidia_processes = nvidia_processes or self._default_nvidia_processes
        self._torch_probe = torch_probe or self._default_torch_probe
        self._meminfo = meminfo or self._default_meminfo
        self._disk_usage = disk_usage or self._default_disk_usage
        self._host_id = host_id
        self._offer_id = offer_id
        self._instance_id = instance_id

    @staticmethod
    def _default_nvidia_query() -> str:
        if shutil.which("nvidia-smi") is None:
            return ""
        try:
            return subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total,memory.free,memory.used,driver_version,temperature.gpu,ecc.mode.current",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=30,
            ).stdout
        except Exception:
            return ""

    @staticmethod
    def _default_nvidia_processes() -> tuple[str, str]:
        if shutil.which("nvidia-smi") is None:
            return (GPU_PROCESS_UNSUPPORTED, "")
        try:
            proc = subprocess.run(
                ["nvidia-smi", "--query-compute-apps=pid,process_name,used_gpu_memory", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=30,
            )
        except Exception:
            return (GPU_PROCESS_ERROR, "")
        if proc.returncode != 0:
            return (GPU_PROCESS_ERROR, "")
        return (GPU_PROCESS_MEASURED, proc.stdout)

    @staticmethod
    def _default_meminfo() -> str:
        try:
            return Path("/proc/meminfo").read_text(encoding="utf-8")
        except Exception:
            return ""

    @staticmethod
    def _default_disk_usage(path: str) -> int:
        try:
            return int(shutil.disk_usage(path).free // (1024 * 1024))
        except Exception:
            return -1

    @staticmethod
    def _default_torch_probe() -> dict:
        try:
            import torch

            out = {
                "cuda_available": torch.cuda.is_available(),
                "torch_version": torch.__version__,
                "torch_cuda_build": torch.version.cuda,
            }
            if not out["cuda_available"]:
                return out
            out["device_name"] = torch.cuda.get_device_name(0)
            out["vram_total_mb"] = int(torch.cuda.get_device_properties(0).total_memory // (1024 * 1024))
            a = torch.randn(256, 256, device="cuda")
            b = torch.randn(256, 256, device="cuda")
            c = a @ b
            torch.cuda.synchronize()
            out["matmul_sanity"] = bool(c.isfinite().all().item())
            try:
                x = torch.randn(64, 64, device="cuda", dtype=torch.bfloat16)
                out["bf16_sanity"] = bool((x @ x).float().isfinite().all().item())
            except Exception:
                out["bf16_sanity"] = False
            try:
                w = torch.randn(32, 32, device="cuda", requires_grad=True)
                (w.sum() ** 2).backward()
                out["backward_sanity"] = w.grad is not None
            except Exception:
                out["backward_sanity"] = False
            try:
                before_alloc = torch.cuda.memory_allocated()
                for _ in range(20):
                    t = torch.empty(8 * 1024 * 1024, device="cuda")
                    del t
                torch.cuda.synchronize()
                after_alloc = torch.cuda.memory_allocated()
                retained = after_alloc - before_alloc
                out["alloc_release_sanity"] = retained < (8 * 1024 * 1024)
                out["alloc_release_detail"] = f"retained_bytes={retained}"
            except Exception:
                out["alloc_release_sanity"] = False
            return out
        except Exception:
            return {"cuda_available": False, "torch_version": None, "torch_cuda_build": None}

    def run(
        self,
        *,
        min_vram_mb: int,
        min_free_vram_mb: int,
        min_host_ram_mb: int,
        min_disk_mb: int,
        hf_cache_path: str | None = None,
        allow_unexpected_process: bool = False,
    ) -> HostPreflightResult:
        result = HostPreflightResult(host_id=self._host_id, offer_id=self._offer_id, instance_id=self._instance_id)
        query = _parse_nvidia_query(self._nvidia_query())
        try:
            proc_status, proc_csv = self._nvidia_processes()
        except Exception:
            proc_status, proc_csv = GPU_PROCESS_ERROR, ""
        torch_state = self._torch_probe()

        result.gpu_name = query.get("name") or torch_state.get("device_name")
        result.vram_total_mb = _int_or_none(query.get("memory.total")) or torch_state.get("vram_total_mb")
        result.vram_free_mb = _int_or_none(query.get("memory.free"))
        result.vram_used_mb = _int_or_none(query.get("memory.used"))
        result.driver_version = query.get("driver_version") or None
        result.torch_version = torch_state.get("torch_version")
        result.torch_cuda_build = torch_state.get("torch_cuda_build")
        result.cuda_runtime_version = torch_state.get("cuda_runtime_version")
        result.cuda_available = torch_state.get("cuda_available")
        result.gpu_temperature_c = _int_or_none(query.get("temperature.gpu"))
        result.ecc_mode = query.get("ecc.mode.current")
        result.gpu_process_telemetry_status = proc_status
        result.active_gpu_processes = _parse_compute_processes(proc_csv) if proc_status == GPU_PROCESS_MEASURED else []
        result.matmul_sanity = torch_state.get("matmul_sanity")
        result.bf16_sanity = torch_state.get("bf16_sanity")
        result.backward_sanity = torch_state.get("backward_sanity")
        result.alloc_release_sanity = torch_state.get("alloc_release_sanity")
        result.alloc_release_detail = torch_state.get("alloc_release_detail")

        if result.vram_total_mb and result.vram_free_mb is not None:
            result.free_vram_percent = round(result.vram_free_mb / result.vram_total_mb * 100, 1)

        meminfo = self._meminfo()
        for line in meminfo.splitlines():
            if line.startswith("MemTotal:"):
                result.host_ram_total_mb = int(line.split()[1]) // 1024
            if line.startswith("MemAvailable:"):
                result.host_ram_available_mb = int(line.split()[1]) // 1024

        result.work_disk_free_mb = self._disk_usage(os.getcwd())

        resolved_cache = resolve_hf_cache_path(hf_cache_path)
        if resolved_cache is None:
            result.failures.append("hf_cache_path_unresolved")
        else:
            result.hf_cache_path = resolved_cache
            result.hf_cache_path_resolved = True
            free_mb = self._disk_usage(resolved_cache)
            result.hf_cache_disk_free_mb = free_mb
            if free_mb < 0:
                result.failures.append("hf_cache_disk_not_measured")
            elif free_mb < min_disk_mb:
                result.failures.append("insufficient_hf_cache_disk")

        # Required CUDA/driver identity (fail closed).
        if result.cuda_available is not True:
            result.failures.append("gpu_unavailable")
        if result.driver_version is None:
            result.failures.append("driver_version_not_measured")
        if result.torch_version is None:
            result.failures.append("torch_version_not_measured")
        if result.torch_cuda_build is None:
            result.failures.append("torch_cuda_build_not_measured")

        # GPU process telemetry (fail closed on non-MEASURED).
        if proc_status != GPU_PROCESS_MEASURED:
            result.failures.append(f"gpu_process_telemetry_{proc_status.lower()}")
        elif not allow_unexpected_process:
            for proc in result.active_gpu_processes:
                if int(_int_or_none(proc.get("used_mb")) or 0) > 512:
                    result.failures.append(f"unexpected_gpu_process_pid_{proc.get('pid')}")
                    break

        if result.vram_total_mb is None:
            result.failures.append("vram_total_not_measured")
        elif result.vram_total_mb < min_vram_mb:
            result.failures.append("insufficient_vram_total")
        if result.vram_free_mb is None:
            result.failures.append("vram_free_not_measured")
        elif result.vram_free_mb < min_free_vram_mb:
            result.failures.append("insufficient_free_vram")
        if result.host_ram_available_mb is None:
            result.failures.append("host_ram_available_not_measured")
        elif result.host_ram_available_mb < min_host_ram_mb:
            result.failures.append("insufficient_host_ram_available")
        if result.work_disk_free_mb is None or result.work_disk_free_mb < 0:
            result.failures.append("work_disk_not_measured")
        elif result.work_disk_free_mb < min_disk_mb:
            result.failures.append("insufficient_work_disk")
        if result.matmul_sanity is False:
            result.failures.append("matmul_failed")
        if result.bf16_sanity is False:
            result.failures.append("bf16_failed")
        if result.backward_sanity is False:
            result.failures.append("backward_failed")
        if result.alloc_release_sanity is False:
            result.failures.append("alloc_release_retention")

        if not result.failures:
            result.status = "PASS"
            result.passed = True
        elif result.cuda_available is not True:
            result.status = "NOT_A_TRAINING_HOST"
            result.passed = False
        elif any("unexpected_gpu_process" in f for f in result.failures):
            result.status = "HOST_OCCUPIED"
            result.passed = False
        else:
            result.status = "FAIL"
            result.passed = False
        return result


def _int_or_none(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


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
    for module, device in loaded_hf_device_map.items():
        if str(device) in ("cpu", "disk"):
            return False, f"module {module!r} offloaded to {device}"
    if not loaded_hf_device_map:
        return False, "device map is empty"
    return True, "all modules on intended GPU"


def bf16_lora_feasible(*, base_params_billions: float, vram_total_mb: int, overhead_mb: int = 2500) -> tuple[bool, str]:
    base_gb = base_params_billions * 2
    activation_gb = 6.0
    required_mb = int((base_gb + activation_gb) * 1024) + overhead_mb
    if required_mb <= vram_total_mb:
        return True, f"BF16 LoRA estimated {required_mb}MiB <= {vram_total_mb}MiB (estimate only)"
    return False, f"BF16 LoRA estimated {required_mb}MiB > {vram_total_mb}MiB (estimate only)"


# ─────────────────────────────────────────────────────────────
# Assistant-only masking validator (defensive)
# ─────────────────────────────────────────────────────────────

class MaskValidationError(ValueError):
    pass


#: Roles the assistant-only masking pipeline must handle. ``assistant`` is the
#: sole trainable role; every other role (including tool results) must be masked.
TRAINABLE_ROLES = ("assistant",)
NON_TRAINABLE_ROLES = ("system", "user", "tool")
SUPPORTED_MASKING_ROLES = TRAINABLE_ROLES + NON_TRAINABLE_ROLES


def validate_assistant_masking(labels: list[int], role_spans: list[tuple[str, int, int]]) -> tuple[bool, list[str]]:
    if not isinstance(labels, list) or not labels:
        raise MaskValidationError("labels must be a non-empty list")
    if not role_spans:
        raise MaskValidationError("role_spans must be non-empty")
    failures: list[str] = []
    covered: set[int] = set()
    assistant_trainable = 0
    for role, start, end in role_spans:
        if role not in SUPPORTED_MASKING_ROLES:
            raise MaskValidationError(f"unsupported role {role!r}")
        if not (isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(labels)):
            raise MaskValidationError(f"span {role}[{start}:{end}] out of bounds for labels length {len(labels)}")
        if covered & set(range(start, end)):
            raise MaskValidationError(f"span {role}[{start}:{end}] overlaps another span")
        covered.update(range(start, end))
        for pos in range(start, end):
            label = labels[pos]
            if role == "assistant":
                if label == -100:
                    failures.append(f"assistant token {pos} masked")
                else:
                    assistant_trainable += 1
            elif label != -100:
                failures.append(f"{role} token {pos} unmasked")
    if assistant_trainable == 0:
        failures.append("no assistant trainable tokens")
    return (not failures), failures


# ─────────────────────────────────────────────────────────────
# Failed-host blacklist (scoped, atomic, bounded, expiring, fail-closed)
# ─────────────────────────────────────────────────────────────

@dataclass
class FailedHostRecord:
    scope: str  # "instance" | "offer" | "host"
    identifier: str
    reason: str
    failure_class: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: str | None = None
    source_run: str | None = None


def _config_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    return (Path(local_app_data) / "DEFEND") if local_app_data else Path.home() / ".defend"


def required_campaign_blocks() -> list[FailedHostRecord]:
    """Immutable safety exclusions for this candidate-training campaign."""
    return [
        FailedHostRecord("instance", "48423466", "M1.9 canary failure", "HOST_FAILURE"),
        FailedHostRecord("offer", "21050987", "M1.9 canary failure", "HOST_FAILURE"),
        FailedHostRecord("host", "ssh3.vast.ai", "M1.9 canary failure", "HOST_FAILURE"),
    ]


class FailedHostBlacklist:
    def __init__(
        self,
        path: Path | None = None,
        max_entries: int = 200,
        required_blocks: list[FailedHostRecord] | None = None,
    ) -> None:
        self._path = path or (_config_root() / "failed-hosts.json")
        self._max_entries = max_entries
        self._required_blocks = required_blocks if required_blocks is not None else required_campaign_blocks()
        self._lock = threading.Lock()

    def load(self) -> list[FailedHostRecord]:
        if not self._path.exists():
            return list(self._required_blocks)
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return list(self._required_blocks)
        now = datetime.now(timezone.utc)
        active: list[FailedHostRecord] = []
        for e in raw:
            if not isinstance(e, dict):
                continue
            try:
                rec = FailedHostRecord(**e)
            except TypeError:
                continue
            if rec.expires_at:
                try:
                    if datetime.fromisoformat(rec.expires_at) <= now:
                        continue
                except ValueError:
                    continue
            active.append(rec)
        return active + list(self._required_blocks)

    def add(self, record: FailedHostRecord) -> None:
        with self._lock:
            records = [r for r in self.load() if not (r.scope == record.scope and r.identifier == record.identifier)]
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

    def is_blocked(self, *, instance_id: int | None = None, offer_id: int | None = None, host: str | None = None) -> bool:
        for r in self.load():
            if r.scope == "instance" and instance_id is not None and r.identifier == str(instance_id):
                return True
            if r.scope == "offer" and offer_id is not None and r.identifier == str(offer_id):
                return True
            if r.scope == "host" and host is not None and r.identifier == host:
                return True
        return False


# ─────────────────────────────────────────────────────────────
# Production mutation guard
# ─────────────────────────────────────────────────────────────

_MUTATING_OPS = {"PROVISION", "START", "RESUME", "TRAIN", "DESTROY"}


class ProductionMutationGuard:
    def __init__(self, production_instance_id: int) -> None:
        self.production_instance_id = production_instance_id

    def authorize(self, *, instance_id: int, product: str, operation: str, authorized: bool) -> tuple[bool, str]:
        if instance_id == self.production_instance_id and operation in _MUTATING_OPS and not authorized:
            return False, "production instance mutation requires explicit owner authorization"
        return True, "allowed"


# ─────────────────────────────────────────────────────────────
# Paid-canary readiness (derived from real gates)
# ─────────────────────────────────────────────────────────────

REQUIRED_PREFLIGHT_TELEMETRY = (
    "driver_version",
    "torch_version",
    "torch_cuda_build",
    "cuda_available",
    "vram_total",
    "vram_free",
    "gpu_processes_measured",
    "host_ram_available",
    "hf_cache_disk",
)


@dataclass(frozen=True)
class PaidCanaryReadiness:
    clean_branch_head: str
    train_dataset_sha: str
    heldout_sha: str
    evaluator_version: str
    evaluator_code_sha: str
    training_env_profile: str
    training_env_hash: str
    metadata_compatibility: str
    candidate_base_repo: str
    candidate_base_revision: str
    adapter_repo: str
    production_instance_id: int
    failed_instance_block: str
    failed_offer_block: str
    failed_host_block: str
    production_mutation_guard_configured: bool
    preflight_policy_version: str
    required_preflight_telemetry: tuple[str, ...]
    expected_gpu_class: str
    max_hourly_rate: str

    @property
    def ready_to_rent(self) -> bool:
        return bool(
            self.clean_branch_head
            and self.train_dataset_sha
            and self.heldout_sha
            and self.evaluator_version
            and self.evaluator_code_sha
            and self.training_env_profile
            and self.training_env_hash
            and self.metadata_compatibility == "PASS"
            and self.candidate_base_repo
            and self.candidate_base_revision
            and self.adapter_repo
            and self.failed_instance_block
            and self.failed_offer_block
            and self.failed_host_block
            and self.production_mutation_guard_configured
            and bool(self.preflight_policy_version)
            and bool(self.required_preflight_telemetry)
        )


def _canonical_candidate_base() -> tuple[str, str]:
    from .deployment_profiles import default_profiles

    profile = default_profiles().get("defend-ai-candidate-qwen3-v001")
    if profile is None:
        return "Qwen/Qwen3-32B", ""
    return profile.base_repo, profile.base_revision


def build_paid_canary_readiness(
    clean_branch_head: str,
    metadata_compatibility: str = "PASS",
    production_mutation_guard_configured: bool = True,
) -> PaidCanaryReadiness:
    from .eval_runner_v2 import EVAL_DATASET_SHA, EVALUATOR_VERSION, evaluator_code_sha

    candidate_repo, candidate_revision = _canonical_candidate_base()
    return PaidCanaryReadiness(
        clean_branch_head=clean_branch_head,
        train_dataset_sha="d59b05ee323dc6d8bda8086c2aa3f9589acb8eae883afb173095f53117e1e854",
        heldout_sha=EVAL_DATASET_SHA,
        evaluator_version=EVALUATOR_VERSION,
        evaluator_code_sha=evaluator_code_sha(),
        training_env_profile=TRAINING_ENV_PROFILE_V2,
        training_env_hash=training_env_v2().env_hash(),
        metadata_compatibility=metadata_compatibility,
        candidate_base_repo=candidate_repo,
        candidate_base_revision=candidate_revision,
        adapter_repo="Defend-network/defend-qwen3-32b-identity-lora-v001",
        production_instance_id=48416143,
        failed_instance_block="48423466",
        failed_offer_block="21050987",
        failed_host_block="ssh3.vast.ai",
        production_mutation_guard_configured=production_mutation_guard_configured,
        preflight_policy_version=PREFLIGHT_POLICY_VERSION,
        required_preflight_telemetry=REQUIRED_PREFLIGHT_TELEMETRY,
        expected_gpu_class="A100 80GB",
        max_hourly_rate="$1.20/hr",
    )
