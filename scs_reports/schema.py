"""Structured TAB field-report data model (the source of truth).

The generated workbook is derived FROM these records; Excel is never the
canonical data model. Every important value carries provenance.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any


class Provenance(str, Enum):
    TECH_ENTERED = "TECH_ENTERED"
    PHOTO_EXTRACTED = "PHOTO_EXTRACTED"
    PHOTO_CONFIRMED = "PHOTO_CONFIRMED"
    PLAN_EXTRACTED = "PLAN_EXTRACTED"
    MASTER_TEMPLATE = "MASTER_TEMPLATE"
    CALCULATED = "CALCULATED"
    AI_INFERRED_TEXT = "AI_INFERRED_TEXT"


class PhotoClassification(str, Enum):
    NAMEPLATE = "NAMEPLATE"
    INSTRUMENT_READING = "INSTRUMENT_READING"
    AIRFLOW_READING = "AIRFLOW_READING"
    PRESSURE_READING = "PRESSURE_READING"
    TEMP_RH_READING = "TEMP_RH_READING"
    EQUIPMENT = "EQUIPMENT"
    DUCTWORK = "DUCTWORK"
    OUTLET = "OUTLET"
    EXHAUST = "EXHAUST"
    OUTSIDE_AIR = "OUTSIDE_AIR"
    DEFICIENCY = "DEFICIENCY"
    WORK_PERFORMED = "WORK_PERFORMED"
    GENERAL = "GENERAL"
    UNKNOWN = "UNKNOWN"


class ReviewStatus(str, Enum):
    UNREVIEWED = "UNREVIEWED"
    CONFIRMED = "CONFIRMED"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    REJECTED = "REJECTED"


class EquipmentType(str, Enum):
    RTU = "RTU"
    AHU = "AHU"
    FCU = "FCU"
    VAV = "VAV"
    FAN = "FAN"
    VFD = "VFD"
    EXHAUST = "EXHAUST"
    OUTSIDE_AIR = "OUTSIDE_AIR"
    OTHER = "OTHER"


TEST_CATEGORY_LABELS: dict[str, str] = {
    "RTU": "RTU / AHU",
    "AHU": "RTU / AHU",
    "VAV": "VAV",
    "FCU": "FCU",
    "FAN": "FAN",
    "VFD": "VFD",
    "Exhaust": "Exhaust",
    "Outside air": "Outside Air",
    "Traverse": "Duct Traverse",
    "Building pressure": "Building Pressure",
}


def tested_category_labels(categories: list[str]) -> list[str]:
    """Human-readable tested categories, deduplicated, preserving order.

    Unknown raw values pass through unchanged; nothing is invented.
    """
    seen: set[str] = set()
    labels: list[str] = []
    for category in categories:
        label = TEST_CATEGORY_LABELS.get(category, category)
        if label not in seen:
            seen.add(label)
            labels.append(label)
    return labels


@dataclass
class Measurement:
    field: str
    value: Any
    unit: str
    source_type: Provenance
    source_ref: str | None = None
    confidence: float | None = None
    technician_confirmed: bool = False
    not_applicable: bool = False
    timestamp: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "value": self.value,
            "unit": self.unit,
            "source_type": self.source_type.value,
            "source_ref": self.source_ref,
            "confidence": self.confidence,
            "technician_confirmed": self.technician_confirmed,
            "not_applicable": self.not_applicable,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Measurement":
        return cls(
            field=data["field"],
            value=data["value"],
            unit=data.get("unit", ""),
            source_type=Provenance(data.get("source_type", "TECH_ENTERED")),
            source_ref=data.get("source_ref"),
            confidence=data.get("confidence"),
            technician_confirmed=bool(data.get("technician_confirmed", False)),
            not_applicable=bool(data.get("not_applicable", False)),
            timestamp=(
                datetime.fromisoformat(data["timestamp"])
                if data.get("timestamp")
                else None
            ),
        )


@dataclass
class PhotoEvidence:
    photo_id: str
    original_filename: str
    sha256: str
    classification: PhotoClassification = PhotoClassification.UNKNOWN
    captured_at: datetime | None = None
    equipment_association: str | None = None
    candidate_facts: list[dict[str, Any]] = field(default_factory=list)
    confidence: float | None = None
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED

    def to_dict(self) -> dict[str, Any]:
        return {
            "photo_id": self.photo_id,
            "original_filename": self.original_filename,
            "sha256": self.sha256,
            "classification": (
                self.classification.value if self.classification else PhotoClassification.UNKNOWN.value
            ),
            "captured_at": self.captured_at.isoformat() if self.captured_at else None,
            "equipment_association": self.equipment_association,
            "candidate_facts": self.candidate_facts,
            "confidence": self.confidence,
            "review_status": self.review_status.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PhotoEvidence":
        return cls(
            photo_id=data["photo_id"],
            original_filename=data["original_filename"],
            sha256=data["sha256"],
            classification=PhotoClassification(
                data.get("classification") or "UNKNOWN"
            ),
            captured_at=(
                datetime.fromisoformat(data["captured_at"])
                if data.get("captured_at")
                else None
            ),
            equipment_association=data.get("equipment_association"),
            candidate_facts=data.get("candidate_facts") or [],
            confidence=data.get("confidence"),
            review_status=ReviewStatus(data.get("review_status") or "UNREVIEWED"),
        )


@dataclass
class DesignData:
    design_cfm: float | None = None
    design_fpm: float | None = None
    design_tons: float | None = None
    design_pressure: float | None = None
    acceptance_criteria: str | None = None
    design_not_provided: bool = False
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "design_cfm": self.design_cfm,
            "design_fpm": self.design_fpm,
            "design_tons": self.design_tons,
            "design_pressure": self.design_pressure,
            "acceptance_criteria": self.acceptance_criteria,
            "design_not_provided": self.design_not_provided,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "DesignData":
        data = data or {}
        return cls(
            design_cfm=data.get("design_cfm"),
            design_fpm=data.get("design_fpm"),
            design_tons=data.get("design_tons"),
            design_pressure=data.get("design_pressure"),
            acceptance_criteria=data.get("acceptance_criteria"),
            design_not_provided=bool(data.get("design_not_provided", False)),
            notes=data.get("notes"),
        )


@dataclass
class Deficiency:
    description: str
    impact: str | None = None
    evidence_refs: list[str] = field(default_factory=list)
    status: str = "open"

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "impact": self.impact,
            "evidence_refs": self.evidence_refs,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Deficiency":
        return cls(
            description=data["description"],
            impact=data.get("impact"),
            evidence_refs=data.get("evidence_refs", []),
            status=data.get("status", "open"),
        )


@dataclass
class Equipment:
    equipment_id: str
    equipment_type: EquipmentType
    tag: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    serial: str | None = None
    area_served: str | None = None
    design_data: DesignData = field(default_factory=DesignData)
    measurements: list[Measurement] = field(default_factory=list)
    deficiencies: list[Deficiency] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    notes: str | None = None

    def measurement(self, field: str) -> Measurement | None:
        for m in self.measurements:
            if m.field == field:
                return m
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "equipment_id": self.equipment_id,
            "equipment_type": self.equipment_type.value,
            "tag": self.tag,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "serial": self.serial,
            "area_served": self.area_served,
            "design_data": self.design_data.to_dict(),
            "measurements": [m.to_dict() for m in self.measurements],
            "deficiencies": [d.to_dict() for d in self.deficiencies],
            "evidence_refs": self.evidence_refs,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Equipment":
        return cls(
            equipment_id=data["equipment_id"],
            equipment_type=EquipmentType(data.get("equipment_type", "OTHER")),
            tag=data.get("tag"),
            manufacturer=data.get("manufacturer"),
            model=data.get("model"),
            serial=data.get("serial"),
            area_served=data.get("area_served"),
            design_data=DesignData.from_dict(data.get("design_data") or {}),
            measurements=[
                Measurement.from_dict(m) for m in (data.get("measurements") or [])
            ],
            deficiencies=[
                Deficiency.from_dict(d) for d in (data.get("deficiencies") or [])
            ],
            evidence_refs=data.get("evidence_refs") or [],
            notes=data.get("notes"),
        )


@dataclass
class AirDevice:
    device_id: str
    function: str
    area_served: str | None = None
    design_cfm: float | None = None
    as_found_cfm: float | None = None
    final_cfm: float | None = None
    measurement_method: str | None = None
    size: str | None = None
    avg_velocity_fpm: float | None = None
    status: str | None = None
    notes: str | None = None
    evidence_refs: list[str] = field(default_factory=list)

    @property
    def percent_design(self) -> float | None:
        if self.design_cfm and self.final_cfm is not None:
            return self.final_cfm / self.design_cfm
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "function": self.function,
            "area_served": self.area_served,
            "design_cfm": self.design_cfm,
            "as_found_cfm": self.as_found_cfm,
            "final_cfm": self.final_cfm,
            "measurement_method": self.measurement_method,
            "size": self.size,
            "avg_velocity_fpm": self.avg_velocity_fpm,
            "status": self.status,
            "notes": self.notes,
            "evidence_refs": self.evidence_refs,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AirDevice":
        return cls(
            device_id=data["device_id"],
            function=data.get("function", ""),
            area_served=data.get("area_served"),
            design_cfm=data.get("design_cfm"),
            as_found_cfm=data.get("as_found_cfm"),
            final_cfm=data.get("final_cfm"),
            measurement_method=data.get("measurement_method"),
            size=data.get("size"),
            avg_velocity_fpm=data.get("avg_velocity_fpm"),
            status=data.get("status"),
            notes=data.get("notes"),
            evidence_refs=data.get("evidence_refs", []),
        )


@dataclass
class TraversePoint:
    row_label: str
    fpm: float
    column: int


@dataclass
class Traverse:
    traverse_id: str
    system_id: str
    location: str
    duct_size: str
    area_sqft: float
    design_fpm: float | None = None
    final_fpm: float | None = None
    sp: str | None = None
    instrument: str = "pitot"
    air_temp: str | None = None
    points: list[TraversePoint] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)

    @property
    def final_cfm(self) -> float | None:
        if self.final_fpm is not None:
            return self.final_fpm * self.area_sqft
        return None

    @property
    def design_cfm(self) -> float | None:
        if self.design_fpm is not None:
            return self.design_fpm * self.area_sqft
        return None

    @property
    def percent_design(self) -> float | None:
        if self.design_cfm and self.final_cfm:
            return self.final_cfm / self.design_cfm
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "traverse_id": self.traverse_id,
            "system_id": self.system_id,
            "location": self.location,
            "duct_size": self.duct_size,
            "area_sqft": self.area_sqft,
            "design_fpm": self.design_fpm,
            "final_fpm": self.final_fpm,
            "sp": self.sp,
            "instrument": self.instrument,
            "air_temp": self.air_temp,
            "points": [
                {"row_label": p.row_label, "fpm": p.fpm, "column": p.column}
                for p in self.points
            ],
            "evidence_refs": self.evidence_refs,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Traverse":
        return cls(
            traverse_id=data["traverse_id"],
            system_id=data.get("system_id", ""),
            location=data.get("location", ""),
            duct_size=data.get("duct_size", ""),
            area_sqft=data.get("area_sqft", 0.0),
            design_fpm=data.get("design_fpm"),
            final_fpm=data.get("final_fpm"),
            sp=data.get("sp"),
            instrument=data.get("instrument", "pitot"),
            air_temp=data.get("air_temp"),
            points=[
                TraversePoint(p["row_label"], p["fpm"], p["column"])
                for p in data.get("points", [])
            ],
            evidence_refs=data.get("evidence_refs", []),
        )


@dataclass
class EnvironmentalReading:
    field: str
    value: float
    unit: str
    location: str | None = None
    timestamp: datetime | None = None
    evidence_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "value": self.value,
            "unit": self.unit,
            "location": self.location,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "evidence_refs": self.evidence_refs,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EnvironmentalReading":
        return cls(
            field=data["field"],
            value=data["value"],
            unit=data.get("unit", ""),
            location=data.get("location"),
            timestamp=(
                datetime.fromisoformat(data["timestamp"])
                if data.get("timestamp")
                else None
            ),
            evidence_refs=data.get("evidence_refs", []),
        )


@dataclass
class Finding:
    title: str
    detail: str
    category: str = "observation"
    severity: str = "info"
    evidence_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "detail": self.detail,
            "category": self.category,
            "severity": self.severity,
            "evidence_refs": self.evidence_refs,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Finding":
        return cls(
            title=data["title"],
            detail=data.get("detail", ""),
            category=data.get("category", "observation"),
            severity=data.get("severity", "info"),
            evidence_refs=data.get("evidence_refs", []),
        )


@dataclass
class Contractor:
    company_name: str
    contact: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "company_name": self.company_name,
            "contact": self.contact,
            "email": self.email,
            "phone": self.phone,
            "address": self.address,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Contractor":
        return cls(
            company_name=data["company_name"],
            contact=data.get("contact"),
            email=data.get("email"),
            phone=data.get("phone"),
            address=data.get("address"),
            notes=data.get("notes"),
        )


@dataclass
class JobMetadata:
    job_id: str
    project_name: str
    project_number: str | None = None
    site_name: str = ""
    site_address: str = ""
    test_date: date | None = None
    technician: str = ""
    hiring_contractor: str | None = None
    customer: str | None = None
    design_engineer: str | None = None
    report_type: str = "TAB"
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "project_name": self.project_name,
            "project_number": self.project_number,
            "site_name": self.site_name,
            "site_address": self.site_address,
            "test_date": self.test_date.isoformat() if self.test_date else None,
            "technician": self.technician,
            "hiring_contractor": self.hiring_contractor,
            "customer": self.customer,
            "design_engineer": self.design_engineer,
            "report_type": self.report_type,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JobMetadata":
        return cls(
            job_id=data["job_id"],
            project_name=data["project_name"],
            project_number=data.get("project_number"),
            site_name=data.get("site_name", ""),
            site_address=data.get("site_address", ""),
            test_date=(
                date.fromisoformat(data["test_date"]) if data.get("test_date") else None
            ),
            technician=data.get("technician", ""),
            hiring_contractor=data.get("hiring_contractor"),
            customer=data.get("customer"),
            design_engineer=data.get("design_engineer"),
            report_type=data.get("report_type", "TAB"),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )


@dataclass
class JobRecord:
    metadata: JobMetadata
    scope_notes: str = ""
    field_observations: str = ""
    known_deficiencies: str = ""
    technician_notes: str = ""
    categories_tested: list[str] = field(default_factory=list)
    equipment: list[Equipment] = field(default_factory=list)
    air_devices: list[AirDevice] = field(default_factory=list)
    traverses: list[Traverse] = field(default_factory=list)
    environmental_readings: list[EnvironmentalReading] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    photos: list[PhotoEvidence] = field(default_factory=list)
    plan_overrides: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "metadata": self.metadata.to_dict(),
            "scope_notes": self.scope_notes,
            "field_observations": self.field_observations,
            "known_deficiencies": self.known_deficiencies,
            "technician_notes": self.technician_notes,
            "categories_tested": list(self.categories_tested),
            "equipment": [e.to_dict() for e in self.equipment],
            "air_devices": [d.to_dict() for d in self.air_devices],
            "traverses": [t.to_dict() for t in self.traverses],
            "environmental_readings": [
                r.to_dict() for r in self.environmental_readings
            ],
            "findings": [f.to_dict() for f in self.findings],
            "photos": [p.to_dict() for p in self.photos],
            "plan_overrides": list(self.plan_overrides),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JobRecord":
        return cls(
            metadata=JobMetadata.from_dict(data["metadata"]),
            scope_notes=data.get("scope_notes", ""),
            field_observations=data.get("field_observations", ""),
            known_deficiencies=data.get("known_deficiencies", ""),
            technician_notes=data.get("technician_notes", ""),
            categories_tested=list(data.get("categories_tested") or []),
            equipment=[Equipment.from_dict(e) for e in (data.get("equipment") or [])],
            air_devices=[AirDevice.from_dict(d) for d in (data.get("air_devices") or [])],
            traverses=[Traverse.from_dict(t) for t in (data.get("traverses") or [])],
            environmental_readings=[
                EnvironmentalReading.from_dict(r)
                for r in (data.get("environmental_readings") or [])
            ],
            findings=[Finding.from_dict(f) for f in (data.get("findings") or [])],
            photos=[PhotoEvidence.from_dict(p) for p in (data.get("photos") or [])],
            plan_overrides=list(data.get("plan_overrides") or []),
        )