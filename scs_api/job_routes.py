from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request

from scs_data.authorization import ScsPrincipal
from scs_data.identity import ScsIdentityStore
from scs_data.jobs import ScsJobStore
from shared_platform.application import ApplicationContext


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

    return router
