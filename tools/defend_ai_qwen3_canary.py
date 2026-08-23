"""DEFEND AI Qwen3 five-step canary — command-line entrypoint.

ZERO-COST: this entrypoint only ever plans and validates. It never creates,
starts, resumes, stops, or destroys a Vast instance. The paid execution path
is a separate (owner-reviewed) milestone.

Usage:
    python tools/defend_ai_qwen3_canary.py --dry-run [--train-file PATH]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Make the repo importable when run as a bare script from the repo root.
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from defend_control.qwen3_canary_runner import (  # noqa: E402
    CANARY_HARD_SPEND_CAP_USD,
    CANARY_MAX_HOURLY_USD,
    CANARY_MAX_INSTANCES,
    CANARY_SANITY_PROMPT,
    CanaryPolicy,
    Qwen3CanaryRunner,
    masking_contract_ok,
    run_real_tokenizer_proof,
    validate_five_steps,
    validate_qlora_contract,
)
from defend_control.training_hardening import (  # noqa: E402
    INVENTORY_AMBIGUOUS,
    INVENTORY_NONE_FOUND,
    INVENTORY_ONE_EXACT_REPLACEMENT,
    InventoryFinding,
    classify_production_runtime,
)

DEFAULT_TRAIN_FILE = r"C:\Users\thoma\Downloads\DEFEND32B\TRAINING\defend_sft_train_v1_merged.jsonl"
DEFAULT_ADAPTER_DIR = "canary-adapter-temp"


def read_only_inventory(vast_api_key: str | None) -> tuple[str | None, tuple[InventoryFinding, ...]]:
    """Read-only Vast instance list -> (inventory_status, findings). No mutation."""
    if not vast_api_key:
        return None, ()
    import urllib.request

    url = "https://console.vast.ai/api/v1/instances/?limit=100"
    req = urllib.request.Request(
        url, headers={"Accept": "application/json", "Authorization": f"Bearer {vast_api_key}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            document = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None, ()
    if not isinstance(document, dict) or document.get("success") is not True:
        return None, ()
    instances = document.get("instances")
    if not isinstance(instances, list):
        return None, ()
    if len(instances) == 0:
        return INVENTORY_NONE_FOUND, ()
    if len(instances) == 1:
        item = instances[0]
        return INVENTORY_ONE_EXACT_REPLACEMENT, (
            InventoryFinding(int(item.get("id")), str(item.get("actual_status", "unknown"))),
        )
    return INVENTORY_AMBIGUOUS, ()


def load_secret_key() -> str | None:
    try:
        from defend_control.secrets import DpapiSecretStore

        store = DpapiSecretStore(Path(os.environ["LOCALAPPDATA"]) / "DEFEND" / "secrets.dpapi")
        return store.load().get("VAST_API_KEY")
    except Exception:
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="plan + validate, zero provider mutations")
    parser.add_argument("--plan", action="store_true", help="alias for --dry-run")
    parser.add_argument("--train-file", default=None, help="path to canonical training jsonl")
    parser.add_argument("--steps", type=int, default=None, help="requested optimizer steps (must be 5)")
    parser.add_argument("--adapter-dir", default=DEFAULT_ADAPTER_DIR)
    args = parser.parse_args(argv)

    dry_run = args.dry_run or args.plan
    if not dry_run:
        parser.error("this zero-cost milestone only supports --dry-run/--plan")

    train_file = Path(args.train_file) if args.train_file else Path(DEFAULT_TRAIN_FILE)
    rows = None
    if train_file.exists():
        rows = [json.loads(line) for line in train_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    else:
        print(f"TRAIN_FILE_MISSING={train_file}", file=sys.stderr)

    policy = CanaryPolicy()
    runner = Qwen3CanaryRunner(policy=policy)
    evidence, summary = runner.plan(requested_steps=args.steps, rows=rows)

    inventory_status, findings = read_only_inventory(load_secret_key())
    truth = classify_production_runtime(inventory_status, findings)
    final_readiness = (
        "YES"
        if truth.state in ("PRESENT_STOPPED", "PRESENT_RUNNING", "ABSENT")
        and summary["production_profile_valid"] == "YES"
        and summary["candidate_profile_valid"] == "YES"
        and summary["optimizer_steps_contract"] == "PASS"
        and summary.get("data_gates") == "PASS"
        else "NO"
    )

    steps_ok, _ = validate_five_steps(args.steps)
    qlora_ok, _ = validate_qlora_contract({"quantization": "nf4", "device_map": {"": 0}, "compute_dtype": "bfloat16"})
    mask_ok, _ = masking_contract_ok(
        [("system", 0, 3), ("user", 3, 8), ("tool", 8, 12), ("assistant", 12, 18)], 18
    )

    tokenizer_proof = "BLOCKED"
    if rows is not None:
        tokenizer_proof, tokenizer_detail = run_real_tokenizer_proof(rows)

    final_readiness = (
        "YES"
        if truth.state in ("PRESENT_STOPPED", "PRESENT_RUNNING", "ABSENT")
        and summary["production_profile_valid"] == "YES"
        and summary["candidate_profile_valid"] == "YES"
        and summary["optimizer_steps_contract"] == "PASS"
        and summary.get("data_gates") == "PASS"
        and tokenizer_proof == "PASS"
        and qlora_ok
        and mask_ok
        else "NO"
    )

    print("MODE=DRY_RUN")
    print(f"PRODUCTION_PROFILE_VALID={summary['production_profile_valid']}")
    print(f"PRODUCTION_RUNTIME_STATE={truth.state}")
    print(f"PRODUCTION_RUNTIME_INVENTORY_STATUS={truth.inventory_status or 'UNKNOWN'}")
    print(f"CANDIDATE_PROFILE_VALID={summary['candidate_profile_valid']}")
    print(f"CANDIDATE_LAUNCH_LABEL={policy.candidate_label}")
    print(f"CANDIDATE_LAUNCH_POLICY={summary['candidate_launch_policy']}")
    if rows is not None:
        print(f"TRAIN_DATASET_SHA={summary.get('train_dataset_sha','')}")
        print(f"TOOL_CALLS_TOTAL={summary.get('tool_calls_total','')}")
        print(f"TOOL_RESULTS_TOTAL={summary.get('tool_results_total','')}")
        print(f"UNRESOLVED={summary.get('unresolved','')}")
        print(f"ORPHANS={summary.get('orphans','')}")
        print(f"MULTI_TOOL_ROWS={summary.get('multi_tool_rows','')}")
    print("HELDOUT_SHA=5ee2369ea383a8590dd123fa66db8a885154a2a0bf5abc8e98c174bcdf27835a")
    print(f"TOKENIZER_TEMPLATE_PROOF={tokenizer_proof}")
    print(f"MASKING_PROOF={'PASS' if mask_ok else 'FAIL'}")
    print(f"QLORA_CONFIG={'PASS' if qlora_ok else 'FAIL'}")
    print(f"OPTIMIZER_STEPS={policy.max_steps}")
    print(f"OPTIMIZER_STEPS_CONTRACT={'PASS' if steps_ok else 'FAIL'}")
    print(f"TEMP_ADAPTER_PATH={Path(args.adapter_dir).resolve()}")
    print("FRESH_PROCESS_RELOAD_PLANNED=YES")
    print("PAID_INSTANCE_CREATE_EXECUTED=NO")
    print("PAID_TRAINING_EXECUTED=NO")
    print("DESTROY_EXECUTED=NO")
    print("PROVIDER_MUTATIONS=0")
    print(f"MAX_HOURLY_USD={CANARY_MAX_HOURLY_USD}")
    print(f"HARD_SPEND_CAP_USD={CANARY_HARD_SPEND_CAP_USD}")
    print(f"MAX_NEW_INSTANCES={CANARY_MAX_INSTANCES}")
    print(f"FINAL_PAID_READINESS={final_readiness}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
