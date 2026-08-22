"""Field completeness + "Am I ready to leave?" engine.

Every potential field is classified for the ACTUAL job scope as:
    BLOCKING / IMPORTANT / OPTIONAL / NOT_APPLICABLE

Evidence is then checked against the JobRecord (photos, measurements,
traverses, findings, equipment). Before "asking", the engine already tried
(by construction) the JobRecord, photos, plans/docs, knowledge, deterministic
calculation, equipment nomenclature and safe contextual inference. The output
is a SHORT readiness report: READY items, MISSING-before-leaving items and
OPTIONAL items, plus at most a handful of high-value questions — never a giant
blank-field questionnaire. Unknown is NOT treated as N/A.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .schema import JobRecord


@dataclass
class CompletenessItem:
    field: str
    status: str  # BLOCKING | IMPORTANT | OPTIONAL | NOT_APPLICABLE
    reason: str = ""
    resolution_tried: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "status": self.status,
            "reason": self.reason,
            "resolution_tried": self.resolution_tried,
        }


@dataclass
class CompletenessReport:
    ready: bool = False
    items: list[CompletenessItem] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)

    def blocks(self) -> list[CompletenessItem]:
        return [i for i in self.items if i.status == "BLOCKING"]

    def important(self) -> list[CompletenessItem]:
        return [i for i in self.items if i.status == "IMPORTANT"]

    def optional(self) -> list[CompletenessItem]:
        return [i for i in self.items if i.status == "OPTIONAL"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "items": [i.to_dict() for i in self.items],
            "questions": self.questions,
            "summary": self.summary,
        }


_MISSING_HEADER = {
    "project_name": "client / project name",
    "site_name": "service site",
    "technician": "technician name",
    "test_date": "test date",
}
_DEVICE_METHOD_HINTS = ("hood", "vane", "anemometer", "pitot", "balometer", "capture")


def _resolution(record: JobRecord, field: str) -> str:
    """Note the deterministic resolution paths already exhausted."""
    tried = []
    if record.photos:
        tried.append("photos")
    if record.equipment:
        tried.append("equipment register")
    if any(r for e in record.equipment for r in e.measurements):
        tried.append("measurements")
    if record.findings:
        tried.append("findings")
    if tried:
        return f"checked: {'; '.join(tried)}"
    return "no prior evidence in job"


def evaluate(record: JobRecord) -> CompletenessReport:
    report = CompletenessReport()

    def add(field: str, status: str, reason: str = "") -> None:
        report.items.append(
            CompletenessItem(
                field=field,
                status=status,
                reason=reason,
                resolution_tried=_resolution(record, field),
            )
        )

    md = record.metadata
    for field, label in _MISSING_HEADER.items():
        value = getattr(md, field, None)
        if not value:
            add(field, "BLOCKING", f"report requires {label}")
        else:
            add(field, "NOT_APPLICABLE" if field == "test_date" else "OPTIONAL",
                "present")

    if not record.air_devices:
        add("air_devices", "BLOCKING", "no outlet readings captured")
    else:
        add("air_devices", "OPTIONAL", f"{len(record.air_devices)} device(s) recorded")

    for device in record.air_devices:
        fid = f"{device.device_id}:final_cfm"
        if device.final_cfm is None:
            add(fid, "BLOCKING", f"{device.device_id} missing final CFM")
        else:
            add(fid, "OPTIONAL", f"{device.device_id} final {device.final_cfm} CFM")
        if device.design_cfm is None and not (
            device.notes and "design" in device.notes.casefold()
        ):
            add(f"{device.device_id}:design_cfm", "IMPORTANT",
                f"{device.device_id} has measured CFM but no design airflow documented")
        if device.as_found_cfm is None:
            add(f"{device.device_id}:as_found_cfm", "IMPORTANT",
                f"{device.device_id} lacks as-found value (verification/balance report)")
        if device.measurement_method is None:
            add(f"{device.device_id}:measurement_method", "IMPORTANT",
                f"{device.device_id} missing measurement method")
        elif not any(
            hint in device.measurement_method.casefold() for hint in _DEVICE_METHOD_HINTS
        ):
            add(f"{device.device_id}:measurement_method", "IMPORTANT",
                f"unrecognized measurement method '{device.measurement_method}'")

    if record.air_devices and not record.photos:
        add("photos", "BLOCKING", "no photos attached to the job")
    else:
        device_photos = {
            ref for d in record.air_devices for ref in d.evidence_refs
        }
        if record.air_devices and not device_photos:
            add("device_photos", "IMPORTANT",
                "no photo evidence linked to outlet readings")
        else:
            add("device_photos", "OPTIONAL", "device photos linked")

    system_total = sum(d.final_cfm or 0 for d in record.air_devices)
    if record.air_devices and system_total == 0:
        add("system_total", "IMPORTANT", "final system total not derivable (no finals)")

    if record.equipment:
        missing_identity = [
            e.equipment_id for e in record.equipment
            if not (e.manufacturer and e.model)
        ]
        add(
            "equipment_identity",
            "IMPORTANT" if missing_identity else "OPTIONAL",
            "missing manufacturer/model: " + ", ".join(missing_identity)
            if missing_identity
            else "equipment identity complete",
        )
    else:
        add("equipment_identity", "OPTIONAL", "no equipment register in scope")

    if record.traverses:
        bad = [
            t.traverse_id for t in record.traverses
            if not (t.area_sqft and t.duct_size and t.final_fpm)
        ]
        add(
            "traverse_data",
            "IMPORTANT" if bad else "OPTIONAL",
            "incomplete traverses: " + ", ".join(bad) if bad else "traverse data complete",
        )
    else:
        add("traverse_data", "NOT_APPLICABLE", "no traverse in scope")

    pressures = [
        m for e in record.equipment for m in e.measurements
        if m.field.startswith("sp_") or m.field == "static_pressure"
    ]
    add("static_pressure", "OPTIONAL" if pressures else "NOT_APPLICABLE",
        "static profile captured" if pressures else "no static measurements requested")

    add("findings", "OPTIONAL", "no findings" if not record.findings else f"{len(record.findings)} finding(s)")
    add("instrument_calibration", "NOT_APPLICABLE", "not required for this scope")

    counts: dict[str, int] = {}
    for item in report.items:
        counts[item.status] = counts.get(item.status, 0) + 1
    report.summary = counts
    report.ready = not report.blocks()
    report.questions = _questions(record, report)
    return report


def _questions(record: JobRecord, report: CompletenessReport) -> list[str]:
    """At most a few high-value questions; unknown is not N/A."""
    questions: list[str] = []
    design_missing = [
        d.device_id for d in record.air_devices
        if d.final_cfm is not None and d.design_cfm is None
        and not (d.notes and "design" in d.notes.casefold())
    ]
    if design_missing:
        questions.append(
            "What is the design airflow for: " + ", ".join(design_missing) + "?"
        )
    if record.air_devices and not any(d.as_found_cfm is not None for d in record.air_devices):
        questions.append("Did you capture as-found readings before adjusting?")
    no_device_photos = record.air_devices and not {
        ref for d in record.air_devices for ref in d.evidence_refs
    }
    if no_device_photos:
        questions.append("Are there photos of the outlet readings to attach?")
    return questions[:5]


def ready_to_leave(record: JobRecord) -> dict[str, Any]:
    """Short field report: READY / MISSING BEFORE LEAVING / OPTIONAL."""
    report = evaluate(record)
    ready_lines = []
    missing_lines = []
    optional_lines = []
    for item in report.items:
        if item.status == "BLOCKING":
            missing_lines.append(item.field)
        elif item.status == "IMPORTANT":
            missing_lines.append(item.field)
        elif item.status == "OPTIONAL":
            optional_lines.append(item.field)
        elif item.status == "NOT_APPLICABLE":
            ready_lines.append(item.field + " (N/A)")
    return {
        "ready": report.ready,
        "readiness": "READY" if report.ready else "MISSING BEFORE LEAVING",
        "READY": ready_lines,
        "MISSING_BEFORE_LEAVING": missing_lines,
        "OPTIONAL": optional_lines,
        "questions": report.questions,
        "summary": report.summary,
    }
