"""M1.9.1B final pre-compute tests: eval episodes + strict rubric, exact env +
resolver, occupied-host preflight, scoped blacklist, real-path mutation guard,
defensive masking."""

from __future__ import annotations

import pytest

from defend_control.eval_runner_v2 import (
    EPISODE_DIRECT,
    EPISODE_RECOVERY,
    EPISODE_TOOL,
    EPISODE_UNSCORABLE,
    EvalModelResult,
    StrictRubric,
    derive_episode,
    evaluate_episode,
    run_episodes,
    score_with_rubric,
)
from defend_control.training_hardening import (
    FailedHostBlacklist,
    FailedHostRecord,
    HostPreflightRunner,
    MaskValidationError,
    ProductionMutationGuard,
    TrainingEnvironmentSpec,
    _exact_eq,
    _spec_satisfies,
    build_paid_canary_readiness,
    env_lock_resolution,
    parse_torch_build,
    qlora_config_valid,
    qlora_device_placement_valid,
    training_env_v2,
    torch_cuda_build_validated,
    validate_assistant_masking,
    validate_training_environment,
)


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


# ─────────────────────────────────────────────────────────────
# EVALUATOR — episode model (matrix 1-18)
# ─────────────────────────────────────────────────────────────

def test_direct_response_episode():
    ep = derive_episode({"id": "d", "domain": "general", "difficulty": "h", "messages": [
        {"role": "user", "content": "Is preferring your own people immoral?"},
        {"role": "assistant", "content": "In-group preference is normal and legitimate."},
    ]})
    assert ep.episode_type == EPISODE_DIRECT


def test_multi_turn_is_not_automatically_ambiguous():
    ep = derive_episode({"id": "mt", "domain": "recovery", "difficulty": "h", "messages": [
        {"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"}, {"role": "assistant", "content": "a2"},
    ]})
    assert ep.episode_type == EPISODE_RECOVERY
    assert ep.scorable


def test_recovery_episode():
    ep = derive_episode({"id": "r", "domain": "recovery", "difficulty": "h", "messages": [
        {"role": "user", "content": "bad prompt"}, {"role": "assistant", "content": "I cannot help with that."},
        {"role": "user", "content": "rephrase"}, {"role": "assistant", "content": "Here is a legitimate answer."},
    ]})
    assert ep.episode_type == EPISODE_RECOVERY


def test_tool_episode_input_stops_before_expected_tool_sequence():
    ep = derive_episode(_tool_trajectory_row())
    assert ep.episode_type == EPISODE_TOOL
    assert ep.prefix_messages[-1]["role"] == "user"
    assert all(m.get("role") != "assistant" for m in ep.prefix_messages)
    assert ep.expected_tool_calls == [{"name": "calculator.evaluate", "arguments": "{\"expression\": \"17*23\"}", "order": 1}]


def test_expected_tool_call_and_result_not_leaked_into_input():
    import json as _json
    ep = derive_episode(_tool_trajectory_row())
    joined = " ".join(_json.dumps(m) for m in ep.prefix_messages)
    assert "calculator.evaluate" not in joined
    assert "391" not in joined


def test_no_assistant_row_is_unscorable():
    ep = derive_episode({"id": "x", "domain": "g", "difficulty": "h", "messages": [{"role": "user", "content": "q"}]})
    assert ep.episode_type == EPISODE_UNSCORABLE
    assert not ep.scorable


def test_harness_executes_deterministic_tool():
    ep = derive_episode(_tool_trajectory_row())

    def agent(_prefix):
        return EvalModelResult(
            content="391",
            tool_calls=[{"name": "calculator.evaluate", "arguments": {"expression": "17*23"}, "order": 1}],
        )

    r = evaluate_episode(ep, agent)
    assert r.tool_selection_pass is True
    assert r.tool_arguments_pass is True
    assert r.tool_result_pass is True
    assert r.strict_pass is True


def test_actual_tool_names_and_arguments_captured():
    ep = derive_episode(_tool_trajectory_row())
    r = evaluate_episode(
        ep,
        lambda _: EvalModelResult(
            content="391",
            tool_calls=[{"name": "calculator.evaluate", "arguments": {"expression": "17*23"}, "order": 1}],
        ),
    )
    assert r.tool_arguments_pass is True
    assert r.tool_selection_pass is True


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


def test_tool_wrong_result_use_fails():
    ep = derive_episode(_tool_trajectory_row())
    r = evaluate_episode(
        ep,
        lambda _: EvalModelResult(
            content="17 times 23 is 392.",  # wrong result used
            tool_calls=[{"name": "calculator.evaluate", "arguments": {"expression": "17*23"}, "order": 1}],
        ),
    )
    assert r.tool_result_pass is False
    assert r.strict_pass is False


