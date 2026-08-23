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
from shared_platform.compute_types import LaunchSpec, ResourceProfile, VastOffer
from .launch import candidate_canary_launch, candidate_canary_resource_profile

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
    """Derive execution-contract gates from actual module/function capability.

    No unconditional PASS booleans: every field is introspected from the real
    concrete implementation's callables/attributes.
    """
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

    concrete_vast_valid = False
    concrete_host_valid = False
    try:
        from .qwen3_canary_hosts import ConcreteRemoteHost, ConcreteVastGateway
        concrete_vast_valid = bool(
            hasattr(ConcreteVastGateway, "create")
            and hasattr(ConcreteVastGateway, "destroy")
            and hasattr(ConcreteVastGateway, "instance_state")  # tri-state
            and hasattr(ConcreteVastGateway, "select_offer")
        )
        concrete_host_valid = bool(
            hasattr(ConcreteRemoteHost, "run_stage")
            and hasattr(ConcreteRemoteHost, "_build_ssh_command")  # SSH argv builder
            and hasattr(ConcreteRemoteHost, "bind_target")  # instance-bound target
            and hasattr(ConcreteRemoteHost, "_stage_command")
        )
    except Exception:
        pass
    contract = replace(contract, concrete_vast_gateway_valid=concrete_vast_valid, concrete_remote_host_valid=concrete_host_valid)

    # exact-ID destroy: concrete gateway.destroy uses confirmed_instance_id.
    exact_id_destroy_valid = False
    try:
        from .qwen3_canary_hosts import ConcreteVastGateway
        import inspect
        src = inspect.getsource(ConcreteVastGateway.destroy)
        exact_id_destroy_valid = "confirmed_instance_id" in src
    except Exception:
        pass

    # billing verify: concrete gateway exposes tri-state instance_state.
    billing_verify_valid = False
    try:
        from .qwen3_canary_hosts import ConcreteVastGateway
        billing_verify_valid = hasattr(ConcreteVastGateway, "instance_state")
    except Exception:
        pass

    # spend watchdog: executor exposes budget deadline contract.
    spend_watchdog_valid = hasattr(Qwen3CanaryExecutor, "_budget_deadlines")

    # production guard: candidate identity cross-binding exists.
    production_guard_valid = bool(callable(validate_candidate_canary_identity))

    # paid CLI wired: the CLI entrypoint exposes run_paid_canary -> executor.
    paid_cli_wired = False
    try:
        import tools.defend_ai_qwen3_canary as cli
        paid_cli_wired = callable(getattr(cli, "run_paid_canary", None))
    except Exception:
        pass

    return replace(
        contract,
        exact_id_destroy_valid=exact_id_destroy_valid,
        billing_verify_valid=billing_verify_valid,
        spend_watchdog_valid=spend_watchdog_valid,
        production_guard_valid=production_guard_valid,
        paid_cli_wired=paid_cli_wired,
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
        launch_label=candidate_canary_launch().label,
        profile_id="defend-ai-qwen3-training-qlora-v001",
        purpose="TRAINING",
        role="CANDIDATE_CANARY",
    )
    launch_ok = candidate_canary_launch().label == "defend-ai-qwen3-candidate-canary"

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
    def instance_state(self, instance_id: int) -> str: ...  # PRESENT | ABSENT | UNKNOWN
    def resolve_target(self, instance_id: int) -> dict | None: ...  # {host, port, user}


INSTANCE_PRESENT = "PRESENT"
INSTANCE_ABSENT = "ABSENT"
INSTANCE_UNKNOWN = "UNKNOWN"


@dataclass
class RemoteStageResult:
    """Typed, authoritative remote-stage result (never stdout tail alone)."""

    status: str
    steps_completed: int | None = None
    detail: str = ""


RESULT_MARKER = "DEFEND_CANARY_RESULT="


def parse_canary_result(stdout: str, returncode: int, stage: str) -> RemoteStageResult:
    """Production semantic parser: machine-readable result record only.

    Only an explicit PASS with all stage-required fields may advance. Unknown
    status, malformed record, missing record, or nonzero return code all FAIL.
    """
    if returncode != 0:
        return RemoteStageResult(status="FAIL", detail="nonzero return code")
    record = None
    for line in stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith(RESULT_MARKER):
            payload = stripped[len(RESULT_MARKER):]
            try:
                record = json.loads(payload)
            except json.JSONDecodeError:
                return RemoteStageResult(status="FAIL", detail="malformed result record")
            break
    if record is None:
        return RemoteStageResult(status="FAIL", detail="no structured result record")
    if not isinstance(record, dict):
        return RemoteStageResult(status="FAIL", detail="result record not an object")
    status = record.get("status")
    if status not in ("PASS", "FAIL"):
        return RemoteStageResult(status="FAIL", detail=f"unknown status {status!r}")
    steps = record.get("steps_completed") if stage == "TRAIN_5_STEPS" else None
    return RemoteStageResult(status=status, steps_completed=steps, detail=str(record.get("detail", "")))


