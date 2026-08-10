"""
DEFEND API server — thin FastAPI adapter for defend-ui-v2 (Next.js).
"""

from __future__ import annotations

import asyncio
import traceback
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from control_plane import AgentRequest, ControlPlane
from registry import build_default_registry
from model_factory import build_model_client
from admin_auth import AdminPrincipal, configure_identity_store, require_admin
from api_admin_tt_routes import router as admin_tt_router
from api_batch3_routes import router as batch3_router, ensure_visitor_session
from api_identity_routes import SensitivePathRedactionMiddleware, router as identity_router
from api_identity_admin_routes import router as identity_admin_router
from defend_data import DataCore
from defend_data.ingest_policy import AIIngestExcluded, assert_ai_ingest_allowed

from production_policy import ProductionPolicy

API_TOKEN = os.getenv("DEFEND_API_TOKEN", "").strip()
MODEL_NAME = os.getenv("DEFEND_MODEL", "defend-ai:latest")

def _default_data_root() -> Path:
    configured = os.getenv("DEFEND_DATA_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        return Path(r"C:\DEFEND_DATA")
    return Path("./DEFEND_DATA").resolve()

DATA_ROOT = _default_data_root()
UPLOAD_DIR = Path(os.getenv("DEFEND_UPLOAD_DIR", str(DATA_ROOT / "session_uploads")))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

_SESSION_FILES: dict[str, list[dict[str, str]]] = {}
_JOBS: dict[str, dict[str, Any]] = {}

def _safe_conversation_id(raw: str | None) -> str:
    """Reject path traversal; prefer UUID-shaped ids."""
    import re
    s = (raw or "").strip()
    if not s:
        return str(uuid.uuid4())
    # allow uuid hex and simple safe tokens only
    if re.fullmatch(r"[A-Za-z0-9_\-]{8,64}", s):
        return s
    raise HTTPException(status_code=400, detail="Invalid conversation_id")




class SourceOut(BaseModel):
    id: str
    title: str
    url: str | None = None
    page: int | None = None
    authority: str | None = None


class ChatOut(BaseModel):
    content: str
    research_status: str | None = None
    evidence_count: int | None = None
    trace_id: str | None = None
    execution_status: str | None = None
    search_rounds: int | None = None
    recovery_attempts: int | None = None
    sources: list[SourceOut] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)




def _pack_response(resp) -> dict[str, Any]:
    meta = resp.metadata or {}
    sources: list[dict[str, Any]] = []
    for s in resp.sources or []:
        if not isinstance(s, dict):
            continue
        sources.append({
            "id": str(s.get("evidence_id") or s.get("source_id") or s.get("id") or uuid.uuid4().hex[:12]),
            "title": str(s.get("title") or "source"),
            "url": s.get("url"),
            "page": s.get("page"),
            "authority": s.get("authority"),
        })
    return {
        "content": resp.content or "",
        "research_status": meta.get("research_status") or meta.get("route"),
        "evidence_count": meta.get("evidence_count"),
        "trace_id": meta.get("trace_id"),
        "execution_status": meta.get("execution_status"),
        "search_rounds": meta.get("search_rounds"),
        "recovery_attempts": meta.get("recovery_attempts"),
        "sources": sources,
        "metadata": meta,
        "status": "done",
        "job_id": None,
    }


def _conversation_store_user(req: AgentRequest) -> None:
    if state.data is None or not req.session_id:
        return
    state.data.conversations.ensure_conversation(
        req.session_id,
        # user_id is server-assigned pseudonymous visitor identity in Batch 3.
        user_id=req.user_id,
        project_id=req.project_id,
        title=(req.message or "")[:160] or "New chat",
        metadata={"source": "api_chat"},
    )
    state.data.conversations.append_message(
        req.session_id,
        role="user",
        content=req.message,
        request_id=req.request_id,
        metadata={"research_mode": req.research_mode},
    )
    if req.user_id:
        state.data.visitors.touch_conversation(
            conversation_id=req.session_id,
            visitor_id=req.user_id,
            title=(req.message or "")[:160],
            increment_messages=1,
        )
        state.data.visitors.record_event(
            event_type="user_message",
            visitor_id=req.user_id,
            conversation_id=req.session_id,
            request_id=req.request_id,
            model=MODEL_NAME,
            status="accepted",
            metadata={"research_mode": req.research_mode},
        )