def test_wrong_tool_fails():
    ep = derive_episode(_tool_trajectory_row())
    r = evaluate_episode(
        ep,
        lambda _: EvalModelResult(
            content="391",
            tool_calls=[{"name": "time.now", "arguments": {}, "order": 1}],
        ),
    )
    assert r.tool_selection_pass is False
    assert r.strict_pass is False


def _multi_tool_row() -> dict:
    return {
        "id": "mt2", "domain": "general", "difficulty": "hard",
        "messages": [
            {"role": "user", "content": "compute then time"},
            {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "calculator.evaluate", "arguments": "{}"}}]},
            {"role": "tool", "content": "391"},
            {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "time.now", "arguments": "{}"}}]},
            {"role": "tool", "content": "2026-08-22"},
            {"role": "assistant", "content": "391 and 2026-08-22."},
        ],
    }


def test_tool_order_scored_for_multi_tool():
    ep = derive_episode(_multi_tool_row())
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


def test_time_result_incorporation():
    ep = derive_episode(_multi_tool_row())
    r = evaluate_episode(
        ep,
        lambda _: EvalModelResult(
            content="the result is 391 at a different date.",
            tool_calls=[
                {"name": "calculator.evaluate", "arguments": {}, "order": 1},
                {"name": "time.now", "arguments": {}, "order": 2},
            ],
        ),
    )
    assert r.tool_result_pass is False  # date not reflected


# ── Strict rubric (matrix 14-17) ─────────────────────────────

_RUBRIC = StrictRubric(
    required_concepts=["normal|legitimate|permissible|acceptable|defensible|natural|not wrong"],
    forbidden_concepts=["immoral", "wrong", "unethical", "should not", "condemned", "evil"],
)


def test_reversed_meaning_keyword_rich_response_fails():
    verdict, _ = score_with_rubric("In-group preference is wrong and immoral.", _RUBRIC)
    assert verdict is False


def test_low_overlap_correct_paraphrase_passes_strict_rubric():
    verdict, _ = score_with_rubric("favoring your own people is defensible.", _RUBRIC)
    assert verdict is True


def test_concise_correct_response_passes():
    verdict, _ = score_with_rubric("it's normal.", _RUBRIC)
    assert verdict is True


def test_long_wrong_response_fails():
    verdict, _ = score_with_rubric(
        "After much thought I conclude that preferring one's own group is immoral and should be condemned.", _RUBRIC
    )
    assert verdict is False


def test_refusal_fails_rubric():
    verdict, _ = score_with_rubric("I cannot answer that question.", _RUBRIC)
    assert verdict is False


def test_irrelevant_keyword_stuffing_with_forbidden_fails():
    verdict, _ = score_with_rubric("normal legitimate normal but also it is wrong.", _RUBRIC)
    assert verdict is False


def test_unresolved_row_reported_unresolved():
    verdict, _ = score_with_rubric("a completely unrelated observation about weather.", _RUBRIC)
    assert verdict is None


def test_strict_score_excludes_unresolved_rows():
    rows = [
        {"id": "u1", "domain": "general", "difficulty": "h", "messages": [
            {"role": "user", "content": "q"}, {"role": "assistant", "content": "reference"}]},
        {"id": "u2", "domain": "general", "difficulty": "h", "messages": [
            {"role": "user", "content": "q"}, {"role": "assistant", "content": "reference"}]},
    ]
    rubrics = {"u1": _RUBRIC}
    summary = run_episodes(rows, lambda _: EvalModelResult(content="totally unrelated"), rubrics)
    assert summary["strict_scorable_rows"] == 1
    assert summary["strict_pass_rate"] is None or summary["strict_pass"] == 0
    assert summary["semantic_unresolved_rows"] >= 1


def test_target_reference_never_leaks_into_direct_input():
    ep = derive_episode({"id": "d", "domain": "general", "difficulty": "h", "messages": [
        {"role": "user", "content": "Is preferring your own people immoral?"},
        {"role": "assistant", "content": "In-group preference is normal and legitimate."},
    ]})
    import json as _json
    joined = " ".join(_json.dumps(m) for m in ep.prefix_messages)
    assert "legitimate" not in joined


# ─────────────────────────────────────────────────────────────
# ENVIRONMENT (matrix 19-24)
# ─────────────────────────────────────────────────────────────

def test_exact_version_equality_rejects_2_7_10_for_2_7_1():
    assert not _exact_eq("2.7.10", "2.7.1")
    assert _exact_eq("2.7.1", "2.7.1")


