"""Server-authoritative field measurement contract (M1.5B 6.1-6.3).

One canonical registry for field measurement concepts. The browser's UI
options mirror this contract; the server validates every write against it.
Unknown concepts and invalid units are rejected — the UI is NOT the authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CONTRACT_VERSION = "1.0"


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