def _conversation_store_assistant(req: AgentRequest, resp, packed: dict[str, Any]) -> None:
    if state.data is None or not req.session_id:
        return
    meta = resp.metadata or {}
    state.data.conversations.append_message(
        req.session_id,
        role="assistant",
        content=resp.content or "",
        trace_id=meta.get("trace_id"),
        request_id=req.request_id,
        metadata={
            "route": meta.get("route"),
            "research_status": meta.get("research_status"),
            "execution_status": meta.get("execution_status"),
            "job_id": packed.get("job_id"),
        },
    )
    if req.user_id:
        state.data.visitors.touch_conversation(
            conversation_id=req.session_id,
            visitor_id=req.user_id,
            last_route=meta.get("route"),
            last_model=MODEL_NAME,
            research_status=meta.get("research_status"),
            increment_messages=1,
        )
        tool_count = 0
        try:
            tool_count = len(resp.plan_execution.steps) if resp.plan_execution else 0
        except Exception:
            tool_count = 0
        state.data.visitors.record_event(
            event_type="assistant_response",
            visitor_id=req.user_id,
            conversation_id=req.session_id,
            request_id=req.request_id,
            route=meta.get("route"),
            model=MODEL_NAME,
            research_status=meta.get("research_status"),
            evidence_count=meta.get("evidence_count"),
            status=meta.get("execution_status") or "done",
            metadata={
                "trace_id": meta.get("trace_id"),
                "job_id": packed.get("job_id"),
                "tool_count": tool_count,
            },
        )


async def _run_chat_job(job_id: str, req: AgentRequest) -> None:
    visitor_id = (_JOBS.get(job_id) or {}).get("visitor_id") or req.user_id
    try:
        if state.cp is None:
            _JOBS[job_id] = {
                "status": "error",
                "error": "Agent not ready",
                "visitor_id": visitor_id,
            }
            return
        resp = await state.cp.handle(req)
        packed = _pack_response(resp)
        packed["job_id"] = job_id
        packed["status"] = "done"
        _conversation_store_assistant(req, resp, packed)
        _JOBS[job_id] = {
            "status": "done",
            "result": packed,
            "visitor_id": visitor_id,
        }
    except Exception as e:
        traceback.print_exc()
        _JOBS[job_id] = {
            "status": "error",
            "error": f"{type(e).__name__}: {e}",
            "visitor_id": visitor_id,
        }

class AppState:
    model: Any = None
    cp: ControlPlane | None = None
    data: DataCore | None = None


state = AppState()


def _auth(authorization: str | None) -> None:
    if not API_TOKEN:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    if authorization.removeprefix("Bearer ").strip() != API_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")


@asynccontextmanager
async def lifespan(app: FastAPI):
    data = DataCore(DATA_ROOT)
    try:
        configure_identity_store(data.identity)
    except Exception:
        data.close()
        raise
    registry = build_default_registry(memory_manager=data.memory)
    model = build_model_client()
    if hasattr(model, "__aenter__"):
        await model.__aenter__()
    state.data = data
    app.state.defend_data = data
    state.model = model
    state.cp = ControlPlane(
        tool_registry=registry,
        model_client=model,
        memory_manager=data.memory,
        conversation_store=data.conversations,
        policy_engine=ProductionPolicy(),
        parallel_tool_limit=int(os.getenv("DEFEND_PARALLEL_TOOLS", "3")),
    )
    backend = os.getenv("DEFEND_MODEL_BACKEND", "ollama")
    print(
        f"[DEFEND API] backend={backend} model={MODEL_NAME} "
        f"data_root={data.paths.root} tools={list(registry.keys())}"
    )
    try:
        yield
    finally:
        if state.model is not None and hasattr(state.model, "__aexit__"):
            await state.model.__aexit__(None, None, None)
        if state.data is not None:
            state.data.close()
        state.model = None
        state.cp = None
        state.data = None
        app.state.defend_data = None


