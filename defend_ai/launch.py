"""DEFEND AI product-owned launch/resource policy.

Product-specific LaunchSpec/ResourceProfile factories live here (never on the
neutral shared dataclasses).
"""

from __future__ import annotations

from decimal import Decimal

from shared_platform.compute_types import LaunchSpec, ResourceProfile


def production_serving_launch() -> LaunchSpec:
    """DEFEND AI production serving launch (vLLM image, production label)."""
    return LaunchSpec("vllm/vllm-openai:v0.10.0", 160, "ssh_proxy", "defend-vllm")


def candidate_canary_launch() -> LaunchSpec:
    """DEFEND AI Qwen3 QLoRA training canary launch — isolated non-production label."""
    return LaunchSpec(
        "pytorch/pytorch:2.7.1-cuda12.8-cudnn9-devel",
        200,
        "ssh_proxy",
        "defend-ai-qwen3-candidate-canary",
    )


def candidate_canary_resource_profile() -> ResourceProfile:
    """A100 80GB-class only, single GPU canary policy."""
    return ResourceProfile(
        min_gpu_ram_mb=80_000,
        allowed_gpu_families=("A100",),
        num_gpus=1,
        min_reliability=Decimal("0.98"),
        min_disk_gb=200,
        max_model_len=8192,
    )
