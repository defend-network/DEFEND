"""SCS HVAC engineering calculators (M1.3, P9-P19).

Deterministic engineering toolkit. The language model decides WHICH
calculation; deterministic code performs it. Every calculator returns a typed
result contract (calculation_id, formula_id, formula_version, result, units,
inputs_used, input_units, normalized_inputs, assumptions, standard_conditions,
computable, blocked_reason, warnings, source_reference, precision).

No freehand LLM arithmetic where a defined calculator exists.
"""
from __future__ import annotations

import math
from typing import Any

FORMULA_VERSION = "1.0"
STD_AIR_DENSITY = 0.075  # lb/ft3, 70F / 29.92 in.Hg dry air
STD_AIR_VP_FACTOR = 4005.0  # FPM = 4005 * sqrt(Vp) at standard air


def result(calculation_id: str, formula_id: str, value: float | None, *,
           units: str, inputs: dict[str, Any], input_units: dict[str, str],
           normalized: dict[str, float], assumptions: list[str] | None = None,
           standard_conditions: str | None = None,
           computable: bool = True, blocked_reason: str | None = None,
           warnings: list[str] | None = None,
           source_reference: str | None = None, precision: int = 2) -> dict[str, Any]:
    return {
        "calculation_id": calculation_id,
        "formula_id": formula_id,
        "formula_version": FORMULA_VERSION,
        "result": round(value, precision) if value is not None else None,
        "units": units,
        "inputs_used": inputs,
        "input_units": input_units,
        "normalized_inputs": normalized,
        "assumptions": assumptions or [],
        "standard_conditions_used": standard_conditions,
        "computable": computable,
        "blocked_reason": blocked_reason,
        "warnings": warnings or [],
        "source_reference": source_reference,
        "precision": precision,
    }


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _require(name: str, value: Any) -> float:
    number = _num(value)
    if number is None:
        raise ValueError(f"missing input: {name}")
    return number


def _positive(name: str, value: float) -> None:
    if value <= 0:
        raise ValueError(f"input must be positive: {name} = {value}")


# ---------------------------------------------------------------------------
# Duct geometry (P11)
# ---------------------------------------------------------------------------

# 42x20 duct: area = 42/12 * 20/12 = 3.5 * 1.6667 = 5.8333 ft2


def rectangular_duct_area(width_in: Any, height_in: Any) -> dict[str, Any]:
    formula = "duct.rect_area"
    try:
        w, h = _require("width_in", width_in), _require("height_in", height_in)
        _positive("width_in", w)
        _positive("height_in", h)
        area = (w / 12.0) * (h / 12.0)
        return result("duct_area_rect", formula, area, units="FT2",
                      inputs={"width_in": w, "height_in": h},
                      input_units={"width_in": "in", "height_in": "in"},
                      normalized={"width_in": w, "height_in": h},
                      source_reference="SCS engineering: rectangular duct area = (W/12)(H/12)",
                      precision=4)
    except ValueError as error:
        return result("duct_area_rect", formula, None, units="FT2",
                      inputs={"width_in": width_in, "height_in": height_in},
                      input_units={"width_in": "in", "height_in": "in"},
                      normalized={}, computable=False, blocked_reason=str(error))


def round_duct_area(diameter_in: Any) -> dict[str, Any]:
    formula = "duct.round_area"
    try:
        d = _require("diameter_in", diameter_in)
        _positive("diameter_in", d)
        area = math.pi * (d / 24.0) ** 2
        return result("duct_area_round", formula, area, units="FT2",
                      inputs={"diameter_in": d},
                      input_units={"diameter_in": "in"},
                      normalized={"diameter_in": d},
                      source_reference="SCS engineering: A = pi*(D/24)^2",
                      precision=4)
    except ValueError as error:
        return result("duct_area_round", formula, None, units="FT2",
                      inputs={"diameter_in": diameter_in},
                      input_units={"diameter_in": "in"}, normalized={},
                      computable=False, blocked_reason=str(error))