app = FastAPI(title="DEFEND AI API", version="0.4.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        x.strip()
        for x in os.getenv(
            "DEFEND_CORS_ORIGINS",
            "https://ai.defend-network.org,https://api.defend-network.org,https://defend-ai.defend-network.org,http://localhost:3000,http://127.0.0.1:3000",
        ).split(",")
        if x.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SensitivePathRedactionMiddleware)


# Additive server-side admin login + owner-only TableTennis routes.
app.include_router(admin_tt_router)
app.include_router(batch3_router)
app.include_router(identity_router)
app.include_router(identity_admin_router)


async def _health_payload() -> dict[str, Any]:
    ok = state.cp is not None and state.model is not None
    model_ok = True
    if state.model is not None and hasattr(state.model, "healthcheck"):
        try:
            model_ok = bool(await state.model.healthcheck())
        except Exception:
            model_ok = False
    return {
        "ok": ok and model_ok,
        "model": MODEL_NAME,
        "tools": list(state.cp.tools.keys()) if state.cp else [],
    }


@app.get("/health")
async def public_health():
    return await _health_payload()


@app.get("/api/admin/system/health")
async def admin_health(_admin: AdminPrincipal = Depends(require_admin)):
    return await _health_payload()


@app.get("/api/admin/data/health")
async def admin_data_health(_admin: AdminPrincipal = Depends(require_admin)):
    if state.data is None:
        raise HTTPException(status_code=503, detail="DataCore not ready")
    return state.data.health()


@app.get("/api/admin/memory/stats")
async def admin_memory_stats(_admin: AdminPrincipal = Depends(require_admin)):
    if state.data is None:
        raise HTTPException(status_code=503, detail="DataCore not ready")
    return state.data.memory_store.stats()


@app.post("/api/chat")
@app.post("/v1/chat")
async def chat(
    request: Request,
    response: Response,
    authorization: str | None = Header(default=None),
):
    _auth(authorization)
    if state.cp is None:
        raise HTTPException(status_code=503, detail="Agent not ready")

    try:
        raw = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    message = (
        raw.get("message")
        or raw.get("content")
        or raw.get("text")
        or raw.get("query")
        or ""
    )
    if isinstance(message, dict):
        message = message.get("content") or message.get("text") or ""
    message = str(message).strip()
    if not message:
        raise HTTPException(
            status_code=422,
            detail=f"No message in body keys={list(raw.keys())}",
        )

    conversation_id = (
        raw.get("conversation_id")
        or raw.get("conversationId")
        or raw.get("session_id")
        or raw.get("sessionId")
    )
    conversation_id = _safe_conversation_id(conversation_id)

    visitor_id, visitor_session_id = ensure_visitor_session(request, response)
    if state.data is None:
        raise HTTPException(status_code=503, detail="DataCore not ready")
    if not state.data.visitors.claim_or_verify_conversation(
        conversation_id=conversation_id,
        visitor_id=visitor_id,
        session_id=visitor_session_id,
        title=(message or "")[:160] or "New chat",
    ):
        raise HTTPException(status_code=404, detail="Conversation not found")

    raw_docs = raw.get("document_ids") or raw.get("documentIds") or []
    if not isinstance(raw_docs, list):
        raw_docs = []
    document_ids = [str(x) for x in raw_docs if x]

    req = AgentRequest(
        request_id=str(uuid.uuid4()),
        message=message,
        session_id=conversation_id,
        # Never trust request-body user_id; use server-issued visitor identity.
        user_id=visitor_id,
        project_id=None,
        document_ids=document_ids,
        research_mode=(raw.get("research_mode") or raw.get("researchMode") or "fast"),
    )

    _conversation_store_user(req)

    # Single router: ControlPlane decides route (no duplicate keyword list)
    try:
        if hasattr(state.cp, "classify"):
            decision = await state.cp.classify(req)
        else:
            decision = await state.cp._classify(req)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"classify:{type(e).__name__}")

    from execution_protocol import Route

    if decision.route != Route.RESEARCH:
        try:
            resp = await state.cp.handle(req)
            packed = _pack_response(resp)
            _conversation_store_assistant(req, resp, packed)
            return packed
        except Exception as e:
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"{type(e).__name__}")

    # RESEARCH → background job (browser polls status)
    job_id = str(uuid.uuid4())
    _JOBS[job_id] = {"status": "running", "result": None, "visitor_id": visitor_id}
    asyncio.create_task(_run_chat_job(job_id, req))
    return {"status": "running", "job_id": job_id, "route": decision.route.value, "route_reason": decision.reason_code}


