"""M1.9.2C tests: fail-closed readiness/inventory/production-identity, candidate
launch isolation + create allowlist + cross-binding, and the dry-run canary
runner contracts (zero provider mutations)."""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from defend_control.qwen3_canary_runner import (
    CANARY_HARD_SPEND_CAP_USD,
    CANARY_MAX_HOURLY_USD,
    CANARY_MAX_INSTANCES,
    CANARY_SANITY_PROMPT,
    CanaryPhase,
    CanaryPolicy,
    Qwen3CanaryRunner,
    build_fresh_reload_command,
    masking_contract_ok,
    run_real_tokenizer_proof,
    validate_five_steps,
    validate_qlora_contract,
)
from defend_control.training_hardening import (
    CANDIDATE_CANARY_LABEL,
    CANDIDATE_CANARY_PURPOSE,
    CANDIDATE_CANARY_ROLE,
    CANDIDATE_TRAINING_PROFILE_ID,
    INVENTORY_AMBIGUOUS,
    INVENTORY_NONE_FOUND,
    INVENTORY_ONE_EXACT_REPLACEMENT,
    PRODUCTION_PROFILE_ID,
    RUNTIME_ABSENT,
    RUNTIME_AMBIGUOUS,
    RUNTIME_PRESENT_RUNNING,
    RUNTIME_UNKNOWN,
    InventoryFinding,
    build_paid_canary_readiness,
    classify_production_runtime,
    resolve_production_identity,
    validate_candidate_canary_identity,
)
from defend_control.types import LaunchSpec, VastOffer
from defend_control.vast import VastClient

TRAIN_FILE = Path(r"C:\Users\thoma\Downloads\DEFEND32B\TRAINING\defend_sft_train_v1_merged.jsonl")


# ─────────────────────────────────────────────────────────────
# P3 — readiness runtime-truth fail-closed
# ─────────────────────────────────────────────────────────────

def test_readiness_default_runtime_is_unknown():
    r = build_paid_canary_readiness("head")
    assert r.production_runtime_state == RUNTIME_UNKNOWN
    assert r.ready_to_rent is False


def test_readiness_explicit_absent_accepted():
    r = build_paid_canary_readiness("head", production_runtime_state=RUNTIME_ABSENT, production_runtime_instance_id=None)
    assert r.ready_to_rent is True


def test_readiness_unknown_false():
    r = build_paid_canary_readiness("head", production_runtime_state=RUNTIME_UNKNOWN)
    assert r.ready_to_rent is False


def test_readiness_ambiguous_false():
    r = build_paid_canary_readiness("head", production_runtime_state=RUNTIME_AMBIGUOUS)
    assert r.ready_to_rent is False


def test_inventory_failure_is_unknown():
    t = classify_production_runtime(None)
    assert t.state == RUNTIME_UNKNOWN
    assert t.inventory_status in ("UNKNOWN", None)


def test_inventory_malformed_is_unknown():
    t = classify_production_runtime(INVENTORY_ONE_EXACT_REPLACEMENT, ())  # claims one, but zero findings
    assert t.state == RUNTIME_UNKNOWN


def test_inventory_none_found_is_absent():
    t = classify_production_runtime(INVENTORY_NONE_FOUND)
    assert t.state == RUNTIME_ABSENT


def test_inventory_ambiguous_is_ambiguous():
    t = classify_production_runtime(INVENTORY_AMBIGUOUS)
    assert t.state == RUNTIME_AMBIGUOUS


def test_inventory_one_running_is_present_running():
    t = classify_production_runtime(INVENTORY_ONE_EXACT_REPLACEMENT, (InventoryFinding(7, "running"),))
    assert t.state == RUNTIME_PRESENT_RUNNING
    assert t.instance_id == 7


# ─────────────────────────────────────────────────────────────
# P5 — production identity fail-closed
# ─────────────────────────────────────────────────────────────

