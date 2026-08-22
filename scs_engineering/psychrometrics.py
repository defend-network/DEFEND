"""SCS psychrometric / capacity engine (M1.3, P14).

Deterministic psychrometric math (ASHRAE approximations) - never LLM
estimates. Clearly distinguishes RULE_OF_THUMB_STANDARD_AIR from
DENSITY/PSYCHROMETRIC-CORRECTED paths.

Formulas:
  Pws(T)       ASHRAE saturation pressure over liquid water (T in K)
  W(T,RH,P)    humidity ratio
  h(T,W)       moist air enthalpy (Btu/lb)
  Td(T,RH)     dew point (Magnus approximation)
  Qs = 1.085 x CFM x dT        sensible (standard air)
  Qt = 4.5 x CFM x dh          total from enthalpy (standard air)
"""
from __future__ import annotations

import math
from typing import Any

_PWS_C = [
    -5.6745359e3, 6.3925247, -9.6778430e-3, 6.2215701e-7,
    2.0747825e-9, -9.4840240e-13, 4.1635019,
]


def saturation_pressure_kpa(db_f: float) -> float:
    """ASHRAE saturation pressure over liquid water, returned in kPa."""
    t_k = (db_f - 32.0) * 5.0 / 9.0 + 273.15
    ln_pws = (_PWS_C[0] / t_k + _PWS_C[1] + _PWS_C[2] * t_k +
              _PWS_C[3] * t_k ** 2 + _PWS_C[4] * t_k ** 3 +
              _PWS_C[5] * t_k ** 4 + _PWS_C[6] * math.log(t_k))
    return math.exp(ln_pws) / 1000.0  # Pa -> kPa


def humidity_ratio(db_f: float, rh_pct: float, baro_in_hg: float = 29.92) -> float:
    """lb water / lb dry air."""
    pws = saturation_pressure_kpa(db_f)
    pw = (rh_pct / 100.0) * pws
    p_total = baro_in_hg * 3.38639  # in.Hg -> kPa
    return 0.621945 * pw / (p_total - pw)


def enthalpy_bulb(db_f: float, w: float) -> float:
    """Moist air enthalpy in Btu/lb."""
    return 0.24 * db_f + w * (1061.0 + 0.444 * db_f)


def dew_point_f(db_f: float, rh_pct: float) -> float:
    """Dew point via Magnus approximation (Celsius coefficients), in F."""
    c = (db_f - 32.0) * 5.0 / 9.0
    a = 17.625
    b = 243.04
    alpha = math.log(max(rh_pct, 0.1) / 100.0) + (a * c) / (b + c)
    td_c = (b * alpha) / (a - alpha)
    return td_c * 9.0 / 5.0 + 32.0


def temperature_split(db_f: float, cfm: float, sens_capacity_btuh: float,
                      *, standard_air: bool = True) -> dict[str, Any]:
    """Sensible capacity -> temperature split (standard air rule of thumb)."""
    if not standard_air:
        return {"computable": False,
                "blocked_reason": "temperature split requires psychrometric-correced path; supply density/enthalpy",
                "warnings": ["rule-of-thumb split not used for non-standard air"]}
    if not cfm or cfm <= 0:
        return {"computable": False, "blocked_reason": "cfm must be positive"}
    dt = sens_capacity_btuh / (1.085 * cfm)
    return {"computable": True, "formula": "Qs = 1.085 x CFM x dT",
            "result": round(dt, 2), "units": "DELTA_F",
            "standard_conditions_used": "70F/29.92inHg standard air",
            "warnings": ["standard-air rule of thumb; not psychrometrically corrected"],
            "source_reference": "SCS engineering: dT = Qs / (1.085 x CFM)"}


def sensible_capacity(db_f: float, cfm: float, *, standard_air: bool = True,
                      density_corrected: bool = False,
                      density: float = 0.075) -> dict[str, Any]:
    """Sensible capacity from a temperature split. Provide db_f as the split
    OR pass split separately via temperature_split(). This helper computes
    the constant used."""
    return {"computable": True,
            "constant": 1.085 if standard_air else (1.10 * density / 0.075),
            "units": "BTUH_PER_CFM_PER_DELTAF",
            "standard_air": standard_air,
            "source_reference": "SCS engineering: Qs = k x CFM x dT; k=1.085 standard air"}


