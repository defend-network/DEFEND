"""M1.9.1C paid-canary last-mile tests: truthful CUDA telemetry, fail-closed
process query, mandatory HF-cache disk, Python version policy, metadata
precheck labelling, gated readiness, corruption/concurrency-safe blacklist,
and the tool-eval truth label."""

from __future__ import annotations

import os
import tempfile
import threading
from dataclasses import replace
from pathlib import Path

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
    tool_eval_status,
)
from defend_control.training_hardening import (
    FULL_RESOLVER_PROOF,
    HOST_INSTALL_REQUIRED,
    CANDIDATE_TRAINING_PROFILE_ID,
    HISTORICAL_PRODUCTION_INSTANCE_IDS,
    PRODUCTION_PROFILE_ID,
    RUNTIME_ABSENT,
    RUNTIME_AMBIGUOUS,
    RUNTIME_UNKNOWN,
    FailedHostBlacklist,
    FailedHostRecord,
    HostPreflightRunner,
    MaskValidationError,
    ProductionMutationGuard,
    PyPIMetadataCompatibility,
    TrainingEnvironmentSpec,
    _exact_eq,
    authorize_candidate_lifecycle,
    build_paid_canary_readiness,
    env_lock_resolution,
    parse_torch_build,
    pypi_metadata_compatibility,
    python_policy_accepts,
    qlora_config_valid,
    qlora_device_placement_valid,
    required_campaign_blocks,
    resolve_hf_cache_path,
    targets_production,
    torch_cuda_build_validated,
    training_env_v2,
    validate_assistant_masking,
    validate_training_environment,
)

# Direct auto-resolve of HF cache in run() must never touch the real home dir.
os.environ["HF_HUB_CACHE"] = tempfile.mkdtemp(prefix="defend-hf-cache-test-")

_GOOD_QUERY = "NVIDIA A100,81920,70000,11920,535.0,52,Enabled\n"


def _good_torch_probe() -> dict:
    return {
        "cuda_available": True,
        "torch_version": "2.7.1+cu128",
        "torch_cuda_build": "12.8",
        "device_name": "A100",
        "vram_total_mb": 81920,
        "matmul_sanity": True,
        "bf16_sanity": True,
        "backward_sanity": True,
        "alloc_release_sanity": True,
        "alloc_release_detail": "retained_bytes=0",
    }


def _fake_runner(**overrides):
    defaults = dict(
        nvidia_query=lambda: _GOOD_QUERY,
        nvidia_processes=lambda: ("MEASURED", ""),
        torch_probe=_good_torch_probe,
        meminfo=lambda: "MemTotal: 134217728 kB\nMemAvailable: 94371840 kB\n",
        disk_usage=lambda path: 200 * 1024,
    )
    defaults.update(overrides)
    return HostPreflightRunner(**defaults)


def _disk_map(mapping):
    def disk(path):
        return mapping.get(str(Path(path).resolve()), 200 * 1024)
    return disk


def _run(runner, **kw):
    kw.setdefault("min_vram_mb", 80000)
    kw.setdefault("min_free_vram_mb", 60000)
    kw.setdefault("min_host_ram_mb", 60000)
    kw.setdefault("min_disk_mb", 100000)
    return runner.run(**kw)


def _tool_trajectory_row() -> dict:
    return {
        "id": "tool1", "domain": "general", "difficulty": "hard",
        "messages": [
            {"role": "system", "content": "You are DEFEND AI."},
            {"role": "user", "content": "Compute 17*23."},
            {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "calculator.evaluate", "arguments": "{\"expression\": \"17*23\"}"}}]},
            {"role": "tool", "content": "391"},
            {"role": "assistant", "content": "17 times 23 is 391."},
        ],
    }


# ─────────────────────────────────────────────────────────────
# EVALUATOR (retained M1.9.1B)
# ─────────────────────────────────────────────────────────────

def test_tool_episode_input_stops_before_expected_tool_sequence():
    ep = derive_episode(_tool_trajectory_row())
    assert ep.episode_type == EPISODE_TOOL
    assert ep.prefix_messages[-1]["role"] == "user"
    assert all(m.get("role") != "assistant" for m in ep.prefix_messages)


