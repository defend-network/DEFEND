"""Cross-architecture deployment guard: adapter base must match runtime base.

The current production DEFEND adapter (defend-identity-lora-v002) is trained
on Qwen/Qwen2.5-32B-Instruct. Loading it onto a Qwen3 runtime (or vice versa)
must fail closed before any GPU provisioning.
"""

from __future__ import annotations

from defend_control.huggingface import adapter_runtime_base_compatible


def _qwen25_runtime() -> dict:
    return {
        "model_type": "qwen2",
        "architectures": ["Qwen2ForCausalLM"],
    }


def _qwen3_runtime() -> dict:
    return {
        "model_type": "qwen3",
        "architectures": ["Qwen3ForCausalLM"],
    }


def test_qwen25_adapter_matches_qwen25_runtime():
    ok, reason = adapter_runtime_base_compatible(
        adapter_base_repo="Qwen/Qwen2.5-32B-Instruct",
        adapter_architecture="Qwen2ForCausalLM",
        runtime_base_config=_qwen25_runtime(),
    )
    assert ok
    assert "compatible" in reason


def test_qwen25_adapter_rejected_on_qwen3_runtime():
    ok, reason = adapter_runtime_base_compatible(
        adapter_base_repo="Qwen/Qwen2.5-32B-Instruct",
        adapter_architecture="Qwen2ForCausalLM",
        runtime_base_config=_qwen3_runtime(),
    )
    assert not ok
    assert "qwen2" in reason and "qwen3" in reason


def test_qwen3_adapter_rejected_on_qwen25_runtime():
    ok, reason = adapter_runtime_base_compatible(
        adapter_base_repo="Qwen/Qwen3-32B",
        adapter_architecture="Qwen3ForCausalLM",
        runtime_base_config=_qwen25_runtime(),
    )
    assert not ok
    assert "qwen3" in reason and "qwen2" in reason


def test_adapter_architecture_class_must_exist_in_runtime():
    # Contradictory adapter metadata (repo says Qwen2.5, auto_mapping class says
    # Qwen3) must fail closed; the family mismatch takes precedence.
    ok, reason = adapter_runtime_base_compatible(
        adapter_base_repo="Qwen/Qwen2.5-32B-Instruct",
        adapter_architecture="Qwen3ForCausalLM",
        runtime_base_config=_qwen25_runtime(),
    )
    assert not ok
    assert "qwen2" in reason and "qwen3" in reason


def test_current_production_adapter_resolves_to_qwen25_base():
    """CASE-B guard: the pinned current production adapter is Qwen2.5. This
    documents that a Qwen3 upgrade requires a NEW adapter trained on a Qwen3
    base and must never reuse the Qwen2.5 adapter."""
    from defend_control.model_registry import ADAPTER_REPO

    assert ADAPTER_REPO == "Defend-network/defend-identity-lora-v002"
