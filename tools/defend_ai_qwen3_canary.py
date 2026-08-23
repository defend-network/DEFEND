"""DEFEND AI Qwen3 five-step canary — command-line entrypoint.

Safe by default: no flags, --dry-run, and --plan perform ZERO provider
mutations. The paid path requires BOTH --execute-paid-canary and the exact
--owner-authorization literal; it is not invoked in this zero-cost milestone.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from defend_control.qwen3_canary_executor import (  # noqa: E402
    ProductionInventory,
    build_certification,
    classify_production_inventory,
)
from defend_control.qwen3_canary_runner import (  # noqa: E402
    CANARY_HARD_SPEND_CAP_USD,
    CANARY_MAX_HOURLY_USD,
    CANARY_MAX_INSTANCES,
    CANARY_OWNER_AUTHORIZATION,
    CANARY_SANITY_PROMPT,
    CanaryPolicy,
    Qwen3CanaryRunner,
    masking_contract_ok,
    run_real_tokenizer_proof,
    validate_five_steps,
    validate_qlora_contract,
)
from defend_control.training_hardening import InventoryFinding  # noqa: E402

DEFAULT_TRAIN_FILE = r"C:\Users\thoma\Downloads\DEFEND32B\TRAINING\defend_sft_train_v1_merged.jsonl"
DEFAULT_HELDOUT_FILE = r"C:\Users\thoma\Downloads\DEFEND32B\DEFEND_EVAL_HELD_OUT_200.jsonl"
DEFAULT_ADAPTER_DIR = "canary-adapter-temp"


def read_only_inventory(vast_api_key: str | None) -> ProductionInventory:
    """Read-only, pagination-complete production inventory (label-identity)."""
    if not vast_api_key:
        return ProductionInventory("UNKNOWN", False, ())
    import urllib.request
    from urllib.parse import urlencode

    all_instances: list[dict] = []
    next_token = None
    try:
        while True:
            query = {"limit": 100}
            if next_token:
                query["next_token"] = next_token
            url = "https://console.vast.ai/api/v1/instances/?" + urlencode(query)
            req = urllib.request.Request(url, headers={"Accept": "application/json", "Authorization": f"Bearer {vast_api_key}"})
            with urllib.request.urlopen(req, timeout=40) as resp:
                document = json.loads(resp.read().decode("utf-8"))
            if not isinstance(document, dict) or document.get("success") is not True:
                return ProductionInventory("UNKNOWN", False, ())
            instances = document.get("instances")
            if not isinstance(instances, list):
                return ProductionInventory("UNKNOWN", False, ())
            all_instances.extend(instances)
            next_token = document.get("next_token")
            if next_token is None:
                break
    except Exception:
        return ProductionInventory("UNKNOWN", False, ())
    return classify_production_inventory(all_instances, complete=True)


def load_secret_key() -> str | None:
    try:
        from defend_control.secrets import DpapiSecretStore

        store = DpapiSecretStore(Path(os.environ["LOCALAPPDATA"]) / "DEFEND" / "secrets.dpapi")
        return store.load().get("VAST_API_KEY")
    except Exception:
        return None


def _heldout_sha(heldout_file: Path) -> str:
    return hashlib.sha256(heldout_file.read_bytes()).hexdigest() if heldout_file.exists() else ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--execute-paid-canary", action="store_true")
    parser.add_argument("--owner-authorization", default=None)
    parser.add_argument("--train-file", default=DEFAULT_TRAIN_FILE)
    parser.add_argument("--heldout-file", default=DEFAULT_HELDOUT_FILE)
    parser.add_argument("--steps", type=int, default=None)
    parser.add_argument("--adapter-dir", default=DEFAULT_ADAPTER_DIR)
    args = parser.parse_args(argv)

    if args.execute_paid_canary:
        if args.owner_authorization != CANARY_OWNER_AUTHORIZATION:
            print("ERROR: --execute-paid-canary requires --owner-authorization " + CANARY_OWNER_AUTHORIZATION, file=sys.stderr)
            return 2
        # M1.9.2D entrypoint. NOT executed in this zero-cost milestone.
        print("PAID_EXECUTION_GATED_FOR=M1.9.2D")
        print("PAID_CANARY_STARTED=NO")
        return 0

    dry_run = args.dry_run or args.plan or True  # default is safe dry-run

    train_file = Path(args.train_file)
    heldout_file = Path(args.heldout_file)
    rows = [json.loads(line) for line in train_file.read_text(encoding="utf-8").splitlines() if line.strip()] if train_file.exists() else []

    policy = CanaryPolicy()
    runner = Qwen3CanaryRunner(policy=policy)
    _, summary = runner.plan(requested_steps=args.steps, rows=rows)

    inventory = read_only_inventory(load_secret_key())
    tokenizer_proof = run_real_tokenizer_proof(rows)[0] if rows else "BLOCKED"
    mask_ok, _ = masking_contract_ok([("system", 0, 3), ("user", 3, 8), ("tool", 8, 12), ("assistant", 12, 18)], 18)
    cert = build_certification(
        train_rows=rows, heldout_file=heldout_file, inventory=inventory,
        tokenizer_proof_status=tokenizer_proof, masking_ok=mask_ok, requested_steps=args.steps,
    )

    print("MODE=DRY_RUN")
    print(f"PRODUCTION_PROFILE_VALID={'YES' if cert.production_identity_valid else 'NO'}")
    print(f"PRODUCTION_RUNTIME_STATE={cert.production_runtime_truth.state}")
    print(f"PRODUCTION_RUNTIME_INVENTORY_STATUS={inventory.status}")
    print(f"PRODUCTION_INVENTORY_COMPLETE={'YES' if inventory.complete else 'NO'}")
    print(f"CANDIDATE_PROFILE_VALID={'YES' if cert.candidate_identity_valid else 'NO'}")
    print(f"CANDIDATE_LAUNCH_LABEL={policy.candidate_label}")
    print(f"CONVERTED_TRAIN_SHA={cert.converted_sha}")
    print(f"CONVERTED_SHA_MATCH={'YES' if cert.training_data_sha_valid else 'NO'}")
    print(f"HELDOUT_FILE_SHA={cert.heldout_sha or 'MISSING'}")
    print(f"HELDOUT_SHA_MATCH={'YES' if cert.heldout_sha_valid else 'NO'}")
    print(f"TRAIN_HELDOUT_OVERLAP={cert.train_heldout_overlap}")
    if rows:
        data_ok, data_detail = runner.validate_data_gates(rows)
        print(f"TOOL_CALLS_TOTAL={data_detail['tool_calls']}")
        print(f"TOOL_RESULTS_TOTAL={data_detail['tool_results']}")
        print(f"UNRESOLVED={data_detail['unresolved']}")
        print(f"ORPHANS={data_detail['orphans']}")
        print(f"MULTI_TOOL_ROWS={data_detail['multi_tool_rows']}")
    print(f"TOKENIZER_TEMPLATE_PROOF={tokenizer_proof}")
    print(f"MASKING_PROOF={'PASS' if cert.masking_valid else 'FAIL'}")
    print(f"QLORA_CONFIG={'PASS' if cert.qlora_contract_valid else 'FAIL'}")
    print(f"OPTIMIZER_STEPS={policy.max_steps}")
    print(f"OPTIMIZER_STEPS_CONTRACT={'PASS' if cert.five_step_contract_valid else 'FAIL'}")
    print(f"PAID_EXECUTOR_IMPLEMENTED={'YES' if cert.paid_executor_executable else 'NO'}")
    print(f"FRESH_RELOAD_IMPLEMENTED={'YES' if cert.fresh_reload_executable else 'NO'}")
    print("PAID_INSTANCE_CREATE_EXECUTED=NO")
    print("PAID_TRAINING_EXECUTED=NO")
    print("DESTROY_EXECUTED=NO")
    print("PROVIDER_MUTATIONS=0")
    print(f"MAX_HOURLY_USD={CANARY_MAX_HOURLY_USD}")
    print(f"HARD_SPEND_CAP_USD={CANARY_HARD_SPEND_CAP_USD}")
    print(f"MAX_NEW_INSTANCES={CANARY_MAX_INSTANCES}")
    print(f"FINAL_PAID_READINESS={'YES' if cert.final_paid_readiness else 'NO'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
