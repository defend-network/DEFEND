"""Mechanical plan entities (M1.2, P8-P25).

Lightweight, provenance-bearing entity models: equipment, systems, air
devices, dampers, controls, duct segments, rooms/zones, notes, references.
Core standardized attributes + source schedule fields + normalized properties.
Every entity carries source (sheet/page/bbox) + confidence + evidence lineage.
"""
from __future__ import annotations

import re
from typing import Any

DAMPER_TYPES = {
    "VOLUME_DAMPER", "BALANCING_DAMPER", "MANUAL_DAMPER", "MOTORIZED_DAMPER",
    "BACKDRAFT_DAMPER", "FIRE_DAMPER", "SMOKE_DAMPER",
    "COMBINATION_FIRE_SMOKE_DAMPER", "BAROMETRIC_RELIEF_DAMPER",
    "CONTROL_DAMPER", "OTHER",
}
CONTROL_TYPES = {
    "THERMOSTAT", "SPACE_TEMP_SENSOR", "DUCT_TEMP_SENSOR", "HUMIDITY_SENSOR",
    "CO2_SENSOR", "STATIC_PRESSURE_SENSOR", "DIFFERENTIAL_PRESSURE_SENSOR",
    "DUCT_SMOKE_DETECTOR", "OCCUPANCY_SENSOR", "ACTUATOR", "VFD",
    "BAS_CONTROLLER", "CONTROL_PANEL", "END_SWITCH", "CURRENT_SENSOR",
    "FREEZESTAT", "OTHER",
}
FUNCTION_TAGS = {
    "SA": "SUPPLY", "SUP": "SUPPLY", "SF": "SUPPLY",
    "RA": "RETURN", "RET": "RETURN", "RF": "RETURN", "RG": "RETURN",
    "EF": "EXHAUST", "EA": "EXHAUST", "EXH": "EXHAUST", "EG": "EXHAUST",
    "OA": "OUTSIDE_AIR", "TF": "TRANSFER", "RG2": "RETURN",
}
DAMPER_TAG_TYPES = {
    "BD": "BALANCING_DAMPER", "VD": "VOLUME_DAMPER", "MD": "MOTORIZED_DAMPER",
    "FD": "FIRE_DAMPER", "SD": "SMOKE_DAMPER", "SMD": "SMOKE_DAMPER",
    "FSD": "COMBINATION_FIRE_SMOKE_DAMPER", "CD": "CONTROL_DAMPER",
    "BKD": "BACKDRAFT_DAMPER",
}
CONTROL_TAG_TYPES = {
    "T": "THERMOSTAT", "TS": "SPACE_TEMP_SENSOR", "DS": "DUCT_TEMP_SENSOR",
    "RH": "HUMIDITY_SENSOR", "CO2": "CO2_SENSOR", "SP": "STATIC_PRESSURE_SENSOR",
    "DP": "DIFFERENTIAL_PRESSURE_SENSOR", "DSD": "DUCT_SMOKE_DETECTOR",
    "OCC": "OCCUPANCY_SENSOR", "ACT": "ACTUATOR", "VFD": "VFD",
}
DUCT_SIZE_RE = re.compile(
    r"(\d{1,3}(?:\.\d+)?)[xX\u00d7](\d{1,3}(?:\.\d+)?)|(\d{1,3}(?:\.\d+)?)\s*(?:[\u00d8oO]\s*)?(?:IN|\\\"|\\\")"
)


def _tag(text: str) -> str:
    return re.sub(r"\s+", "", text.strip().upper())


def _tag_prefix(tag: str) -> str:
    match = re.match(r"([A-Z0-9]+)-?\d{1,3}$", tag)
    if match:
        return match.group(1)
    match = re.match(r"([A-Z0-9]+)", tag)
    return match.group(1) if match else ""


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def make_entity(kind: str, entity_id: str, **attrs: Any) -> dict[str, Any]:
    entity = {"kind": kind, "id": entity_id}
    entity.update(attrs)
    return entity


def equipment_from_schedule(row: dict[str, Any], *, sheet: str | None,
                            page: int | None) -> dict[str, Any] | None:
    tag = _tag(row.get("TAG") or "")
    if not tag or not re.match(r"^[A-Z]{1,4}-?\d{1,3}$", tag):
        return None
    etype = (row.get("TYPE") or "").strip().upper()
    return make_entity(
        "equipment", tag,
        equipment_type=etype or None,
        manufacturer=row.get("MANUFACTURER") or None,
        model=row.get("MODEL") or None,
        scheduled_fields={k: v for k, v in row.items() if k != "TAG"},
        source={"sheet": sheet, "page": page,
                "extraction_method": "SCHEDULE_EXTRACTED", "confidence": "HIGH"},
    )


