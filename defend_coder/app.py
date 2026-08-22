from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import secrets
import threading
from typing import Callable
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .auth import (
    AuthError,
    AuthService,
    AuthenticatedAccount,
)
from .config import CoderSettings
from .credentials import CredentialStore
from .db import CoderDatabase
from .identity import default_identity_profile
from .providers import (
    NEXT_MODEL,
    SOL_MODEL,
    ModelTarget,
    build_client,
    deepseek_target,
    next_target,
    sol_target,
)
from .repositories import CoderRepository, WorkspaceRecord
from .router import (
    PRODUCT_IDENTITY,
    EscalationReason,
    ModelSelector,
    ModelTier,
    model_for_tier,
    tier_for_model,
)
from .routing import (
    ProductRuntimeAdapterBoundary,
    RuntimeResumeDenied,
    resolve_starting_route,
)
from .runs import (
    RunConflictError,
    RunDetail,
    RunRecord,
    RunsRepository,
    RunRunner,
)
from .workspaces import WorkspaceAccessError, WorkspaceService


SESSION_COOKIE = "defendcoder_session"
CSRF_COOKIE = "defendcoder_csrf"

HEARTBEAT_PATH = "/v1/auth/heartbeat"

#: Fields the consumer-facing runtime status endpoint may expose. Anything
#: else produced by the injected runtime_status() callback stays server-side.
CONSUMER_RUNTIME_FIELDS = (
    "state",
    "model",
    "alias",
    "provider",
    "context_used",
    "context_limit",
    "detail",
)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1)
    role: str


class WorkspaceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    workspace_root: str = Field(min_length=1)
    repository_url: str | None = None
    default_branch: str | None = None


class RunCreateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20000)
    requested_mode: str = Field(default="AUTO", max_length=16)
    model: str | None = Field(default=None, max_length=64)


class ModelSelectRequest(BaseModel):
    requested_mode: str = Field(min_length=1, max_length=16)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20000)


class CredentialRequest(BaseModel):
    api_key: str = Field(min_length=1, max_length=4096)


def _default_secret_store() -> object:
    """Platform DPAPI secret store loader (defendcoder product)."""
    from pathlib import Path as _Path

    from defend_control.secrets import DpapiSecretStore

    local = os.environ.get("LOCALAPPDATA") or "."
    return DpapiSecretStore(_Path(local) / "DEFEND" / "secrets.dpapi")


def _account_dict(account: AuthenticatedAccount) -> dict[str, object]:
    return {
        "account_id": str(account.account_id),
        "username": account.username,
        "email": account.email,
        "role": account.role,
        "is_active": account.is_active,
    }


def project_runtime_status(
    status: dict[str, object],
) -> dict[str, object]:
    """Project a runtime status dict onto the consumer-safe field subset.

    The full status may contain control-plane details; only the documented
    safe fields are returned to authenticated browser clients.
    """
    return {
        name: status[name]
        for name in CONSUMER_RUNTIME_FIELDS
        if name in status
    }


def _workspace_dict(workspace: object) -> dict[str, object]:
    result = {}

    for name in (
        "workspace_id",
        "account_id",
        "name",
        "workspace_root",
        "repository_url",
        "default_branch",
        "created_at",
        "updated_at",
    ):
        if hasattr(workspace, name):
            value = getattr(workspace, name)

            if hasattr(value, "isoformat"):
                value = value.isoformat()
            elif value is not None and name.endswith("_id"):
                value = str(value)

            result[name] = value

    return result


def _run_dict(run: RunRecord) -> dict[str, object]:
    return {
        "run_id": str(run.run_id),
        "workspace_id": str(run.workspace_id),
        "owner_account_id": str(run.owner_account_id),
        "prompt": run.prompt,
        "status": run.status,
        "phase": run.phase,
        "reason": run.reason,
        "error": run.error,
        "created_at": (
            run.created_at.isoformat()
            if run.created_at is not None
            else None
        ),
        "finished_at": (
            run.finished_at.isoformat()
            if run.finished_at is not None
            else None
        ),
    }


