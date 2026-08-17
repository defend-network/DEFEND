"""DEFENDcoder Vast.ai offer-search diagnostic (read-only, zero-spend).

Run:  python -m tools.defend_coder_vast_diagnose [--runtype ssh_proxy|ssh_direct]

Defaults to the ssh_proxy qualification lane (no direct-port filter).
Use --runtype ssh_direct to inspect the explicit direct-SSH lane
(additionally requires direct_port_count >= 1 at search time).

Reports ONLY sanitized counts and categories — never raw provider
payloads, never API keys, never secrets. Performs search/diagnostic
requests only; creates, modifies, or destroys nothing.

Exit codes: 0 = diagnostic complete, 2 = Vast error / invalid config.
"""

from __future__ import annotations

import argparse
import sys

from defend_control.coder_control_plane import (
    CoderNoQualifyingOffer,
    CoderPolicy,
    resource_profile,
)
from defend_control.products import ProductsSettings
from defend_control.vast import (
    OFFER_REJECTION_CATEGORIES,
    VastClient,
    approved_vast_gpu_names,
    vast_gpu_ram_floor,
)

_HEAVY_ALIAS = "defendcoder-heavy"


def _load_api_key() -> str | None:
    import os
    from pathlib import Path

    from defend_control.secrets import DpapiSecretStore
    from tools.defend_control_center import _load_coder_secrets

    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return None
    store = DpapiSecretStore(
        Path(local_app_data) / "DEFEND" / "secrets.dpapi"
    )
    try:
        secrets = _load_coder_secrets(store)
    except Exception:
        return None
    key = secrets.get("VAST_API_KEY")
    if not key or not isinstance(key, str) or not key.strip():
        return None
    return key.strip()


def run_diagnostic(runtype: str = "ssh_proxy") -> int:
    if runtype not in ("ssh_proxy", "ssh_direct"):
        print("  Diagnostic error: runtype must be ssh_proxy or ssh_direct")
        return 2
    settings = ProductsSettings.from_env()
    policy = CoderPolicy(
        max_hourly_usd=settings.coder_max_hourly_usd,
    )
    profile = resource_profile(_HEAVY_ALIAS, policy)
    ceiling = policy.max_hourly_usd
    require_direct_ports = runtype == "ssh_direct"
    key = _load_api_key()
    if key is None:
        print(
            "DEFENDcoder Vast.ai search diagnostic\n"
            "  Authenticated: NO (VAST_API_KEY not present in secret store)\n"
            "  Skipping live requests — nothing sent to Vast.ai."
        )
        print(_profile_lines(settings, policy, profile, runtype))
        return 0

    client = VastClient(key)
    print(
        "DEFENDcoder Vast.ai search diagnostic\n"
        f"  Authenticated: YES\n"
        f"  API key: [redacted]\n"
        f"  Qualification lane: {runtype}"
    )
    print(_profile_lines(settings, policy, profile, runtype))
    try:
        discovery = client.discover_gpu_names(num_gpus=profile.num_gpus)
    except Exception as error:
        print(f"  GPU-name discovery failed: {error}")
        return 2
    print("  GPU-name discovery (sanitized aggregates, zero-spend):")
    approved = approved_vast_gpu_names(policy.heavy_gpu_families)
    for name, count, min_dph, max_ram, max_rel in discovery:
        if name in approved:
            marker = " [approved]"
        else:
            marker = ""
        print(
            f"    {name:<16} count={count:<4} min_dph=${min_dph:<10} "
            f"max_gpu_ram={max_ram:<8} max_rel={max_rel}{marker}"
        )
    try:
        exact_counts = client.exact_name_counts(approved)
    except Exception as error:
        print(f"  Exact-name verification failed: {error}")
        return 2
    print("  Exact approved-name match counts (zero-spend):")
    for name, count in exact_counts:
        print(f"    {name:<16} {count}")
    try:
        no_type, ondemand, on_demand = client.probe_type_semantics()
    except Exception as error:
        print(f"  Type-semantics probe failed: {error}")
        return 2
    print(
        "  Type-semantics (search only, counts):\n"
        f"    no type     {no_type}\n"
        f"    ondemand    {ondemand}\n"
        f"    on-demand   {on_demand}"
    )
    try:
        details = client.approved_offer_details(profile)
    except Exception as error:
        print(f"  Approved offer details failed: {error}")
        return 2
    print(
        "  Approved-universe offer details (non-secret fields, "
        "no VRAM/price filter):\n"
        "    offer_id     gpu_name   gpu_ram num_gpus reliability  dph_total  disk  ports"
    )
    for row in details:
        (
            offer_id,
            gpu_name,
            gpu_ram,
            num_gpus,
            reliability,
            dph_total,
            disk_space,
            direct_port_count,
        ) = row
        print(
            f"    {offer_id:<12} {gpu_name:<10} {gpu_ram:<8} {num_gpus:<8} "
            f"{reliability:<12} ${dph_total:<9} {disk_space:<7} {direct_port_count}"
        )
    try:
        ladder = client.diagnose_filters(
            ceiling, profile, require_direct_ports=require_direct_ports
        )
    except Exception as error:
        print(f"  Filter ladder failed: {error}")
        return 2
    print("  Filter ladder (provider counts only, zero-spend):")
    for label, count in ladder:
        print(f"    {label:<16} {count}")
    try:
        offers = client.search_offers(
            ceiling,
            profile,
            require_direct_ports=require_direct_ports,
        )
    except Exception as error:
        print(f"  Offer search failed: {error}")
        return 2
    provider_returned, eligible, rejections = client.last_search_counts()
    print(
        f"  Provider query matched approved GPU universe: {provider_returned}\n"
        f"  Eligible after local validation: {eligible}"
    )
    for category in OFFER_REJECTION_CATEGORIES:
        count = dict(rejections).get(category, 0)
        if count:
            print(f"    Rejected {category}: {count}")
    if not offers:
        print(
            "  Result: NO qualifying offer under the current policy.\n"
            "  Compare the ladder drop-off points above to find the "
            "narrowing filter."
        )
    else:
        best = offers[0]
        print(
            f"  Result: {len(offers)} qualifying offer(s); cheapest "
            f"{best.offer_id} ({best.gpu_name}) @ ${best.dph_total}/hr"
        )
    return 0


