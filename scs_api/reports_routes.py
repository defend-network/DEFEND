from __future__ import annotations

import os
from dataclasses import asdict
from datetime import date
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from scs_data.authorization import ScsPrincipal
from scs_data.identity import ScsIdentityStore
from shared_platform.application import ApplicationContext

from scs_reports.store import ContractorStore, JobStore, MasterStore, PhotoIngest, ReportPaths
from scs_reports.planner import plan_for
from scs_reports.composer import Composer
from scs_reports.validation import validate_report
from scs_reports.vision import build_vision_router, vision_provider_status
from scs_reports.schema import (
    AirDevice,
    Contractor,
    Equipment,
    EquipmentType,
    Finding,
    JobMetadata,
    JobRecord,
    Measurement,
    Provenance,
    Traverse,
    TraversePoint,
)


class ContractorInput(BaseModel):
    name: str
    contact: str | None = None
    phone: str | None = None
    email: str | None = None


class JobHeaderInput(BaseModel):
    project_name: str
    project_number: str
    site_name: str
    site_address: str
    test_date: date
    technician: str
    hiring_contractor: str | None = None


class EquipmentInput(BaseModel):
    equipment_id: str
    equipment_type: str
    tag: str
    manufacturer: str | None = None
    model: str | None = None
    serial: str | None = None
    area_served: str | None = None


class MeasurementInput(BaseModel):
    field: str
    value: float | str
    unit: str = ""
    source_type: str = "TECH_ENTERED"
    source_ref: str | None = None
    technician_confirmed: bool = True
    timestamp: str | None = None


class AirDeviceInput(BaseModel):
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


class TraverseInput(BaseModel):
    traverse_id: str
    system_id: str
    location: str
    duct_size: str | None = None
    area_sqft: float | None = None
    design_fpm: float | None = None
    final_fpm: float | None = None
    points: list[dict] = []


class FindingInput(BaseModel):
    title: str
    details: str
    severity: str = "open"
    evidence_refs: list[str] = []


class NotesInput(BaseModel):
    notes: str


