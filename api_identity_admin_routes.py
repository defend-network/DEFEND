from __future__ import annotations

import os
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from admin_auth import AdminPrincipal, require_admin
from defend_data.identity_store import AccountRecord, IdentityStore, RoleViolation
from defend_data.visitor_store import VisitorStore, client_ip


router = APIRouter()


class PageParams(BaseModel):
    q: str = Field(default="", max_length=200)
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=1_000_000)


class AccountUpdateIn(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=160)
    role: Literal["admin", "user"] | None = None
    status: Literal["active", "disabled"] | None = None


def _page(
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1_000_000),
) -> PageParams:
    return PageParams(q=q, limit=limit, offset=offset)


def _stores(request: Request) -> tuple[IdentityStore, VisitorStore, object]:
    data = getattr(request.app.state, "defend_data", None)
    identity = getattr(data, "identity", None)
    visitors = getattr(data, "visitors", None)
    conversations = getattr(data, "conversations", None)
    if not isinstance(identity, IdentityStore) or not isinstance(visitors, VisitorStore):
        raise HTTPException(status_code=503, detail="Identity administration is unavailable")
    if conversations is None:
        raise HTTPException(status_code=503, detail="Conversation history is unavailable")
    return identity, visitors, conversations


def _account_payload(account: AccountRecord) -> dict[str, object]:
    return {
        "account_id": account.account_id,
        "email": account.email,
        "display_name": account.display_name,
        "role": account.role,
        "status": account.status,
        "created_at": account.created_at,
        "last_access_at": account.last_access_at,
    }


def _client_context(request: Request) -> dict[str, str]:
    headers = {key.lower(): value for key, value in request.headers.items()}
    observed = request.client.host if request.client is not None else None
    trust_cloudflare = os.getenv("DEFEND_TRUST_CLOUDFLARE", "false").strip().casefold() == "true"
    return {
        "ip_address": client_ip(headers, observed, trust_cloudflare=trust_cloudflare),
        "user_agent": request.headers.get("user-agent", "")[:512],
    }


def _audit(
    identity: IdentityStore,
    request: Request,
    principal: AdminPrincipal,
    *,
    action: str,
    target_type: str,
    target_id: str | None,
    outcome: Literal["success", "failure"],
    metadata: dict | None = None,
) -> None:
    identity.record_audit(
        actor_account_id=principal.account_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        outcome=outcome,
        request_id=(request.headers.get("x-request-id") or "")[:200] or None,
        client_context=_client_context(request),
        metadata=metadata or {},
    )


def _page_payload(result: dict[str, object], page: PageParams) -> dict[str, object]:
    return {
        "items": result["items"],
        "total": result["total"],
        "limit": page.limit,
        "offset": page.offset,
    }


def _safe_invitation(item: dict[str, object]) -> dict[str, object]:
    clean = dict(item)
    if clean.get("delivery_error"):
        clean["delivery_error"] = "Delivery failed"
    return clean


@router.get("/api/admin/accounts")
def list_accounts(
    request: Request,
    page: PageParams = Depends(_page),
    principal: AdminPrincipal = Depends(require_admin),
) -> dict[str, object]:
    identity, visitors, _ = _stores(request)
    result = identity.list_accounts(query=page.q, limit=page.limit, offset=page.offset)
    for item in result["items"]:
        linked = identity.list_linked_visitors(item["account_id"])[:200]
        summary = visitors.telemetry_summary(linked)
        item.update(summary)
    _audit(identity, request, principal, action="account.list", target_type="account", target_id=None, outcome="success", metadata={"result_count": len(result["items"])})
    return _page_payload(result, page)


