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

    @classmethod
    def coder_default(cls) -> "LaunchSpec":
        """DEFENDcoder M0.1 launch — separate label from identity chat."""
        return cls(
            "vllm/vllm-openai:v0.10.0",
            160,
            "ssh_direc ssh_proxy",
            "defendcoder-vllm",
        )


@dataclass(frozen=True)
class ResourceProfile:
    """Configurable resource policy for Vast.ai instance selection.

    Defaults are intentionally higher than the original 80 GB A100/H100 floor
    so that H200 / B200-class cards are preferred while still accepting strong
    single-GPU offers. Single-GPU remains the default path.
    """

    min_gpu_ram_mb: int = 140_000
    allowed_gpu_families: tuple[str, ...] = ("A100", "H100", "H200", "B200")
    num_gpus: int = 1
    min_reliability: Decimal = Decimal("0.98")
    min_disk_gb: int = 160
    max_model_len: int = 8192

    @classmethod
    def coder_default(cls) -> "ResourceProfile":
        """Coder lane: single A100 80GB-class is acceptable (not 140GB chat floor)."""
        return cls(
            min_gpu_ram_mb=80_000,
            allowed_gpu_families=("A100", "H100", "H200", "B200"),
            num_gpus=1,
            min_reliability=Decimal("0.98"),
            min_disk_gb=160,
            max_model_len=8192,
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
