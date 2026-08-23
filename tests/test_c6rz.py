"""C6-RZ tests: immutable run plan, run-scoped candidate identity, behavioral
paid-attempt readiness, and direct-SSH enforcement."""

from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest

from defend_ai.canary_plan import (
    PaidCanaryAttemptReadiness,
    PaidCanaryRunPlan,
    build_readiness,
    new_run_id,
    run_candidate_label,
)
from defend_ai.launch import candidate_canary_launch
from defend_ai.training_hardening import candidate_label_matches


def _plan(run_id: str = "abc123def456") -> PaidCanaryRunPlan:
    return PaidCanaryRunPlan(
        run_id=run_id,
        authorized_git_head="deadbeef",
        trusted_repository_remote="https://github.com/defend-network/DEFEND.git",
        base_repo="Qwen/Qwen3-32B",
        base_revision="9216db5781bf21249d130ec9da846c4624c16137",
        tokenizer_repo="Qwen/Qwen3-32B",
        tokenizer_revision="9216db5781bf21249d130ec9da846c4624c16137",
        raw_training_sha256="raw",
        converted_training_sha256="conv",
        training_environment_profile="DEFEND_AI_QWEN3_TRAIN_ENV_V2",
        training_environment_hash="envhash",
        image="pytorch/pytorch:2.7.1-cuda12.8-cudnn9-devel",
        hourly_cap_usd=Decimal("1.20"),
        total_cap_usd=Decimal("2.00"),
        teardown_reserve_seconds=300.0,
        protocol_version="DEFEND_CANARY_RESULT_V2",
        required_stages=("HOST_PREFLIGHT", "TRAIN_5_STEPS", "FRESH_RELOAD"),
    )


def test_run_plan_is_immutable():
    plan = _plan()
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.run_id = "hijacked"
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.authorized_git_head = "other"


def test_run_scoped_candidate_label():
    run_id = new_run_id()
    label = run_candidate_label(run_id)
    assert label == f"defend-ai-qwen3-canary-{run_id}"
    assert candidate_label_matches(label)


def test_run_scoped_label_in_launch_spec():
    run_id = "abc123"
    spec = candidate_canary_launch(run_id)
    assert spec.label == f"defend-ai-qwen3-canary-{run_id}"
    assert spec.runtype == "ssh_direct"


def test_candidate_label_prefix_matches_only_candidate():
    assert candidate_label_matches("defend-ai-qwen3-canary")
    assert candidate_label_matches("defend-ai-qwen3-canary-abc123")
    assert not candidate_label_matches("defend-vllm")
    assert not candidate_label_matches("defendcoder-vllm")
    assert not candidate_label_matches(None)


def test_readiness_requires_all_gates():
    r = build_readiness(
        owner_authorization="M1.9.2D",
        run_plan=_plan(),
        inventory_status="NONE_FOUND",
        zero_cost_behavioral_contract=True,
    )
    assert r.authorized_to_attempt is True


def test_readiness_false_without_owner_auth():
    r = build_readiness(
        owner_authorization="WRONG",
        run_plan=_plan(),
        inventory_status="NONE_FOUND",
        zero_cost_behavioral_contract=True,
    )
    assert r.authorized_to_attempt is False


def test_readiness_false_without_run_plan():
    r = build_readiness(
        owner_authorization="M1.9.2D",
        run_plan=None,
        inventory_status="NONE_FOUND",
        zero_cost_behavioral_contract=True,
    )
    assert r.authorized_to_attempt is False


def test_readiness_false_without_behavioral_contract():
    r = build_readiness(
        owner_authorization="M1.9.2D",
        run_plan=_plan(),
        inventory_status="NONE_FOUND",
        zero_cost_behavioral_contract=False,
    )
    assert r.authorized_to_attempt is False


def test_readiness_false_on_unknown_inventory():
    r = build_readiness(
        owner_authorization="M1.9.2D",
        run_plan=_plan(),
        inventory_status="UNKNOWN",
        zero_cost_behavioral_contract=True,
    )
    assert r.authorized_to_attempt is False
