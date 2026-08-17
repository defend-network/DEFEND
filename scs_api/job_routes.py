from __future__ import annotations

from dataclasses import asdict

from datetime import date
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from scs_data.authorization import ScsPrincipal
from scs_data.identity import ScsIdentityStore
from scs_data.jobs import ScsJobStore
from shared_platform.application import ApplicationContext

class JobInput(BaseModel):
    customer_id: str; site_id: str; job_type: str; job_date: date; priority: str = "normal"; requested_scope: str | None = None; discipline: str | None = None
class StatusInput(BaseModel): status: str
class VisitInput(BaseModel): work_performed: str = Field(min_length=1); findings: str | None = None; recommendations: str | None = None; readings_summary: str | None = None
class AssignmentInput(BaseModel): employee_id: str; assignment_role: str
class NoteInput(BaseModel): body: str = Field(min_length=1); visibility: str
class ClassificationInput(BaseModel): code: str; source: str


def build_job_router(context: ApplicationContext, identity: ScsIdentityStore, jobs: ScsJobStore) -> APIRouter:
    router = APIRouter(prefix="/api/scs/jobs")

    def principal(request: Request) -> ScsPrincipal:
        raw = request.cookies.get(context.session_cookie)
        employee = identity.resolve_session(raw) if raw else None
        if employee is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        return ScsPrincipal(employee.employee_id, employee.roles, identity.current_functions(employee.employee_id), employee.status)

    @router.get("")
    def list_jobs(request: Request):
        actor = principal(request)
        return {"jobs": [asdict(item) for item in jobs.visible_jobs(actor)]}

    @router.get("/{job_id}")
    def get_job(job_id: str, request: Request):
        actor = principal(request)
        try:
            item = jobs.visible_job(actor, job_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Job not found") from None
        identity.audit.append(actor.employee_id, "job.read", "job", job_id)
        return asdict(item)

    @router.get("/{job_id}/visits")
    def visits(job_id: str, request: Request):
        actor = principal(request)
        try:
            items = jobs.visible_visits(actor, job_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Job not found") from None
        return {"visits": [asdict(item) for item in items]}

    @router.get("/{job_id}/notes")
    def notes(job_id: str, request: Request):
        actor = principal(request)
        try:
            items = jobs.visible_notes(actor, job_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Job not found") from None
        return {"notes": [asdict(item) for item in items]}

    @router.post("", status_code=status.HTTP_201_CREATED)
    def create(body: JobInput, request: Request):
        actor = principal(request)
        try: return asdict(jobs.create_job(actor.employee_id, body.customer_id, body.site_id, body.job_type, job_date=body.job_date, priority=body.priority, requested_scope=body.requested_scope, discipline=body.discipline))
        except PermissionError: raise HTTPException(status_code=403, detail="Permission denied") from None
        except ValueError as error: raise HTTPException(status_code=400, detail=str(error)) from None

    @router.post("/{job_id}/status")
    def change_status(job_id: str, body: StatusInput, request: Request):
        try: return asdict(jobs.change_status(principal(request).employee_id, job_id, body.status))
        except PermissionError: raise HTTPException(status_code=403, detail="Permission denied") from None
        except KeyError: raise HTTPException(status_code=404, detail="Job not found") from None
        except ValueError as error: raise HTTPException(status_code=400, detail=str(error)) from None

    @router.post("/{job_id}/visits", status_code=status.HTTP_201_CREATED)
    def visit(job_id: str, body: VisitInput, request: Request):
        try: return asdict(jobs.add_visit(principal(request).employee_id, job_id, work_performed=body.work_performed, findings=body.findings, recommendations=body.recommendations, readings_summary=body.readings_summary))
        except PermissionError: raise HTTPException(status_code=403, detail="Permission denied") from None
        except KeyError: raise HTTPException(status_code=404, detail="Job not found") from None

    @router.post("/{job_id}/assignments", status_code=status.HTTP_201_CREATED)
    def assign(job_id: str, body: AssignmentInput, request: Request):
        try: return asdict(jobs.assign(principal(request).employee_id, job_id, body.employee_id, body.assignment_role))
        except PermissionError: raise HTTPException(status_code=403, detail="Permission denied") from None
        except KeyError: raise HTTPException(status_code=404, detail="Job not found") from None
        except ValueError as error: raise HTTPException(status_code=400, detail=str(error)) from None

    @router.post("/{job_id}/notes", status_code=status.HTTP_201_CREATED)
    def note(job_id: str, body: NoteInput, request: Request):
        try: return asdict(jobs.add_note(principal(request).employee_id, job_id, body.body, body.visibility))
        except PermissionError: raise HTTPException(status_code=403, detail="Permission denied") from None
        except KeyError: raise HTTPException(status_code=404, detail="Job not found") from None
        except ValueError as error: raise HTTPException(status_code=400, detail=str(error)) from None

    @router.post("/{job_id}/classifications", status_code=status.HTTP_204_NO_CONTENT)
    def classify(job_id: str, body: ClassificationInput, request: Request):
        try: jobs.classify(principal(request).employee_id, job_id, body.code, source=body.source)
        except PermissionError: raise HTTPException(status_code=403, detail="Permission denied") from None
        except KeyError: raise HTTPException(status_code=404, detail="Job not found") from None
        except ValueError as error: raise HTTPException(status_code=400, detail=str(error)) from None

    return router