def equivalent_diameter(width_in: Any, height_in: Any) -> dict[str, Any]:
    """ASHRAE round equivalent diameter for a rectangular duct."""
    formula = "duct.eq_diameter"
    try:
        w, h = _require("width_in", width_in), _require("height_in", height_in)
        _positive("width_in", w)
        _positive("height_in", h)
        de = 1.3 * ((w * h) ** 0.625) / ((w + h) ** 0.25)
        return result("duct_eq_diameter", formula, de, units="IN",
                      inputs={"width_in": w, "height_in": h},
                      input_units={"width_in": "in", "height_in": "in"},
                      normalized={"width_in": w, "height_in": h},
                      assumptions=["ASHRAE round-equivalent for equal friction"],
                      source_reference="ASHRAE Fundamentals: De = 1.30[(WH)^0.625]/[(W+H)^0.25]",
                      precision=2)
    except ValueError as error:
        return result("duct_eq_diameter", formula, None, units="IN",
                      inputs={"width_in": width_in, "height_in": height_in},
                      input_units={"width_in": "in", "height_in": "in"},
                      normalized={}, computable=False, blocked_reason=str(error))


# ---------------------------------------------------------------------------
# Airflow (P11)
# ---------------------------------------------------------------------------


def cfm_from_fpm_area(fpm: Any, area_ft2: Any) -> dict[str, Any]:
    formula = "flow.cfm_from_fpm_area"
    try:
        v, a = _require("fpm", fpm), _require("area_ft2", area_ft2)
        _positive("fpm", v)
        _positive("area_ft2", a)
        cfm = v * a
        return result("cfm_from_fpm_area", formula, cfm, units="CFM",
                      inputs={"fpm": v, "area_ft2": a},
                      input_units={"fpm": "FPM", "area_ft2": "FT2"},
                      normalized={"fpm": v, "area_ft2": a},
                      source_reference="SCS engineering: CFM = FPM x Area")
    except ValueError as error:
        return result("cfm_from_fpm_area", formula, None, units="CFM",
                      inputs={"fpm": fpm, "area_ft2": area_ft2},
                      input_units={"fpm": "FPM", "area_ft2": "FT2"}, normalized={},
                      computable=False, blocked_reason=str(error))


def fpm_from_cfm_area(cfm: Any, area_ft2: Any) -> dict[str, Any]:
    formula = "flow.fpm_from_cfm_area"
    try:
        c, a = _require("cfm", cfm), _require("area_ft2", area_ft2)
        _positive("cfm", c)
        _positive("area_ft2", a)
        fpm = c / a
        return result("fpm_from_cfm_area", formula, fpm, units="FPM",
                      inputs={"cfm": c, "area_ft2": a},
                      input_units={"cfm": "CFM", "area_ft2": "FT2"},
                      normalized={"cfm": c, "area_ft2": a},
                      source_reference="SCS engineering: FPM = CFM / Area")
    except ValueError as error:
        return result("fpm_from_cfm_area", formula, None, units="FPM",
                      inputs={"cfm": cfm, "area_ft2": area_ft2},
                      input_units={"cfm": "CFM", "area_ft2": "FT2"}, normalized={},
                      computable=False, blocked_reason=str(error))


def percent_design(actual: Any, design: Any) -> dict[str, Any]:
    formula = "flow.percent_design"
    try:
        a, d = _require("actual", actual), _require("design", design)
        _positive("design", d)
        pct = (a / d) * 100.0
        return result("percent_design", formula, pct, units="%",
                      inputs={"actual": a, "design": d},
                      input_units={"actual": "CFM", "design": "CFM"},
                      normalized={"actual": a, "design": d},
                      source_reference="SCS engineering: % design = actual/design x 100")
    except ValueError as error:
        return result("percent_design", formula, None, units="%",
                      inputs={"actual": actual, "design": design},
                      input_units={"actual": "CFM", "design": "CFM"}, normalized={},
                      computable=False, blocked_reason=str(error))