@app.get("/api/chat/status/{job_id}")
async def chat_status(
    job_id: str,
    request: Request,
    response: Response,
    authorization: str | None = Header(default=None),
):
    _auth(authorization)
    visitor_id, _ = ensure_visitor_session(request, response)
    job = _JOBS.get(job_id)
    if not job or job.get("visitor_id") != visitor_id:
        raise HTTPException(status_code=404, detail="job not found")
    if job["status"] == "running":
        return {"status": "running", "job_id": job_id}
    if job["status"] == "error":
        return {
            "status": "error",
            "job_id": job_id,
            "error": job.get("error") or "Research job failed",
        }
    result = job.get("result") or {}
    return {"status": "done", "job_id": job_id, **result}


@app.post("/api/files/upload")
async def upload_files(
    request: Request,
    response: Response,
    conversation_id: str = Form(...),
    files: list[UploadFile] = File(...),
    authorization: str | None = Header(default=None),
):
    _auth(authorization)
    conversation_id = _safe_conversation_id(conversation_id)
    visitor_id, visitor_session_id = ensure_visitor_session(request, response)
    if state.data is None:
        raise HTTPException(status_code=503, detail="DataCore not ready")
    if not state.data.visitors.claim_or_verify_conversation(
        conversation_id=conversation_id,
        visitor_id=visitor_id,
        session_id=visitor_session_id,
        title="New chat",
    ):
        raise HTTPException(status_code=404, detail="Conversation not found")
    state.data.conversations.ensure_conversation(
        conversation_id, user_id=visitor_id, title="New chat"
    )
    if len(files) > 8:
        raise HTTPException(status_code=400, detail="Too many files (max 8)")

    saved: list[dict[str, str]] = []
    conv_dir = UPLOAD_DIR / conversation_id
    conv_dir.mkdir(parents=True, exist_ok=True)

    ALLOWED_EXT = {".pdf", ".docx", ".xlsx", ".xlsm", ".txt", ".md", ".csv", ".png", ".jpg", ".jpeg"}

    try:
        from tools.documents_store import save_document, content_hash_bytes
    except Exception:
        from documents_store import save_document, content_hash_bytes  # type: ignore

    for f in files:
        filename = f.filename or "upload.bin"
        raw_name = Path(filename).name
        ext = Path(raw_name).suffix.lower()
        if ext not in ALLOWED_EXT:
            raise HTTPException(status_code=400, detail=f"Extension not allowed: {ext}")
        doc_id = f"doc_sess_{uuid.uuid4().hex[:16]}"
        dest = conv_dir / f"{doc_id}_{raw_name}"
        data = await f.read()
        if len(data) > 25_000_000:
            raise HTTPException(status_code=400, detail=f"File too large: {raw_name}")
        try:
            assert_ai_ingest_allowed(filename=filename, content_prefix=data[:4096])
        except AIIngestExcluded as e:
            raise HTTPException(status_code=400, detail=str(e))
        dest.write_bytes(data)

        # Register in DocumentsStore so documents.read / search can resolve the ID
        media = {
            ".pdf": "pdf",
            ".docx": "docx",
            ".xlsx": "xlsx",
            ".xlsm": "xlsm",
            ".png": "png",
            ".jpg": "jpeg",
            ".jpeg": "jpeg",
            ".txt": "txt",
            ".md": "md",
            ".csv": "csv",
        }.get(ext, "unknown")
        meta = {
            "document_id": doc_id,
            "source_id": f"session:{doc_id}",
            "requested_url": None,
            "final_url": None,
            "source_path": filename,
            "media_type": media,
            "content_type": f.content_type,
            "page_count": None,
            "title": raw_name,
            "content_hash": content_hash_bytes(data),
            "downloaded_bytes": len(data),
            "scope": "session",
            "owner_session_id": conversation_id,
        }
        # light PDF page probe
        if media == "pdf":
            try:
                import pymupdf
                pdf = pymupdf.open(stream=data, filetype="pdf")
                meta["page_count"] = pdf.page_count
                if pdf.metadata:
                    meta["title"] = pdf.metadata.get("title") or raw_name
                pdf.close()
            except Exception:
                pass
        stored_path = save_document(document_id=doc_id, raw=data, metadata=meta)

        artifact_id = None
        if state.data is not None:
            artifact = state.data.catalog.ingest_bytes(
                data,
                media_type=f.content_type or media,
                collector="session_upload",
                dataset="session_uploads",
                scope="session",
                retention_class="session",
                classification="internal",
                artifact_metadata={
                    "filename": raw_name,
                    "document_id": doc_id,
                },
                retrieval_metadata={
                    "conversation_id": conversation_id,
                },
            )
            artifact_id = artifact.artifact_id
            state.data.conversations.add_attachment(
                conversation_id,
                document_id=doc_id,
                artifact_id=artifact_id,
                display_name=raw_name,
                metadata={"media_type": media},
            )

        saved.append(
            {
                "document_id": doc_id,
                "name": raw_name,
                "status": "ready",
                "path": stored_path,
                "artifact_id": artifact_id,
            }
        )

    _SESSION_FILES.setdefault(conversation_id, []).extend(saved)
    return {
        "files": [
            {
                "document_id": x["document_id"],
                "name": x["name"],
                "status": x["status"],
            }
            for x in saved
        ]
    }


