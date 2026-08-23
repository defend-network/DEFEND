"""Source claim applicability (M1.4, H4).

A source existing is not a claim being applicable. Every OEM/technical claim
is evaluated against manufacturer / family / model prefix / revision. Possible
results: EXACT_APPLICABILITY / FAMILY_APPLICABILITY /
GENERAL_MANUFACTURER_REFERENCE / UNCERTAIN_APPLICABILITY / NOT_APPLICABLE.
UNCERTAIN may inform diagnostics but is never presented as exact equipment
truth.
"""
from __future__ import annotations

import re
from typing import Any

# P47: applicability states for OEM/technical claims
APPLICABILITY_STATES = ("EXACT_MODEL", "MODEL_SERIES", "FAMILY",
                        "GENERAL_MANUFACTURER", "UNKNOWN", "CONFLICT")


def applicability_state(model: str | None, source: dict[str, Any]) -> str:
    """Map a source's applicability to the P47 state model.

    OEM numeric limits should require at least FAMILY (or better); a family-
    level fan datum is never presented as exact-model truth without disclosure.
    """
    source_model = str(source.get("model") or "").upper()
    source_family = str(source.get("equipment_family_tags") or "").upper()
    manufacturer = str(source.get("manufacturer") or "").upper()
    model_upper = (model or "").upper()
    if not model_upper:
        return "UNKNOWN"
    if source_model and source_model == model_upper:
        return "EXACT_MODEL"
    if source_model and (model_upper.startswith(source_model) or source_model.startswith(model_upper)):
        if len(min(model_upper, source_model)) >= 6:
            return "MODEL_SERIES"
    if manufacturer and source_family and _manufacturer_in_model(manufacturer, model_upper):
        return "FAMILY"
    if manufacturer and _manufacturer_in_model(manufacturer, model_upper):
        return "GENERAL_MANUFACTURER"
    return "UNKNOWN"


def applicability_of(model: str | None, source: dict[str, Any]) -> str:
    source_model = str(source.get("model") or "").upper()
    source_family = str(source.get("equipment_family_tags") or "")
    manufacturer = str(source.get("manufacturer") or "").upper()
    model_upper = (model or "").upper()
    if not model_upper:
        return "UNCERTAIN_APPLICABILITY"
    if source_model and source_model == model_upper:
        return "EXACT_APPLICABILITY"
    if source_model and (model_upper.startswith(source_model) or source_model.startswith(model_upper)):
        if len(min(model_upper, source_model)) >= 4:
            return "FAMILY_APPLICABILITY"
    if manufacturer and manufacturer and model_upper and _manufacturer_in_model(manufacturer, model_upper):
        return "GENERAL_MANUFACTURER_REFERENCE"
    return "UNCERTAIN_APPLICABILITY"


def _manufacturer_in_model(manufacturer: str, model: str) -> bool:
    # conservative: only known prefix families
    prefixes = {"CARRIER": ("50TC", "48TC", "40RM"), "GREENHECK": ("SQ", "G"),
                "TITUS": ("ESV", "TMS", "TSS"), "TRANE": ("M", "CHC"),
                "LENNOX": ("L",)}
    return any(model.startswith(p) for p in prefixes.get(manufacturer, ()))


def applicability_matrix() -> list[str]:
    return list(APPLICABILITY_STATES)
