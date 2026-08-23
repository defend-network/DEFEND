"""M1.9.1B final pre-compute tests: eval episodes, exact env, host preflight,
scoped blacklist, real-path mutation guard, defensive masking."""

from __future__ import annotations

import pytest

from defend_control.eval_runner_v2 import (
    EPISODE_DIRECT,
    EPISODE_TOOL,
    EPISODE_RECOVERY,
    EPISODE_UNSCORABLE,
    EvalModelResult,
    derive_episode,
    evaluate_episode,
)
from defend_control.training_hardening import (
    FailedHostBlacklist,
    FailedHostRecord,
    HostPreflightRunner,
    MaskValidationError,
    ProductionMutationGuard,
    TrainingEnvironmentSpec,
    bf16_lora_feasible,
    build_paid_canary_readiness,
    parse_torch_build,
    qlora_config_valid,
    qlora_device_placement_valid,
    torch_cuda_build_validated,
    validate_assistant_masking,
    validate_training_environment,
)


# ── Episode model ────────────────────────────────────────────

def _tool_trajectory_row() -> dict:
    return {
        "id": "tool1",
        "domain": "general",
        "difficulty": "hard",
        "messages": [
            {"role": "system", "content": "You are DEFEND AI."},
            {"role": "user", "content": "Compute 17*23."},
            {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "calculator.evaluate", "arguments": "{\"expression\": \"17*23\"}"}}]},
            {"role": "tool", "content": "391"},
            {"role": "assistant", "content": "17 times 23 is 391."},
        ],
    }


def test_tool_episode_input_stops_before_expected_tool_sequence():
    ep = derive_episode(_tool_trajectory_row())
    assert ep.episode_type == EPISODE_TOOL
    # prefix ends at the user turn, BEFORE the assistant tool call.
    assert ep.prefix_messages[-1]["role"] == "user"
    assert all(m.get("role") != "assistant" for m in ep.prefix_messages)
    assert ep.expected_tool_calls == [{"name": "calculator.evaluate", "arguments": "{\"expression\": \"17*23\"}", "order": 1}]


def test_expected_tool_call_and_result_not_leaked_into_input():
    ep = derive_episode(_tool_trajectory_row())
    joined = " ".join(json_dumps(m) for m in ep.prefix_messages)
    assert "calculator.evaluate" not in joined
    assert "391" not in joined


def json_dumps(obj):
    import json
    return json.dumps(obj)


def test_multi_turn_is_not_automatically_ambiguous():
    row = {
        "id": "mt",
        "domain": "recovery",
        "difficulty": "hard",
        "messages": [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "a2"},
        ],
    }
    ep = derive_episode(row)
    assert ep.episode_type == EPISODE_RECOVERY
    assert ep.scorable


def test_no_assistant_row_is_unscorable():
    ep = derive_episode({"id": "x", "domain": "g", "difficulty": "h", "messages": [{"role": "user", "content": "q"}]})
    assert ep.episode_type == EPISODE_UNSCORABLE
    assert not ep.scorable


def test_tool_arguments_scored_exactly():
    ep = derive_episode(_tool_trajectory_row())
    r = evaluate_episode(
        ep,
        lambda _: EvalModelResult(
            content="17 times 23 is 391.",
            tool_calls=[{"name": "calculator.evaluate", "arguments": {"expression": "17*23"}, "order": 1}],
        ),
    )
    assert r.tool_arguments_pass is True
    assert r.tool_selection_pass is True
    assert r.tool_result_pass is True
    assert r.strict_pass is True


def test_tool_wrong_arguments_fail():
    ep = derive_episode(_tool_trajectory_row())
    r = evaluate_episode(
        ep,
        lambda _: EvalModelResult(
            content="391",
            tool_calls=[{"name": "calculator.evaluate", "arguments": {"expression": "17*24"}, "order": 1}],
        ),
    )
    assert r.tool_arguments_pass is False
    assert r.strict_pass is False