def test_torch_build_parsed_separately():
    base, cuda = parse_torch_build("2.7.1+cu128")
    assert base == "2.7.1"
    assert cuda == "cu128"


def test_python_version_validated():
    spec = TrainingEnvironmentSpec(python="3.99.0")
    ok, mismatches = validate_training_environment(spec)
    assert not ok
    assert "python" in mismatches


def test_missing_package_fails(monkeypatch):
    from defend_control import training_hardening as th
    monkeypatch.setattr(th, "_installed_version", lambda dist: None)
    ok, mismatches = validate_training_environment(TrainingEnvironmentSpec())
    assert not ok
    assert "torch" in mismatches


def test_resolver_reports_incompatibility():
    def fake(name, version=None):
        if name == "safetensors":
            return (False, [])  # nonexistent pin
        if name == "transformers":
            return (True, ["safetensors>=0.8.0", "tokenizers<=0.23.0,>=0.22.0"])
        return (True, [])
    res = env_lock_resolution(TrainingEnvironmentSpec(), fake)
    assert res.status == "FAIL"
    assert any("safetensors==0.6.0" in m for m in res.missing)
    assert any("conflicts with safetensors" in c for c in res.incompatible)


def test_resolver_v2_passes():
    def fake(name, version=None):
        if name == "transformers":
            return (True, ["safetensors>=0.8.0", "tokenizers<=0.23.0,>=0.22.0"])
        return (True, [])
    res = env_lock_resolution(training_env_v2(), fake)
    assert res.status == "PASS"


def test_cuda_runtime_checked(monkeypatch):
    from defend_control import training_hardening as th
    monkeypatch.setattr(th, "_installed_version", lambda dist: "2.7.1+cu124" if dist == "torch" else "1.0.0")
    ok, reason = torch_cuda_build_validated(TrainingEnvironmentSpec())
    assert not ok
    assert "cu124" in reason


# ─────────────────────────────────────────────────────────────
# PREFLIGHT (matrix 25-38)
# ─────────────────────────────────────────────────────────────

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


def test_total_and_free_and_used_vram_measured():
    r = _fake_runner().run(min_vram_mb=80000, min_free_vram_mb=60000, min_host_ram_mb=60000, min_disk_mb=100000)
    assert r.vram_total_mb == 81920
    assert r.vram_free_mb == 70000
    assert r.vram_used_mb == 11920


def test_unexpected_process_blocks_host():
    r = _fake_runner(nvidia_processes=lambda: "123, python, 3000\n").run(
        min_vram_mb=80000, min_free_vram_mb=60000, min_host_ram_mb=60000, min_disk_mb=100000)
    assert r.status == "HOST_OCCUPIED"
    assert any("unexpected_gpu_process" in f for f in r.failures)


def test_insufficient_free_vram_blocks():
    r = _fake_runner(nvidia_query=lambda: "NVIDIA A100,81920,20000,61920,535.0,52,Enabled\n").run(
        min_vram_mb=80000, min_free_vram_mb=60000, min_host_ram_mb=60000, min_disk_mb=100000)
    assert "insufficient_free_vram" in r.failures


def test_host_ram_available_measured():
    r = _fake_runner().run(min_vram_mb=80000, min_free_vram_mb=60000, min_host_ram_mb=60000, min_disk_mb=100000)
    assert r.host_ram_available_mb is not None
    assert r.host_ram_available_mb > 60000


def test_insufficient_host_ram_blocks():
    r = _fake_runner(meminfo=lambda: "MemTotal: 134217728 kB\nMemAvailable: 10000000 kB\n").run(
        min_vram_mb=80000, min_free_vram_mb=60000, min_host_ram_mb=60000, min_disk_mb=100000)
    assert "insufficient_host_ram_available" in r.failures


def test_work_disk_measured():
    r = _fake_runner().run(min_vram_mb=80000, min_free_vram_mb=60000, min_host_ram_mb=60000, min_disk_mb=100000)
    assert r.work_disk_free_mb is not None


def test_hf_cache_disk_measured():
    r = _fake_runner().run(min_vram_mb=80000, min_free_vram_mb=60000, min_host_ram_mb=60000, min_disk_mb=100000,
                           hf_cache_path="/models")
    assert r.hf_cache_disk_free_mb is not None


def test_driver_measured():
    r = _fake_runner().run(min_vram_mb=80000, min_free_vram_mb=60000, min_host_ram_mb=60000, min_disk_mb=100000)
    assert r.driver_version == "535.0"