def _profile(**overrides):
    base = dict(
        profile_id=PRODUCTION_PROFILE_ID,
        product_id="defend-ai",
        purpose="PRODUCTION_INFERENCE",
        status="PRODUCTION",
        base_repo="Qwen/Qwen2.5-32B-Instruct",
        base_revision="5ede1c97bbab6ce5cda5812749b4c0bdf79b18dd",
        adapter_repo="Defend-network/defend-identity-lora-v002",
        adapter_revision="46ade1686870210ef0ab4603c32fecb0e563330f",
        tokenizer_repo="Qwen/Qwen2.5-32B-Instruct",
        tokenizer_revision="5ede1c97bbab6ce5cda5812749b4c0bdf79b18dd",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _patch_profiles(monkeypatch, profiles):
    monkeypatch.setattr("defend_control.deployment_profiles.default_profiles", lambda: profiles)


def test_resolve_production_identity_canonical_passes():
    identity = resolve_production_identity()
    assert identity is not None
    assert identity.base_revision == "5ede1c97bbab6ce5cda5812749b4c0bdf79b18dd"
    assert identity.adapter_revision == "46ade1686870210ef0ab4603c32fecb0e563330f"


def test_resolve_production_identity_missing_fails(monkeypatch):
    _patch_profiles(monkeypatch, {})
    assert resolve_production_identity() is None


def test_resolve_production_identity_wrong_purpose_fails(monkeypatch):
    _patch_profiles(monkeypatch, {PRODUCTION_PROFILE_ID: _profile(purpose="TRAINING")})
    assert resolve_production_identity() is None


def test_resolve_production_identity_wrong_status_fails(monkeypatch):
    _patch_profiles(monkeypatch, {PRODUCTION_PROFILE_ID: _profile(status="NOT_TRAINED")})
    assert resolve_production_identity() is None


def test_resolve_production_identity_missing_base_revision_fails(monkeypatch):
    _patch_profiles(monkeypatch, {PRODUCTION_PROFILE_ID: _profile(base_revision="")})
    assert resolve_production_identity() is None


def test_resolve_production_identity_missing_adapter_revision_fails(monkeypatch):
    _patch_profiles(monkeypatch, {PRODUCTION_PROFILE_ID: _profile(adapter_revision="")})
    assert resolve_production_identity() is None


def test_missing_profile_makes_readiness_false(monkeypatch):
    _patch_profiles(monkeypatch, {})
    r = build_paid_canary_readiness("head", production_runtime_state=RUNTIME_ABSENT)
    assert r.production_profile_id == ""
    assert r.ready_to_rent is False


# ─────────────────────────────────────────────────────────────
# P6-P9 — candidate launch isolation + create allowlist + cross-binding
# ─────────────────────────────────────────────────────────────

def test_candidate_canary_launch_exact_fields():
    spec = LaunchSpec.candidate_canary()
    assert spec.label == CANDIDATE_CANARY_LABEL
    assert spec.runtype == "ssh_proxy"
    assert spec.disk_gb == 200
    assert "pytorch" in spec.image


def test_candidate_label_distinct_from_production_and_coder():
    assert LaunchSpec.candidate_canary().label != LaunchSpec.default().label
    assert LaunchSpec.candidate_canary().label != LaunchSpec.coder_default().label


def _offer():
    return VastOffer(123, "A100 PCIE", 81920, Decimal("1.0"), Decimal("0.99"))


def test_vast_create_accepts_exact_candidate_shape():
    client = VastClient("test-key")
    payload = client.build_create_payload(_offer(), LaunchSpec.candidate_canary())
    assert payload["label"] == CANDIDATE_CANARY_LABEL


def test_vast_create_rejects_altered_candidate_image():
    client = VastClient("test-key")
    altered = replace(LaunchSpec.candidate_canary(), image="evil/image:latest")
    with pytest.raises(ValueError):
        client.build_create_payload(_offer(), altered)


def test_vast_create_rejects_altered_candidate_disk():
    client = VastClient("test-key")
    altered = replace(LaunchSpec.candidate_canary(), disk_gb=999)
    with pytest.raises(ValueError):
        client.build_create_payload(_offer(), altered)


def test_vast_create_rejects_altered_candidate_label():
    client = VastClient("test-key")
    altered = replace(LaunchSpec.candidate_canary(), label="defend-vllm")
    with pytest.raises(ValueError):
        client.build_create_payload(_offer(), altered)


def test_cross_binding_candidate_profile_production_label_rejects():
    ok, _ = validate_candidate_canary_identity(
        launch_label=LaunchSpec.default().label,
        profile_id=CANDIDATE_TRAINING_PROFILE_ID,
        purpose=CANDIDATE_CANARY_PURPOSE,
        role=CANDIDATE_CANARY_ROLE,
    )
    assert not ok


def test_cross_binding_production_profile_candidate_label_rejects():
    ok, _ = validate_candidate_canary_identity(
        launch_label=CANDIDATE_CANARY_LABEL,
        profile_id=PRODUCTION_PROFILE_ID,
        purpose=CANDIDATE_CANARY_PURPOSE,
        role=CANDIDATE_CANARY_ROLE,
    )
    assert not ok


def test_cross_binding_candidate_label_production_purpose_rejects():
    ok, _ = validate_candidate_canary_identity(
        launch_label=CANDIDATE_CANARY_LABEL,
        profile_id=CANDIDATE_TRAINING_PROFILE_ID,
        purpose="PRODUCTION_INFERENCE",
        role=CANDIDATE_CANARY_ROLE,
    )
    assert not ok


def test_cross_binding_candidate_label_production_role_rejects():
    ok, _ = validate_candidate_canary_identity(
        launch_label=CANDIDATE_CANARY_LABEL,
        profile_id=CANDIDATE_TRAINING_PROFILE_ID,
        purpose=CANDIDATE_CANARY_PURPOSE,
        role="PRODUCTION_INFERENCE",
    )
    assert not ok


def test_cross_binding_exact_candidate_allowed():
    ok, _ = validate_candidate_canary_identity(
        launch_label=CANDIDATE_CANARY_LABEL,
        profile_id=CANDIDATE_TRAINING_PROFILE_ID,
        purpose=CANDIDATE_CANARY_PURPOSE,
        role=CANDIDATE_CANARY_ROLE,
    )
    assert ok


# ─────────────────────────────────────────────────────────────
# P18-P23 — runner contracts
# ─────────────────────────────────────────────────────────────

def test_five_steps_rejects_non_five():
    assert not validate_five_steps(4)[0]
    assert not validate_five_steps(6)[0]


def test_five_steps_accepts_none_and_five():
    assert validate_five_steps(None)[0]
    assert validate_five_steps(5)[0]


def test_qlora_contract_nf4_passes():
    assert validate_qlora_contract({"quantization": "nf4", "device_map": {"": 0}, "compute_dtype": "bfloat16"})[0]


def test_qlora_contract_rejects_non_nf4():
    assert not validate_qlora_contract({"quantization": "int4", "device_map": {"": 0}, "compute_dtype": "bfloat16"})[0]


def test_qlora_contract_rejects_device_map_auto():
    assert not validate_qlora_contract({"quantization": "nf4", "device_map": "auto", "compute_dtype": "bfloat16"})[0]


def test_masking_contract_single_tool():
    ok, failures = masking_contract_ok(
        [("system", 0, 2), ("user", 2, 5), ("tool", 5, 8), ("assistant", 8, 12)], 12
    )
    assert ok
    assert failures == []


def test_masking_contract_multi_tool():
    ok, _ = masking_contract_ok(
        [("system", 0, 2), ("user", 2, 5), ("assistant", 5, 8), ("tool", 8, 11), ("assistant", 11, 15)], 15
    )
    assert ok


def test_masking_contract_tool_result_masked():
    # tool span tokens must be -100 (masked). If a tool span were trainable it
    # would be labeled with its index and the validator would flag it unmasked.
    spans = [("system", 0, 2), ("user", 2, 5), ("tool", 5, 8), ("assistant", 8, 12)]
    labels = [-100] * 12
    for pos in range(8, 12):  # assistant trainable
        labels[pos] = pos
    from defend_control.training_hardening import validate_assistant_masking
    ok, failures = validate_assistant_masking(labels, spans)
    assert ok
    # a tool token made trainable is rejected
    labels[5] = 5
    ok2, failures2 = validate_assistant_masking(labels, spans)
    assert not ok2
    assert any("tool token 5 unmasked" in f for f in failures2)


def test_data_gates_486_486_9():
    if not TRAIN_FILE.exists():
        pytest.skip("canonical training file not present")
    rows = [json.loads(line) for line in TRAIN_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
    runner = Qwen3CanaryRunner(policy=CanaryPolicy())
    ok, detail = runner.validate_data_gates(rows)
    assert ok
    assert detail["tool_calls"] == 486
    assert detail["tool_results"] == 486
    assert detail["orphans"] == 0
    assert detail["unresolved"] == 0
    assert detail["multi_tool_rows"] == 9
    assert detail["pairing_failures"] == 0
    assert detail["converted_sha"] == "d59b05ee323dc6d8bda8086c2aa3f9589acb8eae883afb173095f53117e1e854"


def test_dry_run_zero_provider_mutations():
    class TrippingVast:
        def __init__(self):
            self.mutations = []
        def create_instance(self, *a, **k):
            self.mutations.append("create"); raise AssertionError("dry-run must not create")
        def set_state(self, *a, **k):
            self.mutations.append("set_state"); raise AssertionError("dry-run must not set_state")
        def destroy_instance(self, *a, **k):
            self.mutations.append("destroy"); raise AssertionError("dry-run must not destroy")

    fake = TrippingVast()
    runner = Qwen3CanaryRunner(policy=CanaryPolicy(), vast_client=fake)
    evidence, summary = runner.plan(requested_steps=5, inventory_status=INVENTORY_NONE_FOUND)
    assert fake.mutations == []
    assert summary["provider_mutations"] == 0
    assert summary["paid_instance_create_executed"] is False
    # mutating phases are SKIPPED_DRY_RUN, not executed
    for e in evidence:
        if e.phase in (CanaryPhase.INSTANCE_CREATE.value, CanaryPhase.DESTROY.value):
            assert e.would_mutate_provider is True
            assert e.executed is False


def test_dry_run_sanitized_output_no_secrets():
    runner = Qwen3CanaryRunner(policy=CanaryPolicy())
    _, summary = runner.plan(requested_steps=5, inventory_status=INVENTORY_NONE_FOUND)
    blob = json.dumps(summary)
    assert "sk-" not in blob
    assert "hf_" not in blob
    assert "Bearer" not in blob


def test_build_fresh_reload_command_uses_new_process():
    cmd = build_fresh_reload_command(Path("canary-adapter-temp"), CANARY_SANITY_PROMPT)
    assert cmd[0].endswith("python.exe") or "python" in cmd[0]
    assert "--adapter-dir" in cmd
    assert CANARY_SANITY_PROMPT in cmd


def test_sanity_prompt_is_not_heldout():
    # The canary-only sanity prompt is synthetic and contains no heldout prose.
    assert "17*23" not in CANARY_SANITY_PROMPT
    assert CANARY_SANITY_PROMPT == "Reply with the single word: ready."


def test_canary_policy_bounds():
    p = CanaryPolicy()
    assert p.max_steps == 5
    assert p.max_hourly_usd == CANARY_MAX_HOURLY_USD == Decimal("1.20")
    assert p.hard_spend_cap_usd == CANARY_HARD_SPEND_CAP_USD == Decimal("2.00")
    assert p.max_instances == CANARY_MAX_INSTANCES == 1
    assert p.candidate_label == CANDIDATE_CANARY_LABEL


def test_real_qwen3_tokenizer_template_proof():
    """Real pinned tokenizer/template/masking proof (local, non-billable).
    Skipped when transformers/tokenizer/network is unavailable."""
    if not TRAIN_FILE.exists():
        pytest.skip("canonical training file not present")
    try:
        import transformers  # noqa: F401
    except Exception:
        pytest.skip("transformers not installed")
    rows = [json.loads(line) for line in TRAIN_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
    status, detail = run_real_tokenizer_proof(rows)
    if status == "BLOCKED":
        pytest.skip(f"tokenizer proof blocked: {detail.get('reason')}")
    assert status == "PASS", detail
    for label in ("direct", "multi_turn", "single_tool", "multi_tool"):
        assert detail[label]["ok"] is True
        assert detail[label]["assistant_trainable"] > 0
