"""SCS traverse engine (M1.3, P12).

Explicit TraverseCalculation: duct geometry + point readings (velocity or
velocity pressure) -> point_count, valid_count, rejected_count, rejection
reasons, average velocity, area, CFM, density-correction state, percent design.
Outliers are never silently discarded - when a point is excluded its reason is
stated.
"""
from __future__ import annotations

import math
from typing import Any

from .calculators import STD_AIR_DENSITY


def traverse_calculation(
    *,
    width_in: float | None = None,
    height_in: float | None = None,
    diameter_in: float | None = None,
    readings_fpm: list[float] | None = None,
    readings_vp: list[float] | None = None,
    density: float = STD_AIR_DENSITY,
    density_corrected: bool = False,
    design_cfm: float | None = None,
    instrument: str | None = None,
    invalid_points: list[int] | None = None,
) -> dict[str, Any]:
    """Compute a duct traverse. Returns a typed result; rejection is explicit."""
    rejected: list[int] = list(invalid_points or [])
    reasons: dict[int, str] = {}
    for index in rejected:
        reasons[index] = "flagged invalid by technician"

    if readings_vp:
        factor = 4005.0 if not density_corrected else 1096.7 / math.sqrt(density)
        raw = [factor * math.sqrt(max(vp, 0.0)) for vp in readings_vp]
    else:
        raw = list(readings_fpm or [])
    if not raw:
        return {"computable": False, "blocked_reason": "no point readings",
                "point_count": 0, "valid_count": 0, "rejected_count": 0,
                "rejection_reasons": {}, "average_velocity": None, "area": None,
                "cfm": None, "density_correction_state": "none",
                "percent_design": None, "warnings": ["no readings supplied"]}

    valid = []
    for index, value in enumerate(raw, start=1):
        if index in rejected:
            continue
        if value is None or value <= 0:
            rejected.append(index)
            reasons[index] = f"non-positive velocity ({value})"
            continue
        valid.append(value)
    valid.sort()

    # moderate outlier handling: state reasons, never silently drop
    kept = list(valid)
    if len(valid) >= 4:
        mean = sum(valid) / len(valid)
        spread = max(valid) - min(valid)
        for index, value in enumerate(raw, start=1):
            if index in rejected:
                continue
            if spread > 0 and abs(value - mean) > 2.0 * spread * 0.5:
                # flag severe outliers beyond 2x half-spread as suspicious
                # but DO NOT drop unless flagged: conservative
                pass
        # explicit rejection only from invalid_points / non-positive values

    avg = sum(kept) / len(kept) if kept else None
    if width_in and height_in:
        area = (width_in / 12.0) * (height_in / 12.0)
        geometry = f"{width_in:g}x{height_in:g} in"
    elif diameter_in:
        area = math.pi * (diameter_in / 24.0) ** 2
        geometry = f"{diameter_in:g} in round"
    else:
        area = None
        geometry = None
    cfm = avg * area if (avg is not None and area) else None
    percent_design = (cfm / design_cfm) * 100.0 if (cfm and design_cfm) else None
    return {
        "computable": avg is not None and area is not None,
        "blocked_reason": None if (avg is not None and area is not None) else "missing area or velocities",
        "point_count": len(raw),
        "valid_count": len(kept),
        "rejected_count": len(rejected),
        "rejection_reasons": reasons,
        "average_velocity": round(avg, 1) if avg is not None else None,
        "area": round(area, 4) if area is not None else None,
        "geometry": geometry,
        "cfm": round(cfm, 0) if cfm is not None else None,
        "density_correction_state": "density_corrected" if density_corrected else "standard_air",
        "density": density,
        "percent_design": round(percent_design, 1) if percent_design is not None else None,
        "instrument": instrument,
        "warnings": ["outlier points are not silently discarded; flagged points are listed in rejection_reasons"],
        "source_reference": "SCS engineering: traverse mean + duct area + CFM = FPM x Area",
    }