def _profile_lines(
    settings: ProductsSettings,
    policy: CoderPolicy,
    profile,
    runtype: str = "ssh_proxy",
) -> str:
    errors = settings.coder_config_errors
    return (
        "  Configured max $/hr: "
        f"${settings.coder_max_hourly_usd}"
        + (f"  [{'; '.join(errors)}]" if errors else "")
        + "\n"
        f"  Qualification lane: {runtype}\n"
        f"  Required GPUs: {policy.heavy_num_gpus}\n"
        f"  Required families: {'/'.join(policy.heavy_gpu_families)}\n"
        f"  GPU memory class: >= "
        f"{vast_gpu_ram_floor(profile.min_gpu_ram_mb) // 1000} GB\n"
        f"  Vast threshold: >= "
        f"{vast_gpu_ram_floor(profile.min_gpu_ram_mb)} MB\n"
        f"  Reliability: >= {profile.min_reliability}\n"
        f"  Disk: >= {profile.min_disk_gb} GB"
        + (
            "\n  Direct ports: required (>= 1)"
            if runtype == "ssh_direct"
            else "\n  Direct ports: NOT required (proxy lane)"
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="DEFENDcoder Vast.ai offer-search diagnostic (zero-spend)."
    )
    parser.add_argument(
        "--runtype",
        choices=("ssh_proxy", "ssh_direct"),
        default="ssh_proxy",
        help="qualification lane (default: ssh_proxy)",
    )
    args = parser.parse_args()
    try:
        return run_diagnostic(runtype=args.runtype)
    except (CoderNoQualifyingOffer, ValueError) as error:
        print(f"  Diagnostic error: {error}")
        return 2


if __name__ == "__main__":
    sys.exit(main())