def damper_from_tag(tag: str, *, sheet: str | None, page: int | None,
                    dictionary=None, bbox=None) -> dict[str, Any]:
    normalized_tag = _tag(tag)
    prefix = _tag_prefix(normalized_tag)
    semantic = DAMPER_TAG_TYPES.get(prefix)
    if dictionary is not None and dictionary.supplied:
        semantic = dictionary.semantic_of(prefix) or semantic
    confidence = "PROJECT_LEGEND_VERIFIED" if dictionary is not None and dictionary.supplied else (
        "GENERIC_SYMBOL_INFERENCE" if semantic else "REVIEW_REQUIRED")
    return make_entity(
        "damper", normalized_tag,
        tag=normalized_tag,
        damper_type=semantic or "REVIEW_REQUIRED",
        size=None, location=None, actuator=None, control_relation=None,
        detail_reference=None, fire_rating=None, smoke_rating=None,
        normally_open=None,
        source={"sheet": sheet, "page": page, "bbox": bbox,
                "extraction_method": "PLAN_EXTRACTED"},
        confidence=confidence,
    )


def control_from_tag(tag: str, *, sheet: str | None, page: int | None,
                     dictionary=None, bbox=None) -> dict[str, Any] | None:
    normalized_tag = _tag(tag)
    prefix = _tag_prefix(normalized_tag)
    if prefix not in CONTROL_TAG_TYPES:
        return None
    if prefix == "T" and not re.match(r"^T-?\d", normalized_tag):
        return None
    semantic = CONTROL_TAG_TYPES[prefix]
    if dictionary is not None and dictionary.supplied:
        semantic = dictionary.semantic_of(prefix) or semantic
    if not semantic:
        return None
    return make_entity(
        "control", normalized_tag,
        tag=normalized_tag,
        control_type=semantic,
        source={"sheet": sheet, "page": page, "bbox": bbox,
                "extraction_method": "PLAN_EXTRACTED"},
        confidence="PROJECT_LEGEND_VERIFIED" if dictionary is not None and dictionary.supplied else "GENERIC_SYMBOL_INFERENCE",
    )


def duct_from_size_callout(text: str, *, sheet: str | None, page: int | None,
                           bbox=None) -> dict[str, Any] | None:
    match = DUCT_SIZE_RE.match(text.strip().upper())
    if not match:
        return None
    if match.group(1):
        size = f"{match.group(1)}x{match.group(2)}"
        shape = "RECTANGULAR"
    else:
        size = f"{match.group(3)}"
        shape = "ROUND"
    return make_entity(
        "duct_segment", f"{sheet or '?'}_p{page}_{size}",
        size=size, shape=shape, system_type=None, airflow_callout=None,
        insulation=None, elevation=None,
        source={"sheet": sheet, "page": page, "bbox": bbox,
                "extraction_method": "PLAN_EXTRACTED"},
        confidence="HIGH",
    )


def room_entity(name: str, *, sheet: str | None, page: int | None) -> dict[str, Any]:
    return make_entity("room", name.upper(), name=name,
                       source={"sheet": sheet, "page": page,
                               "extraction_method": "PLAN_EXTRACTED"},
                       confidence="HIGH")


def note_entity(note_id: str, literal_text: str, *, sheet: str | None,
                page: int | None, bbox=None) -> dict[str, Any]:
    return make_entity("note", note_id, literal_text=literal_text,
                       normalized_topics=_topics(literal_text),
                       applies_to_entities=[], applies_to_sheet=sheet,
                       source={"sheet": sheet, "page": page, "bbox": bbox,
                               "extraction_method": "NATIVE_TEXT"},
                       confidence="HIGH")


_TOPIC_KEYWORDS = [
    ("balancing", "BALANCING"), ("damper", "DAMPER"), ("access", "ACCESS"),
    ("fire", "FIRE"), ("smoke", "SMOKE"), ("vfd", "VFD"), ("rpm", "RPM"),
    ("outside air", "OUTSIDE_AIR"), ("co2", "CO2"), ("static", "STATIC"),
    ("thermostat", "CONTROLS"), ("commission", "COMMISSIONING"),
    ("test", "TESTING"), ("filter", "FILTER"), ("support", "SUPPORT"),
]


def _topics(text: str) -> list[str]:
    upper = text.upper()
    return [topic for keyword, topic in _TOPIC_KEYWORDS if keyword.upper() in upper]


def reference_entity(ref: str, *, source_text: str, sheet: str | None,
                     page: int | None, present: bool | None) -> dict[str, Any]:
    match = re.match(r"(\d{1,2})\s*/\s*([A-Z]\d\.\d+|M-\d{3,4})", ref.upper())
    detail = match.group(1) if match else None
    target = match.group(2) if match else ref.upper()
    return make_entity(
        "reference", ref,
        target_sheet=target, target_detail=detail,
        target_present=present,
        source_text=source_text,
        source={"sheet": sheet, "page": page, "extraction_method": "NATIVE_TEXT"},
        confidence="HIGH",
    )