def average_velocity(readings_fpm: list[Any]) -> dict[str, Any]:
    formula = "flow.average_velocity"
    try:
        values = [_require("readings_fpm", r) for r in (readings_fpm or [])]
        if not values:
            raise ValueError("missing input: readings_fpm")
        avg = sum(values) / len(values)
        return result("average_velocity", formula, avg, units="FPM",
                      inputs={"readings_fpm": values},
                      input_units={"readings_fpm": "FPM"},
                      normalized={"count": len(values)},
                      source_reference="SCS engineering: mean of point readings")
    except ValueError as error:
        return result("average_velocity", formula, None, units="FPM",
                      inputs={"readings_fpm": readings_fpm},
                      input_units={"readings_fpm": "FPM"}, normalized={},
                      computable=False, blocked_reason=str(error))


def velocity_from_vp(vp_in_wc: Any, *, density: float = STD_AIR_DENSITY,
                     density_corrected: bool = False) -> dict[str, Any]:
    formula = "flow.velocity_from_vp"
    try:
        vp = _require("vp_in_wc", vp_in_wc)
        _positive("vp_in_wc", vp)
        factor = 4005.0 if not density_corrected else 1096.7 / math.sqrt(density)
        fpm = factor * math.sqrt(vp)
        return result("velocity_from_vp", formula, fpm, units="FPM",
                      inputs={"vp_in_wc": vp, "density": density},
                      input_units={"vp_in_wc": "IN.W.C.", "density": "LB/FT3"},
                      normalized={"vp_in_wc": vp, "density": density},
                      assumptions=["standard air" if not density_corrected else "density-corrected"],
                      standard_conditions=("70F/29.92inHg" if not density_corrected else f"density {density} lb/ft3"),
                      source_reference=("FPM = 4005 sqrt(VP) at standard air"
                                        if not density_corrected
                                        else "FPM = (1096.7/sqrt(density)) sqrt(VP)"),
                      precision=1)
    except ValueError as error:
        return result("velocity_from_vp", formula, None, units="FPM",
                      inputs={"vp_in_wc": vp_in_wc, "density": density},
                      input_units={"vp_in_wc": "IN.W.C.", "density": "LB/FT3"},
                      normalized={}, computable=False, blocked_reason=str(error))


def vp_from_velocity(fpm: Any) -> dict[str, Any]:
    formula = "flow.vp_from_velocity"
    try:
        v = _require("fpm", fpm)
        _positive("fpm", v)
        vp = (v / STD_AIR_VP_FACTOR) ** 2
        return result("vp_from_velocity", formula, vp, units="IN.W.C.",
                      inputs={"fpm": v}, input_units={"fpm": "FPM"},
                      normalized={"fpm": v},
                      assumptions=["standard air"],
                      standard_conditions="70F/29.92inHg",
                      source_reference="VP = (FPM/4005)^2 at standard air")
    except ValueError as error:
        return result("vp_from_velocity", formula, None, units="IN.W.C.",
                      inputs={"fpm": fpm}, input_units={"fpm": "FPM"},
                      normalized={}, computable=False, blocked_reason=str(error))