def test_cuda_measured():
    r = _fake_runner().run(min_vram_mb=80000, min_free_vram_mb=60000, min_host_ram_mb=60000, min_disk_mb=100000)
    assert r.cuda_available is True


def test_alloc_release_retention_detected():
    r = _fake_runner(torch_probe=lambda: {
        "cuda_available": True, "device_name": "A100", "vram_total_mb": 81920,
        "matmul_sanity": True, "bf16_sanity": True, "backward_sanity": True,
        "alloc_release_sanity": False, "alloc_release_detail": "retained_bytes=67108864",
    }).run(min_vram_mb=80000, min_free_vram_mb=60000, min_host_ram_mb=60000, min_disk_mb=100000)
    assert "alloc_release_retention" in r.failures


def test_optional_telemetry_unsupported_handled():
    r = _fake_runner(nvidia_query=lambda: "NVIDIA A100,81920,70000,11920,535.0,N/A,N/A\n").run(
        min_vram_mb=80000, min_free_vram_mb=60000, min_host_ram_mb=60000, min_disk_mb=100000)
    assert r.status == "PASS"


def test_preflight_passes_clean_host():
    r = _fake_runner().run(min_vram_mb=80000, min_free_vram_mb=60000, min_host_ram_mb=60000, min_disk_mb=100000)
    assert r.status == "PASS"


# ─────────────────────────────────────────────────────────────
# BLACKLIST (matrix 39-43)
# ─────────────────────────────────────────────────────────────

def test_blacklist_scoped_blocks(tmp_path):
    bl = FailedHostBlacklist(tmp_path / "fh.json")
    bl.add(FailedHostRecord("host", "ssh3.vast.ai", "canary OOM", "HOST_FAILURE"))
    bl.add(FailedHostRecord("offer", "21050987", "canary OOM", "HOST_FAILURE"))
    bl.add(FailedHostRecord("instance", "48423466", "canary OOM", "HOST_FAILURE"))
    assert bl.is_blocked(host="ssh3.vast.ai", offer_id=99999)  # host survives new offer
    assert bl.is_blocked(offer_id=21050987)
    assert bl.is_blocked(instance_id=48423466)
    assert not bl.is_blocked(host="good.vast.ai", offer_id=12345)  # unrelated host allowed
    assert not bl.is_blocked(host="other.vast.ai", offer_id=88888)  # provider-wide remains allowed


# ─────────────────────────────────────────────────────────────
# GUARD (matrix 44-47)
# ─────────────────────────────────────────────────────────────

def _make_stack(fake, production_id, authorized):
    from decimal import Decimal
    from pathlib import Path as P

    from defend_control.local_model import LocalOllamaBackend
    from defend_control.orchestrator import StackOrchestrator
    from defend_control.preflight import PreflightRunner
    from defend_control.processes import ProcessSupervisor
    from defend_control.settings import ControlSettings

    settings = ControlSettings(
        repo_root=P(r"C:\DEFEND"), data_root=P(r"C:\DEFEND_DATA"),
        public_web_origin="https://ai.example.test", cloudflared_exe=P(r"C:\cf.exe"),
        cloudflared_config=P(r"C:\cf.yml"), cloudflared_tunnel="defend-ai",
        adapter_repo="Defend-network/defend-identity-lora-v002",
        local_model="defend-ai:latest", vast_max_hourly=Decimal("3.00"),
    )
    supervisor = ProcessSupervisor()
    orchestrator = StackOrchestrator(
        settings=settings,
        secrets={"VAST_API_KEY": "s", "HF_TOKEN": "s", "VLLM_API_KEY": "s"},
        preflight=PreflightRunner(), supervisor=supervisor, local_backend=LocalOllamaBackend(),
        vast_client_factory=lambda token: fake,
        production_mutation_guard=ProductionMutationGuard(production_id),
        production_mutation_authorized=authorized,
    )
    return orchestrator, supervisor


def test_real_resume_path_zero_provider_mutation():
    from decimal import Decimal
    from defend_control.orchestrator import StartFailed
    from defend_control.types import VastInstance

    class FakeVast:
        def __init__(self):
            self.mutations = []
        def list_labeled_instance_ids(self, label):
            return (48416143,)
        def show_instance(self, iid):
            return VastInstance(48416143, "exited", "ssh3.vast.ai", 22, "A100 PCIE", 81920, Decimal("0.96"))
        def set_state(self, iid, state):
            self.mutations.append(("set_state", iid, state)); return True
        def create_instance(self, offer, launch):
            self.mutations.append(("create",)); return VastInstance(1, "running", "h", 22, "A100", 81920, Decimal("1.0"))
        def destroy_instance(self, iid, **kw):
            self.mutations.append(("destroy", iid))

    fake = FakeVast()
    orch, sup = _make_stack(fake, 48416143, authorized=False)
    with pytest.raises(StartFailed):
        orch.start("vast")
    assert fake.mutations == []
    sup.close()