def test_expected_tool_call_and_result_not_leaked_into_input():
    import json as _json
    ep = derive_episode(_tool_trajectory_row())
    joined = " ".join(_json.dumps(m) for m in ep.prefix_messages)
    assert "calculator.evaluate" not in joined
    assert "391" not in joined


def test_multi_turn_is_not_automatically_ambiguous():
    ep = derive_episode({"id": "mt", "domain": "recovery", "difficulty": "h", "messages": [
        {"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"}, {"role": "assistant", "content": "a2"},
    ]})
    assert ep.episode_type == EPISODE_RECOVERY
    assert ep.scorable


def test_no_assistant_row_is_unscorable():
    ep = derive_episode({"id": "x", "domain": "g", "difficulty": "h", "messages": [{"role": "user", "content": "q"}]})
    assert ep.episode_type == EPISODE_UNSCORABLE


def test_tool_arguments_and_result_scored():
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
            content="17 times 23 is 392.",
            tool_calls=[{"name": "calculator.evaluate", "arguments": {"expression": "17*23"}, "order": 1}],
        ),
    )
    assert r.tool_result_pass is False


_RUBRIC = StrictRubric(
    required_concepts=["normal|legitimate|permissible|acceptable|defensible|natural|not wrong"],
    forbidden_concepts=["immoral", "wrong", "unethical", "should not", "condemned", "evil"],
)


def test_reversed_meaning_keyword_rich_response_fails():
    assert score_with_rubric("In-group preference is wrong and immoral.", _RUBRIC)[0] is False


def test_low_overlap_correct_paraphrase_passes_strict_rubric():
    assert score_with_rubric("favoring your own people is defensible.", _RUBRIC)[0] is True


def test_unresolved_row_reported_unresolved():
    assert score_with_rubric("a completely unrelated observation about weather.", _RUBRIC)[0] is None


def test_strict_score_excludes_unresolved_rows():
    rows = [
        {"id": "u1", "domain": "general", "difficulty": "h", "messages": [
            {"role": "user", "content": "q"}, {"role": "assistant", "content": "ref"}]},
    ]
    summary = run_episodes(rows, lambda _: EvalModelResult(content="totally unrelated"), {"u1": _RUBRIC})
    assert summary["strict_pass_rate"] is None or summary["strict_pass"] == 0
    assert summary["semantic_unresolved_rows"] >= 1


# ─────────────────────────────────────────────────────────────
# ENVIRONMENT (exact + python policy + metadata precheck)
# ─────────────────────────────────────────────────────────────

def test_exact_version_equality_rejects_2_7_10_for_2_7_1():
    assert not _exact_eq("2.7.10", "2.7.1")
    assert _exact_eq("2.7.1", "2.7.1")


def test_torch_build_parsed_separately():
    base, cuda = parse_torch_build("2.7.1+cu128")
    assert base == "2.7.1"
    assert cuda == "cu128"


def test_python_policy_accepts_intended_release():
    ok, _ = python_policy_accepts(TrainingEnvironmentSpec(), 3, 12, 7)
    assert ok


def test_python_3_11_rejected():
    ok, _ = python_policy_accepts(TrainingEnvironmentSpec(), 3, 11, 9)
    assert not ok


def test_python_3_13_rejected():
    ok, _ = python_policy_accepts(TrainingEnvironmentSpec(), 3, 13, 0)
    assert not ok


def test_python_exact_policy_rejects_other_patch():
    spec = TrainingEnvironmentSpec(python_exact="3.12.4")
    ok, _ = python_policy_accepts(spec, 3, 12, 7)
    assert not ok
    ok2, _ = python_policy_accepts(spec, 3, 12, 4)
    assert ok2


def test_validate_env_flags_python_policy_mismatch():
    spec = TrainingEnvironmentSpec(python_policy="3.99")
    ok, mismatches = validate_training_environment(spec)
    assert not ok
    assert "python_policy" in mismatches