@router.get("/api/admin/accounts/{account_id}")
def get_account(
    account_id: str,
    request: Request,
    principal: AdminPrincipal = Depends(require_admin),
) -> dict[str, object]:
    identity, visitors, _ = _stores(request)
    detail = identity.account_admin_detail(account_id, nested_limit=200)
    if detail is None:
        _audit(identity, request, principal, action="account.view", target_type="account", target_id=account_id, outcome="failure", metadata={"reason": "not_found"})
        raise HTTPException(status_code=404, detail="Account not found")
    linked_visitors = []
    for link in detail.pop("visitor_links"):
        visitor = visitors.visitor_admin_detail(link["visitor_id"], nested_limit=200)
        linked_visitors.append(
            {
                **link,
                **(visitor or {"visitor": None, "sessions": [], "connections": [], "conversations": [], "usage_events": []}),
                "telemetry": visitors.telemetry_summary([link["visitor_id"]]),
            }
        )
    detail["linked_visitors"] = linked_visitors
    detail["invitations"] = [_safe_invitation(item) for item in detail["invitations"]]
    _audit(identity, request, principal, action="account.view", target_type="account", target_id=account_id, outcome="success")
    return detail


@router.patch("/api/admin/accounts/{account_id}")
def update_account(
    account_id: str,
    body: AccountUpdateIn,
    request: Request,
    principal: AdminPrincipal = Depends(require_admin),
) -> dict[str, object]:
    identity, _, _ = _stores(request)
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status_code=422, detail="At least one account change is required")
    try:
        account = identity.update_account_admin(
            actor_id=principal.account_id, target_id=account_id, **changes
        )
    except KeyError as exc:
        _audit(identity, request, principal, action="account.update", target_type="account", target_id=account_id, outcome="failure", metadata={"reason": "not_found"})
        raise HTTPException(status_code=404, detail="Account not found") from exc
    except RoleViolation as exc:
        _audit(identity, request, principal, action="account.update", target_type="account", target_id=account_id, outcome="failure", metadata={"reason": "forbidden"})
        raise HTTPException(status_code=403, detail="Account action is not permitted") from exc
    except ValueError as exc:
        _audit(identity, request, principal, action="account.update", target_type="account", target_id=account_id, outcome="failure", metadata={"reason": "invalid"})
        raise HTTPException(status_code=400, detail="Invalid account update") from exc
    _audit(identity, request, principal, action="account.update", target_type="account", target_id=account_id, outcome="success", metadata={"fields": sorted(changes)})
    return {"account": _account_payload(account)}


@router.post("/api/admin/accounts/{account_id}/anonymize")
def anonymize_account(
    account_id: str,
    request: Request,
    principal: AdminPrincipal = Depends(require_admin),
) -> dict[str, object]:
    identity, _, _ = _stores(request)
    try:
        account = identity.anonymize_account(actor_id=principal.account_id, target_id=account_id)
    except KeyError as exc:
        _audit(identity, request, principal, action="account.anonymize", target_type="account", target_id=account_id, outcome="failure", metadata={"reason": "not_found"})
        raise HTTPException(status_code=404, detail="Account not found") from exc
    except RoleViolation as exc:
        _audit(identity, request, principal, action="account.anonymize", target_type="account", target_id=account_id, outcome="failure", metadata={"reason": "forbidden"})
        raise HTTPException(status_code=403, detail="Account action is not permitted") from exc
    _audit(identity, request, principal, action="account.anonymize", target_type="account", target_id=account_id, outcome="success")
    return {"account": _account_payload(account)}


@router.delete("/api/admin/accounts/{account_id}", status_code=204)
def delete_account(
    account_id: str,
    request: Request,
    principal: AdminPrincipal = Depends(require_admin),
) -> Response:
    identity, _, _ = _stores(request)
    try:
        identity.delete_account_admin(actor_id=principal.account_id, target_id=account_id)
    except KeyError as exc:
        _audit(identity, request, principal, action="account.delete", target_type="account", target_id=account_id, outcome="failure", metadata={"reason": "not_found"})
        raise HTTPException(status_code=404, detail="Account not found") from exc
    except RoleViolation as exc:
        _audit(identity, request, principal, action="account.delete", target_type="account", target_id=account_id, outcome="failure", metadata={"reason": "forbidden"})
        raise HTTPException(status_code=403, detail="Account action is not permitted") from exc
    _audit(identity, request, principal, action="account.delete", target_type="account", target_id=account_id, outcome="success")
    return Response(status_code=204)