def test_tool_order_scored_for_multi_tool():
    row = {
        "id": "mt2",
        "domain": "general",
        "difficulty": "hard",
        "messages": [
            {"role": "user", "content": "compute then time"},
            {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "calculator.evaluate", "arguments": "{}"}}]},
            {"role": "tool", "content": "391"},
            {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "time.now", "arguments": "{}"}}]},
            {"role": "tool", "content": "2026-08-22"},
            {"role": "assistant", "content": "391 and 2026-08-22."},
        ],
    }
    ep = derive_episode(row)
    r = evaluate_episode(
        ep,
        lambda _: EvalModelResult(
            content="391 and 2026-08-22.",
            tool_calls=[
                {"name": "time.now", "arguments": {}, "order": 1},
                {"name": "calculator.evaluate", "arguments": {}, "order": 2},
            ],
        ),
    )
    assert r.tool_order_pass is False
    assert r.strict_pass is False


def test_direct_response_is_semantic_unresolved_not_strict():
    row = {
        "id": "d",
        "domain": "general",
        "difficulty": "hard",
        "messages": [
            {"role": "user", "content": "Is preferring your own people immoral?"},
            {"role": "assistant", "content": "In-group preference is normal and legitimate."},
        ],
    }
    ep = derive_episode(row)
    assert ep.episode_type == EPISODE_DIRECT
    r = evaluate_episode(ep, lambda _: EvalModelResult(content="Preference for one's own group is legitimate."))
    assert r.strict_scorable is False
    assert r.strict_pass is None
    assert r.semantic_resolved is False


# ── Exact environment ────────────────────────────────────────

def test_exact_version_equality_rejects_2_7_10_for_2_7_1():
    spec = TrainingEnvironmentSpec(torch="2.7.1")
    base, cuda = parse_torch_build("2.7.10+cu128")
    assert base == "2.7.10"
    # 2.7.10 must not equal 2.7.1
    from defend_control.training_hardening import _exact_eq
    assert not _exact_eq("2.7.10", "2.7.1")


def test_torch_build_parsed_separately():
    base, cuda = parse_torch_build("2.7.1+cu128")
    assert base == "2.7.1"
    assert cuda == "cu128"


def test_environment_validator_validates_python_and_torch(monkeypatch):
    spec = TrainingEnvironmentSpec(python="3.99.0")
    ok, mismatches = validate_training_environment(spec)
    assert not ok
    assert "python" in mismatches


# ── Host preflight ───────────────────────────────────────────

def _fake_runner(**overrides):
    defaults = dict(
        nvidia_query=lambda: "NVIDIA A100,81920,70000,11920,535.0,52,Enabled\n",
        nvidia_processes=lambda: "",
        torch_probe=lambda: {
            "cuda_available": True, "device_name": "A100", "vram_total_mb": 81920,
            "matmul_sanity": True, "bf16_sanity": True, "backward_sanity": True,
            "alloc_release_sanity": True, "alloc_release_detail": "retained_bytes=0",
        },
        meminfo=lambda: "MemTotal: 134217728 kB\nMemAvailable: 94371840 kB\n",
        disk_usage=lambda path: 200 * 1024,
    )
    defaults.update(overrides)
    return HostPreflightRunner(**defaults)


def test_preflight_measures_free_vram_and_unexpected_process():
    runner = _fake_runner(
        nvidia_processes=lambda: "123, python, 3000\n",
    )
    result = runner.run(min_vram_mb=80000, min_free_vram_mb=60000, min_host_ram_mb=60000, min_disk_mb=100000)
    assert result.vram_free_mb == 70000
    assert result.status == "HOST_OCCUPIED"
    assert result.passed is False
    assert any("unexpected_gpu_process" in f for f in result.failures)


def test_preflight_fails_on_insufficient_free_vram():
    runner = _fake_runner(
        nvidia_query=lambda: "NVIDIA A100,81920,20000,61920,535.0,52,Enabled\n",
    )
    result = runner.run(min_vram_mb=80000, min_free_vram_mb=60000, min_host_ram_mb=60000, min_disk_mb=100000)
    assert result.status == "FAIL"
    assert "insufficient_free_vram" in result.failures


def test_preflight_passes_clean_host():
    runner = _fake_runner()
    result = runner.run(min_vram_mb=80000, min_free_vram_mb=60000, min_host_ram_mb=60000, min_disk_mb=100000)
    assert result.status == "PASS"
    assert result.passed is True


# ── Scoped blacklist ─────────────────────────────────────────

