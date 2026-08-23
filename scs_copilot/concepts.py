"""Server-authoritative field measurement contract (M1.5B 6.1-6.3).

One canonical registry for field measurement concepts. The browser's UI
options mirror this contract; the server validates every write against it.
Unknown concepts and invalid units are rejected — the UI is NOT the authority.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

CONTRACT_VERSION = "1.1"

# Documented engineering constant: 1 in.w.c. = 249.089 Pa (standard air).
_PASCAL_PER_INWC = 249.089


@dataclass(frozen=True)
class FieldConcept:
    concept_id: str
    scope: str  # EQUIPMENT | JOB
    canonical_unit: str
    accepted_units: tuple[str, ...]
    instrument_recommended: bool = False
    operating_mode_applicable: bool = False


FIELD_CONCEPTS: dict[str, FieldConcept] = {
    "FIELD_SUPPLY_CFM": FieldConcept("FIELD_SUPPLY_CFM", "EQUIPMENT", "CFM", ("CFM",)),
    "FIELD_RETURN_CFM": FieldConcept("FIELD_RETURN_CFM", "EQUIPMENT", "CFM", ("CFM",)),
    "FIELD_OA_CFM": FieldConcept("FIELD_OA_CFM", "EQUIPMENT", "CFM", ("CFM",)),
    "FIELD_EXHAUST_CFM": FieldConcept("FIELD_EXHAUST_CFM", "EQUIPMENT", "CFM", ("CFM",)),
    "FIELD_VAV_CFM": FieldConcept("FIELD_VAV_CFM", "EQUIPMENT", "CFM", ("CFM",)),
    "FIELD_TESP": FieldConcept("FIELD_TESP", "EQUIPMENT", "IN.W.C.",
                               ("IN.W.C.", "IN.W.G.", "PA"), instrument_recommended=True),
    "FIELD_SUPPLY_STATIC": FieldConcept("FIELD_SUPPLY_STATIC", "EQUIPMENT", "IN.W.C.",
                                        ("IN.W.C.", "IN.W.G.", "PA")),
    "FIELD_RETURN_STATIC": FieldConcept("FIELD_RETURN_STATIC", "EQUIPMENT", "IN.W.C.",
                                        ("IN.W.C.", "IN.W.G.", "PA")),
    "FILTER_DP": FieldConcept("FILTER_DP", "EQUIPMENT", "IN.W.C.",
                              ("IN.W.C.", "IN.W.G.", "PA")),
    "COIL_DP": FieldConcept("COIL_DP", "EQUIPMENT", "IN.W.C.",
                            ("IN.W.C.", "IN.W.G.", "PA")),
    "FIELD_RPM": FieldConcept("FIELD_RPM", "EQUIPMENT", "RPM", ("RPM",),
                              instrument_recommended=True),
    "VFD_FREQUENCY": FieldConcept("VFD_FREQUENCY", "EQUIPMENT", "HZ", ("HZ",),
                                  operating_mode_applicable=True),
    "BUILDING_PRESSURE": FieldConcept("BUILDING_PRESSURE", "JOB", "IN.W.C.",
                                      ("IN.W.C.", "IN.W.G.", "PA")),
    "DRY_BULB": FieldConcept("DRY_BULB", "JOB", "DEGF", ("DEGF", "F")),
    "RH": FieldConcept("RH", "JOB", "%", ("%", "RH")),
}

_ALIASES = {
    "SUPPLY_CFM": "FIELD_SUPPLY_CFM",
    "RETURN_CFM": "FIELD_RETURN_CFM",
    "OA_CFM": "FIELD_OA_CFM",
    "EXHAUST_CFM": "FIELD_EXHAUST_CFM",
    "VAV_CFM": "FIELD_VAV_CFM",
    "TESP": "FIELD_TESP",
    "SUPPLY_STATIC": "FIELD_SUPPLY_STATIC",
    "RETURN_STATIC": "FIELD_RETURN_STATIC",
    "FAN_RPM": "FIELD_RPM",
    "VFD_HZ": "VFD_FREQUENCY",
}


def normalize_concept(raw: str | None) -> str | None:
    """Return the canonical concept ID for a client-supplied value, or None if
    unknown. The UI is not authority — unknown concepts are rejected."""
    if not raw:
        return None
    value = raw.strip().upper()
    if value in FIELD_CONCEPTS:
        return value
    return _ALIASES.get(value)


def validate_unit(concept_id: str, unit: str | None) -> str | None:
    """Return the canonical unit when the supplied unit is accepted, else None."""
    concept = FIELD_CONCEPTS.get(concept_id)
    if concept is None:
        return None
    if not unit:
        return concept.canonical_unit  # omitted -> canonical default
    value = unit.strip().upper().replace(".", "").replace(" ", "")
    for accepted in concept.accepted_units:
        if accepted.replace(".", "").replace(" ", "") == value:
            return concept.canonical_unit
    return None


def scope_of(concept_id: str) -> str | None:
    concept = FIELD_CONCEPTS.get(concept_id)
    return concept.scope if concept else None


def contract() -> dict[str, Any]:
    return {
        "version": CONTRACT_VERSION,
        "concepts": [
            {"concept": c.concept_id, "scope": c.scope,
             "unit": c.canonical_unit, "accepted_units": list(c.accepted_units),
             "instrument_recommended": c.instrument_recommended,
             "operating_mode_applicable": c.operating_mode_applicable}
            for c in FIELD_CONCEPTS.values()
        ],
    }


def _compact_unit(value: str) -> str:
    return value.strip().upper().replace(".", "").replace(" ", "")


def normalize_measurement(concept_id: str, submitted_value: float,
                          submitted_unit: str | None) -> dict[str, Any] | None:
    """Server-authoritative numeric measurement normalization (M1.5B2 6.5).

    Returns canonical concept/value/unit plus the technician's submitted
    value/unit. PA is NUMERICALLY converted to IN.W.C. (never relabeled);
    synonymous units (IN.W.G./IN.W.C.) are label-normalized only."""
    concept = FIELD_CONCEPTS.get(concept_id)
    if concept is None:
        return None
    if not isinstance(submitted_value, (int, float)) or isinstance(submitted_value, bool) \
            or not math.isfinite(submitted_value):
        return None
    raw_unit = submitted_unit.strip() if submitted_unit else None
    submitted_unit_norm = raw_unit.upper().replace(".", "").replace(" ", "") if raw_unit else None
    if submitted_unit_norm is None:
        canonical_value = submitted_value
        canonical_unit = concept.canonical_unit
        submitted_unit_norm = concept.canonical_unit
    else:
        accepted = {_compact_unit(u) for u in concept.accepted_units}
        if submitted_unit_norm not in accepted:
            return None
        canonical_unit = concept.canonical_unit
        canonical_value = _convert_value(submitted_value, submitted_unit_norm,
                                         _compact_unit(canonical_unit))
    return {
        "canonical_concept": concept_id,
        "canonical_value": canonical_value,
        "canonical_unit": canonical_unit,
        "submitted_value": submitted_value,
        "submitted_unit": submitted_unit_norm,
    }


def _convert_value(value: float, submitted_unit: str, canonical_unit: str) -> float:
    if submitted_unit == canonical_unit:
        return value
    if submitted_unit == "PA" and canonical_unit == "INWC":
        return value / _PASCAL_PER_INWC
    # INWG -> INWC (and other synonymous pressure labels): magnitude unchanged
    return value
