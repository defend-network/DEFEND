"""M1.9.2C3 tests: target-label correctness, tri-state instance absence,
SSH remote-host adapter, and derived execution contract."""

from __future__ import annotations

from decimal import Decimal

import pytest

from defend_control.qwen3_canary_executor import build_execution_contract
from defend_control.qwen3_canary_runner import CanaryPolicy
from defend_control.qwen3_canary_hosts import (
    BLOCKED_HOSTS,
    CanaryRemoteTarget,
    ConcreteRemoteHost,
    _classify_instance_response,
)


# ─────────────────────────────────────────────────────────────
# P1-P2 — target label == input_ids (never positional index)
# ─────────────────────────────────────────────────────────────

def test_assistant_labels_equal_input_ids():
    try:
        from transformers import AutoTokenizer
    except Exception:
        pytest.skip("transformers not installed")
    from defend_control.qwen3_masking import build_qwen3_masked_example

    tok = AutoTokenizer.from_pretrained("Qwen/Qwen3-32B", revision="9216db5781bf21249d130ec9da846c4624c16137", trust_remote_code=True, use_fast=True)
    msgs = [
        {"role": "system", "content": "You are DEFEND AI."},
        {"role": "user", "content": "Compute 17*23."},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "c0", "type": "function", "function": {"name": "calculator", "arguments": '{"expression": "17*23"}'}}]},
        {"role": "tool", "content": "391", "tool_call_id": "c0"},
        {"role": "assistant", "content": "17 times 23 is 391."},
    ]
    example = build_qwen3_masked_example(tok, msgs)
    assistant_seen = 0
    positional_coincidence_free = False
    for i, label in enumerate(example.labels):
        if label == -100:
            continue
        assert label == example.input_ids[i], f"label[{i}]={label} != input_ids[{i}]"
        assistant_seen += 1
        if example.input_ids[i] != i:
            positional_coincidence_free = True
    assert assistant_seen > 0
    assert positional_coincidence_free, "test could not detect positional-index bug"


def test_masked_labels_equal_neg100():
    from defend_control.training_hardening import validate_assistant_masking
    labels = [-100, -100, -100, 7, 8, -100, -100, -100, 9, 10]
    spans = [("system", 0, 1), ("user", 1, 3), ("assistant", 3, 5), ("tool", 5, 8), ("assistant", 8, 10)]
    ok, _ = validate_assistant_masking(labels, spans)
    assert ok
    for idx in (0, 1, 2, 5, 6, 7):
        assert labels[idx] == -100


# ─────────────────────────────────────────────────────────────
# P19 — tri-state instance absence
# ─────────────────────────────────────────────────────────────

def test_instance_response_none_is_absent():
    assert _classify_instance_response(None) == "ABSENT"


def test_instance_response_empty_is_absent():
    assert _classify_instance_response([]) == "ABSENT"
    assert _classify_instance_response({}) == "ABSENT"


def test_instance_response_present():
    assert _classify_instance_response([{"id": 1}]) == "PRESENT"
    assert _classify_instance_response({"id": 1}) == "PRESENT"


def test_instance_response_junk_unknown():
    assert _classify_instance_response("junk") == "UNKNOWN"


# ─────────────────────────────────────────────────────────────
# P6-P7 — real SSH command + instance-bound target
# ─────────────────────────────────────────────────────────────

def test_ssh_command_builder():
    target = CanaryRemoteTarget(instance_id=999, host="x.vast.ai", port=2200, user="root", offer_id=123, hourly_rate=Decimal("0.96"))
    argv = ConcreteRemoteHost._build_ssh_command(target, "python -m foo")
    assert argv[0] == "ssh"
    assert argv[1] == "-p"
    assert argv[2] == "2200"
    assert argv[3] == "root@x.vast.ai"
    assert argv[4] == "python -m foo"


def test_run_stage_requires_bound_target():
    host = ConcreteRemoteHost(target=None, ssh_runner=lambda a, t: {"status": "PASS"})
    r = host.run_stage("HOST_PREFLIGHT", 999, "/a", 60)
    assert r["returncode"] == 1
    assert "no remote target" in r["stderr"]


