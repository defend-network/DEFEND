"""Product-neutral compute/provider datatypes.

Owned by no product. Provider datatypes (Vast offer/instance), a generic launch
spec data structure, a generic resource profile, and generic service/model-state
literals live here. Product-specific launch/resource POLICY (factory methods such
as a candidate canary launch or a coder heavy launch) must NOT live here — those
belong to their products.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

ModelMode = Literal["vast", "ollama"]
ServiceState = Literal[
    "stopped",
    "validating",
    "provisioning",
    "starting",
    "ready",
    "degraded",
    "stopping",
    "failed",
]


@dataclass(frozen=True)
class ModelReady:
    model: str
    backend: str
    endpoint: str


@dataclass(frozen=True)
class AdapterSpec:
    adapter_repo: str
    adapter_revision: str
    base_repo: str
    base_revision: str
    peft_type: str
    lora_rank: int
    base_architecture: str | None = None


@dataclass(frozen=True)
class LaunchSpec:
    """Generic launch data structure. No product-specific factory methods."""

    image: str
    disk_gb: int
    runtype: str
    label: str


@dataclass(frozen=True)
class ResourceProfile:
    """Generic Vast resource policy data structure. No product factories."""

    min_gpu_ram_mb: int = 140_000
    allowed_gpu_families: tuple[str, ...] = ("A100", "H100", "H200", "B200")
    num_gpus: int = 1
    min_reliability: Decimal = Decimal("0.98")
    min_disk_gb: int = 160
    max_model_len: int = 8192
    min_cuda_max_good: float | None = None


@dataclass(frozen=True)
class VastOffer:
    offer_id: int
    gpu_name: str
    gpu_ram_mb: int
    dph_total: Decimal
    reliability: Decimal
    storage_cost_per_gb_month: Decimal | None = None
    storage_total_hourly: Decimal | None = None
    direct_port_count: int | None = None
    cuda_max_good: float | None = None


@dataclass(frozen=True)
class VastInstance:
    instance_id: int
    actual_status: str | None
    ssh_host: str | None
    ssh_port: int | None
    gpu_name: str
    gpu_ram_mb: int
    dph_total: Decimal
    machine_id: int | None = None
    direct_ssh_host: str | None = None
    direct_ssh_port: int | None = None
    image_runtype: str | None = None