def duct_size_normalize(text: str) -> dict[str, Any]:
    """Normalize a duct size callout like '42x20', '12x12', '10Ø', '10"Ø'."""
    import re
    formula = "duct.size_normalize"
    match = re.search(r"(\d{1,3}(?:\.\d+)?)[xX\u00d7](\d{1,3}(?:\.\d+)?)", text)
    if match:
        w, h = float(match.group(1)), float(match.group(2))
        return result("duct_size_normalize", formula, f"{w:g}x{h:g}", units="IN",
                      inputs={"text": text}, input_units={"text": "raw"},
                      normalized={"width_in": w, "height_in": h},
                      source_reference="SCS engineering: rectangular size normalization")
    round_match = re.search(r"(\d{1,3}(?:\.\d+)?)\s*[\u00d8oO]\s*(?:IN)?", text)
    if round_match:
        d = float(round_match.group(1))
        return result("duct_size_normalize", formula, f"{d:g}D", units="IN",
                      inputs={"text": text}, input_units={"text": "raw"},
                      normalized={"diameter_in": d},
                      source_reference="SCS engineering: round size normalization")
    return result("duct_size_normalize", formula, None, units="IN",
                  inputs={"text": text}, input_units={"text": "raw"},
                  normalized={}, computable=False,
                  blocked_reason=f"unrecognized duct size: {text}")


# ---------------------------------------------------------------------------
# Static / pressure (P15)
# ---------------------------------------------------------------------------


def tesp_from_split(return_static: Any, supply_static: Any) -> dict[str, Any]:
    formula = "static.tesp_split"
    try:
        r = _require("return_static", return_static)
        s = _require("supply_static", supply_static)
        # magnitude convention: return negative, supply positive
        tesp = abs(r) + abs(s)
        return result("tesp_split", formula, tesp, units="IN.W.C.",
                      inputs={"return_static": r, "supply_static": s},
                      input_units={"return_static": "IN.W.C.", "supply_static": "IN.W.C."},
                      normalized={"return_static": r, "supply_static": s},
                      assumptions=["return measured negative / supply positive",
                                   "TESP = |return| + |supply|"],
                      source_reference="SCS engineering: TESP = |RSP| + |SSP|")
    except ValueError as error:
        return result("tesp_split", formula, None, units="IN.W.C.",
                      inputs={"return_static": return_static, "supply_static": supply_static},
                      input_units={"return_static": "IN.W.C.", "supply_static": "IN.W.C."},
                      normalized={}, computable=False, blocked_reason=str(error))


def percent_of_allowable(measured: Any, allowable: Any) -> dict[str, Any]:
    formula = "static.percent_allowable"
    try:
        m, a = _require("measured", measured), _require("allowable", allowable)
        _positive("allowable", a)
        pct = (m / a) * 100.0
        return result("percent_allowable", formula, pct, units="%",
                      inputs={"measured": m, "allowable": a},
                      input_units={"measured": "IN.W.C.", "allowable": "IN.W.C."},
                      normalized={"measured": m, "allowable": a},
                      source_reference="SCS engineering: % allowable = measured/allowable x 100")
    except ValueError as error:
        return result("percent_allowable", formula, None, units="%",
                      inputs={"measured": measured, "allowable": allowable},
                      input_units={"measured": "IN.W.C.", "allowable": "IN.W.C."},
                      normalized={}, computable=False, blocked_reason=str(error))


# ---------------------------------------------------------------------------
# Fan laws / affinity (P13)
# ---------------------------------------------------------------------------


def fan_law_cfm(rpm_old: Any, rpm_new: Any, cfm_old: Any) -> dict[str, Any]:
    formula = "fanlaw.cfm"
    try:
        r1, r2, c1 = _require("rpm_old", rpm_old), _require("rpm_new", rpm_new), _require("cfm_old", cfm_old)
        _positive("rpm_old", r1)
        _positive("rpm_new", r2)
        _positive("cfm_old", c1)
        cfm = c1 * (r2 / r1)
        return result("fanlaw_cfm", formula, cfm, units="CFM",
                      inputs={"rpm_old": r1, "rpm_new": r2, "cfm_old": c1},
                      input_units={"rpm_old": "RPM", "rpm_new": "RPM", "cfm_old": "CFM"},
                      normalized={"rpm_old": r1, "rpm_new": r2, "cfm_old": c1},
                      assumptions=["same fan", "same system", "no significant system change"],
                      source_reference="Fan law 1: CFM2 = CFM1 x (RPM2/RPM1)",
                      warnings=["fan-law estimate; verify with field measurement"])
    except ValueError as error:
        return result("fanlaw_cfm", formula, None, units="CFM",
                      inputs={"rpm_old": rpm_old, "rpm_new": rpm_new, "cfm_old": cfm_old},
                      input_units={"rpm_old": "RPM", "rpm_new": "RPM", "cfm_old": "CFM"},
                      normalized={}, computable=False, blocked_reason=str(error))


