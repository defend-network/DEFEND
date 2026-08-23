"""DEFENDcoder product launch/resource factory methods (product-owned).

These were previously monkeypatched onto the neutral shared dataclasses; they
now live here as plain functions so shared_platform stays product-neutral.
"""

from __future__ import annotations

from decimal import Decimal

from shared_platform.compute_types import LaunchSpec, ResourceProfile

_CODER_IMAGE = "vllm/vllm-openai:v0.10.0"
_CODER_LABEL = "defendcoder-vllm"


def coder_default_launch() -> LaunchSpec:
    return LaunchSpec(_CODER_IMAGE, 160, "ssh_proxy", _CODER_LABEL)


def coder_heavy_direct_launch() -> LaunchSpec:
    return LaunchSpec(_CODER_IMAGE, 160, "ssh_direct", _CODER_LABEL)


def coder_resource_default() -> ResourceProfile:
    return ResourceProfile(
        min_gpu_ram_mb=80_000,
        allowed_gpu_families=("A100", "H100", "H200", "B200"),
        num_gpus=1,
        min_reliability=Decimal("0.98"),
        min_disk_gb=160,
        max_model_len=8192,
    )