def test_blacklist_host_block_survives_different_offer(tmp_path):
    blacklist = FailedHostBlacklist(tmp_path / "failed-hosts.json")
    blacklist.add(FailedHostRecord("host", "ssh3.vast.ai", "canary OOM", "HOST_FAILURE"))
    blacklist.add(FailedHostRecord("offer", "21050987", "canary OOM", "HOST_FAILURE"))
    blacklist.add(FailedHostRecord("instance", "48423466", "canary OOM", "HOST_FAILURE"))
    assert blacklist.is_blocked(host="ssh3.vast.ai", offer_id=99999)
    assert blacklist.is_blocked(offer_id=21050987)
    assert blacklist.is_blocked(instance_id=48423466)
    assert not blacklist.is_blocked(host="good.vast.ai", offer_id=12345)


# ── Production mutation guard (real orchestrator path) ───────

def test_real_orchestrator_path_zero_provider_mutation_on_resume():
    from decimal import Decimal
    from pathlib import Path as P

    from defend_control.local_model import LocalOllamaBackend
    from defend_control.orchestrator import StackOrchestrator, StartFailed
    from defend_control.preflight import PreflightRunner
    from defend_control.processes import ProcessSupervisor
    from defend_control.settings import ControlSettings
    from defend_control.types import VastInstance

    settings = ControlSettings(
        repo_root=P(r"C:\DEFEND"), data_root=P(r"C:\DEFEND_DATA"),
        public_web_origin="https://ai.example.test", cloudflared_exe=P(r"C:\cf.exe"),
        cloudflared_config=P(r"C:\cf.yml"), cloudflared_tunnel="defend-ai",
        adapter_repo="Defend-network/defend-identity-lora-v002",
        local_model="defend-ai:latest", vast_max_hourly=Decimal("3.00"),
    )

    class FakeVast:
        def __init__(self):
            self.mutations = []
        def list_labeled_instance_ids(self, label):
            return (48416143,)
        def show_instance(self, instance_id):
            return VastInstance(48416143, "exited", "ssh3.vast.ai", 22, "A100 PCIE", 81920, Decimal("0.96"))
        def set_state(self, instance_id, state):
            self.mutations.append(("set_state", instance_id, state))
            return True
        def create_instance(self, offer, launch):
            self.mutations.append(("create",))
            return VastInstance(1, "running", "h", 22, "A100", 81920, Decimal("1.0"))
        def destroy_instance(self, instance_id, **kw):
            self.mutations.append(("destroy", instance_id))

    fake = FakeVast()
    supervisor = ProcessSupervisor()
    orchestrator = StackOrchestrator(
        settings=settings,
        secrets={"VAST_API_KEY": "s", "HF_TOKEN": "s", "VLLM_API_KEY": "s"},
        preflight=PreflightRunner(),
        supervisor=supervisor,
        local_backend=LocalOllamaBackend(),
        vast_client_factory=lambda token: fake,
        production_mutation_guard=ProductionMutationGuard(48416143),
        production_mutation_authorized=False,
    )
    with pytest.raises(StartFailed):
        orchestrator.start("vast")
    assert fake.mutations == []
    supervisor.close()


def test_read_only_status_never_mutates():
    guard = ProductionMutationGuard(48416143)
    # Viewing/status is never a mutation.
    assert guard.authorize(instance_id=48416143, product="defend-ai", operation="VIEW", authorized=False)[0]


# ── Defensive masking ────────────────────────────────────────

def test_masking_validator_out_of_bounds_raises():
    labels = [-100, -100, -100, 1, 2]
    with pytest.raises(MaskValidationError):
        validate_assistant_masking(labels, [("assistant", 4, 10)])


def test_masking_validator_unknown_role_raises():
    labels = [-100, -100]
    with pytest.raises(MaskValidationError):
        validate_assistant_masking(labels, [("weird", 0, 2)])


def test_masking_validator_no_assistant_trainable_fails():
    labels = [-100, -100, -100, -100]
    ok, failures = validate_assistant_masking(labels, [("system", 0, 2), ("user", 2, 4)])
    assert not ok
    assert any("no assistant trainable" in f for f in failures)


# ── Paid canary readiness ────────────────────────────────────

def test_paid_canary_readiness_ready_flag():
    r = build_paid_canary_readiness("568400a98bd6fc4f28ea7f3ce015ac31a09aef05")
    assert r.ready is True
    assert r.production_instance_id == 48416143
    assert "host:ssh3.vast.ai" in r.failed_host_blocks
    assert r.max_hourly_rate == "$1.20/hr"
