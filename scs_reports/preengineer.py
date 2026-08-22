"""Pre-engineering: blueprint DesignBasis -> pre-engineered JobRecord.

Once a plan PDF + owner scope are available, SCS pre-builds the job:
- creates/updates the JobRecord (status PRE_ENGINEERED),
- populates equipment from the equipment schedule,
- populates air_devices with DESIGN values (never measured),
- pre-stages the Air Distribution report rows,
- generates the field test plan / checklist,
- computes design totals and design-vs-field analysis hooks.

Design data is always PLAN_EXTRACTED / SCHEDULE_EXTRACTED and is never written
into as-found/final measurement fields.
"""
from __future__ import annotations

from typing import Any

from .schema import (
    AirDevice,
    DesignData,
    Equipment,
    EquipmentType,
    JobRecord,
)

_EQUIPMENT_TYPE_MAP = {
    "RTU": EquipmentType.RTU,
    "AHU": EquipmentType.AHU,
    "FCU": EquipmentType.FCU,
    "FAN": EquipmentType.FAN,
    "VAV": EquipmentType.VAV,
    "EXHAUST": EquipmentType.EXHAUST,
    "OUTSIDE_AIR": EquipmentType.OUTSIDE_AIR,
}


def _equipment_type(tag: str, raw_type: str) -> EquipmentType:
    upper = (tag + " " + (raw_type or "")).upper()
    for key, value in _EQUIPMENT_TYPE_MAP.items():
        if key in upper:
            return value
    return EquipmentType.OTHER


def _function_from_type(raw_type: str) -> str:
    upper = (raw_type or "").upper()
    if any(k in upper for k in ("EXHAUST", "RELIEF", "RETURN")):
        return "EXHAUST" if "EXHAUST" in upper else "RETURN"
    if any(k in upper for k in ("OUTSIDE AIR", "OA", "MAKEUP")):
        return "OUTSIDE AIR"
    return "SUPPLY"


def build_preengineered_record(
    record: JobRecord,
    design: dict[str, Any],
) -> JobRecord:
    """Populate equipment + air devices from a plan pipeline payload."""
    record.metadata.status = "PRE_ENGINEERED"

    equipment_rows = design.get("equipment") or []
    existing_ids = {e.equipment_id for e in record.equipment}
    for row in equipment_rows:
        tag = (row.get("tag") or "").strip()
        if not tag or tag in existing_ids:
            continue
        etype = _equipment_type(tag, row.get("type"))
        equipment = Equipment(
            equipment_id=tag,
            equipment_type=etype,
            tag=tag,
            manufacturer=row.get("manufacturer"),
            model=row.get("model"),
            design_data=DesignData(
                design_cfm=row.get("supply_cfm"),
            ),
            notes=f"source: {_provenance(row)}" if _provenance(row) else None,
        )
        record.equipment.append(equipment)
        existing_ids.add(tag)

    instances = design.get("instances") or []
    existing_devices = {d.device_id for d in record.air_devices}
    for instance in instances:
        device_id = (instance.get("device_id") or "").strip()
        if not device_id or device_id in existing_devices:
            continue
        room = instance.get("room") or ""
        source = instance.get("source") or {}
        device = AirDevice(
            device_id=device_id,
            function=_function_from_type(instance.get("type") or ""),
            area_served=room or None,
            design_cfm=instance.get("design_cfm"),
            size=instance.get("size"),
            status="NOT MEASURED",
            measurement_method="rotating vane",
            design_source=_provenance(source),
        )
        record.air_devices.append(device)
        existing_devices.add(device_id)
    return record


def _provenance(source: dict[str, Any] | None) -> str | None:
    if not source:
        return None
    sheet = source.get("sheet")
    page = source.get("page")
    method = source.get("extraction_method")
    parts = []
    if sheet:
        parts.append(str(sheet))
    if page:
        parts.append(f"page {page}")
    if method:
        parts.append(method)
    return " ".join(parts) if parts else None


def field_test_plan(record: JobRecord) -> list[dict[str, Any]]:
    """Structured field measurement plan for every air device."""
    plan: list[dict[str, Any]] = []
    for device in record.air_devices:
        measured = device.final_cfm is not None
        plan.append({
            "device": device.device_id,
            "room": device.area_served,
            "design_cfm": device.design_cfm,
            "size": device.size,
            "measurement_method_suggested": device.measurement_method or "rotating vane",
            "status": "MEASURED" if measured else "NOT MEASURED",
        })
    return plan


def design_vs_field(record: JobRecord) -> dict[str, Any]:
    """Deterministic design vs actual analysis. Never invents a tolerance.

    If a project tolerance is explicitly documented (device note contains a
    percentage range), a pass/fail flag is produced; otherwise only variance
    is shown.
    """
    rows: list[dict[str, Any]] = []
    for device in record.air_devices:
        design = device.design_cfm
        if design is None:
            continue
        row: dict[str, Any] = {
            "device": device.device_id,
            "room": device.area_served,
            "design_cfm": design,
        }
        tolerance = None
        match = _tolerance_from_notes(device.notes or "")
        if match is not None:
            tolerance = match
        if device.as_found_cfm is not None:
            row["as_found_cfm"] = device.as_found_cfm
            row["as_found_variance_cfm"] = round(device.as_found_cfm - design, 1)
            row["as_found_percent"] = round((device.as_found_cfm - design) / design * 100, 1)
            if tolerance is not None:
                row["as_found_pass"] = abs(device.as_found_cfm - design) / design <= tolerance
        if device.final_cfm is not None:
            row["final_cfm"] = device.final_cfm
            row["final_variance_cfm"] = round(device.final_cfm - design, 1)
            row["final_percent"] = round((device.final_cfm - design) / design * 100, 1)
            if tolerance is not None:
                row["final_pass"] = abs(device.final_cfm - design) / design <= tolerance
        if row.get("as_found_cfm") is not None or row.get("final_cfm") is not None:
            rows.append(row)

    totals = {}
    for room in {d.area_served for d in record.air_devices if d.area_served}:
        devices = [d for d in record.air_devices if d.area_served == room]
        design_total = sum(d.design_cfm or 0 for d in devices
                           if d.function == "SUPPLY")
        final_total = sum(d.final_cfm or 0 for d in devices
                          if d.function == "SUPPLY")
        as_found_total = sum(d.as_found_cfm or 0 for d in devices
                             if d.function == "SUPPLY")
        supply_count = sum(1 for d in devices if d.function == "SUPPLY")
        if design_total:
            entry: dict[str, Any] = {
                "room": room,
                "device_count": supply_count,
                "design_total_cfm": design_total,
            }
            if as_found_total:
                entry["as_found_total_cfm"] = as_found_total
                entry["as_found_total_percent"] = round((as_found_total - design_total) / design_total * 100, 1)
            if final_total:
                entry["final_total_cfm"] = final_total
                entry["final_total_percent"] = round((final_total - design_total) / design_total * 100, 1)
            totals[room] = entry

    return {"rows": rows, "system_totals": totals}


def _tolerance_from_notes(notes: str) -> float | None:
    import re
    match = re.search(r"(?:within|\\u00b1|\+|/-)?\s*(\d{1,2})\s*%", notes)
    return float(match.group(1)) / 100.0 if match else None