def build_reports_router(
    context: ApplicationContext, identity: ScsIdentityStore, paths: ReportPaths | None = None
) -> APIRouter:
    report_paths = paths or ReportPaths(
        Path(os.environ.get("SCS_DATA_ROOT") or r"C:\SCS_DATA")
    ).ensure()
    contractors = ContractorStore(report_paths)
    jobs = JobStore(report_paths)
    masters = MasterStore(report_paths)
    photos = PhotoIngest(report_paths)
    composer = Composer(report_paths, jobs)
    vision = build_vision_router()
    router = APIRouter(prefix="/api/scs/reports")

    def principal(request: Request) -> ScsPrincipal:
        raw = request.cookies.get(context.session_cookie)
        employee = identity.resolve_session(raw) if raw else None
        if employee is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        return ScsPrincipal(
            employee.employee_id, employee.roles,
            identity.current_functions(employee.employee_id), employee.status,
        )

    @router.get("/contractors")
    def list_contractors(request: Request):
        principal(request)
        return {"contractors": [asdict(item) for item in contractors.load()]}

    @router.post("/contractors", status_code=status.HTTP_201_CREATED)
    def add_contractor(body: ContractorInput, request: Request):
        principal(request)
        try:
            item = contractors.add(
                Contractor(company_name=body.name, contact=body.contact, phone=body.phone, email=body.email)
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from None
        return asdict(item)

    @router.get("/jobs")
    def list_jobs(request: Request):
        principal(request)
        items = []
        for job_id in jobs.list_jobs():
            record = jobs.load(job_id)
            items.append({"job_id": job_id, **asdict(record.metadata)})
        return {"jobs": items}

    @router.post("/jobs", status_code=status.HTTP_201_CREATED)
    def create_job(body: JobHeaderInput, request: Request):
        principal(request)
        job_id = body.project_number.replace(" ", "_").lower()
        record = JobRecord(
            metadata=JobMetadata(
                job_id=job_id,
                project_name=body.project_name,
                project_number=body.project_number,
                site_name=body.site_name,
                site_address=body.site_address,
                test_date=body.test_date,
                technician=body.technician,
                hiring_contractor=body.hiring_contractor,
            )
        )
        try:
            jobs.create(record)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from None
        return asdict(record)

    @router.get("/jobs/{job_id}")
    def get_job(job_id: str, request: Request):
        principal(request)
        try:
            record = jobs.load(job_id)
        except (KeyError, FileNotFoundError):
            raise HTTPException(status_code=404, detail="Job not found") from None
        return asdict(record)

    @router.put("/jobs/{job_id}")
    def replace_job(job_id: str, body: dict, request: Request):
        principal(request)
        try:
            record = jobs.load(job_id)
        except (KeyError, FileNotFoundError):
            raise HTTPException(status_code=404, detail="Job not found") from None
        incoming = dict(body)
        if incoming.get("job_id") not in (None, job_id):
            raise HTTPException(status_code=400, detail="job_id cannot change")
        incoming["metadata"] = dict(incoming.get("metadata") or {})
        incoming["metadata"]["job_id"] = job_id
        incoming["metadata"]["created_at"] = record.metadata.created_at.isoformat()
        incoming["metadata"]["updated_at"] = record.metadata.updated_at.isoformat()
        try:
            updated = JobRecord.from_dict(incoming)
        except (KeyError, ValueError, TypeError) as error:
            raise HTTPException(status_code=400, detail=f"Invalid record: {error}") from None
        if not updated.metadata.project_name or not updated.metadata.technician:
            raise HTTPException(status_code=400, detail="project_name and technician are required")
        jobs.save(updated)
        return asdict(updated)

    @router.post("/jobs/{job_id}/equipment", status_code=status.HTTP_201_CREATED)
    def add_equipment(job_id: str, body: EquipmentInput, request: Request):
        principal(request)
        try:
            record = jobs.load(job_id)
        except (KeyError, FileNotFoundError):
            raise HTTPException(status_code=404, detail="Job not found") from None
        try:
            equipment_type = EquipmentType(body.equipment_type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown equipment type: {body.equipment_type}") from None
        if any(item.equipment_id == body.equipment_id for item in record.equipment):
            raise HTTPException(status_code=400, detail=f"Equipment {body.equipment_id} already exists")
        record.equipment.append(
            Equipment(
                equipment_id=body.equipment_id, equipment_type=equipment_type, tag=body.tag,
                manufacturer=body.manufacturer, model=body.model, serial=body.serial,
                area_served=body.area_served,
            )
        )
        jobs.save(record)
        return asdict(record)

    @router.post("/jobs/{job_id}/equipment/{equipment_id}/measurements", status_code=status.HTTP_201_CREATED)
    def add_measurement(job_id: str, equipment_id: str, body: MeasurementInput, request: Request):
        principal(request)
        try:
            record = jobs.load(job_id)
        except (KeyError, FileNotFoundError):
            raise HTTPException(status_code=404, detail="Job not found") from None
        target = next((item for item in record.equipment if item.equipment_id == equipment_id), None)
        if target is None:
            raise HTTPException(status_code=404, detail=f"Equipment {equipment_id} not found")
        try:
            source_type = Provenance(body.source_type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown provenance: {body.source_type}") from None
        target.measurements.append(
            Measurement(
                field=body.field, value=body.value, unit=body.unit, source_type=source_type,
                source_ref=body.source_ref, technician_confirmed=body.technician_confirmed,
                timestamp=body.timestamp,
            )
        )
        jobs.save(record)
        return asdict(record)

    @router.post("/jobs/{job_id}/air-devices", status_code=status.HTTP_201_CREATED)
    def add_air_device(job_id: str, body: AirDeviceInput, request: Request):
        principal(request)
        try:
            record = jobs.load(job_id)
        except (KeyError, FileNotFoundError):
            raise HTTPException(status_code=404, detail="Job not found") from None
        if any(item.device_id == body.device_id for item in record.air_devices):
            raise HTTPException(status_code=400, detail=f"Air device {body.device_id} already exists")
        record.air_devices.append(
            AirDevice(
                device_id=body.device_id, function=body.function, area_served=body.area_served,
                design_cfm=body.design_cfm, as_found_cfm=body.as_found_cfm, final_cfm=body.final_cfm,
                measurement_method=body.measurement_method, size=body.size,
                avg_velocity_fpm=body.avg_velocity_fpm, status=body.status, notes=body.notes,
            )
        )
        jobs.save(record)
        return asdict(record)

    @router.post("/jobs/{job_id}/traverses", status_code=status.HTTP_201_CREATED)
    def add_traverse(job_id: str, body: TraverseInput, request: Request):
        principal(request)
        try:
            record = jobs.load(job_id)
        except (KeyError, FileNotFoundError):
            raise HTTPException(status_code=404, detail="Job not found") from None
        if any(item.traverse_id == body.traverse_id for item in record.traverses):
            raise HTTPException(status_code=400, detail=f"Traverse {body.traverse_id} already exists")
        record.traverses.append(
            Traverse(
                traverse_id=body.traverse_id, system_id=body.system_id, location=body.location,
                duct_size=body.duct_size, area_sqft=body.area_sqft,
                design_fpm=body.design_fpm, final_fpm=body.final_fpm,
                points=[TraversePoint(p["label"], p["fpm"], p.get("depth_inches")) for p in body.points],
            )
        )
        jobs.save(record)
        return asdict(record)

    @router.post("/jobs/{job_id}/findings", status_code=status.HTTP_201_CREATED)
    def add_finding(job_id: str, body: FindingInput, request: Request):
        principal(request)
        try:
            record = jobs.load(job_id)
        except (KeyError, FileNotFoundError):
            raise HTTPException(status_code=404, detail="Job not found") from None
        finding = Finding(body.title, body.details, severity=body.severity, evidence_refs=body.evidence_refs)
        record.findings.append(finding)
        jobs.save(record)
        return asdict(finding)

    @router.post("/jobs/{job_id}/notes", status_code=status.HTTP_204_NO_CONTENT)
    def set_notes(job_id: str, body: NotesInput, request: Request):
        principal(request)
        try:
            record = jobs.load(job_id)
        except (KeyError, FileNotFoundError):
            raise HTTPException(status_code=404, detail="Job not found") from None
        record.technician_notes = body.notes
        jobs.save(record)

    @router.post("/jobs/{job_id}/photos", status_code=status.HTTP_201_CREATED)
    async def add_photos(job_id: str, request: Request, files: list[UploadFile]):
        principal(request)
        try:
            record = jobs.load(job_id)
        except (KeyError, FileNotFoundError):
            raise HTTPException(status_code=404, detail="Job not found") from None
        staging = report_paths.config / "_uploads" / job_id
        staging.mkdir(parents=True, exist_ok=True)
        staged: list[Path] = []
        try:
            for upload in files:
                destination = staging / upload.filename
                destination.write_bytes(await upload.read())
                staged.append(destination)
            entries = photos.ingest(job_id, staged, classifier=vision)
        finally:
            for destination in staged:
                destination.unlink(missing_ok=True)
            try:
                staging.rmdir()
            except OSError:
                pass
        record.photos.extend(entries)
        jobs.save(record)
        return {"photos": [entry.to_dict() for entry in entries]}

    @router.get("/jobs/{job_id}/plan")
    def get_plan(job_id: str, request: Request):
        principal(request)
        try:
            record = jobs.load(job_id)
        except (KeyError, FileNotFoundError):
            raise HTTPException(status_code=404, detail="Job not found") from None
        plan = plan_for(record)
        return {"sections": [s.type for s in plan.sections]}

    @router.post("/jobs/{job_id}/compose")
    def compose(job_id: str, request: Request):
        principal(request)
        try:
            record = jobs.load(job_id)
        except (KeyError, FileNotFoundError):
            raise HTTPException(status_code=404, detail="Job not found") from None
        plan = plan_for(record)
        try:
            output = composer.compose(record, plan)
        except Exception as error:
            raise HTTPException(status_code=400, detail=f"Compose failed: {error}") from None
        report = validate_report(record, plan, output, masters=masters)
        return {
            "output": output.name,
            "blocked": report.blocked,
            "checks": [
                {"name": check.name, "status": check.status, "message": check.message}
                for check in report.checks
            ],
        }

    @router.get("/jobs/{job_id}/outputs")
    def list_outputs(job_id: str, request: Request):
        principal(request)
        directory = report_paths.job_subdir(job_id, "output")
        if not directory.exists():
            return {"outputs": []}
        return {"outputs": sorted(item.name for item in directory.glob("*.xlsx"))}

    @router.get("/jobs/{job_id}/outputs/{filename}")
    def download_output(job_id: str, filename: str, request: Request):
        principal(request)
        if Path(filename).name != filename or not filename.endswith(".xlsx"):
            raise HTTPException(status_code=400, detail="Invalid filename")
        target = report_paths.job_subdir(job_id, "output") / filename
        if not target.exists():
            raise HTTPException(status_code=404, detail="Output not found")
        return FileResponse(
            target,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=filename,
        )

    @router.get("/vision/status")
    def vision_status(request: Request):
        principal(request)
        return vision_provider_status(vision)

    return router