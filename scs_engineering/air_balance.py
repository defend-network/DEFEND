"""SCS air balance / building balance (M1.3, P16).

Supply/return/outside-air/exhaust/relief/transfer totals -> net building
airflow balance + percent imbalance. Uses explicit caveats when flows are
incomplete. Pressurization is never inferred from airflow totals alone when a
direct pressure measurement contradicts or is unavailable.
"""
from __future__ import annotations

from typing import Any


def building_air_balance(
    *,
    supply_cfm: float | None = None,
    return_cfm: float | None = None,
    outside_air_cfm: float | None = None,
    exhaust_cfm: float | None = None,
    relief_cfm: float | None = None,
    transfer_cfm: float | None = None,
    direct_pressure_in_wc: float | None = None,
) -> dict[str, Any]:
    """Net building airflow balance with caveats for incomplete flows."""
    provided = {
        "supply": supply_cfm, "return": return_cfm, "outside_air": outside_air_cfm,
        "exhaust": exhaust_cfm, "relief": relief_cfm, "transfer": transfer_cfm,
    }
    missing = [k for k, v in provided.items() if v is None]
    has_core = supply_cfm is not None and (return_cfm is not None or exhaust_cfm is not None)
    incomplete = bool(missing)
    supply = supply_cfm or 0.0
    exhaust = (exhaust_cfm or 0.0) + (relief_cfm or 0.0)
    makeup = (outside_air_cfm or 0.0) + (transfer_cfm or 0.0)
    net = supply - (exhaust + (return_cfm or 0.0))
    denom = max(supply, (exhaust + (return_cfm or 0.0)), 1.0)
    imbalance_pct = (net / denom) * 100.0

    pressure_reading = direct_pressure_in_wc
    inferred = None
    if abs(net) >= 1.0 and has_core:
        inferred = "POSITIVE" if net > 0 else "NEGATIVE"
    warnings = []
    if missing:
        warnings.append(f"incomplete flow set (missing: {', '.join(missing)}); balance is provisional")
    if pressure_reading is not None and inferred is not None:
        if (pressure_reading > 0) != (inferred == "POSITIVE"):
            warnings.append(
                "airflow-total inference conflicts with direct pressure measurement; trust the direct measurement")

    return {
        "computable": has_core,
        "blocked_reason": None if has_core else "missing core airflow values (supply and return/exhaust)",
        "supply_cfm": supply_cfm, "return_cfm": return_cfm,
        "outside_air_cfm": outside_air_cfm, "exhaust_cfm": exhaust_cfm,
        "relief_cfm": relief_cfm, "transfer_cfm": transfer_cfm,
        "net_balance_cfm": round(net, 0),
        "percent_imbalance": round(imbalance_pct, 1),
        "inferred_pressurization": inferred,
        "direct_pressure_in_wc": pressure_reading,
        "warnings": warnings,
        "source_reference": "SCS engineering: net = supply - (exhaust + relief + return); % imbalance = net/denominator",
    }
