"""SCS field workstation + knowledge API surface (M1.5, P10-P14, P34-P35).

Server-authoritative: the browser sends `{job_id, message}` only. Job truth,
knowledge authority and readiness are resolved server-side from persisted
private state. All routes require the existing SCS session.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from scs_data.authorization import Permission, ScsAuthorizer, ScsPrincipal
from scs_data.identity import ScsIdentityStore
from shared_platform.application import ApplicationContext


def _field_workspace() -> Path:
    return Path(os.environ.get("SCS_FIELD_WORKSPACE", r"C:\SCS_DATA\copilot"))


class ChatInput(BaseModel):
    message: str


class ApproveInput(BaseModel):
    source_id: str
    source_type: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    model_series: str | None = None
    equipment_family_tags: list[str] | None = None
    applicability: str | None = None
    edition: str | None = None


def build_field_router(context: ApplicationContext,
                       identity: ScsIdentityStore) -> APIRouter:
    router = APIRouter()
    authorizer = ScsAuthorizer()

    def principal(request: Request) -> ScsPrincipal:
        raw = request.cookies.get(context.session_cookie)
        employee = identity.resolve_session(raw) if raw else None
        if employee is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        return ScsPrincipal(employee.employee_id, employee.roles,
                            identity.current_functions(employee.employee_id),
                            employee.status)

    def require(actor: ScsPrincipal, permission: Permission) -> None:
        try:
            authorizer.require(actor, permission)
        except PermissionError:
            raise HTTPException(status_code=403, detail="Permission denied") from None

    # ---- job-scoped copilot -------------------------------------------------

    @router.get("/api/scs/field/jobs")
    def field_jobs(request: Request):
        actor = principal(request)
        require(actor, Permission.WORK_ASSIGNED_JOBS)
        from scs_copilot.job_service import FieldJobRuntime
        runtime = FieldJobRuntime.from_workspace(_field_workspace())
        jobs = runtime.store.list_jobs()
        return {"jobs": jobs}

    @router.get("/api/scs/field/jobs/{job_id}/truth")
    def job_truth(job_id: str, request: Request):
        actor = principal(request)
        require(actor, Permission.WORK_ASSIGNED_JOBS)
        from scs_copilot.job_service import FieldJobRuntime, build_job_truth_packet
        from scs_knowledge import resolve_knowledge_root
        from scs_knowledge.registry import SCSKnowledgeLibrary
        runtime = FieldJobRuntime.from_workspace(_field_workspace())
        try:
            record = runtime.load_job(job_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Job not found") from None
        graph = runtime.load_graph(job_id)
        memory = runtime.memory_store(job_id).load(job_id)
        root = resolve_knowledge_root(runtime.paths.root)
        library = SCSKnowledgeLibrary(root / "library.db")
        try:
            packet = build_job_truth_packet(record, graph, memory, library)
        finally:
            library.close()
        return packet

    @router.get("/api/scs/field/jobs/{job_id}/readiness")
    def readiness(job_id: str, request: Request):
        actor = principal(request)
        require(actor, Permission.WORK_ASSIGNED_JOBS)
        from scs_copilot.job_service import FieldJobRuntime
        from scs_reports.readiness import evaluate_readiness
        runtime = FieldJobRuntime.from_workspace(_field_workspace())
        try:
            record = runtime.load_job(job_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Job not found") from None
        graph = runtime.load_graph(job_id)
        memory = runtime.memory_store(job_id).load(job_id)
        return evaluate_readiness(record, graph=graph, memory=memory).to_dict()

    @router.post("/api/scs/field/jobs/{job_id}/copilot/chat")
    def copilot_chat(job_id: str, body: ChatInput, request: Request):
        actor = principal(request)
        require(actor, Permission.WORK_ASSIGNED_JOBS)
        from scs_copilot.job_service import FieldJobRuntime, run_job_scoped_copilot
        runtime = FieldJobRuntime.from_workspace(_field_workspace())
        try:
            runtime.load_job(job_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Job not found") from None
        message = (body.message or "").strip()
        if not message:
            raise HTTPException(status_code=400, detail="message required")
        return run_job_scoped_copilot(runtime, job_id, message)

    # ---- knowledge ----------------------------------------------------------

    @router.get("/api/scs/knowledge/status")
    def knowledge_status(request: Request):
        actor = principal(request)
        require(actor, Permission.VIEW_KNOWLEDGE)
        from scs_copilot.job_service import FieldJobRuntime
        from scs_knowledge import resolve_knowledge_root
        from scs_knowledge.discovery import inventory
        from scs_knowledge.registry import SCSKnowledgeLibrary
        runtime = FieldJobRuntime.from_workspace(_field_workspace())
        root = resolve_knowledge_root(runtime.paths.root)
        library = SCSKnowledgeLibrary(root / "library.db")
        try:
            inv = inventory(library)
        finally:
            library.close()
        return {
            "knowledge_root": str(root),
            "configured": "SCS_KNOWLEDGE_ROOT" in os.environ,
            "state": "CONFIGURED" if "SCS_KNOWLEDGE_ROOT" in os.environ else "NOT_CONFIGURED",
            **inv,
        }

    @router.post("/api/scs/knowledge/discover")
    def knowledge_discover(request: Request):
        actor = principal(request)
        require(actor, Permission.MANAGE_KNOWLEDGE)
        from scs_copilot.job_service import FieldJobRuntime
        from scs_knowledge import resolve_knowledge_root
        from scs_knowledge.discovery import discover_documents
        runtime = FieldJobRuntime.from_workspace(_field_workspace())
        root = resolve_knowledge_root(runtime.paths.root)
        return {"documents": discover_documents(root)}

    @router.post("/api/scs/knowledge/approve")
    def knowledge_approve(body: ApproveInput, request: Request):
        actor = principal(request)
        require(actor, Permission.MANAGE_KNOWLEDGE)
        from scs_copilot.job_service import FieldJobRuntime
        from scs_knowledge import resolve_knowledge_root
        from scs_knowledge.discovery import approve_source
        from scs_knowledge.registry import SCSKnowledgeLibrary
        runtime = FieldJobRuntime.from_workspace(_field_workspace())
        root = resolve_knowledge_root(runtime.paths.root)
        library = SCSKnowledgeLibrary(root / "library.db")
        try:
            result = approve_source(
                library, body.source_id, source_type=body.source_type,
                manufacturer=body.manufacturer, model=body.model,
                model_series=body.model_series,
                equipment_family_tags=body.equipment_family_tags,
                applicability=body.applicability, edition=body.edition,
                verified_by=actor.employee_id)
        finally:
            library.close()
        if result is None:
            raise HTTPException(status_code=404, detail="Source not found")
        return {"source": result}

    @router.post("/api/scs/knowledge/block")
    def knowledge_block(body: ApproveInput, request: Request):
        actor = principal(request)
        require(actor, Permission.MANAGE_KNOWLEDGE)
        from scs_copilot.job_service import FieldJobRuntime
        from scs_knowledge import resolve_knowledge_root
        from scs_knowledge.discovery import block_source
        from scs_knowledge.registry import SCSKnowledgeLibrary
        runtime = FieldJobRuntime.from_workspace(_field_workspace())
        root = resolve_knowledge_root(runtime.paths.root)
        library = SCSKnowledgeLibrary(root / "library.db")
        try:
            result = block_source(library, body.source_id)
        finally:
            library.close()
        if result is None:
            raise HTTPException(status_code=404, detail="Source not found")
        return {"source": result}

    return router
