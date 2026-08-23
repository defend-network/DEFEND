"""DEFEND AI Qwen3 five-step canary runner (zero-cost / dry-run capable).

Owns the canary execution SEQUENCE only. Canonical model identity, the Qwen3
converter/validator, training-environment validation, host preflight, and the
production mutation guard all live in their canonical modules; this runner
composes them and never re-implements them.

``--dry-run`` / ``plan()`` performs every zero-cost validation and emits a
sanitized phase plan while making ZERO provider mutations. The paid execution
path (M1.9.2D) is structurally identical but is not run here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Callable

from .qwen3_candidate import convert_sft_to_qwen3
from .training_hardening import (
    CANDIDATE_CANARY_LABEL,
    CANDIDATE_CANARY_PURPOSE,
    CANDIDATE_CANARY_ROLE,
    CANDIDATE_TRAINING_PROFILE_ID,
    build_paid_canary_readiness,
    classify_production_runtime,
    qlora_config_valid,
    qlora_device_placement_valid,
    resolve_production_identity,
    validate_assistant_masking,
    validate_candidate_canary_identity,
)

CANARY_MAX_STEPS = 5
CANARY_MAX_HOURLY_USD = Decimal("1.20")
CANARY_HARD_SPEND_CAP_USD = Decimal("2.00")
CANARY_MAX_INSTANCES = 1

CANARY_ADAPTER_DIR = "canary-adapter-temp"
CANARY_OWNER_AUTHORIZATION = "M1.9.2D"
EXPECTED_CONVERTED_SHA = "d59b05ee323dc6d8bda8086c2aa3f9589acb8eae883afb173095f53117e1e854"
EXPECTED_HELDOUT_SHA = "5ee2369ea383a8590dd123fa66db8a885154a2a0bf5abc8e98c174bcdf27835a"
PRODUCTION_LABEL = "defend-vllm"


class CanaryPhase(str, Enum):
    PLAN = "PLAN"
    INVENTORY = "INVENTORY"
    OFFER_SELECTION = "OFFER_SELECTION"
    INSTANCE_CREATE = "INSTANCE_CREATE"
    HOST_PREFLIGHT = "HOST_PREFLIGHT"
    TOKENIZER_TEMPLATE_PROOF = "TOKENIZER_TEMPLATE_PROOF"
    QLORA_LOAD = "QLORA_LOAD"
    TRAIN_5_STEPS = "TRAIN_5_STEPS"
    SAVE_TEMP_ADAPTER = "SAVE_TEMP_ADAPTER"
    FRESH_RELOAD = "FRESH_RELOAD"
    SANITY_INFERENCE = "SANITY_INFERENCE"
    DESTROY = "DESTROY"
    VERIFY_DESTROYED = "VERIFY_DESTROYED"
    FINAL_INVENTORY = "FINAL_INVENTORY"


#: Phases that would mutate the Vast provider when executed for real.
_MUTATING_PHASES = {CanaryPhase.INSTANCE_CREATE, CanaryPhase.DESTROY}


@dataclass
class PhaseEvidence:
    phase: str
    status: str  # PASS | BLOCKED | SKIPPED_DRY_RUN
    would_mutate_provider: bool
    executed: bool
    detail: str


@dataclass(frozen=True)
class CanaryPolicy:
    max_steps: int = CANARY_MAX_STEPS
    max_hourly_usd: Decimal = CANARY_MAX_HOURLY_USD
    hard_spend_cap_usd: Decimal = CANARY_HARD_SPEND_CAP_USD
    max_instances: int = CANARY_MAX_INSTANCES
    candidate_label: str = CANDIDATE_CANARY_LABEL
    candidate_profile_id: str = CANDIDATE_TRAINING_PROFILE_ID
    candidate_purpose: str = CANDIDATE_CANARY_PURPOSE
    candidate_role: str = CANDIDATE_CANARY_ROLE


def validate_five_steps(requested_steps: int | None) -> tuple[bool, str]:
    """The canary is exactly five optimizer steps. No epoch ambiguity."""
    if requested_steps is None or requested_steps == CANARY_MAX_STEPS:
        return True, f"steps locked to {CANARY_MAX_STEPS}"
    return False, f"canary must run exactly {CANARY_MAX_STEPS} optimizer steps, got {requested_steps}"


def validate_qlora_contract(cfg: dict) -> tuple[bool, str]:
    """NF4 QLoRA only; CPU/disk offload and device_map='auto' are forbidden."""
    if cfg.get("quantization") != "nf4":
        return False, "canary quantization must be nf4"
    ok, reason = qlora_config_valid(
        {"load_in_4bit": True, "device_map": cfg.get("device_map"), "bnb_4bit_compute_dtype": cfg.get("compute_dtype", "bfloat16")}
    )
    if not ok:
        return False, reason
    return True, "QLoRA NF4 contract valid (no CPU/disk offload)"


def _build_labels_for_spans(role_spans: list[tuple[str, int, int]], token_count: int) -> list[int]:
    """Construct assistant-only training labels from role spans: assistant tokens
    trainable, every other role masked (-100)."""
    labels = [-100] * token_count
    for role, start, end in role_spans:
        if role == "assistant":
            for pos in range(start, end):
                labels[pos] = pos
    return labels


def masking_contract_ok(role_spans: list[tuple[str, int, int]], token_count: int) -> tuple[bool, list[str]]:
    labels = _build_labels_for_spans(role_spans, token_count)
    return validate_assistant_masking(labels, role_spans)


def _sanitize_path(path: Path | None) -> str:
    if path is None:
        return ""
    return str(Path(path).resolve())


class Qwen3CanaryRunner:
    def __init__(self, *, policy: CanaryPolicy | None = None, vast_client=None) -> None:
        self.policy = policy or CanaryPolicy()
        self.vast_client = vast_client

    # ── zero-cost validations ────────────────────────────────

    def validate_production_identity(self) -> tuple[bool, str]:
        identity = resolve_production_identity()
        if identity is None:
            return False, "canonical production profile missing/malformed"
        return True, f"production identity {identity.profile_id} valid"

    def validate_candidate_identity(self) -> tuple[bool, str]:
        return validate_candidate_canary_identity(
            launch_label=self.policy.candidate_label,
            profile_id=self.policy.candidate_profile_id,
            purpose=self.policy.candidate_purpose,
            role=self.policy.candidate_role,
        )

    def validate_data_gates(self, rows: list[dict]) -> tuple[bool, dict]:
        """Reuse the canonical converter/validator; verify 486/486 tool
        trajectory, hashes, and multi-tool pairing."""
        converted, summary = convert_sft_to_qwen3(rows)
        tool_calls = sum(len(m.get("tool_calls", [])) for r in converted for m in r["messages"] if m["role"] == "assistant")
        tool_results = sum(1 for r in converted for m in r["messages"] if m["role"] == "tool")
        multi_tool_rows = 0
        pairing_failures = 0
        orphans = 0
        unresolved = 0
        for r in converted:
            call_ids = [c["id"] for m in r["messages"] if m["role"] == "assistant" for c in m.get("tool_calls", [])]
            result_ids = [m.get("tool_call_id") for m in r["messages"] if m["role"] == "tool"]
            n_calls = len(call_ids)
            if n_calls > 1:
                multi_tool_rows += 1
                if call_ids != result_ids:
                    pairing_failures += 1
            if n_calls < len(result_ids):
                orphans += len(result_ids) - n_calls
            if n_calls > len(result_ids):
                unresolved += n_calls - len(result_ids)
        ok = (
            summary["dataset_sha256"] == EXPECTED_CONVERTED_SHA
            and summary["rows_rejected"] == 0
            and tool_calls == 486
            and tool_results == 486
            and orphans == 0
            and unresolved == 0
            and multi_tool_rows == 9
            and pairing_failures == 0
        )
        detail = {
            "converted_sha": summary["dataset_sha256"],
            "rows_valid": summary["rows_valid"],
            "rows_rejected": summary["rows_rejected"],
            "tool_calls": tool_calls,
            "tool_results": tool_results,
            "orphans": orphans,
            "unresolved": unresolved,
            "multi_tool_rows": multi_tool_rows,
            "pairing_failures": pairing_failures,
        }
        return ok, detail

    def validate_steps(self, requested_steps: int | None) -> tuple[bool, str]:
        return validate_five_steps(requested_steps)

    # ── dry-run plan ─────────────────────────────────────────

    def plan(self, *, requested_steps: int | None = None, rows: list[dict] | None = None, inventory_status: str | None = None) -> tuple[list[PhaseEvidence], dict]:
        """Emit the full phase plan and run every zero-cost validation.

        ZERO provider mutations. ``rows`` is the canonical training rows; when
        None the data-gate phase reports BLOCKED rather than fabricating a pass.
        """
        evidence: list[PhaseEvidence] = []

        identity_ok, identity_msg = self.validate_production_identity()
        candidate_ok, candidate_msg = self.validate_candidate_identity()
        steps_ok, steps_msg = validate_five_steps(requested_steps)

        phases = list(CanaryPhase)
        for phase in phases:
            would_mutate = phase in _MUTATING_PHASES
            if would_mutate:
                evidence.append(PhaseEvidence(phase.value, "SKIPPED_DRY_RUN", True, False, "would mutate provider; not executed"))
            else:
                evidence.append(PhaseEvidence(phase.value, "PLAN", False, False, "zero-cost phase"))

        summary = {
            "mode": "DRY_RUN",
            "production_profile_valid": "YES" if identity_ok else "NO",
            "production_profile_detail": identity_msg,
            "candidate_profile_valid": "YES" if candidate_ok else "NO",
            "candidate_launch_label": self.policy.candidate_label,
            "candidate_launch_policy": "PASS" if candidate_ok else "FAIL",
            "optimizer_steps": self.policy.max_steps,
            "optimizer_steps_contract": "PASS" if steps_ok else "FAIL",
            "provider_mutations": 0,
            "paid_instance_create_executed": False,
            "paid_training_executed": False,
            "destroy_executed": False,
        }

        if rows is not None:
            data_ok, data_detail = self.validate_data_gates(rows)
            summary["train_dataset_sha"] = data_detail["converted_sha"]
            summary["tool_calls_total"] = data_detail["tool_calls"]
            summary["tool_results_total"] = data_detail["tool_results"]
            summary["unresolved"] = data_detail["unresolved"]
            summary["orphans"] = data_detail["orphans"]
            summary["multi_tool_rows"] = data_detail["multi_tool_rows"]
            summary["data_gates"] = "PASS" if data_ok else "FAIL"
        else:
            summary["data_gates"] = "BLOCKED"

        if inventory_status is not None:
            truth = classify_production_runtime(inventory_status)
            summary["production_runtime_state"] = truth.state
            summary["production_runtime_inventory_status"] = truth.inventory_status
            summary["final_paid_readiness"] = "YES" if (truth.state in ("PRESENT_STOPPED", "PRESENT_RUNNING", "ABSENT") and identity_ok and candidate_ok and steps_ok) else "NO"
        else:
            summary["production_runtime_state"] = "UNKNOWN"
            summary["final_paid_readiness"] = "NO"

        return evidence, summary


def build_fresh_reload_command(adapter_dir: Path | None = None, sanity_prompt: str | None = None) -> list[str]:
    """Construct the fresh-process reload + non-heldout sanity inference command.

    The reload MUST be a genuinely new Python process (never the training
    process). The sanity prompt is canary-scoped, never a heldout row.
    """
    import sys

    target = Path(adapter_dir) if adapter_dir else Path(CANARY_ADAPTER_DIR)
    cmd = [
        sys.executable,
        "-m",
        "defend_control.qwen3_canary_reload",
        "--adapter-dir",
        _sanitize_path(target),
    ]
    if sanity_prompt:
        cmd += ["--sanity-prompt", sanity_prompt]
    return cmd


CANARY_SANITY_PROMPT = "Reply with the single word: ready."


def run_real_tokenizer_proof(rows: list[dict]) -> tuple[str, dict]:
    """Real pinned-Qwen3 tokenizer/template + assistant-only masking proof.

    Zero-cost (tokenizer is non-billable). Returns ("PASS" | "BLOCKED" | "FAIL",
    detail). BLOCKED when transformers/tokenizer/network is unavailable.
    """
    try:
        from transformers import AutoTokenizer
    except Exception as exc:  # pragma: no cover - environment dependent
        return "BLOCKED", {"reason": f"transformers unavailable: {exc}"}
    try:
        tokenizer = AutoTokenizer.from_pretrained(
            "Qwen/Qwen3-32B",
            revision="9216db5781bf21249d130ec9da846c4624c16137",
            trust_remote_code=True,
            use_fast=True,
        )
    except Exception as exc:  # pragma: no cover
        return "BLOCKED", {"reason": f"tokenizer load failed: {exc}"}

    from .qwen3_candidate import convert_sft_row_to_qwen3
    from .qwen3_masking import qwen3_masking_proof

    direct = multi_turn = single_tool = multi_tool = None
    for row in rows:
        msgs = row.get("messages", [])
        n_calls = sum(len(m.get("tool_calls", [])) for m in msgs if m.get("role") == "assistant")
        n_assistant = sum(1 for m in msgs if m.get("role") == "assistant")
        if n_calls == 0 and n_assistant == 1 and direct is None:
            direct = row
        elif n_calls == 0 and n_assistant >= 2 and multi_turn is None:
            multi_turn = row
        elif n_calls == 1 and single_tool is None:
            single_tool = row
        elif n_calls >= 2 and multi_tool is None:
            multi_tool = row

    results = {}
    all_ok = True
    for label, row in (("direct", direct), ("multi_turn", multi_turn), ("single_tool", single_tool), ("multi_tool", multi_tool)):
        if row is None:
            results[label] = {"ok": False, "reason": "representative row not found"}
            all_ok = False
            continue
        converted = convert_sft_row_to_qwen3(row)
        ok, detail = qwen3_masking_proof(tokenizer, converted["messages"])
        results[label] = {"ok": ok, "assistant_trainable": detail["assistant_trainable"], "failures": detail["failures"][:3]}
        if not ok:
            all_ok = False

    return ("PASS" if all_ok else "FAIL"), results