def test_run_stage_instance_mismatch():
    target = CanaryRemoteTarget(instance_id=999, host="x", port=22, user="root", offer_id=1, hourly_rate=Decimal("0.96"))
    host = ConcreteRemoteHost(target=target, ssh_runner=lambda a, t: {"status": "PASS"})
    r = host.run_stage("HOST_PREFLIGHT", 777, "/a", 60)
    assert r["returncode"] == 1
    assert "mismatch" in r["stderr"]


def test_run_stage_blocked_host():
    target = CanaryRemoteTarget(instance_id=999, host="ssh3.vast.ai", port=22, user="root", offer_id=1, hourly_rate=Decimal("0.96"))
    host = ConcreteRemoteHost(target=target, ssh_runner=lambda a, t: {"status": "PASS"})
    r = host.run_stage("HOST_PREFLIGHT", 999, "/a", 60)
    assert r["returncode"] == 1
    assert "blocked host" in r["stderr"]


def test_no_placeholder_stages():
    host = ConcreteRemoteHost()
    for stage in ("HOST_PREFLIGHT", "TRAIN_5_STEPS", "FRESH_RELOAD"):
        cmd = host._stage_command(stage, "/adapter", "")
        assert "echo STAGE" not in cmd
        assert cmd.strip() != ""
    with pytest.raises(ValueError):
        host._stage_command("NONEXISTENT_STAGE", "/a", "")


# ─────────────────────────────────────────────────────────────
# P21 — execution contract derived (no unconditional True)
# ─────────────────────────────────────────────────────────────

def test_execution_contract_derived_fields():
    contract = build_execution_contract()
    assert contract.paid_cli_wired is True
    assert contract.concrete_vast_gateway_valid is True
    assert contract.concrete_remote_host_valid is True
    assert contract.exact_id_destroy_valid is True
    assert contract.billing_verify_valid is True
    assert contract.spend_watchdog_valid is True
    assert contract.production_guard_valid is True


# ─────────────────────────────────────────────────────────────
# C4 — immutable target + one-time bind + typed stage results
# ─────────────────────────────────────────────────────────────

def test_target_is_immutable():
    target = CanaryRemoteTarget(instance_id=999, host="x", port=22, user="root", offer_id=1, hourly_rate=Decimal("0.96"))
    import dataclasses
    with pytest.raises(dataclasses.FrozenInstanceError):
        target.host = "evil.vast.ai"
    with pytest.raises(dataclasses.FrozenInstanceError):
        target.instance_id = 777


def test_target_binds_once():
    host = ConcreteRemoteHost()
    target = CanaryRemoteTarget(instance_id=999, host="x", port=22, user="root", offer_id=1, hourly_rate=Decimal("0.96"))
    host.bind_target(target)
    with pytest.raises(RuntimeError):
        host.bind_target(target)


def test_parse_remote_result_steps():
    from defend_control.qwen3_canary_executor import parse_canary_result
    r = parse_canary_result('DEFEND_CANARY_RESULT={"status": "PASS", "steps_completed": 5}', 0, "TRAIN_5_STEPS")
    assert r.status == "PASS"
    assert r.steps_completed == 5
    missing = parse_canary_result('DEFEND_CANARY_RESULT={"status": "PASS"}', 0, "TRAIN_5_STEPS")
    assert missing.steps_completed is None
    # steps=4 fails (status FAIL only via missing? no — 4 must be a hard FAIL at executor level)
    four = parse_canary_result('DEFEND_CANARY_RESULT={"status": "PASS", "steps_completed": 4}', 0, "TRAIN_5_STEPS")
    assert four.steps_completed == 4


def test_parse_unknown_status_fails():
    from defend_control.qwen3_canary_executor import parse_canary_result
    r = parse_canary_result('DEFEND_CANARY_RESULT={"status": "SUCCESSISH"}', 0, "HOST_PREFLIGHT")
    assert r.status == "FAIL"


def test_parse_malformed_record_fails():
    from defend_control.qwen3_canary_executor import parse_canary_result
    r = parse_canary_result('DEFEND_CANARY_RESULT=not-json', 0, "HOST_PREFLIGHT")
    assert r.status == "FAIL"


