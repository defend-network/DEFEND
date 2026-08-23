"""EquipmentResolver V1 (M1.3, P32-P38, P73-P75).

Conservative identity resolution from plan schedule / tag / owner-entered
model / photo-extracted model. Produces EquipmentIdentity with
manufacturer / family / exact-model (only when supported) / identity
evidence. Never fabricates missing model characters; partial models remain
FAMILY_LEVEL_REFERENCE. OEM reference is kept separate from engineer design.
"""
from __future__ import annotations

import re
from typing import Any

from .decoders import DECODERS

KNOWN_MANUFACTURERS = {
    "CARRIER", "TRANE", "YORK", "JCI", "DAIKIN", "MITSUBISHI", "LENNOX",
    "RHEEM", "RUUD", "GOODMAN", "AMANA", "AAON", "GREENHECK", "PRICE",
    "TITUS", "NAILOR", "BELIMO", "HONEYWELL", "SIEMENS", "SCHNEIDER",
}


def detect_manufacturer(model_or_tag: str) -> str | None:
    upper = (model_or_tag or "").upper()
    for name in sorted(KNOWN_MANUFACTURERS, key=len, reverse=True):
        if name in upper:
            return name
    return None


def resolve_equipment(*, model: str | None = None, manufacturer: str | None = None,
                      tag: str | None = None,
                      photo_extracted_model: str | None = None,
                      schedule_manufacturer: str | None = None,
                      schedule_model: str | None = None) -> dict[str, Any]:
    """Resolve an EquipmentIdentity conservatively from available evidence."""
    evidence: list[dict[str, Any]] = []

    def add_evidence(kind: str, text: str | None, value: str | None) -> None:
        if value:
            evidence.append({"kind": kind, "text": text, "value": value})

    candidate_manufacturer = (manufacturer or schedule_manufacturer or
                              (detect_manufacturer(model) if model else None) or
                              (detect_manufacturer(photo_extracted_model)
                               if photo_extracted_model else None))
    # infer manufacturer from the model prefix via the decoder families
    if candidate_manufacturer is None:
        probe = photo_extracted_model or model or schedule_model
        if probe:
            for name, decoder in DECODERS.items():
                result = decoder.decode(probe)
                if result.get("family") or result.get("resolution") != "UNKNOWN_MODEL_NOMENCLATURE":
                    candidate_manufacturer = name
                    break
    add_evidence("SCHEDULE_MANUFACTURER", schedule_manufacturer, schedule_manufacturer)
    add_evidence("SCHEDULE_MODEL", schedule_model, schedule_model)
    add_evidence("TAG", tag, tag)
    add_evidence("PHOTO_MODEL", photo_extracted_model, photo_extracted_model)

    exact_model = None
    model_confidence = "LOW"
    if photo_extracted_model and schedule_model:
        if _conservative_exact_match(photo_extracted_model, schedule_model):
            exact_model = photo_extracted_model
            model_confidence = "HIGH"
            add_evidence("MODEL_AGREEMENT", "photo and schedule match", exact_model)
        else:
            # disagree -> never merge; use the photo as a MEDIUM candidate
            exact_model = photo_extracted_model
            model_confidence = "MEDIUM"
            add_evidence("PHOTO_MODEL", photo_extracted_model, photo_extracted_model)
            add_evidence("MODEL_DISAGREEMENT", "photo and schedule differ", schedule_model)
    elif photo_extracted_model:
        exact_model = photo_extracted_model
        model_confidence = "MEDIUM"
        add_evidence("PHOTO_MODEL", photo_extracted_model, photo_extracted_model)
    elif schedule_model:
        exact_model = schedule_model
        model_confidence = "MEDIUM"
        add_evidence("SCHEDULE_MODEL", schedule_model, schedule_model)
    elif model:
        exact_model = model
        model_confidence = "MEDIUM"
        add_evidence("OWNER_MODEL", model, model)

    family = None
    decoded = []
    resolution = "EXACT_MODEL_REFERENCE" if exact_model else "UNKNOWN_MODEL_IDENTITY"
    if candidate_manufacturer:
        decoder = DECODERS.get(candidate_manufacturer.upper())
        if decoder and exact_model:
            result = decoder.decode(exact_model)
            family = result.get("family")
            decoded = result.get("decoded", [])
            resolution = result.get("resolution", resolution)
        elif decoder:
            # partial/family-level resolution from whatever model we have
            probe = exact_model or photo_extracted_model or schedule_model
            if probe:
                result = decoder.decode(probe)
                family = result.get("family")
                decoded = result.get("decoded", [])
                resolution = result.get("resolution", resolution)
                if resolution != "FAMILY_LEVEL_REFERENCE":
                    resolution = "FAMILY_LEVEL_REFERENCE"

    identity = {
        "manufacturer": candidate_manufacturer,
        "product_family": family,
        "model_exact": exact_model,
        "model_confidence": model_confidence,
        "serial": None,
        "equipment_type": None,
        "nominal_capacity": None,
        "voltage": None,
        "phase": None,
        "heat_type": None,
        "refrigerant": None,
        "fan_drive_type": None,
        "controller": None,
        "supported_oem_documents": [],
        "identity_evidence": evidence,
        "resolution": resolution,
        "oem_reference_level": ("EXACT_MODEL_REFERENCE" if (exact_model and model_confidence == "HIGH")
                                else "FAMILY_LEVEL_REFERENCE" if family else None),
    }
    return identity


def _conservative_exact_match(a: str, b: str) -> bool:
    """Accept only strong agreement: normalized equality or one is a clean
    prefix of the other with no contradicting suffix."""
    norm = lambda s: re.sub(r"[^A-Z0-9]", "", s.upper())
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    if longer.startswith(shorter) and len(shorter) >= 6:
        return True
    return False