@router.get("/api/admin/visitors")
def list_visitors(
    request: Request,
    page: PageParams = Depends(_page),
    principal: AdminPrincipal = Depends(require_admin),
) -> dict[str, object]:
    identity, visitors, _ = _stores(request)
    linked_matches = identity.visitor_ids_matching_account(page.q) if page.q else []
    result = visitors.search_visitors(query=page.q, linked_visitor_ids=linked_matches, limit=page.limit, offset=page.offset)
    linked = identity.linked_accounts_for_visitors([item["visitor_id"] for item in result["items"]])
    for item in result["items"]:
        item["linked_account"] = linked.get(item["visitor_id"])
    _audit(identity, request, principal, action="visitor.list", target_type="visitor", target_id=None, outcome="success", metadata={"result_count": len(result["items"])})
    return _page_payload(result, page)


@router.get("/api/admin/visitors/{visitor_id}")
def get_visitor(
    visitor_id: str,
    request: Request,
    principal: AdminPrincipal = Depends(require_admin),
) -> dict[str, object]:
    identity, visitors, _ = _stores(request)
    detail = visitors.visitor_admin_detail(visitor_id, nested_limit=200)
    if detail is None:
        _audit(identity, request, principal, action="visitor.view", target_type="visitor", target_id=visitor_id, outcome="failure", metadata={"reason": "not_found"})
        raise HTTPException(status_code=404, detail="Visitor not found")
    detail["linked_account"] = identity.linked_accounts_for_visitors([visitor_id]).get(visitor_id)
    _audit(identity, request, principal, action="visitor.view", target_type="visitor", target_id=visitor_id, outcome="success")
    return detail


@router.get("/api/admin/visitors/{visitor_id}/conversations/{conversation_id}")
def get_visitor_conversation(
    visitor_id: str,
    conversation_id: str,
    request: Request,
    principal: AdminPrincipal = Depends(require_admin),
) -> dict[str, object]:
    identity, visitors, conversations = _stores(request)
    if not visitors.owns_conversation(visitor_id, conversation_id):
        _audit(identity, request, principal, action="conversation.view", target_type="conversation", target_id=conversation_id, outcome="failure", metadata={"reason": "not_found", "visitor_id": visitor_id})
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = conversations.get_messages(conversation_id, limit=500)
    payload = [
        {
            "message_id": message.message_id,
            "seq": message.seq,
            "role": message.role,
            "content": message.content,
            "created_at": message.created_at,
        }
        for message in messages
    ]
    _audit(identity, request, principal, action="conversation.view", target_type="conversation", target_id=conversation_id, outcome="success", metadata={"visitor_id": visitor_id, "message_count": len(payload)})
    return {"visitor_id": visitor_id, "conversation_id": conversation_id, "messages": payload}


@router.get("/api/admin/invitations")
def list_invitations(
    request: Request,
    page: PageParams = Depends(_page),
    principal: AdminPrincipal = Depends(require_admin),
) -> dict[str, object]:
    identity, _, _ = _stores(request)
    result = identity.list_invitations_admin(query=page.q, limit=page.limit, offset=page.offset)
    result["items"] = [_safe_invitation(item) for item in result["items"]]
    _audit(identity, request, principal, action="invitation.list", target_type="invitation", target_id=None, outcome="success", metadata={"result_count": len(result["items"])})
    return _page_payload(result, page)


@router.get("/api/admin/audit")
def list_audit(
    request: Request,
    page: PageParams = Depends(_page),
    principal: AdminPrincipal = Depends(require_admin),
) -> dict[str, object]:
    identity, _, _ = _stores(request)
    items = identity.list_audit_events(query=page.q, limit=page.limit, offset=page.offset)
    total = identity.count_audit_events(query=page.q)
    _audit(identity, request, principal, action="audit.list", target_type="audit", target_id=None, outcome="success", metadata={"result_count": len(items)})
    return {"items": items, "total": total, "limit": page.limit, "offset": page.offset}
