"""M1.9.2C1 tests: label-based production inventory, authoritative
certification with real SHA gates, and the dependency-injected paid executor
lifecycle (success + failure injection) with zero real provider mutations."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from defend_ai.qwen3_canary_executor import (
    CanaryRunResult,
    PaidCanaryCertification,
    ProductionInventory,
    Qwen3CanaryExecutor,
    build_certification,
    candidate_canary_resource_profile,
    classify_production_inventory,
)
from defend_ai.qwen3_canary_runner import (
    CANARY_OWNER_AUTHORIZATION,
    EXPECTED_CONVERTED_SHA,
    EXPECTED_HELDOUT_SHA,
    CanaryPolicy,
    validate_five_steps,
)
from defend_ai.training_hardening import (
    INVENTORY_AMBIGUOUS,
    INVENTORY_NONE_FOUND,
    INVENTORY_ONE_EXACT_REPLACEMENT,
    INVENTORY_UNKNOWN,
)
from defend_control.types import LaunchSpec, VastOffer

TRAIN_FILE = Path(r"C:\Users\thoma\Downloads\DEFEND32B\TRAINING\defend_sft_train_v1_merged.jsonl")
HELDOUT_FILE = Path(r"C:\Users\thoma\Downloads\DEFEND32B\DEFEND_EVAL_HELD_OUT_200.jsonl")


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# P3 â€” production inventory (label identity + completeness)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _inst(*items):
    return [dict(i) for i in items]



def _v2(stage, status, steps=None, run_id="RUN", adapter_dir=None):
    import json as _json
    if adapter_dir:
        parts = adapter_dir.replace("\\", "/").rstrip("/").split("/")
        if len(parts) >= 2 and parts[0] == "canary-artifacts":
            run_id = parts[1]
    r = {"protocol_version": "DEFEND_CANARY_RESULT_V2", "run_id": run_id, "stage": stage, "status": status}
    if steps is not None:
        r["steps_completed"] = steps
    return "DEFEND_CANARY_RESULT=" + _json.dumps(r)

def test_inventory_zero_instances_absent():
    inv = classify_production_inventory([])
    assert inv.status == INVENTORY_NONE_FOUND


def test_inventory_lone_coder_absent():
    inv = classify_production_inventory(_inst({"id": 1, "label": "defendcoder-vllm", "actual_status": "running"}))
    assert inv.status == INVENTORY_NONE_FOUND


def test_inventory_lone_candidate_absent():
    inv = classify_production_inventory(_inst({"id": 2, "label": "defend-ai-qwen3-candidate-canary", "actual_status": "running"}))
    assert inv.status == INVENTORY_NONE_FOUND


def test_inventory_coder_plus_candidate_absent():
    inv = classify_production_inventory(_inst(
        {"id": 1, "label": "defendcoder-vllm", "actual_status": "running"},
        {"id": 2, "label": "defend-ai-qwen3-candidate-canary", "actual_status": "running"},
    ))
    assert inv.status == INVENTORY_NONE_FOUND


def test_inventory_one_production_stopped():
    inv = classify_production_inventory(_inst({"id": 48416143, "label": "defend-vllm", "actual_status": "stopped"}))
    assert inv.status == INVENTORY_ONE_EXACT_REPLACEMENT
    assert inv.findings[0].instance_id == 48416143


def test_inventory_production_plus_coder():
    inv = classify_production_inventory(_inst(
        {"id": 7, "label": "defend-vllm", "actual_status": "running"},
        {"id": 9, "label": "defendcoder-vllm", "actual_status": "running"},
    ))
    assert inv.status == INVENTORY_ONE_EXACT_REPLACEMENT


def test_inventory_two_production_ambiguous():
    inv = classify_production_inventory(_inst(
        {"id": 1, "label": "defend-vllm", "actual_status": "stopped"},
        {"id": 2, "label": "defend-vllm", "actual_status": "stopped"},
    ))
    assert inv.status == INVENTORY_AMBIGUOUS


def test_inventory_malformed_production_unknown():
    inv = classify_production_inventory(_inst({"label": "defend-vllm"}))  # missing id
    assert inv.status == INVENTORY_UNKNOWN


def test_inventory_incomplete_unknown():
    inv = classify_production_inventory(_inst({"id": 1, "label": "defend-vllm", "actual_status": "stopped"}), complete=False)
    assert inv.status == INVENTORY_UNKNOWN
    assert inv.complete is False


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# P20-P21 â€” candidate resource profile (A100 80GB only)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def test_candidate_resource_profile_is_a100_80gb():
    p = candidate_canary_resource_profile()
    assert p.allowed_gpu_families == ("A100",)
    assert p.min_gpu_ram_mb == 80_000
    assert p.num_gpus == 1


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# P4-P7 â€” authoritative certification (real gates)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _load_rows():
    return [json.loads(line) for line in TRAIN_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]


def _cert(rows, heldout=HELDOUT_FILE, **kw):
    return build_certification(
        train_rows=rows,
        heldout_file=Path(heldout),
        inventory=ProductionInventory(INVENTORY_NONE_FOUND, True, ()),
        tokenizer_proof_status=kw.get("tokenizer", "PASS"),
        masking_ok=kw.get("masking", True),
        requested_steps=kw.get("steps", 5),
    )


def test_certification_converted_sha_matches():
    if not TRAIN_FILE.exists():
        pytest.skip("train file missing")
    cert = _cert(_load_rows())
    assert cert.converted_sha == EXPECTED_CONVERTED_SHA
    assert cert.training_data_sha_valid is True


def test_certification_heldout_sha_matches():
    if not TRAIN_FILE.exists() or not HELDOUT_FILE.exists():
        pytest.skip("files missing")
    cert = _cert(_load_rows())
    assert cert.heldout_sha == EXPECTED_HELDOUT_SHA
    assert cert.heldout_sha_valid is True


def test_certification_heldout_missing_fails():
    if not TRAIN_FILE.exists():
        pytest.skip("train file missing")
    cert = _cert(_load_rows(), heldout=r"C:\nonexistent\heldout.jsonl")
    assert cert.heldout_sha_valid is False
    assert cert.final_paid_readiness is False


def test_certification_overlap_zero():
    if not TRAIN_FILE.exists() or not HELDOUT_FILE.exists():
        pytest.skip("files missing")
    cert = _cert(_load_rows())
    assert cert.train_heldout_overlap == 0


def test_certification_wrong_converted_sha_fails(monkeypatch):
    if not TRAIN_FILE.exists():
        pytest.skip("train file missing")
    monkeypatch.setattr("defend_ai.qwen3_canary_executor.EXPECTED_CONVERTED_SHA", "0" * 64)
    cert = _cert(_load_rows())
    assert cert.training_data_sha_valid is False
    assert cert.final_paid_readiness is False


def test_certification_unknown_runtime_not_ready():
    rows = _load_rows() if TRAIN_FILE.exists() else []
    cert = build_certification(
        train_rows=rows, heldout_file=HELDOUT_FILE,
        inventory=ProductionInventory(INVENTORY_UNKNOWN, False, ()),
        tokenizer_proof_status="PASS", masking_ok=True, requested_steps=5,
    )
    assert cert.final_paid_readiness is False


def test_certification_full_ready():
    if not TRAIN_FILE.exists() or not HELDOUT_FILE.exists():
        pytest.skip("files missing")
    cert = _cert(_load_rows())
    assert cert.final_paid_readiness is True


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# P16-P17, P27-P31 â€” executor lifecycle (fake provider/host)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class FakeVast:
    def __init__(self, destroy_ok=True, absent_ok=True):
        self.mutations = []
        self.destroy_ok = destroy_ok
        self.absent_ok = absent_ok

    def inventory(self):
        return ProductionInventory(INVENTORY_NONE_FOUND, True, ())

    def select_offer(self, policy):
        return VastOffer(123, "A100 PCIE", 81920, Decimal("0.96"), Decimal("0.99"))

    def create(self, offer):
        self.mutations.append("create")
        return SimpleNamespace(instance_id=999, dph_total=Decimal("0.96"))

    def destroy(self, instance_id):
        self.mutations.append("destroy")
        return self.destroy_ok

    def instance_state(self, instance_id):
        return "ABSENT" if self.absent_ok else "PRESENT"

    def resolve_target(self, instance_id):
        return {"host": "x.vast.ai", "port": 22, "user": "root"}


class FakeRemote:
    def __init__(self, fail_stage=None):
        self.calls = []
        self.fail_stage = fail_stage
        self._target = None

    def bind_target(self, target):
        self._target = target

    def run_stage(self, stage, instance_id, adapter_dir, timeout_seconds=None):
        self.calls.append(stage)
        if stage == self.fail_stage:
            return {"returncode": 1, "stdout": "", "stderr": f"injected {stage}"}
        if stage == "TRAIN_5_STEPS":
            return {"returncode": 0, "stdout": _v2('TRAIN_5_STEPS', 'PASS', steps=5, adapter_dir=adapter_dir), "stderr": ""}
        return {"returncode": 0, "stdout": _v2(stage, 'PASS', adapter_dir=adapter_dir), "stderr": ""}


EXPECTED_STAGES = [
    "HOST_PREFLIGHT", "TRAIN_5_STEPS", "FRESH_RELOAD",
]


def _run(fail_stage=None, destroy_ok=True, absent_ok=True):
    vast = FakeVast(destroy_ok=destroy_ok, absent_ok=absent_ok)
    remote = FakeRemote(fail_stage=fail_stage)
    ex = Qwen3CanaryExecutor(policy=CanaryPolicy(), vast=vast, remote=remote, clock=lambda: 0.0, sleep=lambda s: None)
    result = ex.run()
    return result, vast, remote


def test_executor_success_lifecycle():
    result, vast, remote = _run()
    assert result.status == "SUCCESS"
    assert result.provider_mutations == 2  # create + destroy
    assert vast.mutations == ["create", "destroy"]
    assert result.steps_completed == 5
    assert remote.calls == EXPECTED_STAGES
    assert result.billing_termination_verified is True
    assert result.billing_risk == "NONE"


def test_executor_exactly_one_create_one_destroy():
    result, vast, _ = _run()
    assert vast.mutations.count("create") == 1
    assert vast.mutations.count("destroy") == 1


def test_executor_preflight_failure_teardown():
    result, vast, remote = _run(fail_stage="HOST_PREFLIGHT")
    assert "create" in vast.mutations and "destroy" in vast.mutations
    assert result.status == "FAILED"
    assert result.steps_completed == 0


def test_executor_model_load_failure_teardown():
    result, vast, _ = _run(fail_stage="QLORA_LOAD")
    assert vast.mutations.count("destroy") == 1


def test_executor_step3_failure_teardown():
    result, vast, _ = _run(fail_stage="TRAIN_5_STEPS")
    assert vast.mutations.count("destroy") == 1
    assert result.status == "FAILED"


def test_executor_reload_failure_teardown():
    result, vast, _ = _run(fail_stage="FRESH_RELOAD")
    assert vast.mutations.count("destroy") == 1


def test_executor_destroy_failure_billing_risk_high():
    result, vast, _ = _run(destroy_ok=False)
    assert result.billing_risk == "HIGH"
    assert result.billing_termination_verified is False


def test_executor_absent_not_verified_billing_risk():
    result, _, _ = _run(absent_ok=False)
    assert result.billing_termination_verified is False
    assert result.billing_risk == "HIGH"


def test_executor_no_offer_does_not_create():
    class NoOfferVast(FakeVast):
        def select_offer(self, policy):
            return None
    vast = NoOfferVast()
    ex = Qwen3CanaryExecutor(policy=CanaryPolicy(), vast=vast, remote=FakeRemote(), clock=lambda: 0.0, sleep=lambda s: None)
    result = ex.run()
    assert result.status == "CANARY_NOT_STARTED"
    assert vast.mutations == []
    assert result.provider_mutations == 0


def test_executor_binds_git_head_and_run_scoped_adapter():
    vast = FakeVast()
    ex = Qwen3CanaryExecutor(policy=CanaryPolicy(), vast=vast, remote=FakeRemote(), clock=lambda: 0.0,
                             sleep=lambda s: None, run_id="abc123", git_head="42433eda3cf0ac0ca3fb07f9d9dce275b8259ebf")
    result = ex.run()
    assert result.git_head == "42433eda3cf0ac0ca3fb07f9d9dce275b8259ebf"
    assert result.adapter_dir == "canary-artifacts/abc123/adapter"


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# P18-P19 â€” paid CLI authorization gate
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def test_cli_paid_requires_authorization():
    import tools.defend_ai_qwen3_canary as cli
    assert cli.main(["--execute-paid-canary"]) == 2  # no auth -> no rent


def test_cli_paid_wrong_authorization():
    import tools.defend_ai_qwen3_canary as cli
    assert cli.main(["--execute-paid-canary", "--owner-authorization", "WRONG"]) == 2


def test_run_paid_canary_wires_to_executor_with_fakes():
    import tools.defend_ai_qwen3_canary as cli
    vast = FakeVast()
    remote = FakeRemote()
    cert = _cert_full()
    policy = CanaryPolicy()
    result = cli.run_paid_canary(cert=cert, policy=policy, vast_gateway=vast, remote_host=remote, git_head="x")
    assert vast.mutations.count("create") == 1
    assert vast.mutations.count("destroy") == 1
    assert result.status == "SUCCESS"


def test_run_paid_canary_blocked_when_readiness_false():
    import tools.defend_ai_qwen3_canary as cli
    vast = FakeVast()
    remote = FakeRemote()
    cert = _cert_full()
    cert = cert.__class__(**{**cert.__dict__, "training_data_sha_valid": False})
    result = cli.run_paid_canary(cert=cert, policy=CanaryPolicy(), vast_gateway=vast, remote_host=remote, git_head="x")
    assert result.status == "BLOCKED_READINESS"
    assert vast.mutations == []


def test_five_steps_locked():
    assert validate_five_steps(10)[0] is False
    assert validate_five_steps(5)[0] is True


def test_training_parser_rejects_forbidden_flags():
    from defend_ai.qwen3_canary_train import parse_args
    with pytest.raises(SystemExit):
        parse_args(["--data-file", "x", "--adapter-dir", "y", "--steps", "10"])
    with pytest.raises(SystemExit):
        parse_args(["--data-file", "x", "--adapter-dir", "y", "--full-train"])


def test_training_parser_rejects_wrong_base_revision():
    from defend_ai.qwen3_canary_train import parse_args
    with pytest.raises(SystemExit):
        parse_args(["--data-file", "x", "--adapter-dir", "y", "--base-revision", "deadbeef"])


def test_reload_rejects_wrong_base_revision(capsys):
    from defend_ai.qwen3_canary_reload import main as reload_main
    assert reload_main(["--adapter-dir", "x", "--run-id", "RUN", "--base-revision", "deadbeef"]) == 5


def test_reload_parser_and_peft_validation(tmp_path):
    from defend_ai.qwen3_canary_reload import _validate_adapter_dir
    ok, _ = _validate_adapter_dir(tmp_path)
    assert not ok  # empty dir -> no PEFT artifacts
    (tmp_path / "adapter_config.json").write_text("{}")
    (tmp_path / "adapter_model.safetensors").write_bytes(b"x")
    ok2, _ = _validate_adapter_dir(tmp_path)
    assert ok2


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# C2 â€” executor fail-closed + offer/price validation
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _cert_full():
    rows = _load_rows() if TRAIN_FILE.exists() else []
    return build_certification(
        train_rows=rows, heldout_file=HELDOUT_FILE,
        inventory=ProductionInventory(INVENTORY_NONE_FOUND, True, ()),
        tokenizer_proof_status="PASS", masking_ok=True, requested_steps=5,
    )


def _executor_with(inventory, offer=None, created_rate=Decimal("0.96")):
    class V(FakeVast):
        def inventory(self):
            return inventory
        def select_offer(self, policy):
            return offer if offer is not None else VastOffer(123, "A100 PCIE", 81920, Decimal("0.96"), Decimal("0.99"))
        def create(self, offer):
            self.mutations.append("create")
            if created_rate is None:
                return SimpleNamespace(instance_id=999, dph_total=None)
            return SimpleNamespace(instance_id=999, dph_total=created_rate)
    vast = V()
    ex = Qwen3CanaryExecutor(policy=CanaryPolicy(), vast=vast, remote=FakeRemote(), clock=lambda: 0.0, sleep=lambda s: None)
    return ex.run(), vast


def test_executor_unknown_inventory_no_create():
    result, vast = _executor_with(ProductionInventory(INVENTORY_UNKNOWN, True, ()))
    assert vast.mutations == []
    assert result.status == "CANARY_NOT_STARTED"


def test_executor_ambiguous_inventory_no_create():
    result, vast = _executor_with(ProductionInventory(INVENTORY_AMBIGUOUS, True, ()))
    assert vast.mutations == []


def test_executor_incomplete_inventory_no_create():
    result, vast = _executor_with(ProductionInventory(INVENTORY_NONE_FOUND, False, ()))
    assert vast.mutations == []


def test_executor_invalid_offer_gpu_no_create():
    bad = VastOffer(124, "RTX 4090", 24000, Decimal("0.50"), Decimal("0.99"))
    result, vast = _executor_with(ProductionInventory(INVENTORY_NONE_FOUND, True, ()), offer=bad)
    assert vast.mutations == []


def test_executor_offer_over_rate_no_create():
    bad = VastOffer(125, "A100 PCIE", 81920, Decimal("1.21"), Decimal("0.99"))
    result, vast = _executor_with(ProductionInventory(INVENTORY_NONE_FOUND, True, ()), offer=bad)
    assert vast.mutations == []


def test_executor_failed_offer_no_create():
    bad = VastOffer(21050987, "A100 PCIE", 81920, Decimal("0.96"), Decimal("0.99"))
    result, vast = _executor_with(ProductionInventory(INVENTORY_NONE_FOUND, True, ()), offer=bad)
    assert vast.mutations == []


def test_executor_created_missing_price_teardown():
    result, vast = _executor_with(ProductionInventory(INVENTORY_NONE_FOUND, True, ()), created_rate=None)
    assert vast.mutations.count("destroy") == 1
    assert result.billing_risk == "HIGH"


def test_executor_created_rate_over_cap_teardown():
    result, vast = _executor_with(ProductionInventory(INVENTORY_NONE_FOUND, True, ()), created_rate=Decimal("1.30"))
    assert vast.mutations.count("destroy") == 1