def _message_dict(message: object) -> dict[str, object]:
    result = {
        "seq": getattr(message, "seq"),
        "role": getattr(message, "role"),
        "content": getattr(message, "content"),
        "tool_call_id": getattr(message, "tool_call_id"),
        "tool_name": getattr(message, "tool_name"),
        "tool_result": getattr(message, "tool_result"),
        "kind": getattr(message, "kind"),
        "ok": getattr(message, "ok"),
        "created_at": (
            getattr(message, "created_at").isoformat()
            if getattr(message, "created_at") is not None
            else None
        ),
    }

    if getattr(message, "role") == "assistant":
        result["tool_calls"] = getattr(message, "tool_arguments")
    else:
        result["tool_calls"] = None

    return result


def build_coder_app(
    *,
    settings: CoderSettings,
    db: CoderDatabase,
    auth: AuthService,
    runtime_status: Callable[[], dict[str, object]],
    repository: CoderRepository | None = None,
    runs_repository: RunsRepository | None = None,
    runner: RunRunner | None = None,
    configured_root: str | Path | None = None,
    idle_timeout_seconds: int | None = None,
    runtime_stop_callback: Callable[[str], None] | None = None,
    idle_reaper_interval_seconds: float = 15.0,
    # Router integration (additive; defaults preserve legacy behavior).
    credentials: object | None = None,
    runtime_adapter: object | None = None,
    model_selector: ModelSelector | None = None,
) -> FastAPI:
    idle_timeout_seconds = (
        settings.idle_timeout_seconds
        if idle_timeout_seconds is None
        else idle_timeout_seconds
    )

    if idle_timeout_seconds < 0:
        raise ValueError("idle_timeout_seconds must be >= 0")

    def _reaper_loop(stop_event: threading.Event) -> None:
        while not stop_event.wait(idle_reaper_interval_seconds):
            try:
                run_idle_cycle(
                    auth,
                    runtime_stop_callback,
                    idle_timeout=timedelta(
                        seconds=idle_timeout_seconds
                    ),
                )
            except Exception:
                continue

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        task: asyncio.Task | None = None
        stop_event = threading.Event()

        if idle_timeout_seconds > 0:
            task = asyncio.create_task(
                asyncio.to_thread(_reaper_loop, stop_event)
            )

        try:
            yield
        finally:
            if task is not None:
                stop_event.set()

                try:
                    await task
                except asyncio.CancelledError:
                    pass

    app = FastAPI(
        title="DEFENDcoder API",
        version="1.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    repository = repository or CoderRepository(db)
    runs_repository = runs_repository or RunsRepository(db)
    workspace_service = WorkspaceService(
        repository=repository,
        configured_root=(
            configured_root
            if configured_root is not None
            else settings.workspace_root
        ),
    )

    # Router integration state (additive). Defaults keep the legacy single
    # model path intact when no provider is configured.
    _credentials = credentials or CredentialStore(
        store_loader=_default_secret_store
    )
    _runtime_adapter = runtime_adapter or ProductRuntimeAdapterBoundary()
    _selector = model_selector or ModelSelector()

    def _live_targets() -> dict[str, ModelTarget]:
        """Targets keyed by MODEL ID with LIVE credential availability."""
        deepseek = deepseek_target(
            availability=_credentials.configured("deepseek")
        )
        return {
            deepseek.model_id: deepseek,
            NEXT_MODEL: next_target(availability=True),
            SOL_MODEL: sol_target(
                availability=_credentials.configured("sol")
            ),
        }

    def _target_for_model(model: str) -> ModelTarget:
        try:
            return _live_targets()[model]
        except KeyError:
            raise HTTPException(
                status_code=400,
                detail=f"no configured target for model {model!r}",
            ) from None

    def _require_owner(account: AuthenticatedAccount) -> None:
        if account.role != "admin":
            raise HTTPException(
                status_code=403,
                detail="owner/admin authority required",
            )

    def _owned_run(
        account: AuthenticatedAccount,
        workspace_id: str,
        run_id: str,
    ) -> RunDetail:
        workspace = owned_workspace(account, workspace_id)
        parsed = UUID(run_id)
        detail = runs_repository.get_run(parsed)
        if detail is None or detail.workspace_id != workspace.workspace_id:
            raise HTTPException(status_code=404, detail="run not found")
        return detail

    def _resume_same_run(
        detail: RunDetail,
        workspace_id: str,
        run_id: str,
        account: AuthenticatedAccount,
    ) -> None:
        """Continue the SAME run after an owner escalation choice.

        Persists route change first (done by the caller), transitions to
        resuming/running, and re-dispatches the worker on the same run_id.
        The per-run RoutingAgentClient resolves the CURRENT routing before
        the next generation call, so the approved provider is actually used.
        """
        workspace = owned_workspace(account, workspace_id)
        runs_repository.update_run_phase(UUID(run_id), "resuming")
        runs_repository.update_run_status(
            UUID(run_id),
            status="running",
            error=None,
            reason="unknown",
        )
        if runner is not None:
            runner.start_existing(
                run_id=UUID(run_id),
                workspace=workspace,
                prompt=detail.prompt,
            )

    def _resolve_targets_public() -> dict[str, object]:
        return {
            model: target.as_public_dict()
            for model, target in _live_targets().items()
        }

    def current_account(request: Request) -> AuthenticatedAccount:
        token = request.cookies.get(SESSION_COOKIE)

        if not token:
            raise HTTPException(
                status_code=401,
                detail="invalid session",
            )

        try:
            account = auth.authenticate_session(token)
        except AuthError:
            raise HTTPException(
                status_code=401,
                detail="invalid session",
            ) from None

        if (
            idle_timeout_seconds > 0
            and request.url.path != HEARTBEAT_PATH
        ):
            auth.touch_session(token)

        return account

    def require_csrf(request: Request) -> None:
        expected = request.cookies.get(CSRF_COOKIE)
        supplied = request.headers.get("X-CSRF-Token")

        if (
            not expected
            or not supplied
            or not secrets.compare_digest(expected, supplied)
        ):
            raise HTTPException(
                status_code=403,
                detail="csrf validation failed",
            )

    @app.get("/health")
    def health() -> dict[str, object]:
        return {
            "ok": True,
            "application_id": "coder",
        }

    @app.post("/v1/auth/login")
    def login(
        payload: LoginRequest,
        response: Response,
    ) -> dict[str, object]:
        if payload.role not in {"admin", "consumer"}:
            raise HTTPException(
                status_code=401,
                detail="invalid credentials",
            )

        try:
            session = auth.login(
                payload.username,
                payload.password,
            )
        except AuthError:
            raise HTTPException(
                status_code=401,
                detail="invalid credentials",
            ) from None

        if session.account.role != payload.role:
            try:
                auth.logout(session.token)
            except AuthError:
                pass

            raise HTTPException(
                status_code=401,
                detail="invalid credentials",
            )

        csrf_token = secrets.token_urlsafe(32)

        response.set_cookie(
            key=SESSION_COOKIE,
            value=session.token,
            httponly=True,
            secure=settings.public_https,
            samesite="lax",
            path="/",
        )

        response.set_cookie(
            key=CSRF_COOKIE,
            value=csrf_token,
            httponly=False,
            secure=settings.public_https,
            samesite="lax",
            path="/",
        )

        return {
            "account": _account_dict(session.account),
            "csrf_token": csrf_token,
        }

    @app.post("/v1/auth/heartbeat")
    def heartbeat(request: Request) -> dict[str, object]:
        account = current_account(request)

        return {
            "ok": True,
            "role": account.role,
        }

    @app.get("/v1/auth/session")
    def session(request: Request) -> dict[str, object]:
        account = current_account(request)

        return {
            "account": _account_dict(account),
        }

    @app.post(
        "/v1/auth/logout",
        status_code=204,
    )
    def logout(
        request: Request,
        response: Response,
    ) -> Response:
        require_csrf(request)

        token = request.cookies.get(SESSION_COOKIE)

        if not token:
            raise HTTPException(
                status_code=401,
                detail="invalid session",
            )

        try:
            auth.logout(token)
        except AuthError:
            raise HTTPException(
                status_code=401,
                detail="invalid session",
            ) from None

        response.delete_cookie(
            SESSION_COOKIE,
            path="/",
        )
        response.delete_cookie(
            CSRF_COOKIE,
            path="/",
        )

        response.status_code = 204
        return response

    @app.get("/v1/workspaces")
    def list_workspaces(
        request: Request,
    ) -> dict[str, object]:
        account = current_account(request)

        workspaces = repository.list_workspaces_for_owner(
            account.account_id
        )

        return {
            "workspaces": [
                _workspace_dict(workspace)
                for workspace in workspaces
            ]
        }

    @app.post(
        "/v1/workspaces",
        status_code=201,
    )
    def create_workspace(
        payload: WorkspaceCreateRequest,
        request: Request,
    ) -> dict[str, object]:
        account = current_account(request)
        require_csrf(request)

        workspace = repository.create_workspace(
            owner_account_id=account.account_id,
            name=payload.name,
            workspace_root=payload.workspace_root,
            repository_url=payload.repository_url,
            default_branch=payload.default_branch,
        )

        return {
            "workspace": _workspace_dict(workspace),
        }

    @app.get("/v1/runtime/status")
    def runtime_status_view(
        request: Request,
    ) -> dict[str, object]:
        current_account(request)

        return {
            "application_id": "coder",
            "runtime": project_runtime_status(runtime_status()),
        }

    @app.get("/v1/admin/status")
    def admin_status(
        request: Request,
    ) -> dict[str, object]:
        account = current_account(request)

        try:
            auth.require_role(account, "admin")
        except AuthError:
            raise HTTPException(
                status_code=403,
                detail="forbidden",
            ) from None

        return {
            "application_id": "coder",
            "runtime": runtime_status(),
        }

    def owned_workspace(
        account: AuthenticatedAccount,
        workspace_id: str,
    ) -> WorkspaceRecord:
        try:
            parsed = UUID(workspace_id)
        except ValueError:
            raise HTTPException(
                status_code=404,
                detail="workspace not found",
            ) from None

        for workspace in repository.list_workspaces_for_owner(
            account.account_id
        ):
            if workspace.workspace_id == parsed:
                return workspace

        raise HTTPException(
            status_code=404,
            detail="workspace not found",
        )

    def owned_run(
        account: AuthenticatedAccount,
        workspace_id: str,
        run_id: str,
    ) -> RunDetail:
        workspace = owned_workspace(account, workspace_id)

        try:
            parsed = UUID(run_id)
        except ValueError:
            raise HTTPException(
                status_code=404,
                detail="run not found",
            ) from None

        run = runs_repository.get_run(parsed)
        if (
            run is None
            or run.workspace_id != workspace.workspace_id
            or run.owner_account_id != account.account_id
        ):
            raise HTTPException(
                status_code=404,
                detail="run not found",
            )

        return RunDetail(
            run=run,
            messages=runs_repository.messages_for_run(parsed),
        )

    @app.post(
        "/v1/workspaces/{workspace_id}/runs",
        status_code=201,
    )
    def create_run(
        workspace_id: str,
        payload: RunCreateRequest,
        request: Request,
    ) -> dict[str, object]:
        account = current_account(request)
        require_csrf(request)
        workspace = owned_workspace(account, workspace_id)

        if runner is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    "agent execution is not connected; the model runtime "
                    "must be started first"
                ),
            )

        if runs_repository.get_active_run_for_workspace(
            workspace.workspace_id
        ) is not None:
            raise HTTPException(
                status_code=409,
                detail="an agent run is already active for this workspace",
            )

        # ROUTE BEFORE START: validate, resolve, and gate the actual model
        # target BEFORE creating a run or spawning any worker/model call.
        mode = (payload.requested_mode or "AUTO").strip().upper()
        if mode not in ("AUTO", "DEEPSEEK", "NEXT", "SOL"):
            raise HTTPException(
                status_code=400,
                detail="requested_mode must be AUTO, DEEPSEEK, NEXT, or SOL",
            )
        explicit_tier = None if mode == "AUTO" else ModelTier(mode)
        if explicit_tier in (ModelTier.NEXT, ModelTier.SOL):
            _require_owner(account)
        route = resolve_starting_route(
            requested_mode=mode,
            explicit_tier=explicit_tier,
            targets=_live_targets(),
            selector=_selector,
        )
        if mode in ("AUTO", "DEEPSEEK") and not route.target.availability:
            raise HTTPException(
                status_code=503,
                detail=(
                    "DeepSeek is not configured; AUTO cannot silently fall "
                    "back to another runtime"
                ),
            )
        if route.tier in (ModelTier.NEXT, ModelTier.SOL) and not route.target.availability:
            raise HTTPException(
                status_code=400,
                detail=f"{route.tier.value} is not currently configured",
            )

        # Create the run record, persist the selected routing, THEN start
        # execution using that exact route.
        run = runs_repository.create_run(
            workspace=workspace,
            prompt=payload.prompt,
        )
        runs_repository.set_run_routing(
            run.run_id,
            requested_mode=mode,
            selected_tier=route.tier.value,
            selected_model=route.target.model_id,
            selected_provider=route.target.provider,
            route_reason=(
                "OWNER_REQUESTED"
                if explicit_tier is not None
                else "AUTO_DEFAULT"
            ),
        )

        # ONLY NOW start execution on the persisted route.
        runner.start_existing(
            run_id=run.run_id,
            workspace=workspace,
            prompt=payload.prompt,
        )

        return {
            "run": _run_dict(run),
            "routing": runs_repository.get_run_routing(run.run_id).as_public_dict(),
        }

    @app.post("/v1/workspaces/{workspace_id}/runs/{run_id}/cancel")
    def cancel_run(
        workspace_id: str,
        run_id: str,
        request: Request,
    ) -> dict[str, object]:
        account = current_account(request)
        require_csrf(request)
        workspace = owned_workspace(account, workspace_id)
        parsed_run_id = UUID(run_id)
        detail = runs_repository.get_run(parsed_run_id)
        if detail is None or detail.workspace_id != workspace.workspace_id:
            raise HTTPException(status_code=404, detail="run not found")
        if detail.status not in ("queued", "running"):
            raise HTTPException(
                status_code=409,
                detail=f"run is already {detail.status}",
            )
        if runner is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    "agent execution is not connected; the model runtime "
                    "must be started first"
                ),
            )
        try:
            runner.cancel(parsed_run_id)
        except KeyError as error:
            raise HTTPException(
                status_code=409,
                detail=str(error),
            ) from None
        return {"cancelled": True}

    @app.get("/v1/workspaces/{workspace_id}/runs/{run_id}/routing")
    def get_run_routing(
        workspace_id: str,
        run_id: str,
        request: Request,
    ) -> dict[str, object]:
        account = current_account(request)
        _owned_run(account, workspace_id, run_id)
        routing = runs_repository.get_run_routing(UUID(run_id))
        return {
            "identity": PRODUCT_IDENTITY,
            "routing": routing.as_public_dict() if routing is not None else None,
            "targets": _resolve_targets_public(),
            "runtime": _runtime_adapter.runtime_status("defendcoder"),
        }

    @app.post("/v1/workspaces/{workspace_id}/runs/{run_id}/model")
    def select_run_model(
        workspace_id: str,
        run_id: str,
        payload: ModelSelectRequest,
        request: Request,
    ) -> dict[str, object]:
        account = current_account(request)
        _owned_run(account, workspace_id, run_id)
        mode = (payload.requested_mode or "AUTO").strip().upper()
        if mode not in ("AUTO", "DEEPSEEK", "NEXT", "SOL"):
            raise HTTPException(
                status_code=400,
                detail="requested_mode must be AUTO, DEEPSEEK, NEXT, or SOL",
            )
        explicit_tier = None if mode == "AUTO" else ModelTier(mode)
        if explicit_tier in (ModelTier.NEXT, ModelTier.SOL):
            _require_owner(account)
        route = resolve_starting_route(
            requested_mode=mode,
            explicit_tier=explicit_tier,
            targets=_live_targets(),
            selector=_selector,
        )
        if mode in ("AUTO", "DEEPSEEK") and not route.target.availability:
            raise HTTPException(
                status_code=503,
                detail=(
                    "DeepSeek is not configured; AUTO cannot silently fall "
                    "back to another runtime"
                ),
            )
        if route.tier in (ModelTier.NEXT, ModelTier.SOL) and not route.target.availability:
            raise HTTPException(
                status_code=400,
                detail=f"{route.tier.value} is not currently configured",
            )
        runtime = _runtime_adapter.runtime_status("defendcoder")
        next_step = None
        if route.tier == ModelTier.NEXT and route.target.requires_external_runtime:
            next_step = (
                "resume_approval_required"
                if runtime.get("state") != "ready"
                else "ready_reuse"
            )
        runs_repository.set_run_routing(
            UUID(run_id),
            requested_mode=mode,
            selected_tier=route.tier.value,
            selected_model=route.target.model_id,
            selected_provider=route.target.provider,
            route_reason=(
                "OWNER_REQUESTED" if explicit_tier is not None else "AUTO_DEFAULT"
            ),
        )
        return {
            "routing": runs_repository.get_run_routing(UUID(run_id)).as_public_dict(),
            "next_step": next_step,
        }

    @app.get("/v1/workspaces/{workspace_id}/runs/{run_id}/escalation")
    def get_run_escalation(
        workspace_id: str,
        run_id: str,
        request: Request,
    ) -> dict[str, object]:
        account = current_account(request)
        _owned_run(account, workspace_id, run_id)
        proposals = runs_repository.list_escalation_proposals(UUID(run_id))
        return {"proposals": proposals}

    @app.post(
        "/v1/workspaces/{workspace_id}/runs/{run_id}/escalation/"
        "{proposal_id}/approve"
    )
    def approve_run_escalation(
        workspace_id: str,
        run_id: str,
        proposal_id: str,
        request: Request,
    ) -> dict[str, object]:
        account = current_account(request)
        _require_owner(account)
        detail = _owned_run(account, workspace_id, run_id)
        proposals = runs_repository.list_escalation_proposals(UUID(run_id))
        proposal = next(
            (
                item
                for item in proposals
                if item["proposal_id"] == proposal_id
            ),
            None,
        )
        if proposal is None:
            raise HTTPException(status_code=404, detail="proposal not found")
        if proposal["status"] != "pending":
            raise HTTPException(status_code=409, detail="proposal is not pending")
        expires_at = proposal.get("expires_at")
        if expires_at is not None:
            try:
                parsed_expiry = datetime.fromisoformat(str(expires_at))
                if parsed_expiry.tzinfo is None:
                    parsed_expiry = parsed_expiry.replace(
                        tzinfo=timezone.utc
                    )
            except ValueError:
                parsed_expiry = None
            if parsed_expiry is not None and parsed_expiry < datetime.now(
                timezone.utc
            ):
                raise HTTPException(status_code=409, detail="proposal has expired")
        to_model = str(proposal["to_model"])
        try:
            to_tier = tier_for_model(to_model)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from None
        target = _target_for_model(to_model)
        if not target.availability:
            raise HTTPException(
                status_code=400,
                detail=f"{to_model} is not currently configured",
            )
        if to_tier == ModelTier.NEXT:
            runtime_state = _runtime_adapter.runtime_status("defendcoder")
            retained = bool(
                runtime_state.get("instance_id")
                or runtime_state.get("provider_instance_state")
                or runtime_state.get("gpu")
            )
            if runtime_state.get("state") == "ready":
                # Reuse the ready runtime.
                pass
            elif runtime_state.get("state") == "stopped" and retained:
                # Resume the retained instance (owner-authorized escalation).
                try:
                    _runtime_adapter.start_runtime(
                        "defendcoder", authorize_resume=True
                    )
                except RuntimeResumeDenied as error:
                    raise HTTPException(status_code=409, detail=str(error)) from None
            else:
                # No retained instance: "Approve stronger intelligence" does
                # NOT authorize renting unknown GPU at any price.
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "PRICE_CONFIRMATION_REQUIRED: no retained Next "
                        "instance; a new GPU rental requires explicit price "
                        "approval"
                    ),
                )
        now = datetime.now(timezone.utc)
        runs_repository.set_run_routing(
            UUID(run_id),
            requested_mode="AUTO",
            selected_tier=to_tier.value,
            selected_model=to_model,
            selected_provider=target.provider,
            route_reason=str(proposal["reason_code"]),
            escalated_from=str(proposal["from_model"]),
            escalation_approved_at=now,
            escalation_approved_by=account.username,
        )
        runs_repository.update_escalation_proposal_status(
            UUID(run_id),
            proposal_id,
            status="approved",
            approved_by=account.username,
            approved_at=now,
        )
        _resume_same_run(detail, workspace_id, run_id, account)
        return {
            "routing": runs_repository.get_run_routing(UUID(run_id)).as_public_dict(),
            "runtime": _runtime_adapter.runtime_status("defendcoder"),
            "state": "resuming",
        }

    @app.post(
        "/v1/workspaces/{workspace_id}/runs/{run_id}/escalation/"
        "{proposal_id}/deny"
    )
    def deny_run_escalation(
        workspace_id: str,
        run_id: str,
        proposal_id: str,
        request: Request,
    ) -> dict[str, object]:
        account = current_account(request)
        _require_owner(account)
        detail = _owned_run(account, workspace_id, run_id)
        proposals = runs_repository.list_escalation_proposals(UUID(run_id))
        if not any(item["proposal_id"] == proposal_id for item in proposals):
            raise HTTPException(status_code=404, detail="proposal not found")
        runs_repository.update_escalation_proposal_status(
            UUID(run_id),
            proposal_id,
            status="denied",
        )
        _resume_same_run(detail, workspace_id, run_id, account)
        return {"status": "denied", "state": "resuming", "unchanged": False}

    @app.get("/v1/admin/model-credentials")
    def model_credentials(request: Request) -> dict[str, object]:
        account = current_account(request)
        _require_owner(account)
        return {"providers": _credentials.status()}

    @app.post("/v1/admin/model-credentials/{provider}")
    def set_model_credential(
        provider: str,
        payload: CredentialRequest,
        request: Request,
    ) -> dict[str, object]:
        account = current_account(request)
        _require_owner(account)
        require_csrf(request)
        try:
            _credentials.set(provider, payload.api_key)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from None
        except RuntimeError as error:
            raise HTTPException(status_code=503, detail=str(error)) from None
        # Availability is dynamic: no restart required.
        return {
            "provider": provider,
            "configured": _credentials.configured(provider),
        }

    @app.post("/v1/chat", status_code=200)
    def chat_without_workspace(
        payload: ChatRequest,
        request: Request,
    ) -> dict[str, object]:
        account = current_account(request)
        require_csrf(request)
        if not _credentials.configured("deepseek"):
            raise HTTPException(
                status_code=503,
                detail=(
                    "DeepSeek is not configured; workspace-less chat is "
                    "unavailable until DEEPSEEK_API_KEY is set"
                ),
            )
        deepseek = next(
            target
            for target in _live_targets().values()
            if target.tier == "DEEPSEEK"
        )
        try:
            client = build_client(
                deepseek,
                api_key=_credentials.resolve("deepseek"),
            )
        except ValueError as error:
            raise HTTPException(status_code=503, detail=str(error)) from None
        from defend_coder.agent import CodingAgent
        from defend_coder.tools import CoderToolkit as _CoderToolkit

        toolkit = _CoderToolkit(
            repository=repository,
            configured_root=(
                configured_root if configured_root is not None else settings.workspace_root
            ),
            enabled=False,
        )
        agent = CodingAgent(
            client=client,
            toolkit=toolkit,
            max_steps=4,
            max_loop_seconds=120.0,
            identity_profile=default_identity_profile(),
        )
        replies: list[str] = []

        def sink(**fields: object) -> None:
            if fields.get("role") == "assistant" and fields.get("content"):
                replies.append(str(fields["content"]))

        outcome = agent.run(
            prompt=payload.message,
            account_id=account.account_id,
            workspace_id=None,  # type: ignore[arg-type]
            sink=sink,
        )
        if outcome.state != "succeeded" or not replies:
            raise HTTPException(
                status_code=502,
                detail=f"chat generation failed ({outcome.reason or outcome.state})",
            )
        return {
            "reply": "\n".join(replies),
            "model": deepseek.model_id,
            "provider": deepseek.provider,
            "tier": "DEEPSEEK",
            "requested_mode": "AUTO",
        }

    @app.get("/v1/workspaces/{workspace_id}/runs")
    def list_runs(
        workspace_id: str,
        request: Request,
        limit: int = 50,
    ) -> dict[str, object]:
        account = current_account(request)
        workspace = owned_workspace(account, workspace_id)

        runs = runs_repository.list_runs_for_workspace(
            workspace.workspace_id,
            limit=limit,
        )

        return {
            "runs": [_run_dict(run) for run in runs]
        }

    @app.get("/v1/agent/policy")
    def agent_policy(request: Request) -> dict[str, object]:
        """Effective step/finalization/wall-clock/model policy (P3).

        Session-authenticated; contains no secrets. Useful for
        benchmarks and runtime diagnostics."""
        current_account(request)
        if runner is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    "agent execution is not connected; the model runtime "
                    "must be started first"
                ),
            )
        return {"policy": runner.policy}

    @app.get("/v1/workspaces/{workspace_id}/runs/{run_id}")
    def get_run(
        workspace_id: str,
        run_id: str,
        request: Request,
    ) -> dict[str, object]:
        account = current_account(request)
        detail = owned_run(account, workspace_id, run_id)

        return {
            "run": _run_dict(detail.run),
            "messages": [
                _message_dict(message)
                for message in detail.messages
            ],
        }

    @app.get("/v1/workspaces/{workspace_id}/files")
    def list_files(
        workspace_id: str,
        request: Request,
        path: str = ".",
    ) -> dict[str, object]:
        account = current_account(request)
        workspace = owned_workspace(account, workspace_id)

        try:
            target = workspace_service.resolve_owned_path(
                account.account_id,
                workspace.workspace_id,
                path,
            )
        except WorkspaceAccessError as error:
            raise HTTPException(
                status_code=400,
                detail=str(error),
            ) from None

        if target.is_file():
            return {
                "path": str(path),
                "kind": "file",
                "name": target.name,
            }

        if not target.is_dir():
            raise HTTPException(
                status_code=404,
                detail="path not found",
            )

        entries = []
        try:
            children = sorted(
                target.iterdir(),
                key=lambda entry: (
                    not entry.is_dir(),
                    entry.name.casefold(),
                ),
            )
        except OSError as error:
            raise HTTPException(
                status_code=500,
                detail="could not read directory",
            ) from error

        for entry in children:
            if entry.name in {
                ".git",
                "node_modules",
                ".next",
                "__pycache__",
                ".venv",
                "venv",
            }:
                continue
            try:
                is_dir = entry.is_dir()
            except OSError:
                continue
            entries.append(
                {
                    "name": entry.name,
                    "type": "directory" if is_dir else "file",
                }
            )

        return {
            "path": str(path),
            "kind": "directory",
            "entries": entries,
        }

    return app


def run_idle_cycle(
    auth: AuthService,
    runtime_stop_callback: Callable[[str], None] | None,
    *,
    idle_timeout: timedelta,
    now: datetime | None = None,
) -> tuple[tuple[str, str], ...]:
    """One server-authoritative idle-policy cycle (sync, testable).

    Revokes consumer sessions idle past ``idle_timeout`` and — when wired —
    asks the runtime owner to stop the billable runtime for each revoked
    session. Returns (session_id, account_id) pairs.
    """
    revoked = auth.revoke_idle_sessions(
        now=now,
        idle_timeout=idle_timeout,
    )

    if runtime_stop_callback is not None:
        for session_id, _account_id in revoked:
            try:
                runtime_stop_callback(str(session_id))
            except Exception:
                continue

    return tuple(
        (str(session_id), str(account_id))
        for session_id, account_id in revoked
    )
