"""M1.8 tests: held-out eval, deployment profiles, templates, lease, Qwen3 candidate."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from defend_control.deployment_profiles import (
    DeploymentProfileRegistry,
    ProfileStatus,
    default_profiles,
    profile_adapter_base_compatible,
)
from defend_control.qwen3_candidate import (
    HELDOUT_EVAL_ROWS,
    HELDOUT_EVAL_SHA256,
    convert_sft_to_qwen3,
    heldout_evaluator_config,
    qwen3_qlora_config,
    validate_sft_row,
)
from defend_control.runtime_lease import RuntimeLeaseStore, RuntimeMutationConflict
from defend_control.vast_templates import (
    VastTemplateRegistry,
    default_templates,
    template_compatible_with_offer,
)

EVAL_PATH = Path(r"C:\Users\thoma\Downloads\DEFEND32B\DEFEND_EVAL_HELD_OUT_200.jsonl")


def _sample_sft_row() -> dict:
    return {
        "id": "defend_sft_v002_000001",
        "domain": "policy",
        "difficulty": "medium",
        "policy_version": "2026-08-13",
        "tool_schema_version": "1.0",
        "provenance": {"source": "synthetic_reviewed_repaired"},
        "messages": [
            {"role": "system", "content": "You are DEFEND AI. Follow the active policy."},
            {"role": "user", "content": "What did the Naturalization Act of 1790 say?"},
            {"role": "assistant", "content": "It limited naturalization to free White persons.", "tool_calls": [{"id": "t0"}]},
            {"role": "tool", "content": "result payload"},
        ],
    }


# ── 1-3 held-out eval path/count/hash ────────────────────────

def test_heldout_eval_path_exists_and_hash_and_count():
    assert EVAL_PATH.exists(), "held-out eval file missing"
    digest = hashlib.sha256(EVAL_PATH.read_bytes()).hexdigest()
    assert digest == HELDOUT_EVAL_SHA256
    count = 0
    for line in EVAL_PATH.open(encoding="utf-8"):
        if line.strip():
            count += 1
    assert count == HELDOUT_EVAL_ROWS == 200


def test_heldout_eval_constants_are_canonical():
    assert HELDOUT_EVAL_ROWS == 200
    assert len(HELDOUT_EVAL_SHA256) == 64


# ── 4-5 held-out exclusion + leakage ─────────────────────────

def test_manifest_marks_eval_excluded_and_leakage_zero():
    summary, _ = None, None
    rows, conversion = convert_sft_to_qwen3([_sample_sft_row()])
    manifest = __import__("defend_control.qwen3_candidate", fromlist=["build_training_manifest"]).build_training_manifest(
        conversion_summary=conversion, code_commit="test"
    )
    assert manifest["heldout_eval"]["excluded_from_training"] is True
    assert manifest["heldout_eval"]["sha256"] == HELDOUT_EVAL_SHA256
    assert manifest["heldout_eval"]["rows"] == 200
    assert manifest["validation"]["eval_exact_leakage"] == 0


def test_eval_hash_does_not_appear_in_synthetic_train_hashes():
    from defend_control.qwen3_candidate import normalize_row_hash

    train = {normalize_row_hash(_sample_sft_row())}
    assert HELDOUT_EVAL_SHA256 not in train


# ── 6-9 deployment profiles + independent guard ──────────────

def test_production_profile_resolves_immutable_qwen25_pair():
    profiles = default_profiles()
    prod = profiles["defend-ai-production-qwen25-v002"]
    assert prod.base_repo == "Qwen/Qwen2.5-32B-Instruct"
    assert prod.base_revision == "5ede1c97bbab6ce5cda5812749b4c0bdf79b18dd"
    assert prod.adapter_repo == "Defend-network/defend-identity-lora-v002"
    assert prod.adapter_revision == "46ade1686870210ef0ab4603c32fecb0e563330f"
    assert prod.status == ProfileStatus.PRODUCTION


def test_qwen3_candidate_profile_exists_not_trained():
    profiles = default_profiles()
    cand = profiles["defend-ai-candidate-qwen3-v001"]
    assert cand.base_repo == "Qwen/Qwen3-32B"
    assert cand.base_revision == "9216db5781bf21249d130ec9da846c4624c16137"
    assert cand.status == ProfileStatus.NOT_TRAINED


def test_qwen3_profile_rejects_qwen25_adapter():
    cand = default_profiles()["defend-ai-candidate-qwen3-v001"]
    ok, _ = profile_adapter_base_compatible(
        cand,
        adapter_base_model_name_or_path="Qwen/Qwen2.5-32B-Instruct",
        adapter_architecture="Qwen2ForCausalLM",
        profile_base_config={"model_type": "qwen3", "architectures": ["Qwen3ForCausalLM"]},
    )
    assert not ok


def test_qwen25_profile_rejects_qwen3_adapter_fixture():
    prod = default_profiles()["defend-ai-production-qwen25-v002"]
    ok, _ = profile_adapter_base_compatible(
        prod,
        adapter_base_model_name_or_path="Qwen/Qwen3-32B",
        adapter_architecture="Qwen3ForCausalLM",
        profile_base_config={"model_type": "qwen2", "architectures": ["Qwen2ForCausalLM"]},
    )
    assert not ok


def test_qwen25_profile_accepts_qwen25_adapter():
    prod = default_profiles()["defend-ai-production-qwen25-v002"]
    ok, _ = profile_adapter_base_compatible(
        prod,
        adapter_base_model_name_or_path="Qwen/Qwen2.5-32B-Instruct",
        adapter_architecture="Qwen2ForCausalLM",
        profile_base_config={"model_type": "qwen2", "architectures": ["Qwen2ForCausalLM"]},
    )
    assert ok


# ── 10-14 templates ───────────────────────────────────────────

def test_template_registry_has_no_secrets():
    raw = json.dumps(default_templates(), default=str)
    assert "HF_TOKEN" not in raw
    assert "VLLM_API_KEY" not in raw
    assert "Bearer " not in raw
    assert "-----BEGIN" not in raw


def test_template_version_identity_is_immutable():
    templates = default_templates()
    assert templates["defend-ai-prod-inference-a10080-v1"].version == "1"
    assert templates["defend-ai-prod-inference-a10080-v1"].template_name.startswith("defend-ai-prod-inference-a10080-v")


def test_production_template_min_vram_enforced():
    t = default_templates()["defend-ai-prod-inference-a10080-v1"]
    assert t.min_gpu_ram_gb == 80
    ok, _ = template_compatible_with_offer(
        t, offer_gpu_ram_mb=48 * 1024, offer_gpu_name="A100 PCIE", offer_reliability=0.99, offer_disk_gb=200, profile_min_vram_gb=80
    )
    assert not ok


def test_training_template_min_vram_enforced_and_offer_rejected_before_rental():
    t = default_templates()["defend-ai-qwen3-training-qlora-a10080-v1"]
    assert t.min_gpu_ram_gb == 80
    ok, _ = template_compatible_with_offer(
        t, offer_gpu_ram_mb=80 * 1024, offer_gpu_name="A100 PCIE", offer_reliability=0.99, offer_disk_gb=200, profile_min_vram_gb=80
    )
    assert ok
    ok2, _ = template_compatible_with_offer(
        t, offer_gpu_ram_mb=48 * 1024, offer_gpu_name="A100 PCIE", offer_reliability=0.99, offer_disk_gb=200, profile_min_vram_gb=80
    )
    assert not ok2


# ── 16-21 runtime lease ───────────────────────────────────────

def _lease_store(tmp_path, alive=()):
    return RuntimeLeaseStore(tmp_path / "lease.json", is_pid_alive=lambda pid: pid in alive)


def test_one_session_acquires_lease(tmp_path):
    store = _lease_store(tmp_path, alive=(111,))
    lease = store.acquire(product_id="defend-ai", provider="vast", instance_id=48416143,
                          owner_session_id="A", owner_pid=111, owner_worktree="wt", owner_branch="br",
                          purpose="RESUME")
    assert lease.operation_id
    assert store.status(product_id="defend-ai", provider="vast", instance_id=48416143)["owner_session_id"] == "A"


def test_second_session_cannot_mutate_same_instance(tmp_path):
    store = _lease_store(tmp_path, alive=(111,))
    store.acquire(product_id="defend-ai", provider="vast", instance_id=48416143,
                  owner_session_id="A", owner_pid=111, owner_worktree="wt", owner_branch="br", purpose="RESUME")
    with pytest.raises(RuntimeMutationConflict):
        store.acquire(product_id="defend-ai", provider="vast", instance_id=48416143,
                      owner_session_id="B", owner_pid=222, owner_worktree="wt", owner_branch="br", purpose="RESUME")


def test_second_session_can_read_status(tmp_path):
    store = _lease_store(tmp_path, alive=(111,))
    store.acquire(product_id="defend-ai", provider="vast", instance_id=48416143,
                  owner_session_id="A", owner_pid=111, owner_worktree="wt", owner_branch="br", purpose="RESUME")
    status = store.status(product_id="defend-ai", provider="vast", instance_id=48416143)
    assert status is not None
    assert status["owner_session_id"] == "A"


def test_heartbeat_preserves_active_lease(tmp_path):
    store = _lease_store(tmp_path, alive=(111,))
    store.acquire(product_id="defend-ai", provider="vast", instance_id=48416143,
                  owner_session_id="A", owner_pid=111, owner_worktree="wt", owner_branch="br", purpose="RESUME", ttl_seconds=3600)
    store.heartbeat(product_id="defend-ai", provider="vast", instance_id=48416143,
                    owner_session_id="A", ttl_seconds=3600)
    status = store.status(product_id="defend-ai", provider="vast", instance_id=48416143)
    assert status["owner_pid_alive"] is True
    assert status["expired"] is False


def test_expired_dead_lease_is_recoverable(tmp_path):
    from datetime import datetime, timedelta, timezone

    start = datetime.now(timezone.utc)
    times = {"now": start}

    def clock():
        return times["now"]

    store = RuntimeLeaseStore(tmp_path / "lease.json", is_pid_alive=lambda pid: False, clock=clock)
    store.acquire(product_id="defend-ai", provider="vast", instance_id=48416143,
                  owner_session_id="A", owner_pid=999, owner_worktree="wt", owner_branch="br",
                  purpose="RESUME", ttl_seconds=60)
    times["now"] = start + timedelta(seconds=120)  # expired + owner dead
    lease = store.acquire(product_id="defend-ai", provider="vast", instance_id=48416143,
                          owner_session_id="B", owner_pid=222, owner_worktree="wt", owner_branch="br", purpose="RESUME")
    assert lease.owner_session_id == "B"


def test_exact_m17_collision_regression(tmp_path):
    # Two sessions raced on instance 48416143 in M1.7; a live owner PID must
    # block the second mutator.
    store = _lease_store(tmp_path, alive=(1001,))
    store.acquire(product_id="defend-ai", provider="vast", instance_id=48416143,
                  owner_session_id="session-A", owner_pid=1001, owner_worktree="worktreeA",
                  owner_branch="platform/control-center-v2-integrate", purpose="RESUME")
    with pytest.raises(RuntimeMutationConflict):
        store.acquire(product_id="defend-ai", provider="vast", instance_id=48416143,
                      owner_session_id="session-B", owner_pid=1002, owner_worktree="worktreeB",
                      owner_branch="other", purpose="RESUME")


# ── 22-24 Qwen3 conversion ────────────────────────────────────

def test_qwen3_conversion_preserves_semantic_content():
    row = _sample_sft_row()
    out = __import__("defend_control.qwen3_candidate", fromlist=["convert_sft_row_to_qwen3"]).convert_sft_row_to_qwen3(row)
    original_contents = [(m["role"], m["content"]) for m in row["messages"]]
    new_contents = [(m["role"], m["content"]) for m in out["messages"]]
    assert new_contents == original_contents  # role+content preserved verbatim
    assert out["format_version"] == "qwen3-chat-tool-v1"
    assert any(m.get("tool_call_id") for m in out["messages"] if m["role"] == "tool")


def test_malformed_row_rejected():
    ok, _ = validate_sft_row({"messages": [{"role": "tool", "content": "x"}]})
    assert not ok
    ok2, _ = validate_sft_row({"messages": [{"role": "user", "content": "hi"}]})
    assert ok2


def test_qwen3_training_config_and_evaluator_ready():
    cfg = qwen3_qlora_config()
    assert cfg["method"] == "QLORA"
    assert cfg["base_revision"] == "9216db5781bf21249d130ec9da846c4624c16137"
    assert cfg["target_adapter"] == "Defend-network/defend-qwen3-32b-identity-lora-v001"
    evaluator = heldout_evaluator_config(code_commit="test")
    assert evaluator["eval_reference"]["rows"] == 200
    assert evaluator["baseline"]["status"] == "not_yet_captured"


def test_instance_48416143_is_stopped_retained_in_runtime_registry():
    from defend_control.product_runtime import ProductRuntimeRegistry

    registry = ProductRuntimeRegistry()
    record = registry.load()["defend-ai"]
    assert record.state == "stopped_retained"
    assert record.instance_id == 48416143
