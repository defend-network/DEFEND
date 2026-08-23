"""DEFEND AI Qwen3 candidate preparation (no training).

Faithful technical transfer of the SAME current DEFEND identity content onto a
Qwen3-compatible format: tokenizer/chat-template/tool serialization changes
only. No identity, tone, ideology, or policy rewriting. The current production
Qwen2.5 + identity-lora-v002 profile is untouched.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any


# ─────────────────────────────────────────────────────────────
# v002 training recipe reconstruction from immutable evidence
# ─────────────────────────────────────────────────────────────

V002_RECIPE: dict[str, str | int | float | list[str] | None] = {
    "base_repo": "Qwen/Qwen2.5-32B-Instruct",
    "base_revision": "5ede1c97bbab6ce5cda5812749b4c0bdf79b18dd",
    "adapter_repo": "Defend-network/defend-identity-lora-v002",
    "adapter_revision": "46ade1686870210ef0ab4603c32fecb0e563330f",
    "peft_version": "0.20.0",
    "trl_version": "1.10.0",
    "transformers_version": "5.15.0",
    "pytorch_version": "2.12.0+cu130",
    "datasets_version": "5.0.1",
    "tokenizers_version": "0.22.2",
    "lora_rank": 16,
    "lora_alpha": 32,
    "lora_dropout": 0.05,
    "target_modules": ["q_proj", "k_proj", "v_proj", "down_proj", "gate_proj", "o_proj", "up_proj"],
    "task_type": "CAUSAL_LM",
    "global_step": 147,
    "num_train_epochs": 1,
    "last_epoch": 0.987,
    "method": "TRL SFT",
    # Not recoverable from available immutable artifacts:
    "learning_rate": "UNKNOWN",
    "scheduler": "UNKNOWN",
    "optimizer": "UNKNOWN",
    "micro_batch_size": "UNKNOWN",
    "gradient_accumulation_steps": "UNKNOWN",
    "max_sequence_length": "UNKNOWN",
    "warmup_steps": "UNKNOWN",
    "weight_decay": "UNKNOWN",
    "bf16": "UNKNOWN",
    "gradient_checkpointing": "UNKNOWN",
    "packing": "UNKNOWN",
    "seed": "UNKNOWN",
}


# ─────────────────────────────────────────────────────────────
# Faithful Qwen3 technical transfer
# ─────────────────────────────────────────────────────────────

_VALID_ROLES = {"system", "user", "assistant", "tool"}


def normalize_row_hash(row: dict) -> str:
    return hashlib.sha256(
        json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def validate_sft_row(row: dict) -> tuple[bool, str]:
    if not isinstance(row, dict):
        return False, "row is not an object"
    messages = row.get("messages")
    if not isinstance(messages, list) or not messages:
        return False, "row has no messages list"
    prev_role = None
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            return False, f"message {index} is not an object"
        role = message.get("role")
        if role not in _VALID_ROLES:
            return False, f"message {index} has invalid role {role!r}"
        if not isinstance(message.get("content"), str):
            return False, f"message {index} content is not a string"
        if role == "tool" and prev_role != "assistant":
            return False, f"message {index} tool without prior assistant message"
        prev_role = role
    return True, "valid"


def convert_sft_row_to_qwen3(row: dict) -> dict:
    """Faithful transfer to Qwen3-native tool serialization.

    Content and order are preserved verbatim. Only technical role/tool framing
    is normalized to Qwen3's chat-template tool-call structure.
    """
    ok, _reason = validate_sft_row(row)
    if not ok:
        raise ValueError(f"invalid SFT row: {_reason}")
    messages: list[dict[str, Any]] = []
    tool_seq = 0
    for message in row["messages"]:
        role = message["role"]
        content = message["content"]
        if role == "tool":
            tool_seq += 1
            messages.append(
                {
                    "role": "tool",
                    "content": content,
                    "tool_call_id": f"q3_call_{tool_seq}",
                }
            )
        else:
            messages.append({"role": role, "content": content})
    out = dict(row)
    out["messages"] = messages
    out["format_version"] = "qwen3-chat-tool-v1"
    return out


def convert_sft_to_qwen3(rows: list[dict]) -> tuple[list[dict], dict]:
    valid: list[dict] = []
    rejected = 0
    for row in rows:
        ok, _ = validate_sft_row(row)
        if not ok:
            rejected += 1
            continue
        valid.append(convert_sft_row_to_qwen3(row))
    raw = "\n".join(json.dumps(r, ensure_ascii=False) for r in valid)
    return valid, {
        "rows_input": len(rows),
        "rows_valid": len(valid),
        "rows_rejected": rejected,
        "dataset_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "exact_duplicates": len(valid) - len({normalize_row_hash(r) for r in valid}),
    }


# ─────────────────────────────────────────────────────────────
# Qwen3 training config (planned, not executed)
# ─────────────────────────────────────────────────────────────

def qwen3_qlora_config() -> dict[str, object]:
    return {
        "training_config_id": "defend-ai-qwen3-training-qlora-v001",
        "method": "QLORA",
        "base_repo": "Qwen/Qwen3-32B",
        "base_revision": "9216db5781bf21249d130ec9da846c4624c16137",
        "target_adapter": "Defend-network/defend-qwen3-32b-identity-lora-v001",
        "quantization": "nf4",
        "compute_dtype": "bfloat16",
        "lora_rank": 16,
        "lora_alpha": 32,
        "lora_dropout": 0.05,
        "target_modules": ["q_proj", "k_proj", "v_proj", "down_proj", "gate_proj", "o_proj", "up_proj"],
        "learning_rate": 2.0e-4,
        "scheduler": "cosine",
        "optimizer": "adamw_torch",
        "epochs": 1,
        "max_sequence_length": 8192,
        "micro_batch_size": 2,
        "gradient_accumulation_steps": 8,
        "gradient_checkpointing": True,
        "warmup_ratio": 0.03,
        "weight_decay": 0.01,
        "seed": 20260822,
        "eval_cadence": "holdout 200 examples per 1/4 epoch",
        "save_cadence": "every 10% of steps + final",
        "early_stopping": None,
        "technical_differences_from_v002": [
            "base Qwen2.5-32B-Instruct -> Qwen/Qwen3-32B (new tokenizer vocab 151936 vs 152064; new chat template; new tool-call schema)",
            "4-bit NF4 quantization for QLoRA (v002 was unquantized bf16 LoRA)",
            "micro batch/grad accum tuned for single 80GB A100 at 8K context",
            "same identity content; only technical formatting changes",
        ],
    }


# ─────────────────────────────────────────────────────────────
# Candidate training manifest (portable; no owner-specific paths)
# ─────────────────────────────────────────────────────────────

HELDOUT_EVAL_LOGICAL_NAME = "DEFEND_EVAL_HELD_OUT_200"
HELDOUT_EVAL_SHA256 = "5ee2369ea383a8590dd123fa66db8a885154a2a0bf5abc8e98c174bcdf27835a"
HELDOUT_EVAL_ROWS = 200


def build_training_manifest(*, conversion_summary: dict, code_commit: str) -> dict[str, object]:
    return {
        "manifest_version": "1.0",
        "candidate_profile_id": "defend-ai-candidate-qwen3-v001",
        "training_config_id": "defend-ai-qwen3-training-qlora-v001",
        "base_repo": "Qwen/Qwen3-32B",
        "base_revision": "9216db5781bf21249d130ec9da846c4624c16137",
        "tokenizer_repo": "Qwen/Qwen3-32B",
        "tokenizer_revision": "9216db5781bf21249d130ec9da846c4624c16137",
        "source_sft_repo": "Defend-network/defend-sft-v1",
        "source_sft_revision": None,  # resolved at runtime from immutable main ref
        "source_rows": conversion_summary.get("rows_input"),
        "heldout_eval": {
            "logical_name": HELDOUT_EVAL_LOGICAL_NAME,
            "sha256": HELDOUT_EVAL_SHA256,
            "rows": HELDOUT_EVAL_ROWS,
            "excluded_from_training": True,
        },
        "conversion_code_commit": code_commit,
        "training_dataset_sha256": conversion_summary.get("dataset_sha256"),
        "training_rows": conversion_summary.get("rows_valid"),
        "template_schema_version": "qwen3-chat-tool-v1",
        "validation": {
            "exact_duplicates": conversion_summary.get("exact_duplicates"),
            "eval_exact_leakage": conversion_summary.get("eval_exact_leakage", 0),
        },
        "target_adapter_repo": "Defend-network/defend-qwen3-32b-identity-lora-v001",
    }


# ─────────────────────────────────────────────────────────────
# Held-out evaluator config
# ─────────────────────────────────────────────────────────────

def heldout_evaluator_config(*, code_commit: str) -> dict[str, object]:
    return {
        "evaluator_id": "defend-ai-identity-eval-v1",
        "grader_version": "1",
        "eval_reference": {
            "logical_name": HELDOUT_EVAL_LOGICAL_NAME,
            "sha256": HELDOUT_EVAL_SHA256,
            "rows": HELDOUT_EVAL_ROWS,
        },
        "code_commit": code_commit,
        "gates": [
            "identity",
            "instruction_following",
            "direct_reasoning",
            "factual_accuracy",
            "calculator",
            "time",
            "multi_tool_sequential",
            "unknown_tool_honesty",
            "tool_failure_recovery",
            "documents",
            "rag",
            "memory",
            "research",
            "latency_tokens_per_sec",
            "vram_context",
        ],
        "baseline": {
            "profile": "defend-ai-production-qwen25-v002",
            "status": "not_yet_captured",
        },
    }