def fan_law_pressure(rpm_old: Any, rpm_new: Any, sp_old: Any) -> dict[str, Any]:
    formula = "fanlaw.pressure"
    try:
        r1, r2, p1 = _require("rpm_old", rpm_old), _require("rpm_new", rpm_new), _require("sp_old", sp_old)
        _positive("rpm_old", r1)
        _positive("rpm_new", r2)
        _positive("sp_old", p1)
        sp = p1 * (r2 / r1) ** 2
        return result("fanlaw_pressure", formula, sp, units="IN.W.C.",
                      inputs={"rpm_old": r1, "rpm_new": r2, "sp_old": p1},
                      input_units={"rpm_old": "RPM", "rpm_new": "RPM", "sp_old": "IN.W.C."},
                      normalized={"rpm_old": r1, "rpm_new": r2, "sp_old": p1},
                      assumptions=["same fan", "same system", "no significant system change"],
                      source_reference="Fan law 2: SP2 = SP1 x (RPM2/RPM1)^2",
                      warnings=["fan-law estimate; verify with field measurement"])
    except ValueError as error:
        return result("fanlaw_pressure", formula, None, units="IN.W.C.",
                      inputs={"rpm_old": rpm_old, "rpm_new": rpm_new, "sp_old": sp_old},
                      input_units={"rpm_old": "RPM", "rpm_new": "RPM", "sp_old": "IN.W.C."},
                      normalized={}, computable=False, blocked_reason=str(error))


def fan_law_bhp(rpm_old: Any, rpm_new: Any, bhp_old: Any) -> dict[str, Any]:
    formula = "fanlaw.bhp"
    try:
        r1, r2, b1 = _require("rpm_old", rpm_old), _require("rpm_new", rpm_new), _require("bhp_old", bhp_old)
        _positive("rpm_old", r1)
        _positive("rpm_new", r2)
        _positive("bhp_old", b1)
        bhp = b1 * (r2 / r1) ** 3
        return result("fanlaw_bhp", formula, bhp, units="BHP",
                      inputs={"rpm_old": r1, "rpm_new": r2, "bhp_old": b1},
                      input_units={"rpm_old": "RPM", "rpm_new": "RPM", "bhp_old": "BHP"},
                      normalized={"rpm_old": r1, "rpm_new": r2, "bhp_old": b1},
                      assumptions=["same fan", "same system", "similar efficiency"],
                      source_reference="Fan law 3: BHP2 = BHP1 x (RPM2/RPM1)^3",
                      warnings=["power varies as RPM^3; verify motor loading and OEM limits",
                                "do not exceed motor/OEM limits"])
    except ValueError as error:
        return result("fanlaw_bhp", formula, None, units="BHP",
                      inputs={"rpm_old": rpm_old, "rpm_new": rpm_new, "bhp_old": bhp_old},
                      input_units={"rpm_old": "RPM", "rpm_new": "RPM", "bhp_old": "BHP"},
                      normalized={}, computable=False, blocked_reason=str(error))