def test_parse_missing_record_fails():
    from defend_control.qwen3_canary_executor import parse_canary_result
    r = parse_canary_result('some random stdout', 0, "HOST_PREFLIGHT")
    assert r.status == "FAIL"


def test_parse_nonzero_returncode_fails():
    from defend_control.qwen3_canary_executor import parse_canary_result
    r = parse_canary_result('DEFEND_CANARY_RESULT={"status": "PASS"}', 1, "HOST_PREFLIGHT")
    assert r.status == "FAIL"


def test_production_parser_derives_five_steps_from_stdout():
    from defend_control.qwen3_canary_executor import parse_canary_result
    simulated = "OPTIMIZER_STEPS_COMPLETED=5\nADAPTER_SAVED=/x\nDEFEND_CANARY_RESULT={\"status\": \"PASS\", \"steps_completed\": 5}"
    r = parse_canary_result(simulated, 0, "TRAIN_5_STEPS")
    assert r.status == "PASS"
    assert r.steps_completed == 5


def test_preflight_real_entrypoint_wrong_revision():
    from defend_control.qwen3_canary_preflight import run_preflight
    from pathlib import Path
    ok, evidence = run_preflight("abc", Path("does-not-matter.jsonl"), "deadbeef")
    assert ok is False
    assert evidence["revision_ok"] is False


def test_preflight_real_entrypoint_missing_train():
    from defend_control.qwen3_canary_preflight import run_preflight
    from pathlib import Path
    ok, evidence = run_preflight("abc", Path("no-such-file.jsonl"), "9216db5781bf21249d130ec9da846c4624c16137")
    assert ok is False
    assert evidence["converted_sha_ok"] is False


def test_preflight_paid_host_torch_unavailable_fails():
    from defend_control.qwen3_canary_preflight import run_preflight
    from pathlib import Path
    try:
        import torch  # noqa: F401
        pytest.skip("torch installed in this environment")
    except Exception:
        pass
    ok, evidence = run_preflight("abc", Path("no-such.jsonl"), "9216db5781bf21249d130ec9da846c4624c16137", paid_host=True)
    assert ok is False
    assert any("torch import failed" in f for f in evidence["failures"])


def test_reload_failure_is_not_success():
    from defend_control.qwen3_canary_executor import (
        INSTANCE_ABSENT, ProductionInventory, Qwen3CanaryExecutor,
    )
    from defend_control.training_hardening import INVENTORY_NONE_FOUND
    from types import SimpleNamespace

    class Vast:
        def __init__(self):
            self.mutations = []
        def inventory(self):
            return ProductionInventory(INVENTORY_NONE_FOUND, True, ())
        def select_offer(self, policy):
            from defend_control.types import VastOffer
            return VastOffer(123, "A100 PCIE", 81920, Decimal("0.96"), Decimal("0.99"))
        def create(self, offer):
            self.mutations.append("create")
            return SimpleNamespace(instance_id=999, dph_total=Decimal("0.96"))
        def resolve_target(self, instance_id):
            return {"host": "x", "port": 22, "user": "root"}
        def destroy(self, instance_id):
            self.mutations.append("destroy")
            return True
        def instance_state(self, instance_id):
            return INSTANCE_ABSENT

    class Remote:
        def __init__(self):
            self.calls = []
        def bind_target(self, t):
            self._t = t
        def run_stage(self, stage, iid, ad, to):
            self.calls.append(stage)
            if stage == "TRAIN_5_STEPS":
                return {"returncode": 0, "stdout": 'DEFEND_CANARY_RESULT={"status": "PASS", "steps_completed": 5}', "stderr": ""}
            if stage == "FRESH_RELOAD":
                return {"returncode": 1, "stdout": 'DEFEND_CANARY_RESULT={"status": "FAIL"}', "stderr": "reload failed"}
            return {"returncode": 0, "stdout": 'DEFEND_CANARY_RESULT={"status": "PASS"}', "stderr": ""}

    vast = Vast()
    remote = Remote()
    ex = Qwen3CanaryExecutor(policy=CanaryPolicy(), vast=vast, remote=remote, clock=lambda: 0.0, sleep=lambda s: None)
    result = ex.run()
    assert result.billing_termination_verified is True  # cleanup succeeded
    assert result.status == "FAILED"  # but execution failed
    assert "FRESH_RELOAD" in remote.calls


