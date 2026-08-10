from __future__ import annotations

import os
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from admin_auth import AdminPrincipal, require_owner
from defend_data.visitor_store import (
    client_ip,
    coarse_client_meta,
    cookie_identifiers_hmac,
    fingerprint_hmac,
)

router = APIRouter()

VISITOR_COOKIE = "defend_vid"
SESSION_COOKIE = "defend_vsid"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365


def _data(request: Request):
    data = getattr(request.app.state, "defend_data", None)
    if data is None:
        raise HTTPException(status_code=503, detail="DataCore not ready")
    return data


def _truthy_env(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _set_cookie(response: Response, name: str, value: str) -> None:
    response.set_cookie(
        name,
        value,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=_truthy_env("DEFEND_COOKIE_SECURE", "true"),
        samesite="lax",
        path="/",
    )


def ensure_visitor_session(request: Request, response: Response) -> tuple[str, str]:
    data = _data(request)
    headers = {k.lower(): v for k, v in request.headers.items()}
    observed = request.client.host if request.client else None
    ip = client_ip(
        headers,
        observed,
        trust_cloudflare=_truthy_env("DEFEND_TRUST_CLOUDFLARE", "false"),
    )
    meta = coarse_client_meta(
        request.headers.get("user-agent"),
        request.headers.get("accept-language"),
    )
    try:
        fp = fingerprint_hmac(ip, meta)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    old_vid = request.cookies.get(VISITOR_COOKIE)
    old_sid = request.cookies.get(SESSION_COOKIE)
    visitor_id = data.visitors.ensure_visitor(
        old_vid,
        fingerprint=fp,
        client_meta=meta,
    )
    session_id = data.visitors.ensure_session(
        old_sid,
        visitor_id,
        client_meta=meta,
    )
    data.visitors.record_connection(
        visitor_id=visitor_id,
        session_id=session_id,
        ip_address=ip,
        user_agent=request.headers.get("user-agent", ""),
        client_meta=meta,
        cookie_hash=cookie_identifiers_hmac(visitor_id, session_id),
    )
    if old_vid != visitor_id:
        _set_cookie(response, VISITOR_COOKIE, visitor_id)
    if old_sid != session_id:
        _set_cookie(response, SESSION_COOKIE, session_id)
    return visitor_id, session_id


@router.get("/api/conversations")
async def list_conversations(
    request: Request,
    response: Response,
    limit: int = 5,
) -> dict[str, Any]:
    data = _data(request)
    visitor_id, _ = ensure_visitor_session(request, response)
    return {
        "conversations": data.visitors.list_conversations_for_visitor(
            visitor_id, limit=max(1, min(int(limit), 5))
        )
    }


@router.post("/api/conversations")
async def create_conversation(request: Request, response: Response) -> dict[str, str]:
    data = _data(request)
    visitor_id, visitor_session_id = ensure_visitor_session(request, response)
    conversation_id = str(uuid.uuid4())
    ok = data.visitors.claim_or_verify_conversation(
        conversation_id=conversation_id,
        visitor_id=visitor_id,
        session_id=visitor_session_id,
        title="New chat",
    )
    if not ok:
        raise HTTPException(status_code=409, detail="Unable to create conversation")
    data.conversations.ensure_conversation(conversation_id, user_id=visitor_id, title="New chat")
    return {"conversation_id": conversation_id}


@router.get("/api/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    request: Request,
    response: Response,
) -> dict[str, Any]:
    data = _data(request)
    visitor_id, _ = ensure_visitor_session(request, response)
    if not data.visitors.owns_conversation(visitor_id, conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = data.conversations.get_messages(conversation_id, limit=500)
    return {
        "conversation_id": conversation_id,
        "messages": [
            {
                "message_id": m.message_id,
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at,
                "seq": m.seq,
                "trace_id": m.trace_id,
                "request_id": m.request_id,
                "metadata": m.metadata,
            }
            for m in messages
        ],
    }


@router.delete("/api/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    request: Request,
    response: Response,
) -> dict[str, bool]:
    data = _data(request)
    visitor_id, _ = ensure_visitor_session(request, response)
    if not data.visitors.owns_conversation(visitor_id, conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    # Remove durable messages first, then the cross-database visitor index.
    data.conversations.delete_conversation(conversation_id)
    data.visitors.delete_conversation_index(visitor_id, conversation_id)
    return {"ok": True}


# Owner-only analytics. These endpoints intentionally expose pseudonymous IDs,
# never raw IP addresses or raw user-agent strings.
@router.get("/api/admin/analytics/overview")
async def analytics_overview(
    request: Request,
    _owner: AdminPrincipal = Depends(require_owner),
) -> dict[str, Any]:
    data = _data(request)
    return {
        "ok": True,
        **data.visitors.overview(),
        "conversation_store": data.conversations.stats(),
        "memory": data.memory_store.stats(),
    }


@router.get("/api/admin/analytics/visitors")
async def analytics_visitors(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    _owner: AdminPrincipal = Depends(require_owner),
) -> dict[str, Any]:
    return {
        "visitors": _data(request).visitors.list_visitors(limit=limit, offset=offset)
    }


@router.get("/api/admin/analytics/visitors/{visitor_id}")
async def analytics_visitor(
    visitor_id: str,
    request: Request,
    _owner: AdminPrincipal = Depends(require_owner),
) -> dict[str, Any]:
    detail = _data(request).visitors.visitor_detail(visitor_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Unknown visitor")
    return detail


@router.get("/api/admin/analytics/conversations")
async def analytics_conversations(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    _owner: AdminPrincipal = Depends(require_owner),
) -> dict[str, Any]:
    return {
        "conversations": _data(request).visitors.list_recent_conversations(
            limit=limit, offset=offset
        )
    }


@router.get("/api/admin/analytics/conversations/{conversation_id}")
async def analytics_conversation(
    conversation_id: str,
    request: Request,
    _owner: AdminPrincipal = Depends(require_owner),
) -> dict[str, Any]:
    data = _data(request)
    messages = data.conversations.get_messages(conversation_id, limit=1000)
    if not messages:
        row = data.visitors.conn.execute(
            "SELECT 1 FROM conversation_index WHERE conversation_id=?",
            (conversation_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Unknown conversation")
    return {
        "conversation_id": conversation_id,
        "messages": [
            {
                "message_id": m.message_id,
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at,
                "seq": m.seq,
                "trace_id": m.trace_id,
                "request_id": m.request_id,
                "metadata": m.metadata,
            }
            for m in messages
        ],
    }


@router.get("/api/admin/memory/proposals")
async def memory_proposals(
    request: Request,
    status: str = "pending",
    limit: int = 100,
    offset: int = 0,
    _owner: AdminPrincipal = Depends(require_owner),
) -> dict[str, Any]:
    try:
        rows = _data(request).memory_store.list_proposals(
            status=status, limit=limit, offset=offset
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"proposals": rows}


class MemoryCommitIn(BaseModel):
    proposal_id: str = Field(min_length=1, max_length=128)
    allow_restricted: bool = False


class MemoryRejectIn(BaseModel):
    proposal_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(default="", max_length=1000)


@router.post("/api/admin/memory/commit")
async def memory_commit(
    body: MemoryCommitIn,
    request: Request,
    owner: AdminPrincipal = Depends(require_owner),
) -> dict[str, Any]:
    try:
        result = _data(request).memory.commit(
            body.proposal_id,
            approved_by=owner.username,
            allow_restricted=body.allow_restricted,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "memory_id": result.memory.memory_id,
        "was_duplicate": result.was_duplicate,
    }


@router.post("/api/admin/memory/reject")
async def memory_reject(
    body: MemoryRejectIn,
    request: Request,
    owner: AdminPrincipal = Depends(require_owner),
) -> dict[str, bool]:
    try:
        _data(request).memory.reject(
            body.proposal_id,
            approved_by=owner.username,
            reason=body.reason or "rejected by owner",
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}
