"""DEFEND AI product-owned settings authority.

Control Center may READ these values; it never DEFINES them. There is no
fallback to Control Center settings for product runtime authority.

Port truth (verified against runtime evidence, not guessed):
  * DEFEND-AI product API  -> 8401  (dedicated product port; NOT the admin API)
  * DEFEND-AI UI/web       -> 3000
  * DEFEND-AI model forward-> 8402
The shared/admin API (8000) is Control Center's, not DEFEND-AI's.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from .model_registry import ADAPTER_REPO
from shared_platform.compute_types import ResourceProfile

PRODUCT_ID = "DEFEND_AI"
DISPLAY_NAME = "DEFEND AI"

API_PORT_DEFAULT = 8401
WEB_PORT_DEFAULT = 3000
MODEL_PORT_DEFAULT = 8402

_DEFAULT_GPU_FAMILIES = ("A100", "H100", "H200", "B200")
_MIN_GPU_RAM_FLOOR = 140_000


@dataclass(frozen=True)
class DefendAISettings:
    api_port: int
    web_port: int
    model_port: int
    data_root: str
    api_mode: str
    public_web_origin: str
    adapter_repo: str
    local_model: str
    vast_max_hourly: Decimal
    vllm_image: str
    vllm_disk_gb: int
    max_model_len: int
    min_gpu_ram_mb: int
    allowed_gpu_families: tuple[str, ...]

    def resource_profile(self) -> ResourceProfile:
        floor = max(self.min_gpu_ram_mb, _MIN_GPU_RAM_FLOOR)
        return ResourceProfile(
            min_gpu_ram_mb=floor,
            allowed_gpu_families=self.allowed_gpu_families,
            num_gpus=1,
            min_reliability=Decimal("0.98"),
            min_disk_gb=self.vllm_disk_gb,
            max_model_len=self.max_model_len,
        )


def _default_data_root() -> str:
    configured = os.getenv("DEFEND_DATA_ROOT", "").strip()
    if configured:
        return configured
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return str(Path(base) / "DEFEND" / "data")
    return str(Path.cwd() / ".defend-data")


def load_settings() -> DefendAISettings:
    return DefendAISettings(
        api_port=int(os.getenv("DEFEND_API_PORT", str(API_PORT_DEFAULT))),
        web_port=int(os.getenv("DEFEND_UI_PORT", str(WEB_PORT_DEFAULT))),
        model_port=int(os.getenv("DEFEND_MODEL_PORT", str(MODEL_PORT_DEFAULT))),
        data_root=_default_data_root(),
        api_mode=os.getenv("DEFEND_API_MODE", "defend-ai").strip().lower(),
        public_web_origin=os.getenv("DEFEND_PUBLIC_WEB_ORIGIN", "").strip(),
        adapter_repo=os.getenv("DEFEND_ADAPTER_REPO", ADAPTER_REPO).strip(),
        local_model=os.getenv("DEFEND_LOCAL_MODEL", "defend-identity-local").strip(),
        vast_max_hourly=Decimal(os.getenv("DEFEND_VAST_MAX_HOURLY", "0.60")),
        vllm_image=os.getenv("DEFEND_VLLM_IMAGE", "vllm/vllm-openai:v0.10.0").strip(),
        vllm_disk_gb=int(os.getenv("DEFEND_VLLM_DISK_GB", "160")),
        max_model_len=int(os.getenv("DEFEND_MAX_MODEL_LEN", "8192")),
        min_gpu_ram_mb=int(os.getenv("DEFEND_MIN_GPU_RAM_MB", str(_MIN_GPU_RAM_FLOOR))),
        allowed_gpu_families=tuple(
            f.strip()
            for f in os.getenv("DEFEND_ALLOWED_GPU_FAMILIES", ",".join(_DEFAULT_GPU_FAMILIES)).split(",")
            if f.strip()
        ),
    )
