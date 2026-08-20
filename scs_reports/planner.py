"""Report planner: decides WHAT belongs in the report.

Deterministic rule-based planning for the MVP. Sections are selected ONLY
from actual record content — no phantom sections, no repetitive empty
equipment blocks. The Excel composer executes the plan; it never decides
what belongs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .schema import JobRecord, EquipmentType

SectionType = Literal[
    "cover",
    "certification",
    "abbreviations",
    "executive_summary",
    "scope_summary",
    "rtu_nameplate",
    "building_pressure",
    "traverse_summary",
    "traverse_points",
    "vav_data",
    "fan_test",
    "vfd_report",
    "photo_log",
    "remarks",
    "closeout",
]

VALID_SECTION_TYPES = frozenset(SectionType.__args__)


@dataclass
class SectionPlan:
    type: SectionType
    equipment_id: str | None = None
    system_id: str | None = None
    title: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "equipment_id": self.equipment_id,
            "system_id": self.system_id,
            "title": self.title,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SectionPlan":
        return cls(
            type=data["type"],
            equipment_id=data.get("equipment_id"),
            system_id=data.get("system_id"),
            title=data.get("title"),
        )


@dataclass
class ReportPlan:
    report_type: str
    sections: list[SectionPlan] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_type": self.report_type,
            "sections": [s.to_dict() for s in self.sections],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReportPlan":
        return cls(
            report_type=data.get("report_type", "TAB"),
            sections=[
                SectionPlan.from_dict(s) for s in data.get("sections", [])
            ],
        )


def plan_for(record: JobRecord) -> ReportPlan:
    sections: list[SectionPlan] = [SectionPlan("cover"), SectionPlan("certification")]

    has_equipment = bool(record.equipment)
    has_air_devices = bool(record.air_devices)
    has_traverses = bool(record.traverses)
    has_vavs = any(
        e.equipment_type in (EquipmentType.VAV, EquipmentType.FCU)
        for e in record.equipment
    )
    rtu_ahus = [
        e
        for e in record.equipment
        if e.equipment_type in (EquipmentType.RTU, EquipmentType.AHU)
    ]
    fans = [
        e
        for e in record.equipment
        if e.equipment_type == EquipmentType.FAN
    ]
    vfds = [
        e
        for e in record.equipment
        if e.equipment_type == EquipmentType.VFD
    ]

    if has_equipment or has_air_devices or has_traverses:
        sections.append(SectionPlan("abbreviations"))

    if record.findings or record.field_observations or rtu_ahus:
        sections.append(SectionPlan("executive_summary"))

    if record.scope_notes or record.field_observations:
        sections.append(SectionPlan("scope_summary"))

    if rtu_ahus:
        sections.append(SectionPlan("rtu_nameplate"))

    if has_air_devices:
        sections.append(SectionPlan("building_pressure"))

    for traverse in record.traverses:
        sections.append(
            SectionPlan("traverse_summary", system_id=traverse.system_id)
        )

    for traverse in record.traverses:
        sections.append(
            SectionPlan("traverse_points", system_id=traverse.system_id)
        )

    if has_vavs:
        sections.append(SectionPlan("vav_data"))

    for fan in fans:
        sections.append(SectionPlan("fan_test", equipment_id=fan.equipment_id))

    for vfd in vfds:
        sections.append(SectionPlan("vfd_report", equipment_id=vfd.equipment_id))

    if record.photos:
        sections.append(SectionPlan("photo_log"))

    if record.technician_notes or record.known_deficiencies:
        sections.append(SectionPlan("remarks"))

    sections.append(SectionPlan("closeout"))

    plan = ReportPlan(
        report_type=record.metadata.report_type or "TAB", sections=sections
    )
    apply_overrides(record, plan)
    return plan


def apply_overrides(record: JobRecord, plan: ReportPlan) -> ReportPlan:
    """Apply technician plan overrides recorded on the job.

    Override entries are strings of the form "add:<section>" or
    "remove:<section>". Removes drop existing sections; adds append sections
    the technician explicitly requested. Overrides are manual by definition
    and surface in the plan output so validation can distinguish deliberate
    decisions from phantom sections.
    """
    if not record.plan_overrides:
        return plan
    known = {s.type for s in plan.sections}
    for entry in record.plan_overrides:
        action, _, section = entry.partition(":")
        if section not in VALID_SECTION_TYPES:
            continue
        if action == "remove":
            plan.sections = [s for s in plan.sections if s.type != section]
        elif action == "add" and section not in known:
            plan.sections.append(SectionPlan(section))
            known.add(section)
    return plan