"""DEFEND AI Qwen3 canary fresh-process adapter reload + non-heldout sanity.

REAL executable reload path (M1.9.2D). Runs in a genuinely new Python process
(never the training process). Loads the pinned Qwen3 base + the temporary
five-step PEFT adapter, proves the adapter is actually attached, and runs one
tiny synthetic (non-heldout) sanity prompt.

torch/peft/transformers are imported lazily so the module remains structurally
importable in the zero-cost environment, but the paid-host code path is real.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CANARY_BASE_REPO = "Qwen/Qwen3-32B"
CANARY_BASE_REVISION = "9216db5781bf21249d130ec9da846c4624c16137"

PEFT_FILES = ("adapter_config.json", "adapter_model.safetensors")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Qwen3 canary adapter reload sanity")
    parser.add_argument("--adapter-dir", required=True)
    parser.add_argument("--sanity-prompt", default="Reply with the single word: ready.")
    parser.add_argument("--base-repo", default=CANARY_BASE_REPO)
    parser.add_argument("--base-revision", default=CANARY_BASE_REVISION)
    return parser


def _validate_adapter_dir(adapter_dir: Path) -> tuple[bool, str]:
    if not adapter_dir.is_dir():
        return False, "adapter dir missing"
    missing = [f for f in PEFT_FILES if not (adapter_dir / f).exists()]
    if missing:
        return False, f"adapter missing PEFT artifacts: {missing}"
    return True, "adapter PEFT artifacts present"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.base_repo != CANARY_BASE_REPO:
        print("RELOAD_SANITY=FAIL (base repo pin mismatch)", file=sys.stderr)
        return 5
    if args.base_revision != CANARY_BASE_REVISION:
        print("RELOAD_SANITY=FAIL (base revision pin mismatch)", file=sys.stderr)
        return 5
    adapter_dir = Path(args.adapter_dir).expanduser().resolve()

    ok, detail = _validate_adapter_dir(adapter_dir)
    print(f"ADAPTER_DIR_VALID={'YES' if ok else 'NO'} ({detail})", flush=True)
    if not ok:
        print("RELOAD_SANITY=FAIL", flush=True)
        return 2

    # Real reload happens here on the paid host.
    import torch  # noqa: F401  (paid host only)

    from peft import PeftModel  # noqa: F401
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig  # noqa: F401

    if not torch.cuda.is_available():
        print("RELOAD_SANITY=FAIL (CUDA required)", file=sys.stderr)
        return 3

    print("BASE_PIN_MATCH=YES", flush=True)
    tokenizer = AutoTokenizer.from_pretrained(CANARY_BASE_REPO, revision=CANARY_BASE_REVISION, trust_remote_code=True, use_fast=True)
    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    model = AutoModelForCausalLM.from_pretrained(
        CANARY_BASE_REPO,
        revision=CANARY_BASE_REVISION,
        quantization_config=bnb,
        torch_dtype=torch.bfloat16,
        trust_remote_code=True,
        device_map={"": 0},  # explicit, no CPU/disk offload
    )
    model = PeftModel.from_pretrained(model, str(adapter_dir))
    print("ADAPTER_LOADED=YES", flush=True)

    inputs = tokenizer(args.sanity_prompt, return_tensors="pt").to(model.device)
    input_length = inputs["input_ids"].shape[1]
    outputs = model.generate(**inputs, max_new_tokens=16, do_sample=False)
    generated_ids = outputs[0][input_length:]
    generated_text = tokenizer.decode(generated_ids, skip_special_tokens=True).strip()
    generated_nonempty = len(generated_ids) > 0 and bool(generated_text)
    print(f"GENERATED_TOKENS={len(generated_ids)}", flush=True)
    print(f"SANITY_COMPLETION_NONEMPTY={'YES' if generated_nonempty else 'NO'}", flush=True)
    print(f"CUDA_DEVICE={model.device}", flush=True)
    print(f"RELOAD_SANITY={'PASS' if generated_nonempty else 'FAIL'}", flush=True)
    print('DEFEND_CANARY_RESULT={"status": "' + ("PASS" if generated_nonempty else "FAIL") + '"}', flush=True)
    return 0 if generated_nonempty else 4


if __name__ == "__main__":
    raise SystemExit(main())