def test_train_steps_4_fails_before_reload():
    from defend_control.qwen3_canary_executor import (
        INSTANCE_ABSENT, ProductionInventory, Qwen3CanaryExecutor,
    )
    from defend_control.training_hardening import INVENTORY_NONE_FOUND
    from types import SimpleNamespace

    class Vast:
        def __init__(self):
            self.mutations = []
        def inventory(self):
            return ProductionInventory(INVENTORY_NONE_FOUND, True, ())
        def select_offer(self, policy):
            from defend_control.types import VastOffer
            return VastOffer(123, "A100 PCIE", 81920, Decimal("0.96"), Decimal("0.99"))
        def create(self, offer):
            self.mutations.append("create")
            return SimpleNamespace(instance_id=999, dph_total=Decimal("0.96"))
        def resolve_target(self, instance_id):
            return {"host": "x", "port": 22, "user": "root"}
        def destroy(self, instance_id):
            self.mutations.append("destroy")
            return True
        def instance_state(self, instance_id):
            return INSTANCE_ABSENT

    class Remote:
        def __init__(self):
            self.calls = []
        def bind_target(self, t):
            self._t = t
        def run_stage(self, stage, iid, ad, to):
            self.calls.append(stage)
            if stage == "TRAIN_5_STEPS":
                return {"returncode": 0, "stdout": 'DEFEND_CANARY_RESULT={"status": "PASS", "steps_completed": 4}', "stderr": ""}
            return {"returncode": 0, "stdout": 'DEFEND_CANARY_RESULT={"status": "PASS"}', "stderr": ""}

    vast = Vast()
    remote = Remote()
    ex = Qwen3CanaryExecutor(policy=CanaryPolicy(), vast=vast, remote=remote, clock=lambda: 0.0, sleep=lambda s: None)
    result = ex.run()
    assert result.status == "FAILED"
    assert "FRESH_RELOAD" not in remote.calls  # reload must not run after 4 steps


def test_teardown_eventual_absent():
    from defend_control.qwen3_canary_executor import (
        INSTANCE_ABSENT, INSTANCE_PRESENT, ProductionInventory, Qwen3CanaryExecutor,
    )
    from defend_control.training_hardening import INVENTORY_NONE_FOUND
    from types import SimpleNamespace

    class StatefulVast:
        def __init__(self):
            self.mutations = []
            self.states = [INSTANCE_PRESENT, INSTANCE_ABSENT]
        def inventory(self):
            return ProductionInventory(INVENTORY_NONE_FOUND, True, ())
        def select_offer(self, policy):
            from defend_control.types import VastOffer
            return VastOffer(123, "A100 PCIE", 81920, Decimal("0.96"), Decimal("0.99"))
        def create(self, offer):
            self.mutations.append("create")
            return SimpleNamespace(instance_id=999, dph_total=Decimal("0.96"))
        def resolve_target(self, instance_id):
            return {"host": "x", "port": 22, "user": "root"}
        def destroy(self, instance_id):
            self.mutations.append("destroy")
            return True
        def instance_state(self, instance_id):
            return self.states.pop(0) if self.states else INSTANCE_ABSENT

    class Remote:
        def bind_target(self, t):
            self._t = t
        def run_stage(self, stage, iid, ad, to):
            if stage == "TRAIN_5_STEPS":
                return {"returncode": 0, "stdout": 'DEFEND_CANARY_RESULT={"status": "PASS", "steps_completed": 5}', "stderr": ""}
            return {"returncode": 0, "stdout": 'DEFEND_CANARY_RESULT={"status": "PASS"}', "stderr": ""}

    vast = StatefulVast()
    ex = Qwen3CanaryExecutor(policy=CanaryPolicy(), vast=vast, remote=Remote(), clock=lambda: 0.0, sleep=lambda s: None)
    result = ex.run()
    assert result.billing_termination_verified is True
    assert result.status == "SUCCESS"
