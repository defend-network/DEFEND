"""DEFEND AI Qwen3 five-step canary TRAINING entrypoint (paid host).

Real executable path (M1.9.2D). Uses the CANONICAL assistant-only masking
pipeline (``prepare_qwen3_training_example``) so the labels the model trains on
are exactly the labels the zero-cost proof verified. Hard-enforces the pinned
base repo/revision. Saves the trained PEFT model (``trainer.model``), never the
original quantized base. Requires ``trainer.state.global_step == 5``.

torch/peft/transformers are imported lazily so this module stays structurally
importable in the zero-cost environment.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .qwen3_candidate import convert_sft_to_qwen3
from .qwen3_canary_runner import EXPECTED_CONVERTED_SHA, CANARY_MAX_STEPS

CANARY_BASE_REPO = "Qwen/Qwen3-32B"
CANARY_BASE_REVISION = "9216db5781bf21249d130ec9da846c4624c16137"

_FORBIDDEN_FLAGS = ("--full-train", "--publish", "--epochs", "--promote")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Qwen3 five-step canary training")
    parser.add_argument("--data-file", required=True)
    parser.add_argument("--adapter-dir", required=True)
    parser.add_argument("--steps", type=int, default=CANARY_MAX_STEPS)
    parser.add_argument("--base-repo", default=CANARY_BASE_REPO)
    parser.add_argument("--base-revision", default=CANARY_BASE_REVISION)
    return parser


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    for flag in _FORBIDDEN_FLAGS:
        if argv and any(a == flag for a in argv):
            raise SystemExit(f"forbidden flag {flag}: canary is exactly-five-step only")
    args = build_parser().parse_args(argv)
    if args.steps != CANARY_MAX_STEPS:
        raise SystemExit(f"canary is locked to exactly {CANARY_MAX_STEPS} optimizer steps (got {args.steps})")
    if args.base_repo != CANARY_BASE_REPO:
        raise SystemExit(f"base repo must be {CANARY_BASE_REPO}")
    if args.base_revision != CANARY_BASE_REVISION:
        raise SystemExit(f"base revision must be pinned to {CANARY_BASE_REVISION}")
    return args


def _load_and_convert(data_file: Path) -> list[dict]:
    rows = [json.loads(line) for line in data_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    converted, summary = convert_sft_to_qwen3(rows)
    if summary["dataset_sha256"] != EXPECTED_CONVERTED_SHA:
        raise SystemExit(f"converted dataset SHA mismatch: {summary['dataset_sha256']}")
    return converted


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    converted = _load_and_convert(Path(args.data_file))
    print(f"CONVERTED_SHA_MATCH=YES rows={len(converted)}", flush=True)

    # Real training on the paid host (torch/peft/transformers present there).
    import torch  # noqa: F401

    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training  # noqa: F401
    from transformers import (  # noqa: F401
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
        DataCollatorForSeq2Seq,
        Trainer,
        TrainingArguments,
    )

    from .qwen3_masking import prepare_qwen3_training_example

    tokenizer = AutoTokenizer.from_pretrained(CANARY_BASE_REPO, revision=CANARY_BASE_REVISION, trust_remote_code=True, use_fast=True)
    tokenizer.pad_token = tokenizer.eos_token
    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    model = AutoModelForCausalLM.from_pretrained(
        CANARY_BASE_REPO, revision=CANARY_BASE_REVISION, quantization_config=bnb,
        torch_dtype=torch.bfloat16, trust_remote_code=True, device_map={"": 0},
    )
    model = prepare_model_for_kbit_training(model)
    lora = LoraConfig(
        r=16, lora_alpha=32, lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        task_type="CAUSAL_LM", bias="none",
    )
    model = get_peft_model(model, lora)
    model.config.use_cache = False

    examples = [prepare_qwen3_training_example(tokenizer, r["messages"]) for r in converted]
    import datasets as ds_lib
    dataset = ds_lib.Dataset.from_list(examples)
    collator = DataCollatorForSeq2Seq(tokenizer, padding=True, label_pad_token_id=-100)

    trainer = Trainer(
        model=model,
        args=TrainingArguments(
            output_dir=args.adapter_dir,
            per_device_train_batch_size=1,
            gradient_accumulation_steps=8,
            learning_rate=2.0e-4,
            max_steps=CANARY_MAX_STEPS,
            bf16=True,
            logging_steps=1,
            save_strategy="no",
            report_to=[],
            seed=20260822,
        ),
        train_dataset=dataset,
        tokenizer=tokenizer,
        data_collator=collator,
    )
    trainer.train()

    actual_steps = trainer.state.global_step
    print(f"OPTIMIZER_STEPS_COMPLETED={actual_steps}", flush=True)
    if actual_steps != CANARY_MAX_STEPS:
        return 1

    # Save the trained PEFT-wrapped model (adapter), never the original base.
    trainer.model.save_pretrained(args.adapter_dir)
    tokenizer.save_pretrained(args.adapter_dir)
    print("ADAPTER_SAVED=" + str(Path(args.adapter_dir).resolve()), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