def vfd_frequency_estimate(rpm_old: Any, rpm_new: Any, freq_old: Any = 60.0) -> dict[str, Any]:
    """Frequency-based VFD approximation when the fan is VFD-driven."""
    formula = "fanlaw.vfd_frequency"
    try:
        r1, r2, f1 = _require("rpm_old", rpm_old), _require("rpm_new", rpm_new), _require("freq_old", freq_old)
        _positive("rpm_old", r1)
        _positive("rpm_new", r2)
        _positive("freq_old", f1)
        freq = f1 * (r2 / r1)
        return result("vfd_frequency_estimate", formula, freq, units="HZ",
                      inputs={"rpm_old": r1, "rpm_new": r2, "freq_old": f1},
                      input_units={"rpm_old": "RPM", "rpm_new": "RPM", "freq_old": "HZ"},
                      normalized={"rpm_old": r1, "rpm_new": r2, "freq_old": f1},
                      assumptions=["VFD-driven fan", "linear RPM vs frequency",
                                   "same system"],
                      source_reference="SCS engineering: f2 = f1 x (RPM2/RPM1) for VFD",
                      warnings=["verify with tachometer; do not exceed OEM/VFD limits"])
    except ValueError as error:
        return result("vfd_frequency_estimate", formula, None, units="HZ",
                      inputs={"rpm_old": rpm_old, "rpm_new": rpm_new, "freq_old": freq_old},
                      input_units={"rpm_old": "RPM", "rpm_new": "RPM", "freq_old": "HZ"},
                      normalized={}, computable=False, blocked_reason=str(error))


# ---------------------------------------------------------------------------
# Electrical / motor (P17)
# ---------------------------------------------------------------------------


def three_phase_power(volts: Any, amps: Any, pf: Any = None) -> dict[str, Any]:
    formula = "elec.three_phase_power"
    try:
        v, i = _require("volts", volts), _require("amps", amps)
        _positive("volts", v)
        _positive("amps", i)
        if pf is None:
            apparent = v * i * math.sqrt(3)
            return result("three_phase_power", formula, apparent, units="VA",
                          inputs={"volts": v, "amps": i},
                          input_units={"volts": "V", "amps": "A"},
                          normalized={"volts": v, "amps": i},
                          assumptions=["apparent power; no power factor supplied"],
                          warnings=["power factor not supplied; result is VA not W"],
                          source_reference="S = sqrt(3) x V x I (3-phase)")
        pf_val = _require("pf", pf)
        if not 0.0 < pf_val <= 1.0:
            raise ValueError(f"power factor must be 0..1: {pf_val}")
        watts = v * i * math.sqrt(3) * pf_val
        return result("three_phase_power", formula, watts, units="W",
                      inputs={"volts": v, "amps": i, "pf": pf_val},
                      input_units={"volts": "V", "amps": "A", "pf": "unitless"},
                      normalized={"volts": v, "amps": i, "pf": pf_val},
                      source_reference="P = sqrt(3) x V x I x PF (3-phase)")
    except ValueError as error:
        return result("three_phase_power", formula, None, units="W",
                      inputs={"volts": volts, "amps": amps, "pf": pf},
                      input_units={"volts": "V", "amps": "A", "pf": "unitless"},
                      normalized={}, computable=False, blocked_reason=str(error))


def hp_to_kw(hp: Any) -> dict[str, Any]:
    formula = "elec.hp_to_kw"
    try:
        h = _require("hp", hp)
        _positive("hp", h)
        return result("hp_to_kw", formula, h * 0.7457, units="KW",
                      inputs={"hp": h}, input_units={"hp": "HP"},
                      normalized={"hp": h},
                      source_reference="1 HP = 0.7457 kW")
    except ValueError as error:
        return result("hp_to_kw", formula, None, units="KW",
                      inputs={"hp": hp}, input_units={"hp": "HP"}, normalized={},
                      computable=False, blocked_reason=str(error))


# ---------------------------------------------------------------------------
# VAV (P18) - conservative; no universal constants assumed
# ---------------------------------------------------------------------------


