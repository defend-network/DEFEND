"""DEFEND AI product-owned launch/resource policy.

Product-specific LaunchSpec/ResourceProfile factories live here (never on the
neutral shared dataclasses).
"""

from __future__ import annotations

from decimal import Decimal

from shared_platform.compute_types import LaunchSpec, ResourceProfile

CANDIDATE_LABEL_PREFIX = "defend-ai-qwen3-canary"


def production_serving_launch() -> LaunchSpec:
    """DEFEND AI production serving launch (vLLM image, production label)."""
    return LaunchSpec("vllm/vllm-openai:v0.10.0", 160, "ssh_proxy", "defend-vllm")


def candidate_canary_launch(run_id: str = "") -> LaunchSpec:
    """DEFEND AI Qwen3 QLoRA training canary launch — direct SSH, non-production,
    run-scoped label derived from the trusted run_id."""
    from .canary_plan import run_candidate_label

    label = run_candidate_label(run_id) if run_id else CANDIDATE_LABEL_PREFIX
    return LaunchSpec(
        "pytorch/pytorch:2.7.1-cuda12.8-cudnn9-devel",
        200,
        "ssh_direct",
        label,
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
