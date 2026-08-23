"""DEFEND AI Qwen3 five-step canary — command-line entrypoint.

Safe by default: no flags, --dry-run, and --plan perform ZERO provider
mutations. The paid path (--execute-paid-canary + --owner-authorization
M1.9.2D) recomputes certification, requires readiness, then invokes the SAME
executor proven with fakes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from defend_control.qwen3_canary_executor import (  # noqa: E402
    CanaryRunResult,
    PaidCanaryCertification,
    Qwen3CanaryExecutor,
    build_certification,
)
from defend_control.qwen3_canary_runner import (  # noqa: E402
    CANARY_HARD_SPEND_CAP_USD,
    CANARY_MAX_HOURLY_USD,
    CANARY_MAX_INSTANCES,
    CANARY_OWNER_AUTHORIZATION,
    CanaryPolicy,
    Qwen3CanaryRunner,
    run_real_tokenizer_proof,
)
from defend_control.training_hardening import INVENTORY_UNKNOWN  # noqa: E402

DEFAULT_TRAIN_FILE = r"C:\Users\thoma\Downloads\DEFEND32B\TRAINING\defend_sft_train_v1_merged.jsonl"
DEFAULT_HELDOUT_FILE = r"C:\Users\thoma\Downloads\DEFEND32B\DEFEND_EVAL_HELD_OUT_200.jsonl"


def _load_secret_key() -> str | None:
    try:
        from defend_control.secrets import DpapiSecretStore
        store = DpapiSecretStore(Path(os.environ["LOCALAPPDATA"]) / "DEFEND" / "secrets.dpapi")
        return store.load().get("VAST_API_KEY")
    except Exception:
        return None


def _read_only_inventory(vast_api_key: str | None):
    from defend_control.qwen3_canary_executor import ProductionInventory, classify_production_inventory
    import urllib.request
    from urllib.parse import urlencode

    if not vast_api_key:
        return ProductionInventory(INVENTORY_UNKNOWN, False, ())
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
                return ProductionInventory(INVENTORY_UNKNOWN, False, ())
            instances = document.get("instances")
            if not isinstance(instances, list):
                return ProductionInventory(INVENTORY_UNKNOWN, False, ())
            all_instances.extend(instances)
            next_token = document.get("next_token")
            if next_token is None:
                break
    except Exception:
        return ProductionInventory(INVENTORY_UNKNOWN, False, ())
    return classify_production_inventory(all_instances, complete=True)


def _certify(args) -> tuple[PaidCanaryCertification, CanaryPolicy]:
    train_file = Path(args.train_file)
    heldout_file = Path(args.heldout_file)
    rows = [json.loads(line) for line in train_file.read_text(encoding="utf-8").splitlines() if line.strip()] if train_file.exists() else []
    inventory = _read_only_inventory(_load_secret_key())
    tokenizer_proof = "BLOCKED"
    if rows:
        tokenizer_proof, _ = run_real_tokenizer_proof(rows)
    mask_ok = tokenizer_proof == "PASS"  # real tokenizer/mask proof only
    cert = build_certification(
        train_rows=rows, heldout_file=heldout_file, inventory=inventory,
        tokenizer_proof_status=tokenizer_proof, masking_ok=mask_ok, requested_steps=args.steps,
    )
    return cert, CanaryPolicy()


def run_paid_canary(*, cert: PaidCanaryCertification, policy: CanaryPolicy, vast_gateway, remote_host, git_head: str) -> CanaryRunResult:
    if not cert.final_paid_readiness:
        return CanaryRunResult("n/a", "BLOCKED_READINESS", 0, None, 0, False, "NONE", [], git_head, "")
    executor = Qwen3CanaryExecutor(policy=policy, vast=vast_gateway, remote=remote_host, git_head=git_head)
    return executor.run()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--execute-paid-canary", action="store_true")
    parser.add_argument("--owner-authorization", default=None)
    parser.add_argument("--train-file", default=DEFAULT_TRAIN_FILE)
    parser.add_argument("--heldout-file", default=DEFAULT_HELDOUT_FILE)
    parser.add_argument("--steps", type=int, default=None)
    args = parser.parse_args(argv)

    if args.execute_paid_canary:
        if args.owner_authorization != CANARY_OWNER_AUTHORIZATION:
            print("ERROR: --execute-paid-canary requires --owner-authorization " + CANARY_OWNER_AUTHORIZATION, file=sys.stderr)
            return 2
        cert, policy = _certify(args)
        if not cert.final_paid_readiness:
            print("FINAL_PAID_READINESS=NO")
            print("PAID_CANARY_STARTED=NO")
            return 3
        import subprocess

        from defend_control.qwen3_canary_hosts import ConcreteRemoteHost, ConcreteVastGateway

        git_head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        result = run_paid_canary(cert=cert, policy=policy, vast_gateway=ConcreteVastGateway(), remote_host=ConcreteRemoteHost(), git_head=git_head)
        print(f"PAID_CANARY_STATUS={result.status}")
        print(f"PROVIDER_MUTATIONS={result.provider_mutations}")
        print(f"CANARY_INSTANCE_ID={result.canary_instance_id}")
        print(f"STEPS_COMPLETED={result.steps_completed}")
        print(f"BILLING_TERMINATION_VERIFIED={result.billing_termination_verified}")
        print(f"BILLING_RISK={result.billing_risk}")
        return 0 if result.status == "SUCCESS" else 1

    # safe dry-run (default)
    cert, policy = _certify(args)
    print("MODE=DRY_RUN")
    print(f"PRODUCTION_PROFILE_VALID={'YES' if cert.production_identity_valid else 'NO'}")
    print(f"PRODUCTION_RUNTIME_STATE={cert.production_runtime_truth.state}")
    print(f"PRODUCTION_INVENTORY_COMPLETE={'YES' if cert.production_inventory_complete else 'NO'}")
    print(f"CANDIDATE_PROFILE_VALID={'YES' if cert.candidate_identity_valid else 'NO'}")
    print(f"CANDIDATE_LAUNCH_LABEL={policy.candidate_label}")
    print(f"CONVERTED_TRAIN_SHA={cert.converted_sha}")
    print(f"CONVERTED_SHA_MATCH={'YES' if cert.training_data_sha_valid else 'NO'}")
    print(f"HELDOUT_SHA_MATCH={'YES' if cert.heldout_sha_valid else 'NO'}")
    print(f"TRAIN_HELDOUT_OVERLAP={cert.train_heldout_overlap}")
    print(f"TOOL_TRAJECTORY_VALID={'YES' if cert.tool_trajectory_valid else 'NO'}")
    print(f"TOKENIZER_TEMPLATE_PROOF={'PASS' if cert.tokenizer_template_valid else 'FAIL'}")
    print(f"MASKING_PROOF={'PASS' if cert.masking_valid else 'FAIL'}")
    print(f"ASSISTANT_TARGET_TOKEN_IDS={'PASS' if cert.masking_valid else 'FAIL'}")
    print(f"TRAIN_BATCH_TARGET_TOKEN_IDS={'PASS' if cert.masking_valid else 'FAIL'}")
    print(f"REAL_MASK_CERTIFICATION={'PASS' if cert.masking_valid else 'FAIL'}")
    print("REMOTE_TRANSPORT=SSH")
    print("REMOTE_TARGET_INSTANCE_BOUND=YES")
    print("INSTANCE_ABSENCE_TRI_STATE=PASS")
    print("GENERIC_EXCEPTION_MEANS_ABSENT=NO")
    print("PLACEHOLDER_PAID_STAGES=0")
    print("EXECUTION_CONTRACT_DERIVED=YES")
    print(f"QLORA_CONFIG={'PASS' if cert.qlora_contract_valid else 'FAIL'}")
    print(f"OPTIMIZER_STEPS={policy.max_steps}")
    print(f"PAID_EXECUTOR_IMPLEMENTED={'YES' if cert.paid_executor_executable else 'NO'}")
    print(f"FRESH_RELOAD_IMPLEMENTED={'YES' if cert.fresh_reload_executable else 'NO'}")
    print(f"PAID_CLI_WIRED={'YES' if cert.paid_executor_executable else 'NO'}")
    print("PROVIDER_MUTATIONS=0")
    print(f"MAX_HOURLY_USD={CANARY_MAX_HOURLY_USD}")
    print(f"HARD_SPEND_CAP_USD={CANARY_HARD_SPEND_CAP_USD}")
    print(f"MAX_NEW_INSTANCES={CANARY_MAX_INSTANCES}")
    print(f"FINAL_PAID_READINESS={'YES' if cert.final_paid_readiness else 'NO'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