def vav_cfm_from_vp(k_factor: Any, vp_in_wc: Any) -> dict[str, Any]:
    """CFM = K x sqrt(VP) where K is the controller/box flow coefficient."""
    formula = "vav.cfm_from_vp"
    try:
        k, vp = _require("k_factor", k_factor), _require("vp_in_wc", vp_in_wc)
        _positive("k_factor", k)
        _positive("vp_in_wc", vp)
        cfm = k * math.sqrt(vp)
        return result("vav_cfm_from_vp", formula, cfm, units="CFM",
                      inputs={"k_factor": k, "vp_in_wc": vp},
                      input_units={"k_factor": "unitless", "vp_in_wc": "IN.W.C."},
                      normalized={"k_factor": k, "vp_in_wc": vp},
                      assumptions=["K factor from controller/box documentation"],
                      warnings=["only valid for the specific controller/box K factor"],
                      source_reference="SCS engineering: CFM = K x sqrt(VP); K from controller doc")
    except ValueError as error:
        return result("vav_cfm_from_vp", formula, None, units="CFM",
                      inputs={"k_factor": k_factor, "vp_in_wc": vp_in_wc},
                      input_units={"k_factor": "unitless", "vp_in_wc": "IN.W.C."},
                      normalized={}, computable=False, blocked_reason=str(error))


def vav_min_max_percent(measured: Any, min_cfm: Any, max_cfm: Any) -> dict[str, Any]:
    formula = "vav.min_max_percent"
    try:
        m, lo, hi = _require("measured", measured), _require("min_cfm", min_cfm), _require("max_cfm", max_cfm)
        _positive("max_cfm", hi)
        pct_min = (m / lo) * 100.0 if lo else None
        pct_max = (m / hi) * 100.0 if hi else None
        return result("vav_min_max_percent", formula, {
            "percent_of_min": round(pct_min, 1) if pct_min is not None else None,
            "percent_of_max": round(pct_max, 1) if pct_max is not None else None,
        }, units="%",
                      inputs={"measured": m, "min_cfm": lo, "max_cfm": hi},
                      input_units={"measured": "CFM", "min_cfm": "CFM", "max_cfm": "CFM"},
                      normalized={"measured": m, "min_cfm": lo, "max_cfm": hi},
                      source_reference="SCS engineering: measured vs min/max setpoints")
    except ValueError as error:
        return result("vav_min_max_percent", formula, None, units="%",
                      inputs={"measured": measured, "min_cfm": min_cfm, "max_cfm": max_cfm},
                      input_units={"measured": "CFM", "min_cfm": "CFM", "max_cfm": "CFM"},
                      normalized={}, computable=False, blocked_reason=str(error))


# ---------------------------------------------------------------------------
# Toolkit dispatch (tool-first routing support)
# ---------------------------------------------------------------------------

CALCULATORS: dict[str, Any] = {
    "rect_area": rectangular_duct_area,
    "round_area": round_duct_area,
    "eq_diameter": equivalent_diameter,
    "cfm": cfm_from_fpm_area,
    "fpm": fpm_from_cfm_area,
    "percent_design": percent_design,
    "avg_velocity": average_velocity,
    "velocity_from_vp": velocity_from_vp,
    "vp_from_velocity": vp_from_velocity,
    "duct_size": duct_size_normalize,
    "tesp": tesp_from_split,
    "percent_allowable": percent_of_allowable,
    "fanlaw_cfm": fan_law_cfm,
    "fanlaw_pressure": fan_law_pressure,
    "fanlaw_bhp": fan_law_bhp,
    "vfd_frequency": vfd_frequency_estimate,
    "three_phase_power": three_phase_power,
    "hp_kw": hp_to_kw,
    "vav_cfm": vav_cfm_from_vp,
    "vav_min_max": vav_min_max_percent,
}


def run_calculator(name: str, **inputs: Any) -> dict[str, Any]:
    calc = CALCULATORS.get(name)
    if calc is None:
        return result(name, "unknown", None, units="", inputs=inputs,
                      input_units={}, normalized={}, computable=False,
                      blocked_reason=f"unknown calculator: {name}")
    return calc(**inputs)