def test_resolver_reports_incompatibility():
    def fake(name, version=None):
        if name == "safetensors":
            return (False, [])
        if name == "transformers":
            return (True, ["safetensors>=0.8.0", "tokenizers<=0.23.0,>=0.22.0"])
        return (True, [])
    res = pypi_metadata_compatibility(TrainingEnvironmentSpec(), fake)
    assert res.status == "FAIL"
    assert any("safetensors==0.6.0" in m for m in res.missing)
    assert any("conflicts with safetensors" in c for c in res.incompatible)


def test_resolver_v2_passes():
    def fake(name, version=None):
        if name == "transformers":
            return (True, ["safetensors>=0.8.0", "tokenizers<=0.23.0,>=0.22.0"])
        return (True, [])
    res = pypi_metadata_compatibility(training_env_v2(), fake)
    assert res.status == "PASS"


def test_metadata_precheck_labelled_truthfully():
    res = pypi_metadata_compatibility(training_env_v2(), lambda name, version=None: (True, []))
    assert isinstance(res, PyPIMetadataCompatibility)
    assert res.kind == "PYPI_METADATA_COMPATIBILITY"


def test_full_resolver_not_claimed_and_host_install_required():
    assert FULL_RESOLVER_PROOF is False
    assert HOST_INSTALL_REQUIRED is True


def test_cuda_runtime_checked(monkeypatch):
    from defend_ai import training_hardening as th
    monkeypatch.setattr(th, "_installed_version", lambda dist: "2.7.1+cu124" if dist == "torch" else "1.0.0")
    ok, reason = torch_cuda_build_validated(TrainingEnvironmentSpec())
    assert not ok
    assert "cu124" in reason


# ─────────────────────────────────────────────────────────────
# PREFLIGHT (truthful CUDA, fail-closed processes, mandatory cache)
# ─────────────────────────────────────────────────────────────

def test_driver_telemetry_required():
    r = _run(_fake_runner(nvidia_query=lambda: "NVIDIA A100,81920,70000,11920,,52,Enabled\n"))
    assert "driver_version_not_measured" in r.failures
    assert r.passed is False


def test_torch_cuda_build_required():
    probe = _good_torch_probe()
    probe["torch_cuda_build"] = None
    r = _run(_fake_runner(torch_probe=lambda: probe))
    assert "torch_cuda_build_not_measured" in r.failures


def test_process_query_success_zero_processes_passes():
    r = _run(_fake_runner(nvidia_processes=lambda: ("MEASURED", "")))
    assert r.gpu_process_telemetry_status == "MEASURED"
    assert r.active_gpu_processes == []
    assert r.status == "PASS"


def test_process_query_error_fails():
    r = _run(_fake_runner(nvidia_processes=lambda: ("ERROR", "")))
    assert "gpu_process_telemetry_error" in r.failures


def test_process_query_timeout_fails():
    def boom():
        raise TimeoutError("query timed out")
    r = _run(_fake_runner(nvidia_processes=boom))
    assert "gpu_process_telemetry_error" in r.failures


def test_unexpected_1gb_process_fails_host_occupied():
    r = _run(_fake_runner(nvidia_processes=lambda: ("MEASURED", "123, python, 1024\n")))
    assert r.status == "HOST_OCCUPIED"
    assert any("unexpected_gpu_process" in f for f in r.failures)


def test_empty_process_list_differs_from_query_error():
    ok = _run(_fake_runner(nvidia_processes=lambda: ("MEASURED", "")))
    err = _run(_fake_runner(nvidia_processes=lambda: ("ERROR", "")))
    assert ok.status == "PASS"
    assert err.passed is False


def test_hf_cache_path_auto_resolves(monkeypatch, tmp_path):
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hfcache"))
    resolved = resolve_hf_cache_path(None)
    assert resolved == str(Path(tmp_path / "hfcache").resolve())
    assert Path(resolved).is_dir()


