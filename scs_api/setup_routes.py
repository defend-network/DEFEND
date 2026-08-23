"""SCS product-owned Setup API (M1.5C-S).

Owner-facing Setup surface. SCS owns it — Control Center does NOT. Reuses the
existing SCS session/permission boundary; the server is always the authority.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from scs_data.authorization import Permission, ScsAuthorizer, ScsPrincipal
from scs_data.identity import ScsIdentityStore
from scs_data.settings import ScsSettingsStore, validate_knowledge_root
from scs_data.supervision import supervision_manifest
from shared_platform.application import ApplicationContext


class KnowledgeRootInput(BaseModel):
    path: str


class RecoverInput(BaseModel):
    confirm_unknown_authority: bool = False


def build_setup_router(context: ApplicationContext,
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

    def settings() -> ScsSettingsStore:
        return ScsSettingsStore(Path(context.data_root) / "settings.json")

    def discovery_store():
        from scs_knowledge.discovery import KnowledgeDiscoveryStore
        store = settings()
        root, source = store.knowledge_root()
        if root is None:
            return None, None, "not_configured"
        root_path = Path(root)
        return KnowledgeDiscoveryStore(root_path / "discovery.json", root=root_path), root_path, source

    @router.get("/api/scs/setup")
    def setup_status(request: Request):
        actor = principal(request)
        require(actor, Permission.VIEW_KNOWLEDGE)
        store = settings()
        root, source = store.knowledge_root()
        ledger_state = None
        if root is not None:
            from scs_knowledge.discovery import KnowledgeDiscoveryStore
            ds = KnowledgeDiscoveryStore(Path(root) / "discovery.json", root=Path(root))
            ledger_state = ds.ledger_state
        return {
            "manifest": supervision_manifest(context),
            "knowledge_root": root,
            "knowledge_root_source": source,
            "knowledge_configured": root is not None,
            "discovery_ledger_state": ledger_state,
        }

    @router.get("/api/scs/setup/knowledge")
    def knowledge_settings(request: Request):
        actor = principal(request)
        require(actor, Permission.VIEW_KNOWLEDGE)
        store = settings()
        root, source = store.knowledge_root()
        return {"knowledge_root": root, "source": source,
                "configured": root is not None}

    @router.put("/api/scs/setup/knowledge/root")
    def set_knowledge_root(body: KnowledgeRootInput, request: Request):
        actor = principal(request)
        require(actor, Permission.MANAGE_KNOWLEDGE)
        try:
            resolved = validate_knowledge_root(body.path)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from None
        store = settings()
        store.set("knowledge_root", str(resolved))
        return {"knowledge_root": str(resolved), "source": "persisted"}

    @router.get("/api/scs/setup/knowledge/ledger")
    def ledger_state(request: Request):
        actor = principal(request)
        require(actor, Permission.VIEW_KNOWLEDGE)
        ds, _root, source = discovery_store()
        if ds is None:
            return {"discovery_ledger_state": "NOT_CONFIGURED",
                    "knowledge_authority_blocked": "KNOWLEDGE_AUTHORITY_BLOCKED_ROOT_NOT_CONFIGURED"}
        return {"discovery_ledger_state": ds.ledger_state,
                "discovered_count": len(ds.list())}

    @router.post("/api/scs/setup/knowledge/recover")
    def recover_ledger(body: RecoverInput, request: Request):
        actor = principal(request)
        require(actor, Permission.MANAGE_KNOWLEDGE)
        ds, _root, _source = discovery_store()
        if ds is None:
            raise HTTPException(status_code=409,
                                detail="KNOWLEDGE_AUTHORITY_BLOCKED_ROOT_NOT_CONFIGURED")
        result = ds.archive_and_rediscover(
            actor=actor.employee_id,
            confirm_unknown_authority=body.confirm_unknown_authority)
        return result

    @router.post("/api/scs/setup/knowledge/discover")
    def discover(request: Request):
        actor = principal(request)
        require(actor, Permission.MANAGE_KNOWLEDGE)
        ds, _root, _source = discovery_store()
        if ds is None:
            raise HTTPException(status_code=409,
                                detail="KNOWLEDGE_AUTHORITY_BLOCKED_ROOT_NOT_CONFIGURED")
        return {"documents": ds.discover()}

    return router
