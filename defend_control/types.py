"""Compatibility shim: re-exports neutral compute/provider datatypes and
re-attaches the legacy product launch factory methods for old callers.

Canonical DEFEND AI code does NOT import this module; it uses
``defend_ai.launch`` and ``shared_platform.compute_types`` directly.
"""

from __future__ import annotations

from decimal import Decimal

from shared_platform.compute_types import (  # noqa: F401
    AdapterSpec,
    LaunchSpec,
    ModelMode,
    ModelReady,
    ResourceProfile,
    ServiceState,
    VastInstance,
    VastOffer,
)


def _production_default(cls):
    from defend_ai.launch import production_serving_launch

    return production_serving_launch()


def _candidate_canary(cls):
    from defend_ai.launch import candidate_canary_launch

    return candidate_canary_launch()


def _coder_default(cls):
    return cls("vllm/vllm-openai:v0.10.0", 160, "ssh_proxy", "defendcoder-vllm")


def _coder_heavy_direct(cls):
    return cls("vllm/vllm-openai:v0.10.0", 160, "ssh_direct", "defendcoder-vllm")


def _coder_resource_default(cls):
    return cls(
        min_gpu_ram_mb=80_000,
        allowed_gpu_families=("A100", "H100", "H200", "B200"),
        num_gpus=1,
        min_reliability=Decimal("0.98"),
        min_disk_gb=160,
        max_model_len=8192,
    )


LaunchSpec.default = classmethod(_production_default)
LaunchSpec.candidate_canary = classmethod(_candidate_canary)
LaunchSpec.coder_default = classmethod(_coder_default)
LaunchSpec.coder_heavy_direct = classmethod(_coder_heavy_direct)
ResourceProfile.coder_default = classmethod(_coder_resource_default)