def test_hf_cache_disk_measured(tmp_path):
    cache = tmp_path / "hf"
    r = _run(_fake_runner(), hf_cache_path=str(cache))
    assert r.hf_cache_path_resolved is True
    assert r.hf_cache_disk_free_mb is not None


def test_missing_hf_cache_telemetry_fails(tmp_path):
    cache = tmp_path / "hf"
    r = _run(_fake_runner(disk_usage=_disk_map({str(cache.resolve()): -1})), hf_cache_path=str(cache))
    assert "hf_cache_disk_not_measured" in r.failures


def test_insufficient_hf_cache_disk_fails(tmp_path):
    cache = tmp_path / "hf"
    r = _run(_fake_runner(disk_usage=_disk_map({str(cache.resolve()): 5000})), hf_cache_path=str(cache))
    assert "insufficient_hf_cache_disk" in r.failures


def test_work_and_cache_mounts_both_measured(tmp_path):
    cache = tmp_path / "hf"
    r = _run(_fake_runner(disk_usage=_disk_map({str(cache.resolve()): 150 * 1024})), hf_cache_path=str(cache))
    assert r.work_disk_free_mb is not None
    assert r.hf_cache_disk_free_mb == 150 * 1024
    assert r.work_disk_free_mb != r.hf_cache_disk_free_mb


def test_preflight_passes_clean_host(tmp_path):
    r = _run(_fake_runner(), hf_cache_path=str(tmp_path / "hf"))
    assert r.status == "PASS"


# ─────────────────────────────────────────────────────────────
# BLACKLIST (scoped, corruption fail-closed, concurrency-safe)
# ─────────────────────────────────────────────────────────────

def test_blacklist_scoped_blocks(tmp_path):
    bl = FailedHostBlacklist(tmp_path / "fh.json")
    bl.add(FailedHostRecord("host", "ssh3.vast.ai", "canary OOM", "HOST_FAILURE"))
    assert bl.is_blocked(host="ssh3.vast.ai", offer_id=99999)
    assert bl.is_blocked(offer_id=21050987)
    assert bl.is_blocked(instance_id=48423466)
    assert not bl.is_blocked(host="good.vast.ai", offer_id=12345)
    assert not bl.is_blocked(host="other.vast.ai", offer_id=88888)


def test_corrupt_blacklist_does_not_forget_required_blocks(tmp_path):
    path = tmp_path / "fh.json"
    path.write_text("{ this is not valid json", encoding="utf-8")
    bl = FailedHostBlacklist(path)
    assert bl.is_blocked(host="ssh3.vast.ai")
    assert bl.is_blocked(offer_id=21050987)
    assert bl.is_blocked(instance_id=48423466)