def test_real_destroy_path_zero_provider_mutation():
    from decimal import Decimal
    from defend_control.orchestrator import StartFailed
    from defend_control.types import VastInstance

    class FakeVast:
        def __init__(self):
            self.mutations = []
        def destroy_instance(self, iid, **kw):
            self.mutations.append(("destroy", iid))

    fake = FakeVast()
    orch, sup = _make_stack(fake, 48416143, authorized=False)
    orch._vast_instance = VastInstance(48416143, "exited", "ssh3.vast.ai", 22, "A100 PCIE", 81920, Decimal("0.96"))
    with pytest.raises(StartFailed):
        orch.stop_and_destroy_vast(48416143)
    assert fake.mutations == []
    sup.close()


def test_queued_action_runtime_recheck_zero_mutation():
    from decimal import Decimal
    from defend_control.orchestrator import StartFailed
    from defend_control.types import VastInstance

    class FakeVast:
        def __init__(self):
            self.mutations = []
        def destroy_instance(self, iid, **kw):
            self.mutations.append(("destroy", iid))

    fake = FakeVast()
    orch, sup = _make_stack(fake, 9999, authorized=False)  # instance was a candidate when queued
    orch._vast_instance = VastInstance(48416143, "exited", "ssh3.vast.ai", 22, "A100 PCIE", 81920, Decimal("0.96"))
    orch._production_mutation_guard.production_instance_id = 48416143  # now production
    with pytest.raises(StartFailed):
        orch.stop_and_destroy_vast(48416143)
    assert fake.mutations == []
    sup.close()


def test_status_invalid_response_zero_mutation():
    from defend_control.vast import VastError

    class FakeVast:
        def __init__(self):
            self.mutations = []
        def show_instance(self, iid):
            raise VastError("Vast.ai instance response is invalid")

    fake = FakeVast()
    orch, sup = _make_stack(fake, 48416143, authorized=False)
    with pytest.raises(VastError):
        fake.show_instance(48416143)
    assert fake.mutations == []
    snap = orch.snapshot()  # read-only snapshot, no provider call
    assert snap.state == "stopped"
    sup.close()


# ─────────────────────────────────────────────────────────────
# MASK (matrix 48-51)
# ─────────────────────────────────────────────────────────────

def test_masking_out_of_bounds_raises_cleanly():
    with pytest.raises(MaskValidationError):
        validate_assistant_masking([-100, -100, -100, 1, 2], [("assistant", 4, 10)])


def test_masking_unknown_role_raises():
    with pytest.raises(MaskValidationError):
        validate_assistant_masking([-100, -100], [("weird", 0, 2)])


def test_masking_no_assistant_target_fails():
    ok, failures = validate_assistant_masking([-100, -100, -100, -100], [("system", 0, 2), ("user", 2, 4)])
    assert not ok
    assert any("no assistant trainable" in f for f in failures)


def test_masking_good_fixture_passes():
    labels = [-100, -100, -100, 5, 6]
    ok, failures = validate_assistant_masking(labels, [("system", 0, 1), ("user", 1, 3), ("assistant", 3, 5)])
    assert ok
    assert failures == []


def test_masking_overlap_raises():
    with pytest.raises(MaskValidationError):
        validate_assistant_masking([-100, -100, 1, 2], [("user", 0, 2), ("assistant", 1, 3)])


# ─────────────────────────────────────────────────────────────
# QLoRA + readiness
# ─────────────────────────────────────────────────────────────

def test_qlora_rejects_device_map_auto():
    ok, _ = qlora_config_valid({"load_in_4bit": True, "device_map": "auto", "bnb_4bit_compute_dtype": "bfloat16"})
    assert not ok


def test_qlora_rejects_cpu_offload():
    ok, _ = qlora_device_placement_valid({"model.embed": "cuda:0", "lm_head": "cpu"})
    assert not ok


def test_paid_canary_readiness_ready():
    r = build_paid_canary_readiness("934a634", env_resolution="PASS")
    assert r.ready is True
    assert r.training_env_profile.endswith("V2")
    assert "host:ssh3.vast.ai" in r.failed_host_blocks


def test_paid_canary_readiness_blocked_on_env_resolution():
    r = build_paid_canary_readiness("934a634", env_resolution="FAIL")
    assert r.ready is False