def capacity_from_enthalpy(cfm: float, h_enter: float, h_leave: float,
                           *, standard_air: bool = True) -> dict[str, Any]:
    """Total capacity from enthalpy difference. Qt = 4.5 x CFM x dh (Btu/hr)."""
    if not cfm or cfm <= 0:
        return {"computable": False, "blocked_reason": "cfm must be positive"}
    qt = 4.5 * cfm * (h_enter - h_leave)
    qs = 1.085 * cfm * 0  # sensible requires temperature split
    return {"computable": True, "formula": "Qt = 4.5 x CFM x dh",
            "result": round(qt, 0), "units": "BTUH",
            "standard_conditions_used": "standard air (4.5 = 60min x 0.075 lb/ft3)",
            "warnings": ["total capacity; sensible/latent split requires dry-bulb + humidity data"],
            "source_reference": "SCS engineering: Qt = 4.5 x CFM x dh"}


def split_sensible_latent(cfm: float, db_e: float, db_l: float,
                          w_e: float, w_l: float) -> dict[str, Any]:
    """Sensible + latent + total + SHR from entering/leaving conditions."""
    if not cfm or cfm <= 0:
        return {"computable": False, "blocked_reason": "cfm must be positive"}
    qs = 1.085 * cfm * (db_e - db_l)
    h_e = enthalpy_bulb(db_e, w_e)
    h_l = enthalpy_bulb(db_l, w_l)
    qt = 4.5 * cfm * (h_e - h_l)
    ql = qt - qs
    shr = qs / qt if qt else None
    return {"computable": True,
            "sensible_btuh": round(qs, 0),
            "latent_btuh": round(ql, 0),
            "total_btuh": round(qt, 0),
            "shr": round(shr, 3) if shr is not None else None,
            "units": "BTUH",
            "standard_conditions_used": "standard air",
            "source_reference": "SCS engineering: Qs=1.085xCFMxdT, Qt=4.5xCFMxdh, SHR=Qs/Qt"}


def mixed_air_temp(oa_db: float, ra_db: float, oa_cfm: float, ra_cfm: float) -> dict[str, Any]:
    """Mixed air dry-bulb from outside + return streams."""
    total = oa_cfm + ra_cfm
    if total <= 0:
        return {"computable": False, "blocked_reason": "no airflow"}
    mixed = (oa_db * oa_cfm + ra_db * ra_cfm) / total
    return {"computable": True, "result": round(mixed, 2), "units": "F",
            "source_reference": "SCS engineering: Tma = (Toa x CFMoa + Tra x CFMra)/(CFMoa+CFMra)"}


def oa_fraction_temperature(ra_db: float, ma_db: float, oa_db: float) -> dict[str, Any]:
    """Outside-air fraction via temperature method.

    X = (Tra - Tma) / (Tra - Toa). Guard: mixed must lie between return and
    outside, and the denominator must be non-zero.
    """
    denom = ra_db - oa_db
    if abs(denom) < 0.01:
        return {"computable": False, "blocked_reason": "return and outdoor temperatures equal; method invalid",
                "warnings": ["temperature method not valid"]}
    fraction = (ra_db - ma_db) / denom
    lo, hi = sorted((ra_db, oa_db))
    if not (lo - 0.5 <= ma_db <= hi + 0.5):
        return {"computable": False, "blocked_reason": f"mixed air {ma_db} outside return/outdoor range",
                "warnings": ["measurement quality suspect; mixed air must lie between streams"]}
    return {"computable": True, "result": round(fraction, 4), "units": "fraction",
            "result_percent": round(fraction * 100.0, 1),
            "source_reference": "SCS engineering: OA fraction = (Tra-Tma)/(Tra-Toa)"}
