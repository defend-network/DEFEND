"""Phase C live probes for providers whose credentials are configured.

Runs each provider's probe adapter once within its per-provider budget,
archives sanitized evidence, and writes a probe summary. Providers without
credentials report the missing key and spend nothing (owner adds credentials
via the Setup & Integrations control plane, never here).

Hard caps: per-provider 40 requests this sprint, $0 spend, sanitized evidence
only. Safe to re-run: evidence files are immutable (skipped if present).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from defend_integrations.phase_c_adapters import PHASE_C_ADAPTERS, phase_c_adapter_for
from defend_integrations.probing import ProbeBudget, utc_now_iso
from defend_integrations.stores import SecretRegistry, default_secret_path
from defend_control.secrets import DpapiSecretStore

# provider_id -> credential names it needs
CREDENTIALS: dict[str, tuple[str, ...]] = {
    "oddspapi": ("ODDSPAPI_API_KEY",),
    "the_odds_api": ("THE_ODDS_API_KEY",),
    "odds_api_io": ("ODDS_API_IO_API_KEY",),
    "sports_game_odds": ("SPORTS_GAME_ODDS_API_KEY",),
    "sportradar_tt": ("SPORTRADAR_API_KEY",),
    "rapidapi_tt_micro": ("RAPIDAPI_KEY",),
    "rapidapi_tabletennis": ("RAPIDAPI_KEY",),
    "rapidapi_allscores": ("RAPIDAPI_KEY",),
    "rapidapi_allsportsapi2": ("RAPIDAPI_KEY",),
    "rapidapi_tt_live": ("RAPIDAPI_KEY",),
}

# prior OddsPapi usage this sprint (4 retries + 27 deepen) stays visible
PRIOR_REQUESTS = {"oddspapi": 31}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--providers", default=None,
                        help="comma-separated subset; default: all with credentials")
    parser.add_argument("--evidence-dir", type=Path,
                        default=REPO / "docs" / "provider-contracts" / "evidence")
    parser.add_argument("--out", type=Path,
                        default=REPO / "docs" / "operations" / "PHASE_C_PROBES_V1.json")
    parser.add_argument("--spacing-seconds", type=float, default=1.5)
    args = parser.parse_args()

    reg = SecretRegistry(DpapiSecretStore(default_secret_path()))
    secrets: dict[str, str] = {}
    for name in {c for creds in CREDENTIALS.values() for c in creds}:
        value = reg.get(name)
        if value:
            secrets[name] = value

    wanted = (
        set(args.providers.split(",")) if args.providers
        else {pid for pid, creds in CREDENTIALS.items() if any(secrets.get(c) for c in creds)}
    )

    existing: dict = {}
    if args.out.is_file():
        existing = json.loads(args.out.read_text(encoding="utf-8"))
    previous = existing.get("providers", {})
    summaries = dict(previous)
    total_requests = 0
    for provider_id in sorted(wanted):
        adapter = PHASE_C_ADAPTERS.get(provider_id)
        if adapter is None:
            summaries[provider_id] = {"status": "no_adapter"}
            continue
        creds = CREDENTIALS.get(provider_id, ())
        missing = [c for c in creds if not secrets.get(c)]
        cap = max(0, 40 - PRIOR_REQUESTS.get(provider_id, 0))
        budget = ProbeBudget(provider_id, cap=cap)
        started = time.monotonic()
        if missing:
            result_note = f"missing credential(s): {', '.join(missing)}"
            summaries[provider_id] = {
                "status": "NOT_CONFIGURED",
                "note": result_note,
                "requests_used": 0,
            }
            continue
        time.sleep(args.spacing_seconds)
        result = adapter.run(secrets, budget, args.evidence_dir)
        elapsed = round(time.monotonic() - started, 1)
        total_requests += budget.used
        summaries[provider_id] = {
            "status": "PROBED",
            "requests_used": budget.used,
            "sprint_prior": PRIOR_REQUESTS.get(provider_id, 0),
            "elapsed_seconds": elapsed,
            "capabilities": dict(result.capabilities),
            "endpoints": {name: dict(d) for name, d in result.endpoints.items()},
            "notes": list(result.notes),
            "evidence_files": len(result.evidence),
            "observations": len(result.observations),
        }
        print(f"{provider_id}: used={budget.used} notes={result.notes[:3]}")

    document = {
        "schema": "Phase C live probe summary",
        "updated_at": utc_now_iso(),
        "requests_used_this_run": total_requests,
        "providers": summaries,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())