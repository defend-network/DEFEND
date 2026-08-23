"""DEFEND AI Qwen3 five-step canary TRAINING entrypoint (paid host).

Real, executable training path (M1.9.2D). Imports the CANONICAL converter from
``qwen3_candidate`` (never the obsolete M1.9 conversion). Hard-locks exactly
five optimizer steps. torch/peft/transformers are imported lazily so this
module remains structurally importable in the zero-cost environment.

This is NOT a general-purpose training CLI — full-training, epoch, publish, and
promotion flags are rejected.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .qwen3_candidate import convert_sft_to_qwen3
from .qwen3_canary_runner import EXPECTED_CONVERTED_SHA, CANARY_MAX_STEPS

ALLOWED_STEPS = {CANARY_MAX_STEPS}

_FORBIDDEN_FLAGS = ("--full-train", "--publish", "--epochs", "--promote")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Qwen3 five-step canary training")
    parser.add_argument("--data-file", required=True)
    parser.add_argument("--adapter-dir", required=True)
    parser.add_argument("--steps", type=int, default=CANARY_MAX_STEPS)
    parser.add_argument("--base-repo", default="Qwen/Qwen3-32B")
    parser.add_argument("--base-revision", default="9216db5781bf21249d130ec9da846c4624c16137")
    return parser


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    for flag in _FORBIDDEN_FLAGS:
        if argv and any(a == flag for a in argv):
            raise SystemExit(f"forbidden flag {flag}: canary is exactly-five-step only")
    args = build_parser().parse_args(argv)
    if args.steps != CANARY_MAX_STEPS:
        raise SystemExit(f"canary is locked to exactly {CANARY_MAX_STEPS} optimizer steps (got {args.steps})")
    return args


def _load_and_convert(data_file: Path) -> tuple[list[dict], str]:
    rows = [json.loads(line) for line in data_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    converted, summary = convert_sft_to_qwen3(rows)
    if summary["dataset_sha256"] != EXPECTED_CONVERTED_SHA:
        raise SystemExit(f"converted dataset SHA mismatch: {summary['dataset_sha256']}")
    return converted, summary["dataset_sha256"]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    converted, sha = _load_and_convert(Path(args.data_file))
    print(f"CONVERTED_SHA_MATCH=YES sha={sha}", flush=True)
    print(f"TRAIN_ROWS={len(converted)}", flush=True)

    # Real training happens here on the paid host (torch/peft/transformers are
    # present there). The five-step loop and NF4 QLoRA load are the contract.
    import torch  # noqa: F401  (paid host only)

    from peft import LoraConfig  # noqa: F401
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, TrainingArguments  # noqa: F401
    from trl import SFTConfig, SFTTrainer  # noqa: F401

    tokenizer = AutoTokenizer.from_pretrained(args.base_repo, revision=args.base_revision, trust_remote_code=True, use_fast=True)
    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    model = AutoModelForCausalLM.from_pretrained(
        args.base_repo,
        revision=args.base_revision,
        quantization_config=bnb,
        torch_dtype=torch.bfloat16,
        trust_remote_code=True,
        device_map={"": 0},  # explicit single-GPU, never 'auto'
    )
    model.config.use_cache = False

    lora = LoraConfig(
        r=16, lora_alpha=32, lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        task_type="CAUSAL_LM", bias="none",
    )
    config = SFTConfig(
        output_dir=args.adapter_dir,
        max_seq_length=8192,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=8,
        learning_rate=2.0e-4,
        max_steps=CANARY_MAX_STEPS,
        num_train_epochs=1,
        bf16=True,
        logging_steps=1,
        save_strategy="steps",
        save_steps=1,
        report_to=[],
        seed=20260822,
        packing=False,
    )
    dataset = [{"text": tokenizer.apply_chat_template(r["messages"], tokenize=False, add_generation_prompt=False)} for r in converted]
    import datasets as ds_lib
    trainer = SFTTrainer(model=model, args=config, train_dataset=ds_lib.Dataset.from_list(dataset), tokenizer=tokenizer, peft_config=lora)
    trainer.train()
    model.save_pretrained(args.adapter_dir)
    tokenizer.save_pretrained(args.adapter_dir)
    print("OPTIMIZER_STEPS_COMPLETED=5", flush=True)
    print("ADAPTER_SAVED=" + str(Path(args.adapter_dir).resolve()), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