@app.get("/api/admin/rag/documents")
async def admin_rag_documents(_admin: AdminPrincipal = Depends(require_admin)):
    return {"documents": [], "note": "Connect to rag store metadata next"}


@app.post("/api/admin/research/run")
async def admin_research_run(
    body: dict[str, Any],
    _admin: AdminPrincipal = Depends(require_admin),
):
    if state.cp is None:
        raise HTTPException(status_code=503, detail="Agent not ready")
    question = (body.get("question") or body.get("message") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question required")
    if "cite" not in question.lower() and "official" not in question.lower():
        question = f"Find official sources and cite them: {question}"
    req = AgentRequest(request_id=str(uuid.uuid4()), message=question)
    resp = await state.cp.handle(req)
    meta = resp.metadata or {}
    return {
        "content": resp.content,
        "research_status": meta.get("research_status"),
        "execution_status": meta.get("execution_status"),
        "evidence_count": meta.get("evidence_count"),
        "search_rounds": meta.get("search_rounds"),
        "recovery_attempts": meta.get("recovery_attempts"),
        "trace_id": meta.get("trace_id"),
        "source_outcomes": meta.get("source_outcomes"),
        "sources": resp.sources,
        "metadata": meta,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api_server:app",
        host="127.0.0.1",
        port=int(os.getenv("DEFEND_API_PORT", "8000")),
        reload=False,
    )
