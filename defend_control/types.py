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


@dataclass(frozen=True)
class LaunchSpec:
    image: str
    disk_gb: int
    runtype: str
    label: str

    @classmethod
    def default(cls) -> "LaunchSpec":
        return cls(
            "vllm/vllm-openai:v0.10.0",
            160,
            "ssh_direc ssh_proxy",
            "defend-vllm",
        )


@dataclass(frozen=True)
class VastOffer:
    offer_id: int
    gpu_name: str
    gpu_ram_mb: int
    dph_total: Decimal
    reliability: Decimal
    storage_cost_per_gb_month: Decimal | None = None
    storage_total_hourly: Decimal | None = None


@dataclass(frozen=True)
class VastInstance:
    instance_id: int
    actual_status: str | None
    ssh_host: str | None
    ssh_port: int | None
    gpu_name: str
    gpu_ram_mb: int
    dph_total: Decimal