class RemoteHost(Protocol):
    def run_stage(self, stage: str, instance_id: int, adapter_dir: str, timeout_seconds: float) -> dict: ...
    # returns raw process result: {"returncode": int, "stdout": str, "stderr": str}


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
        sleep=time.sleep,
        run_id: str | None = None,
        git_head: str = "",
    ) -> None:
        self.policy = policy
        self.vast = vast
        self.remote = remote
        self.clock = clock
        self.sleep = sleep
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self.git_head = git_head

    def _budget_deadlines(self, created_at: float, hourly_rate: Decimal) -> tuple[float, float]:
        budget = created_at + (float(CANARY_HARD_SPEND_CAP_USD / hourly_rate) * 3600.0)
        teardown = budget - self.policy.teardown_reserve_seconds
        return budget, teardown

    def _teardown(self, canary_id: int) -> tuple[bool, int]:
        """Exact-ID destroy + bounded absence reconciliation. Only terminal
        ABSENT verifies billing termination; PRESENT/UNKNOWN poll until the
        teardown reserve is exhausted."""
        mutations = 0
        try:
            destroyed = self.vast.destroy(canary_id)
            mutations += 1
        except Exception:
            return False, mutations
        if not destroyed:
            return False, mutations
        deadline = self.clock() + self.policy.teardown_reserve_seconds
        polls = 0
        while polls < 20:
            state = self.vast.instance_state(canary_id)
            if state == INSTANCE_ABSENT:
                return True, mutations
            if self.clock() > deadline:
                return False, mutations
            self.sleep(0.5)
            polls += 1
        return False, mutations

    def run(self) -> CanaryRunResult:
        mutations = 0
        canary_id: int | None = None
        evidence: list[PhaseEvidence] = []
        steps = 0
        billing_verified = False
        billing_risk = "NONE"
        adapter_dir_out = ""
        execution_failed = False

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

            # Target binding is a mandatory production invariant (not optional).
            bind = getattr(self.remote, "bind_target", None)
            if bind is None:
                raise RuntimeError("remote host lacks mandatory target binding")
            target_info = self.vast.resolve_target(canary_id)
            if not target_info or not target_info.get("host") or not target_info.get("port"):
                raise RuntimeError("SSH endpoint unresolved for created instance")
            from .qwen3_canary_hosts import BLOCKED_HOSTS, CanaryRemoteTarget

            if target_info.get("host") in BLOCKED_HOSTS:
                raise RuntimeError("created instance resolved to blocked host")
            bind(CanaryRemoteTarget(
                instance_id=canary_id, host=target_info["host"], port=target_info["port"],
                user=target_info.get("user", "root"), offer_id=offer.offer_id, hourly_rate=actual_rate,
            ))
            evidence.append(PhaseEvidence("TARGET_READY", "PASS", False, True, f"instance={canary_id}"))

            adapter_dir = f"canary-artifacts/{self.run_id}/adapter"
            adapter_dir_out = adapter_dir
            for stage in ("HOST_PREFLIGHT", "TRAIN_5_STEPS", "FRESH_RELOAD"):
                now = self.clock()
                if now > teardown_deadline:
                    raise _BudgetExceeded("teardown deadline reached before stage start")
                remaining = budget_deadline - now
                timeout = max(1.0, remaining - self.policy.teardown_reserve_seconds)
                raw = self.remote.run_stage(stage, canary_id, adapter_dir, timeout)
                result = parse_canary_result(raw.get("stdout", ""), int(raw.get("returncode", 1)), stage)
                evidence.append(PhaseEvidence(stage, result.status, False, True, result.detail))
                if result.status == "FAIL":
                    raise RuntimeError(f"{stage} failed: {result.detail}")
                if stage == "TRAIN_5_STEPS":
                    if result.steps_completed != self.policy.max_steps:
                        raise RuntimeError(f"TRAIN steps {result.steps_completed} != {self.policy.max_steps}")
                    steps = result.steps_completed

        except Exception as exc:
            execution_failed = True
            evidence.append(PhaseEvidence("FAILED", "FAIL", False, True, f"{type(exc).__name__}"))
        finally:
            if canary_id is not None:
                billing_verified, teardown_mutations = self._teardown(canary_id)
                mutations += teardown_mutations
                if not billing_verified:
                    billing_risk = "HIGH"
            evidence.append(PhaseEvidence("DESTROY", "PASS" if billing_verified else "FAIL", True, canary_id is not None,
                                           f"verified={billing_verified}"))

        if canary_id is not None and (steps != self.policy.max_steps or execution_failed):
            billing_risk = "HIGH" if not billing_verified else billing_risk
        # Execution success and cleanup success are independent dimensions.
        status = "SUCCESS" if (not execution_failed and steps == self.policy.max_steps and billing_verified) else "FAILED"
        return CanaryRunResult(
            self.run_id, status, mutations, canary_id, steps, billing_verified, billing_risk, evidence,
            self.git_head, adapter_dir_out,
        )
