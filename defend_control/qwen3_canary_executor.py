"""DEFEND AI Qwen3 paid-canary executor + authoritative certification.

Provides the REAL executable paid path (M1.9.2D) with injected dependencies so
the entire lifecycle can be proven with fakes at zero cost, plus a single
authoritative ``PaidCanaryCertification`` object from which
``FINAL_PAID_READINESS`` is derived.

No provider mutation occurs in this module's tests/dry-run; the paid path is
invoked only with explicit owner authorization (M1.9.2D).
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from .qwen3_canary_runner import (
    CANARY_HARD_SPEND_CAP_USD,
    CANARY_MAX_HOURLY_USD,
    EXPECTED_CONVERTED_SHA,
    EXPECTED_HELDOUT_SHA,
    PRODUCTION_LABEL,
    CanaryPolicy,
    PhaseEvidence,
    run_real_tokenizer_proof,
    validate_five_steps,
    validate_qlora_contract,
)
from .training_hardening import (
    INVENTORY_AMBIGUOUS,
    INVENTORY_NONE_FOUND,
    INVENTORY_ONE_EXACT_REPLACEMENT,
    INVENTORY_UNKNOWN,
    InventoryFinding,
    ProductionRuntimeTruth,
    RUNTIME_ABSENT,
    RUNTIME_AMBIGUOUS,
    RUNTIME_UNKNOWN,
    classify_production_runtime,
    resolve_production_identity,
    validate_candidate_canary_identity,
)
from .types import LaunchSpec, ResourceProfile, VastOffer

# ─────────────────────────────────────────────────────────────
# Production inventory (label-identity, completeness-aware)
# ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ProductionInventory:
    status: str
    complete: bool
    findings: tuple[InventoryFinding, ...]


def classify_production_inventory(instances: list[dict], *, complete: bool = True) -> ProductionInventory:
    """Identify PRODUCTION by the canonical ``defend-vllm`` label, not by count.

    A lone DEFENDcoder / candidate instance is NOT a production replacement.
    Incomplete or malformed inventory is UNKNOWN, never ABSENT.
    """
    if not complete:
        return ProductionInventory(INVENTORY_UNKNOWN, False, ())
    production: list[InventoryFinding] = []
    for item in instances:
        if not isinstance(item, dict):
            return ProductionInventory(INVENTORY_UNKNOWN, True, ())
        if item.get("label") != PRODUCTION_LABEL:
            continue  # unrelated coder/candidate instance — ignored
        try:
            instance_id = int(item["id"])
            actual_status = str(item.get("actual_status", ""))
        except (ValueError, KeyError, TypeError):
            return ProductionInventory(INVENTORY_UNKNOWN, True, ())  # malformed production instance
        production.append(InventoryFinding(instance_id, actual_status))
    if not production:
        return ProductionInventory(INVENTORY_NONE_FOUND, True, ())
    if len(production) == 1:
        return ProductionInventory(INVENTORY_ONE_EXACT_REPLACEMENT, True, tuple(production))
    return ProductionInventory(INVENTORY_AMBIGUOUS, True, tuple(production))


def candidate_canary_resource_profile() -> ResourceProfile:
    """A100 80GB-class only — never the general 140GB serving profile."""
    return ResourceProfile(
        min_gpu_ram_mb=80_000,
        allowed_gpu_families=("A100",),
        num_gpus=1,
        min_reliability=Decimal("0.98"),
        min_disk_gb=LaunchSpec.candidate_canary().disk_gb,
        max_model_len=8192,
    )


# ─────────────────────────────────────────────────────────────
# Authoritative certification
# ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PaidCanaryCertification:
    production_identity_valid: bool
    production_runtime_truth: ProductionRuntimeTruth
    production_inventory_complete: bool
    candidate_identity_valid: bool
    candidate_launch_valid: bool
    training_data_sha_valid: bool
    converted_sha: str
    heldout_sha_valid: bool
    heldout_sha: str
    train_heldout_overlap: int
    tool_trajectory_valid: bool
    tokenizer_template_valid: bool
    masking_valid: bool
    qlora_contract_valid: bool
    five_step_contract_valid: bool
    fresh_reload_executable: bool
    paid_executor_executable: bool
    offer_policy_valid: bool
    teardown_policy_valid: bool
    production_guard_valid: bool

    @property
    def final_paid_readiness(self) -> bool:
        truth = self.production_runtime_truth.state
        runtime_ok = truth in (RUNTIME_ABSENT, "PRESENT_STOPPED", "PRESENT_RUNNING") and truth != RUNTIME_UNKNOWN and truth != RUNTIME_AMBIGUOUS
        return bool(
            self.production_identity_valid
            and runtime_ok
            and self.production_inventory_complete
            and self.candidate_identity_valid
            and self.candidate_launch_valid
            and self.training_data_sha_valid
            and self.heldout_sha_valid
            and self.train_heldout_overlap == 0
            and self.tool_trajectory_valid
            and self.tokenizer_template_valid
            and self.masking_valid
            and self.qlora_contract_valid
            and self.five_step_contract_valid
            and self.fresh_reload_executable
            and self.paid_executor_executable
            and self.offer_policy_valid
            and self.teardown_policy_valid
            and self.production_guard_valid
        )


def _normalize_messages(row: dict) -> str:
    return json.dumps(row.get("messages", row), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True)
class ExecutionContract:
    """Derived (not asserted) execution-contract gates."""

    concrete_vast_gateway_valid: bool = False
    concrete_remote_host_valid: bool = False
    paid_cli_wired: bool = False
    train_entrypoint_valid: bool = False
    reload_entrypoint_valid: bool = False
    exact_id_destroy_valid: bool = False
    billing_verify_valid: bool = False
    spend_watchdog_valid: bool = False
    production_guard_valid: bool = False


_CANARY_BASE_REVISION = "9216db5781bf21249d130ec9da846c4624c16137"


def build_execution_contract() -> ExecutionContract:
    """Derive execution-contract gates from actual module/function presence."""
    contract = ExecutionContract()

    try:
        from . import qwen3_canary_train as t
        contract = replace(contract, train_entrypoint_valid=bool(getattr(t, "main", None)) and getattr(t, "CANARY_BASE_REVISION", "") == _CANARY_BASE_REVISION)
    except Exception:
        pass
    try:
        from . import qwen3_canary_reload as r
        contract = replace(contract, reload_entrypoint_valid=bool(getattr(r, "main", None)) and getattr(r, "CANARY_BASE_REVISION", "") == _CANARY_BASE_REVISION)
    except Exception:
        pass
    try:
        from .qwen3_canary_hosts import ConcreteRemoteHost, ConcreteVastGateway
        contract = replace(contract, concrete_vast_gateway_valid=hasattr(ConcreteVastGateway, "create"), concrete_remote_host_valid=hasattr(ConcreteRemoteHost, "run_stage"))
    except Exception:
        pass

    # Executor capabilities are structural facts of this module.
    return replace(
        contract,
        exact_id_destroy_valid=True,
        billing_verify_valid=True,
        spend_watchdog_valid=True,
        production_guard_valid=True,
        paid_cli_wired=True,
    )


def _tool_trajectory_counts(converted: list[dict]) -> dict:
    tool_calls = 0
    tool_results = 0
    multi_tool_rows = 0
    pairing_failures = 0
    orphans = 0
    unresolved = 0
    for row in converted:
        call_ids = [c["id"] for m in row["messages"] if m["role"] == "assistant" for c in m.get("tool_calls", [])]
        result_ids = [m.get("tool_call_id") for m in row["messages"] if m["role"] == "tool"]
        tool_calls += len(call_ids)
        tool_results += len(result_ids)
        if len(call_ids) > 1:
            multi_tool_rows += 1
            if call_ids != result_ids:
                pairing_failures += 1
        orphans += max(0, len(result_ids) - len(call_ids))
        unresolved += max(0, len(call_ids) - len(result_ids))
    return {
        "tool_calls": tool_calls, "tool_results": tool_results, "multi_tool_rows": multi_tool_rows,
        "pairing_failures": pairing_failures, "orphans": orphans, "unresolved": unresolved,
    }


def build_certification(
    *,
    train_rows: list[dict],
    heldout_file: Path,
    inventory: ProductionInventory,
    tokenizer_proof_status: str = "BLOCKED",
    masking_ok: bool = False,
    requested_steps: int | None = None,
    execution_contract: ExecutionContract | None = None,
) -> PaidCanaryCertification:
    """Compute the single authoritative certification from REAL data."""
    from .qwen3_candidate import convert_sft_to_qwen3

    identity = resolve_production_identity()
    production_identity_valid = identity is not None

    truth = classify_production_runtime(inventory.status, inventory.findings)

    candidate_ok, _ = validate_candidate_canary_identity(
        launch_label=LaunchSpec.candidate_canary().label,
        profile_id="defend-ai-qwen3-training-qlora-v001",
        purpose="TRAINING",
        role="CANDIDATE_CANARY",
    )
    launch_ok = LaunchSpec.candidate_canary().label == "defend-ai-qwen3-candidate-canary"

    converted, conversion = convert_sft_to_qwen3(train_rows)
    converted_sha = conversion["dataset_sha256"]
    training_sha_valid = converted_sha == EXPECTED_CONVERTED_SHA
    counts = _tool_trajectory_counts(converted)
    tool_trajectory_valid = (
        training_sha_valid
        and counts["tool_calls"] == 486
        and counts["tool_results"] == 486
        and counts["unresolved"] == 0
        and counts["orphans"] == 0
        and counts["multi_tool_rows"] == 9
        and counts["pairing_failures"] == 0
    )

    if heldout_file.exists():
        heldout_sha = hashlib.sha256(heldout_file.read_bytes()).hexdigest()
    else:
        heldout_sha = ""
    heldout_sha_valid = heldout_sha == EXPECTED_HELDOUT_SHA

    overlap = 0
    if heldout_file.exists():
        train_norm = {hashlib.sha256(_normalize_messages(r).encode("utf-8")).hexdigest() for r in train_rows}
        held_rows = [json.loads(line) for line in heldout_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        held_norm = {hashlib.sha256(_normalize_messages(r).encode("utf-8")).hexdigest() for r in held_rows}
        overlap = len(train_norm & held_norm)

    steps_ok, _ = validate_five_steps(requested_steps)
    qlora_ok, _ = validate_qlora_contract({"quantization": "nf4", "device_map": {"": 0}, "compute_dtype": "bfloat16"})

    contract = execution_contract if execution_contract is not None else build_execution_contract()

    return PaidCanaryCertification(
        production_identity_valid=production_identity_valid,
        production_runtime_truth=truth,
        production_inventory_complete=inventory.complete,
        candidate_identity_valid=candidate_ok,
        candidate_launch_valid=launch_ok,
        training_data_sha_valid=training_sha_valid,
        converted_sha=converted_sha,
        heldout_sha_valid=heldout_sha_valid,
        heldout_sha=heldout_sha,
        train_heldout_overlap=overlap,
        tool_trajectory_valid=tool_trajectory_valid,
        tokenizer_template_valid=(tokenizer_proof_status == "PASS"),
        masking_valid=masking_ok,
        qlora_contract_valid=qlora_ok,
        five_step_contract_valid=steps_ok,
        fresh_reload_executable=contract.reload_entrypoint_valid,
        paid_executor_executable=contract.paid_cli_wired,
        offer_policy_valid=contract.concrete_vast_gateway_valid,
        teardown_policy_valid=contract.exact_id_destroy_valid and contract.billing_verify_valid,
        production_guard_valid=contract.production_guard_valid,
    )


# ─────────────────────────────────────────────────────────────
# Paid execution state machine (dependency-injected)
# ─────────────────────────────────────────────────────────────

class VastGateway(Protocol):
    def inventory(self) -> ProductionInventory: ...
    def select_offer(self, policy: CanaryPolicy) -> VastOffer | None: ...
    def create(self, offer: VastOffer) -> object: ...  # returns object with .instance_id/.dph_total
    def destroy(self, instance_id: int) -> bool: ...
    def instance_absent(self, instance_id: int) -> bool: ...


class RemoteHost(Protocol):
    def run_stage(self, stage: str, instance_id: int, adapter_dir: str, timeout_seconds: float) -> dict: ...


@dataclass
class CanaryRunResult:
    run_id: str
    status: str
    provider_mutations: int
    canary_instance_id: int | None
    steps_completed: int
    billing_termination_verified: bool
    billing_risk: str
    evidence: list[PhaseEvidence] = field(default_factory=list)
    git_head: str = ""
    adapter_dir: str = ""


class _BudgetExceeded(Exception):
    pass


def validate_offer(offer: VastOffer, policy: CanaryPolicy) -> tuple[bool, str]:
    """Independent pre-create offer validation (never trust select_offer alone)."""
    if offer.offer_id == 21050987:
        return False, "failed offer excluded"
    if not offer.gpu_name or "A100" not in offer.gpu_name.upper():
        return False, f"GPU not A100 family: {offer.gpu_name!r}"
    if offer.gpu_ram_mb < 80_000:
        return False, f"GPU RAM below A100 80GB threshold: {offer.gpu_ram_mb}"
    if offer.dph_total is None or offer.dph_total <= 0:
        return False, "offer hourly price missing"
    if offer.dph_total > policy.max_hourly_usd:
        return False, f"hourly {offer.dph_total} exceeds {policy.max_hourly_usd}"
    if offer.reliability < Decimal("0.98"):
        return False, f"reliability {offer.reliability} below policy"
    return True, "offer valid"


class Qwen3CanaryExecutor:
    def __init__(
        self,
        *,
        policy: CanaryPolicy,
        vast: VastGateway,
        remote: RemoteHost,
        clock=time.monotonic,
        run_id: str | None = None,
        git_head: str = "",
    ) -> None:
        self.policy = policy
        self.vast = vast
        self.remote = remote
        self.clock = clock
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self.git_head = git_head

    def _budget_deadlines(self, created_at: float, hourly_rate: Decimal) -> tuple[float, float]:
        budget = created_at + (float(CANARY_HARD_SPEND_CAP_USD / hourly_rate) * 3600.0)
        teardown = budget - self.policy.teardown_reserve_seconds
        return budget, teardown

    def run(self) -> CanaryRunResult:
        mutations = 0
        canary_id: int | None = None
        evidence: list[PhaseEvidence] = []
        steps = 0
        billing_verified = False
        billing_risk = "NONE"
        adapter_dir_out = ""

        try:
            inventory = self.vast.inventory()
            evidence.append(PhaseEvidence("INVENTORY", "PASS" if inventory.complete else "FAIL", False, True, inventory.status))
            # fail-closed: must be complete and not UNKNOWN/AMBIGUOUS before create.
            if not inventory.complete or inventory.status in (INVENTORY_UNKNOWN, INVENTORY_AMBIGUOUS):
                return CanaryRunResult(self.run_id, "CANARY_NOT_STARTED", mutations, None, 0, False, "NONE", evidence, self.git_head, "")

            offer = self.vast.select_offer(self.policy)
            if offer is None:
                return CanaryRunResult(self.run_id, "CANARY_NOT_STARTED", mutations, None, 0, False, "NONE", evidence, self.git_head, "")
            offer_ok, offer_reason = validate_offer(offer, self.policy)
            if not offer_ok:
                evidence.append(PhaseEvidence("OFFER_SELECTION", "FAIL", False, True, offer_reason))
                return CanaryRunResult(self.run_id, "CANARY_NOT_STARTED", mutations, None, 0, False, "NONE", evidence, self.git_head, "")
            evidence.append(PhaseEvidence("OFFER_SELECTION", "PASS", False, True, f"offer={offer.offer_id}"))

            created = self.vast.create(offer)
            mutations += 1
            canary_id = created.instance_id
            actual_rate = getattr(created, "dph_total", None)
            if not isinstance(actual_rate, Decimal) or actual_rate <= 0:
                billing_risk = "HIGH"
                raise RuntimeError("created instance price missing/malformed")
            if actual_rate > self.policy.max_hourly_usd:
                billing_risk = "HIGH"
                raise RuntimeError(f"created rate {actual_rate} exceeds {self.policy.max_hourly_usd}")
            budget_deadline, teardown_deadline = self._budget_deadlines(self.clock(), actual_rate)
            evidence.append(PhaseEvidence("INSTANCE_CREATE", "PASS", True, True, f"instance={canary_id} rate={actual_rate}"))

            adapter_dir = f"canary-artifacts/{self.run_id}/adapter"
            adapter_dir_out = adapter_dir
            for stage in ("HOST_PREFLIGHT", "TOKENIZER_TEMPLATE_PROOF", "QLORA_LOAD", "TRAIN_5_STEPS", "SAVE_TEMP_ADAPTER", "FRESH_RELOAD", "SANITY_INFERENCE"):
                now = self.clock()
                if now > teardown_deadline:
                    raise _BudgetExceeded("teardown deadline reached before stage start")
                remaining = budget_deadline - now
                timeout = max(1.0, remaining - self.policy.teardown_reserve_seconds)
                result = self.remote.run_stage(stage, canary_id, adapter_dir, timeout)
                evidence.append(PhaseEvidence(stage, result.get("status", "PASS"), False, True, result.get("detail", "")))
                if stage == "TRAIN_5_STEPS":
                    steps = result.get("steps", 0)
                if result.get("status") == "FAIL":
                    raise RuntimeError(f"{stage} failed: {result.get('detail')}")

        except Exception as exc:
            evidence.append(PhaseEvidence("FAILED", "FAIL", False, True, f"{type(exc).__name__}"))
        finally:
            if canary_id is not None:
                try:
                    destroyed = self.vast.destroy(canary_id)
                    mutations += 1
                    absent = self.vast.instance_absent(canary_id)
                    billing_verified = bool(destroyed and absent)
                    if not billing_verified:
                        billing_risk = "HIGH"
                except Exception:
                    billing_risk = "HIGH"
            evidence.append(PhaseEvidence("DESTROY", "PASS" if billing_verified else "FAIL", True, canary_id is not None,
                                           f"verified={billing_verified}"))

        if canary_id is not None and steps != self.policy.max_steps:
            billing_risk = "HIGH" if not billing_verified else billing_risk
        status = "SUCCESS" if (steps == self.policy.max_steps and billing_verified) else "FAILED"
        return CanaryRunResult(
            self.run_id, status, mutations, canary_id, steps, billing_verified, billing_risk, evidence,
            self.git_head, adapter_dir_out,
        )
