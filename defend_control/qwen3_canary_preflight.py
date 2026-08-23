"""DEFEND AI Qwen3 canary remote preflight + tokenizer/mask proof entrypoint.

Runs on the paid host (M1.9.2D) BEFORE any model weight load or optimizer step.
Emits machine-readable evidence and exits nonzero on any semantic failure.
Zero-cost observable checks run now; host GPU checks are fail-closed code that
reports NOT_OBSERVABLE when no CUDA is present locally.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .qwen3_candidate import convert_sft_to_qwen3
from .qwen3_canary_runner import EXPECTED_CONVERTED_SHA, run_real_tokenizer_proof
from .qwen3_canary_train import CANARY_BASE_REVISION


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Qwen3 canary remote preflight")
    parser.add_argument("--repo-head", required=True)
    parser.add_argument("--train-file", required=True)
    parser.add_argument("--base-revision", default=CANARY_BASE_REVISION)
    parser.add_argument("--paid-host", action="store_true", help="paid-host mode: hardware facts are hard failures")
    return parser


def run_preflight(repo_head: str, train_file: Path, base_revision: str, *, paid_host: bool = False) -> tuple[bool, dict]:
    evidence: dict = {}
    failures: list[str] = []

    # 1. revision authority
    if base_revision != CANARY_BASE_REVISION:
        failures.append("base revision mismatch")
    evidence["revision_ok"] = base_revision == CANARY_BASE_REVISION
    evidence["authorized_head"] = repo_head

    # 2. dataset existence + converted SHA
    if train_file.exists():
        rows = [json.loads(line) for line in train_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        _, conversion = convert_sft_to_qwen3(rows)
        sha_ok = conversion["dataset_sha256"] == EXPECTED_CONVERTED_SHA
        evidence["converted_sha"] = conversion["dataset_sha256"]
        evidence["converted_sha_ok"] = sha_ok
        if not sha_ok:
            failures.append("converted dataset SHA mismatch")
    else:
        evidence["converted_sha_ok"] = False
        failures.append("training file missing")

    # 3. real tokenizer/template/mask proof (executes the actual proof)
    if train_file.exists():
        rows = [json.loads(line) for line in train_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        proof_status, detail = run_real_tokenizer_proof(rows)
        evidence["tokenizer_proof"] = proof_status
        if proof_status != "PASS":
            failures.append("tokenizer/mask proof failed")
    else:
        evidence["tokenizer_proof"] = "BLOCKED"
        failures.append("tokenizer proof blocked (no data)")

    # 4. GPU/CUDA (hard FAIL in paid-host mode; NOT_OBSERVABLE in zero-cost simulation)
    try:
        import torch
        cuda = torch.cuda.is_available()
        evidence["cuda_available"] = cuda
        if cuda:
            gpu_count = torch.cuda.device_count()
            gpu_name = torch.cuda.get_device_name(0)
            vram = torch.cuda.get_device_properties(0).total_memory // (1024 * 1024)
            evidence["gpu_count"] = gpu_count
            evidence["gpu_name"] = gpu_name
            evidence["vram_total_mb"] = vram
            if gpu_count != 1:
                failures.append("expected exactly one GPU")
            if "A100" not in (gpu_name or "").upper():
                failures.append("GPU not A100 family")
            if vram < 80_000:
                failures.append("VRAM below A100 80GB class")
        else:
            failures.append("CUDA unavailable")
    except Exception as exc:
        evidence["cuda_available"] = "NOT_OBSERVABLE"
        evidence["cuda_note"] = f"torch unavailable ({type(exc).__name__})"
        if paid_host:
            failures.append(f"torch import failed on paid host ({type(exc).__name__})")

    ok = not failures
    evidence["ok"] = ok
    evidence["failures"] = failures
    evidence["paid_host_mode"] = paid_host
    return ok, evidence


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ok, evidence = run_preflight(args.repo_head, Path(args.train_file), args.base_revision, paid_host=args.paid_host)
    for key, value in evidence.items():
        if not isinstance(value, (dict, list)):
            print(f"{key.upper()}={value}", flush=True)
    print(f"PREFLIGHT={'PASS' if ok else 'FAIL'}", flush=True)
    print('DEFEND_CANARY_RESULT={"status": "' + ("PASS" if ok else "FAIL") + '"}', flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