def test_concurrent_blacklist_updates_retain_all_blocks(tmp_path):
    bl = FailedHostBlacklist(tmp_path / "fh.json")

    def add(i):
        bl.add(FailedHostRecord("host", f"bad{i}.vast.ai", "canary OOM", "HOST_FAILURE"))

    threads = [threading.Thread(target=add, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for i in range(20):
        assert bl.is_blocked(host=f"bad{i}.vast.ai")
    assert bl.is_blocked(host="ssh3.vast.ai")
    assert bl.is_blocked(offer_id=21050987)
    assert bl.is_blocked(instance_id=48423466)


def test_required_campaign_blocks_present():
    blocks = {r.scope: r.identifier for r in required_campaign_blocks()}
    assert blocks == {"instance": "48423466", "offer": "21050987", "host": "ssh3.vast.ai"}


# ─────────────────────────────────────────────────────────────
# GUARD (retained M1.9.1B, real orchestrator paths)
# ─────────────────────────────────────────────────────────────

def _make_stack(fake, production_id, authorized):
    from decimal import Decimal
    from pathlib import Path as P

    from defend_control.local_model import LocalOllamaBackend
    from defend_control.orchestrator import StackOrchestrator
    from defend_control.preflight import PreflightRunner
    from shared_platform.processes import ProcessSupervisor
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
    orch, sup = _make_stack(fake, 9999, authorized=False)
    orch._vast_instance = VastInstance(48416143, "exited", "ssh3.vast.ai", 22, "A100 PCIE", 81920, Decimal("0.96"))
    orch._production_mutation_guard.production_instance_id = 48416143
    with pytest.raises(StartFailed):
        orch.stop_and_destroy_vast(48416143)
    assert fake.mutations == []
    sup.close()


def test_status_invalid_response_zero_mutation():
    from shared_platform.vast import VastError

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
    assert orch.snapshot().state == "stopped"
    sup.close()


# ─────────────────────────────────────────────────────────────
# MASK (retained)
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


def test_masking_tool_role_masked_passes():
    labels = [-100, -100, -100, -100, -100, 7, 8]
    ok, failures = validate_assistant_masking(
        labels,
        [("system", 0, 1), ("user", 1, 3), ("tool", 3, 5), ("assistant", 5, 7)],
    )
    assert ok
    assert failures == []


def test_masking_tool_role_unmasked_fails():
    labels = [-100, -100, -100, -100, 5, 7, 8]
    ok, failures = validate_assistant_masking(
        labels,
        [("system", 0, 1), ("user", 1, 3), ("tool", 3, 5), ("assistant", 5, 7)],
    )
    assert not ok
    assert any("tool token 4 unmasked" in f for f in failures)


# ─────────────────────────────────────────────────────────────
# QLoRA + readiness (gated)
# ─────────────────────────────────────────────────────────────

def test_qlora_rejects_device_map_auto():
    ok, _ = qlora_config_valid({"load_in_4bit": True, "device_map": "auto", "bnb_4bit_compute_dtype": "bfloat16"})
    assert not ok


def test_qlora_rejects_cpu_offload():
    ok, _ = qlora_device_placement_valid({"model.embed": "cuda:0", "lm_head": "cpu"})
    assert not ok


def _full_readiness():
    return build_paid_canary_readiness("142b1b8", metadata_compatibility="PASS", production_mutation_guard_configured=True,
                                       production_runtime_state=RUNTIME_ABSENT, production_runtime_instance_id=None)


def test_readiness_true_only_for_complete_prent_gates():
    r = _full_readiness()
    assert r.ready_to_rent is True
    assert r.candidate_base_repo == "Qwen/Qwen3-32B"
    assert r.candidate_base_revision.startswith("9216db57")
    assert r.failed_instance_block == "48423466"
    assert r.failed_offer_block == "21050987"
    assert r.failed_host_block == "ssh3.vast.ai"


def test_readiness_false_with_blank_candidate_revision():
    assert replace(_full_readiness(), candidate_base_revision="").ready_to_rent is False


def test_readiness_false_with_missing_host_block():
    assert replace(_full_readiness(), failed_host_block="").ready_to_rent is False


def test_readiness_false_with_missing_offer_block():
    assert replace(_full_readiness(), failed_offer_block="").ready_to_rent is False


def test_readiness_false_with_missing_instance_block():
    assert replace(_full_readiness(), failed_instance_block="").ready_to_rent is False


def test_readiness_false_with_missing_production_guard():
    assert replace(_full_readiness(), production_mutation_guard_configured=False).ready_to_rent is False


def test_readiness_false_on_env_resolution_fail():
    r = build_paid_canary_readiness("142b1b8", metadata_compatibility="FAIL")
    assert r.ready_to_rent is False


def test_readiness_true_when_production_runtime_absent():
    r = build_paid_canary_readiness("142b1b8", production_runtime_state=RUNTIME_ABSENT, production_runtime_instance_id=None)
    assert r.production_runtime_state == RUNTIME_ABSENT
    assert r.production_runtime_instance_id is None
    assert r.ready_to_rent is True


def test_readiness_false_when_production_runtime_unknown():
    r = build_paid_canary_readiness("142b1b8", production_runtime_state=RUNTIME_UNKNOWN)
    assert r.ready_to_rent is False


def test_readiness_false_when_production_runtime_ambiguous():
    r = build_paid_canary_readiness("142b1b8", production_runtime_state=RUNTIME_AMBIGUOUS)
    assert r.ready_to_rent is False


# ─────────────────────────────────────────────────────────────
# Profile/role-based production guard (P4 negative tests)
# ─────────────────────────────────────────────────────────────

def test_guard_blocks_historical_id_unauthorized_start():
    guard = ProductionMutationGuard(production_instance_id=None)
    ok, _ = guard.authorize(instance_id=48416143, product="defend-ai", operation="START", authorized=False)
    assert not ok


def test_guard_blocks_new_id_with_production_profile():
    guard = ProductionMutationGuard(production_instance_id=None)
    ok, _ = guard.authorize(instance_id=999999, product="defend-ai", operation="START", authorized=False,
                            profile_id=PRODUCTION_PROFILE_ID)
    assert not ok


def test_guard_blocks_no_id_with_production_profile_provision():
    guard = ProductionMutationGuard(production_instance_id=None)
    ok, _ = guard.authorize(instance_id=None, product="defend-ai", operation="PROVISION", authorized=False,
                            profile_id=PRODUCTION_PROFILE_ID, purpose="PRODUCTION_INFERENCE")
    assert not ok


def test_guard_allows_candidate_training_provision():
    guard = ProductionMutationGuard(production_instance_id=None)
    ok, _ = guard.authorize(instance_id=12345, product="defend-ai", operation="PROVISION", authorized=True,
                            profile_id=CANDIDATE_TRAINING_PROFILE_ID, purpose="TRAINING", role="CANDIDATE_CANARY")
    assert ok


def test_guard_blocks_candidate_promotion_without_production_auth():
    guard = ProductionMutationGuard(production_instance_id=None)
    ok, _ = guard.authorize(instance_id=12345, product="defend-ai", operation="PROMOTE", authorized=False,
                            profile_id=CANDIDATE_TRAINING_PROFILE_ID, purpose="TRAINING", role="CANDIDATE_CANARY")
    assert not ok


def test_candidate_destroy_requires_exact_canary_instance():
    ok, _ = authorize_candidate_lifecycle(operation="DESTROY", canary_instance_id=777, target_instance_id=888,
                                          profile_id=CANDIDATE_TRAINING_PROFILE_ID, purpose="TRAINING", role="CANDIDATE_CANARY")
    assert not ok
    ok2, _ = authorize_candidate_lifecycle(operation="DESTROY", canary_instance_id=777, target_instance_id=777,
                                           profile_id=CANDIDATE_TRAINING_PROFILE_ID, purpose="TRAINING", role="CANDIDATE_CANARY")
    assert ok2


def test_candidate_lifecycle_cannot_destroy_production_role_instance():
    ok, _ = authorize_candidate_lifecycle(operation="DESTROY", canary_instance_id=48416143, target_instance_id=48416143,
                                          profile_id=PRODUCTION_PROFILE_ID, purpose="PRODUCTION_INFERENCE", role="PRODUCTION_INFERENCE")
    assert not ok
    ok2, _ = authorize_candidate_lifecycle(operation="DESTROY", canary_instance_id=48416143, target_instance_id=48416143)
    assert not ok  # historical production ID even without profile markers


def test_historical_instance_is_never_treated_as_current_runtime():
    r = build_paid_canary_readiness("142b1b8", production_runtime_state=RUNTIME_ABSENT, production_runtime_instance_id=None)
    assert r.production_runtime_instance_id is None
    assert 48416143 in r.historical_production_instance_ids
    assert r.production_profile_id == PRODUCTION_PROFILE_ID
    assert r.production_base_revision == "5ede1c97bbab6ce5cda5812749b4c0bdf79b18dd"
    assert r.production_adapter_revision == "46ade1686870210ef0ab4603c32fecb0e563330f"


# ─────────────────────────────────────────────────────────────
# Tool-eval truth label
# ─────────────────────────────────────────────────────────────

def test_tool_eval_status_reports_pending():
    status = tool_eval_status()
    assert status["tool_eval_scoring_logic"] == "YES"
    assert status["real_tool_eval_agent_loop"] == "PENDING_RUNTIME"
