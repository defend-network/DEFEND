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
from scs_data.jobs import ScsJobStore
from shared_platform.application import ApplicationContext


def _field_workspace() -> Path:
    return Path(os.environ.get("SCS_FIELD_WORKSPACE", r"C:\SCS_DATA\copilot"))


class ChatInput(BaseModel):
    message: str


class ReadingInput(BaseModel):
    equipment_id: str
    concept: str
    value: float
    unit: str | None = None
    stage: str = "FINAL"
    instrument_id: str | None = None
    operating_mode: str | None = None
    observed_at: str | None = None


class ApproveInput(BaseModel):
    source_id: str | None = None
    discovery_id: str | None = None
    source_type: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    model_series: str | None = None
    equipment_family_tags: list[str] | None = None
    applicability: str | None = None
    edition: str | None = None


STAGES = ("AS_FOUND", "INTERMEDIATE", "FINAL")


def build_field_router(context: ApplicationContext,
                       identity: ScsIdentityStore,
                       jobs: ScsJobStore | None = None) -> APIRouter:
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

    def authorize_field_job(actor: ScsPrincipal, job_id: str) -> None:
        """P7: assignment-scoped field job access (non-enumeration 404).

        The field JobRecord uses the canonical SCS dispatch job ID (P8)."""
        require(actor, Permission.WORK_ASSIGNED_JOBS)
        if jobs is not None:
            try:
                jobs.visible_job(actor, job_id)
                return
            except KeyError:
                raise HTTPException(status_code=404, detail="Job not found") from None
        # no dispatch store: fail closed unless the actor can see all jobs
        if Permission.VIEW_ALL_JOBS not in authorizer.permissions(actor):
            raise HTTPException(status_code=404, detail="Job not found")

    def visible_field_job_ids(actor: ScsPrincipal) -> set[str] | None:
        from scs_copilot.job_service import FieldJobRuntime
        runtime = FieldJobRuntime.from_workspace(_field_workspace())
        field_ids = set(runtime.store.list_jobs())
        if jobs is None:
            if Permission.VIEW_ALL_JOBS in authorizer.permissions(actor):
                return field_ids
            return set()
        return field_ids & {j.job_id for j in jobs.visible_jobs(actor)}

    # ---- job-scoped copilot -------------------------------------------------

    @router.get("/api/scs/field/jobs")
    def field_jobs(request: Request):
        actor = principal(request)
        ids = visible_field_job_ids(actor)
        return {"jobs": sorted(ids) if ids is not None else []}

    @router.get("/api/scs/field/jobs/{job_id}/truth")
    def job_truth(job_id: str, request: Request):
        actor = principal(request)
        authorize_field_job(actor, job_id)
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
        authorize_field_job(actor, job_id)
        from scs_copilot.job_service import FieldJobRuntime
        from scs_reports.readiness import evaluate_readiness
        from scs_reports.completeness import evaluate as evaluate_report
        runtime = FieldJobRuntime.from_workspace(_field_workspace())
        try:
            record = runtime.load_job(job_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Job not found") from None
        graph = runtime.load_graph(job_id)
        memory = runtime.memory_store(job_id).load(job_id)
        field = evaluate_readiness(record, graph=graph, memory=memory).to_dict()
        report = evaluate_report(record)
        return {
            "ready_to_leave": field,
            "report_readiness": {
                "ready": report.ready,
                "readiness": "REPORT_READY" if report.ready else "REPORT_NOT_READY",
                "summary": report.summary,
                "questions": report.questions,
            },
        }

    @router.post("/api/scs/field/jobs/{job_id}/copilot/chat")
    def copilot_chat(job_id: str, body: ChatInput, request: Request):
        actor = principal(request)
        authorize_field_job(actor, job_id)
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

    @router.get("/api/scs/field/jobs/{job_id}/history")
    def chat_history(job_id: str, request: Request):
        actor = principal(request)
        authorize_field_job(actor, job_id)
        from scs_copilot.answer_history import AnswerHistoryStore
        from scs_copilot.job_service import FieldJobRuntime
        runtime = FieldJobRuntime.from_workspace(_field_workspace())
        history = AnswerHistoryStore(runtime.paths.job_subdir(job_id, "answers")).load(job_id)
        return {"history": [
            {k: h.get(k) for k in ("answer_id", "question", "answer", "mode",
                                   "verified_claim_ids", "blocked_claim_ids",
                                   "tool_calls", "source_ids", "calculator_ids",
                                   "timestamp")}
            for h in history[-50:]
        ]}

    @router.post("/api/scs/field/jobs/{job_id}/readings", status_code=201)
    def record_reading(job_id: str, body: ReadingInput, request: Request):
        actor = principal(request)
        authorize_field_job(actor, job_id)
        if body.stage not in STAGES:
            raise HTTPException(status_code=400, detail="invalid stage")
        from scs_copilot.job_service import FieldJobRuntime
        from scs_copilot.memory import canonical_measurement
        runtime = FieldJobRuntime.from_workspace(_field_workspace())
        try:
            runtime.load_job(job_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Job not found") from None
        memory_store = runtime.memory_store(job_id)
        concept = canonical_measurement(body.concept) or body.concept.upper()
        entry = memory_store.update(job_id, lambda m: m.record_reading(
            body.concept, body.value, stage=body.stage,
            equipment_id=body.equipment_id, instrument_id=body.instrument_id,
            operating_mode=body.operating_mode, concept=concept,
            recorded_at=body.observed_at))
        return {"reading": entry}

    # ---- knowledge ----------------------------------------------------------

    def _discovery_store() -> Any:
        from scs_copilot.job_service import FieldJobRuntime
        from scs_knowledge import resolve_knowledge_root
        from scs_knowledge.discovery import KnowledgeDiscoveryStore
        runtime = FieldJobRuntime.from_workspace(_field_workspace())
        root = resolve_knowledge_root(runtime.paths.root)
        return KnowledgeDiscoveryStore(root / "discovery.json", root=root)

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
        store = _discovery_store()
        return {
            "knowledge_root": str(root),
            "configured": "SCS_KNOWLEDGE_ROOT" in os.environ,
            "state": "CONFIGURED" if "SCS_KNOWLEDGE_ROOT" in os.environ else "NOT_CONFIGURED",
            "discovery": store.list(),
            **inv,
        }

    @router.post("/api/scs/knowledge/discover")
    def knowledge_discover(request: Request):
        actor = principal(request)
        require(actor, Permission.MANAGE_KNOWLEDGE)
        store = _discovery_store()
        return {"documents": store.discover()}

    @router.post("/api/scs/knowledge/classify")
    def knowledge_classify(body: ApproveInput, request: Request):
        actor = principal(request)
        require(actor, Permission.MANAGE_KNOWLEDGE)
        store = _discovery_store()
        result = store.classify(body.discovery_id or body.source_id or "",
                                source_type=body.source_type,
                                manufacturer=body.manufacturer, model=body.model,
                                model_series=body.model_series,
                                family_tags=body.equipment_family_tags,
                                applicability=body.applicability, edition=body.edition)
        if result is None:
            raise HTTPException(status_code=404, detail="Candidate not found")
        return {"document": result}

    @router.post("/api/scs/knowledge/approve")
    def knowledge_approve(body: ApproveInput, request: Request):
        actor = principal(request)
        require(actor, Permission.MANAGE_KNOWLEDGE)
        store = _discovery_store()
        from scs_copilot.job_service import FieldJobRuntime
        from scs_knowledge import resolve_knowledge_root
        from scs_knowledge.registry import SCSKnowledgeLibrary
        runtime = FieldJobRuntime.from_workspace(_field_workspace())
        root = resolve_knowledge_root(runtime.paths.root)
        library = SCSKnowledgeLibrary(root / "library.db")
        try:
            if body.discovery_id:
                result = store.approve_and_index(
                    body.discovery_id, library, verified_by=actor.employee_id,
                    private_root=root / "documents",
                    source_type=body.source_type, manufacturer=body.manufacturer,
                    model=body.model, model_series=body.model_series,
                    family_tags=body.equipment_family_tags,
                    applicability=body.applicability, edition=body.edition)
            else:
                from scs_knowledge.discovery import approve_source
                result = approve_source(
                    library, body.source_id or "", source_type=body.source_type,
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
        store = _discovery_store()
        if body.discovery_id:
            result = store.block(body.discovery_id)
            if result is None:
                raise HTTPException(status_code=404, detail="Candidate not found")
            return {"document": result}
        from scs_copilot.job_service import FieldJobRuntime
        from scs_knowledge import resolve_knowledge_root
        from scs_knowledge.discovery import block_source
        from scs_knowledge.registry import SCSKnowledgeLibrary
        runtime = FieldJobRuntime.from_workspace(_field_workspace())
        root = resolve_knowledge_root(runtime.paths.root)
        library = SCSKnowledgeLibrary(root / "library.db")
        try:
            result = block_source(library, body.source_id or "")
        finally:
            library.close()
        if result is None:
            raise HTTPException(status_code=404, detail="Source not found")
        return {"source": result}

    return router
