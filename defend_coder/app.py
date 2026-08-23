from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import secrets
import subprocess
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
from .lifecycle import (
    EnvelopeValidationError,
    NotResumableError,
    RecoveryRequiredError,
    RunConflictError,
    RunLifecycleError,
    RunLifecycleService,
)
from .preparation import RunPreparationService
from .tool_ledger import ToolLedgerError
from .provider_adapters import CoderProviderFactory
from .providers import (
    NEXT_MODEL,
    SOL_MODEL,
    ModelTarget,
    build_client,
    deepseek_target,
    next_target,
    sol_target,
)
from .registry import (
    IdentityRegistry,
    PromptAuthorityComposer,
    PromptBundleRegistry,
    ProviderTechnicalRegistry,
    build_prompt_core_bundle,
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


class RecoveryRequest(BaseModel):
    resolution: str = Field(min_length=1, max_length=64)
    note: str | None = Field(default=None, max_length=2000)


def _default_secret_store() -> object:
    """Platform DPAPI secret store loader (defendcoder product)."""
    from pathlib import Path as _Path

    from shared_platform.dpapi import DpapiSecretStore

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


def _git_snapshot(root: Path) -> dict[str, object]:
    """Read-only git truth from the workspace root.

    Distinguishes unstaged/staged/untracked/conflict state server-side so the
    UI never fabricates a changed-file list. Diffs are bounded with explicit
    truncation flags.
    """
    if not (root / ".git").exists():
        return {
            "is_repo": False,
            "status": "",
            "unstaged_diff": "",
            "staged_diff": "",
            "untracked": [],
            "conflicts": [],
            "dirty": False,
        }

    def _run(args: list[str]) -> str | None:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=str(root),
                capture_output=True,
                text=True,
                errors="replace",
                timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
        if result.returncode != 0:
            return None
        return result.stdout

    short = _run(["status", "--porcelain"]) or ""
    lines = [ln for ln in short.splitlines() if ln.strip()]

    untracked: list[str] = []
    conflicts: list[str] = []
    staged_count = 0
    unstaged_count = 0
    for line in lines:
        x = line[:1]
        y = line[1:2]
        path = line[3:].strip()
        if x == "?" and y == "?":
            untracked.append(path)
            continue
        # Conflict markers: U in either column, or AA/DD.
        if x == "U" or y == "U" or (x == "A" and y == "A") or (x == "D" and y == "D"):
            conflicts.append(path)
        if x not in (" ", "?"):
            staged_count += 1
        if y not in (" ", "?"):
            unstaged_count += 1

    unstaged = _run(["diff"]) or ""
    staged = _run(["diff", "--cached"]) or ""
    unstaged_truncated = len(unstaged) > 64 * 1024
    staged_truncated = len(staged) > 64 * 1024

    return {
        "is_repo": True,
        "status": short,
        "unstaged_diff": unstaged[: 64 * 1024],
        "staged_diff": staged[: 64 * 1024],
        "unstaged_diff_truncated": unstaged_truncated,
        "staged_diff_truncated": staged_truncated,
        "untracked": untracked,
        "conflicts": conflicts,
        "staged_count": staged_count,
        "unstaged_count": unstaged_count,
        "dirty": bool(lines),
    }


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
    runtime_manager: object | None = None,
    model_selector: ModelSelector | None = None,
    identity_registry: IdentityRegistry | None = None,
    prompt_registry: PromptBundleRegistry | None = None,
    prompt_authority: PromptAuthorityComposer | None = None,
    provider_factory: object | None = None,
    technical_registry: object | None = None,
    preparation: object | None = None,
    attempt_store: object | None = None,
    checkpoint_store: object | None = None,
    tool_ledger: object | None = None,
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
                # Product-owned runtime idle authority: STOP/RETAIN (never
                # destroy) via the product runtime manager.
                if _runtime_manager is not None:
                    _runtime_manager.maybe_reap_idle()
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
    # Runtime authority: the concrete product manager is the production
    # authority. ProductRuntimeAdapterBoundary is a deterministic TEST fake and
    # is used only when a test explicitly injects it; the production default
    # is the fail-closed concrete manager (never manufactures READY).
    if runtime_manager is not None:
        _runtime_manager = runtime_manager
    elif runtime_adapter is not None:
        _runtime_manager = runtime_adapter
    else:
        from .runtime_manager import CoderRuntimeManager

        _runtime_manager = CoderRuntimeManager()
    _selector = model_selector or ModelSelector()
    _identity_registry = identity_registry or IdentityRegistry()
    if _identity_registry.active_key is None:
        _identity_registry.activate(default_identity_profile())
    _prompt_authority = prompt_authority or PromptAuthorityComposer()
    _prompt_registry = prompt_registry or PromptBundleRegistry()
    if _prompt_registry.active_key is None:
        _prompt_registry.activate(
            build_prompt_core_bundle(
                _identity_registry.active(),
                _prompt_authority,
            )
        )
    _provider_factory = provider_factory or CoderProviderFactory(_credentials)
    _technical_registry = technical_registry or ProviderTechnicalRegistry()
    _preparation = preparation or RunPreparationService(db)
    _attempt_store = attempt_store
    _checkpoint_store = checkpoint_store
    _tool_ledger = tool_ledger
    _lifecycle = RunLifecycleService(
        runs=runs_repository,
        preparation=_preparation,
        tool_ledger=_tool_ledger,
        runner=runner,
    )

    def _live_targets() -> dict[str, ModelTarget]:
        """Targets keyed by MODEL ID with LIVE availability.

        DeepSeek/Sol availability comes from credentials. NEXT availability
        comes from the product runtime manager (fail-closed): READY only when
        the manager reports a concrete healthy intended endpoint, never
        hardcoded True.
        """
        deepseek = deepseek_target(
            availability=_credentials.configured("deepseek")
        )
        return {
            deepseek.model_id: deepseek,
            NEXT_MODEL: next_target(
                availability=_runtime_manager.next_availability(),
                endpoint=_runtime_manager.get_runtime_endpoint(),
            ),
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

    def _require_actionable(run: object) -> None:
        """Reject routing/mutation on a non-actionable (terminal) run.

        A historical/terminal run must not become mutable merely because it
        was opened in the UI; routing mutation is legal only for actionable
        run states (queued/running/resumable failed/partial).
        """
        if getattr(run, "status", None) in ("succeeded", "cancelled"):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"run is {run.status}; routing mutation is not allowed "
                    "on a terminal run"
                ),
            )

    def _owner_runtime_status() -> dict[str, object]:
        """Sanitized owner/admin runtime view (no secrets)."""
        if _runtime_manager is None:
            return {"state": "UNKNOWN"}
        status = _runtime_manager.runtime_status()
        return {
            "state": status.get("state"),
            "model": status.get("model"),
            "provider": status.get("provider"),
            "instance_id": status.get("instance_id"),
            "gpu": status.get("gpu"),
            "hourly_cost": status.get("hourly_cost"),
            "endpoint": status.get("endpoint"),
            "runtime_ready": _runtime_manager.runtime_ready(),
            "routing_available": _runtime_manager.routing_available(),
            "model_selectable": _runtime_manager.model_selectable(),
            "runtime_resumable": _runtime_manager.runtime_resumable(),
        }

    def _resume_same_run(
        detail: RunDetail,
        workspace_id: str,
        run_id: str,
        account: AuthenticatedAccount,
    ) -> None:
        """Continue the SAME run after an owner escalation choice.

        Persists route change first (done by the caller), then re-dispatches
        the worker through the single authoritative lifecycle (reconcile ->
        recovery-eval -> authority validation -> atomic claim -> dispatch).
        """
        workspace = owned_workspace(account, workspace_id)
        runs_repository.update_run_phase(UUID(run_id), "resuming")
        _lifecycle.start(
            run_id=UUID(run_id),
            workspace=workspace,
            account_id=account.account_id,
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

        # Filesystem authority: consumers get a server-authoritative root;
        # admins may select a root only inside the configured admin root.
        if account.role == "admin":
            try:
                root = workspace_service.validate_admin_root(
                    payload.workspace_root
                )
            except WorkspaceAccessError as error:
                raise HTTPException(status_code=400, detail=str(error)) from None
        else:
            root = workspace_service.allocate_consumer_root(
                account.account_id,
                payload.name,
            )

        workspace = repository.create_workspace(
            owner_account_id=account.account_id,
            name=payload.name,
            workspace_root=root,
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

        # Server-authoritative pins: derive identity/prompt/technical from
        # durable ACTIVE authority + selected route. The client only supplies
        # intent (workspace, prompt, requested mode); it can never supply
        # authority hashes.
        identity = _identity_registry.active()
        bundle = _prompt_registry.active()
        technical = _technical_registry.active_for_provider(
            route.target.provider
        )
        try:
            prepared = _preparation.prepare_run(
                workspace_id=workspace.workspace_id,
                owner_account_id=account.account_id,
                prompt=payload.prompt,
                requested_mode=mode,
                selected_tier=route.tier.value,
                provider=route.target.provider,
                model=route.target.model_id,
                identity=(
                    identity.profile_id,
                    identity.version,
                    identity.hash,
                ),
                prompt_core=(bundle.bundle_id, bundle.version, bundle.hash),
                technical=(
                    technical.profile_id,
                    technical.version,
                    technical.hash,
                ),
                reason=(
                    "OWNER_REQUESTED"
                    if explicit_tier is not None
                    else "AUTO_DEFAULT"
                ),
            )
        except Exception as error:  # noqa: BLE001
            raise HTTPException(
                status_code=500,
                detail=f"run preparation failed: {type(error).__name__}",
            ) from None

        # ONLY NOW start execution through the single authoritative lifecycle
        # (reconcile -> recovery-eval -> authority validation -> atomic claim
        # -> dispatch). The prepare_run INSERT already atomically reserved the
        # workspace's execution authority (partial unique index).
        try:
            _lifecycle.start(
                run_id=prepared.run_id,
                workspace=workspace,
                account_id=account.account_id,
            )
        except RunLifecycleError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None

        run = runs_repository.get_run(prepared.run_id)
        return {
            "run": _run_dict(run),
            "routing": runs_repository.get_run_routing(
                prepared.run_id
            ).as_public_dict(),
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

    @app.post("/v1/workspaces/{workspace_id}/runs/{run_id}/resume")
    def resume_run(
        workspace_id: str,
        run_id: str,
        request: Request,
    ) -> dict[str, object]:
        account = current_account(request)
        require_csrf(request)
        workspace = owned_workspace(account, workspace_id)
        parsed_run_id = UUID(run_id)
        if runner is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    "agent execution is not connected; the model runtime "
                    "must be started first"
                ),
            )
        # Single authoritative resume flow: reconcile -> recovery-eval ->
        # authority validation -> atomic claim -> dispatch. Recovery and
        # resumability gates are enforced here (fail closed, no worker on
        # any failure).
        try:
            result = _lifecycle.start(
                run_id=parsed_run_id,
                workspace=workspace,
                account_id=account.account_id,
            )
        except RecoveryRequiredError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
        except NotResumableError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
        except RunConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
        except EnvelopeValidationError as error:
            raise HTTPException(status_code=403, detail=str(error)) from None
        except RunLifecycleError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
        run = runs_repository.get_run(parsed_run_id)
        return {"run": _run_dict(run), "resumed": result.resumed}

    @app.post(
        "/v1/workspaces/{workspace_id}/runs/{run_id}/recovery/"
        "{execution_id}/resolve"
    )
    def resolve_recovery(
        workspace_id: str,
        run_id: str,
        execution_id: str,
        payload: RecoveryRequest,
        request: Request,
    ) -> dict[str, object]:
        account = current_account(request)
        require_csrf(request)
        workspace = owned_workspace(account, workspace_id)
        parsed_run_id = UUID(run_id)
        run = runs_repository.get_run(parsed_run_id)
        if run is None or run.workspace_id != workspace.workspace_id:
            raise HTTPException(status_code=404, detail="run not found")
        if _tool_ledger is None:
            raise HTTPException(
                status_code=503,
                detail="tool ledger is not connected",
            )
        resolution = payload.resolution.strip().upper()
        executions = _tool_ledger.list_for_run(parsed_run_id)
        target = next(
            (e for e in executions if str(e.execution_id) == execution_id),
            None,
        )
        if target is None:
            raise HTTPException(status_code=404, detail="execution not found")
        try:
            resulting = _tool_ledger.resolve_recovery(
                run_id=parsed_run_id,
                execution_id=target.execution_id,
                tool_call_id=target.tool_call_id,
                tool_name=target.tool_name,
                owner_account_id=account.account_id,
                resolution=resolution,
                note=payload.note,
            )
        except ToolLedgerError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
        if resolution == "ABANDON_RUN":
            runs_repository.update_run_status(
                parsed_run_id,
                status="cancelled",
                error="abandoned after UNKNOWN_AFTER_INTERRUPTION recovery",
                reason="user_cancel",
            )
        return {
            "execution_id": execution_id,
            "resolution": resolution,
            "resulting_state": resulting,
        }

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
            "runtime": _runtime_manager.runtime_status("defendcoder"),
        }

    @app.post("/v1/workspaces/{workspace_id}/runs/{run_id}/model")
    def select_run_model(
        workspace_id: str,
        run_id: str,
        payload: ModelSelectRequest,
        request: Request,
    ) -> dict[str, object]:
        account = current_account(request)
        require_csrf(request)
        detail = _owned_run(account, workspace_id, run_id)
        _require_actionable(detail)
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
        runtime = _runtime_manager.runtime_status("defendcoder")
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
        require_csrf(request)
        _require_owner(account)
        detail = _owned_run(account, workspace_id, run_id)
        _require_actionable(detail)
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
            runtime_state = _runtime_manager.runtime_status("defendcoder")
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
                    _runtime_manager.start_runtime(
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
            "runtime": _runtime_manager.runtime_status("defendcoder"),
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
        require_csrf(request)
        _require_owner(account)
        detail = _owned_run(account, workspace_id, run_id)
        _require_actionable(detail)
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

    # ---- Owner runtime authority (admin-only, CSRF on mutations) ----

    @app.get("/v1/admin/runtime")
    def admin_runtime_status(request: Request) -> dict[str, object]:
        account = current_account(request)
        _require_owner(account)
        return _owner_runtime_status()

    @app.post("/v1/admin/runtime/plan")
    def admin_runtime_plan(request: Request) -> dict[str, object]:
        account = current_account(request)
        _require_owner(account)
        require_csrf(request)
        if _runtime_manager is None or _runtime_manager._control_plane is None:
            return {"state": "PROVIDER_NOT_CONFIGURED", "plan": None}
        try:
            plan = _runtime_manager.plan_runtime()
        except Exception as error:  # noqa: BLE001
            return {"state": "PROVIDER_NOT_CONFIGURED", "plan": None, "detail": str(error)}
        public = plan.as_public_dict() if hasattr(plan, "as_public_dict") else {"alias": getattr(plan, "alias", None)}
        return {"state": "PLANNED", "plan": public}

    @app.post("/v1/admin/runtime/resume")
    def admin_runtime_resume(request: Request) -> dict[str, object]:
        account = current_account(request)
        _require_owner(account)
        require_csrf(request)
        try:
            result = _runtime_manager.resume_retained(authorize_resume=True)
        except Exception as error:  # noqa: BLE001
            raise HTTPException(status_code=409, detail=str(error)) from None
        return {"state": "RESUMING", "detail": result}

    @app.post("/v1/admin/runtime/stop-retain")
    def admin_runtime_stop_retain(request: Request) -> dict[str, object]:
        account = current_account(request)
        _require_owner(account)
        require_csrf(request)
        result = _runtime_manager.stop_runtime()
        return {"state": result.get("state"), "retained": result.get("retained")}

    @app.post("/v1/admin/runtime/destroy")
    def admin_runtime_destroy(
        request: Request,
        instance_id: int,
    ) -> dict[str, object]:
        account = current_account(request)
        _require_owner(account)
        require_csrf(request)
        try:
            result = _runtime_manager.destroy_exact(instance_id=instance_id)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
        except Exception as error:  # noqa: BLE001
            raise HTTPException(status_code=409, detail=str(error)) from None
        return {"state": "DESTROYING", "detail": result}

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
        from defend_coder.providers import DEFAULT_DEEPSEEK_MODEL

        deepseek_model = DEFAULT_DEEPSEEK_MODEL
        try:
            provider = _provider_factory.for_model(deepseek_model)
        except Exception as error:  # noqa: BLE001
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
            provider=provider,
            toolkit=toolkit,
            max_steps=4,
            max_loop_seconds=120.0,
            system_authority=_prompt_authority.compose(
                _identity_registry.active(), provider="deepseek"
            ),
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
            "model": provider.model_id,
            "provider": provider.provider_id,
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

    @app.get("/v1/workspaces/{workspace_id}/runs/{run_id}/attempts")
    def run_attempts(workspace_id: str, run_id: str, request: Request):
        account = current_account(request)
        owned_run(account, workspace_id, run_id)
        if _attempt_store is None:
            return {"attempts": []}
        attempts = _attempt_store.list(UUID(run_id))
        return {
            "attempts": [
                {
                    "attempt_id": str(a.attempt_id),
                    "checkpoint_revision": a.checkpoint_revision,
                    "summary": a.summary,
                    "failure_class": a.failure_class,
                    "relevant_files": list(a.relevant_files),
                    "test_summary": a.test_summary,
                    "tool_refs": list(a.tool_refs),
                    "state": a.state,
                }
                for a in attempts
            ]
        }

    @app.get("/v1/workspaces/{workspace_id}/runs/{run_id}/checkpoints")
    def run_checkpoints(workspace_id: str, run_id: str, request: Request):
        account = current_account(request)
        owned_run(account, workspace_id, run_id)
        if _checkpoint_store is None:
            return {"checkpoints": []}
        checkpoints = _checkpoint_store.list(UUID(run_id))
        return {
            "checkpoints": [
                {
                    "checkpoint_id": str(c.checkpoint_id),
                    "revision": c.revision,
                    "objective": c.objective,
                    "current_task": c.current_task,
                    "completed_work": list(c.completed_work),
                    "current_failure": c.current_failure,
                    "relevant_files": list(c.relevant_files),
                    "latest_tests": list(c.latest_tests),
                    "provider": c.provider,
                    "model": c.model,
                    "identity_version": c.identity_version,
                    "prompt_core_version": c.prompt_core_version,
                    "technical_profile_version": c.technical_profile_version,
                }
                for c in checkpoints
            ]
        }

    @app.get("/v1/workspaces/{workspace_id}/runs/{run_id}/tool-executions")
    def run_tool_executions(workspace_id: str, run_id: str, request: Request):
        account = current_account(request)
        owned_run(account, workspace_id, run_id)
        if _tool_ledger is None:
            return {"tool_executions": []}
        executions = _tool_ledger.list_for_run(UUID(run_id))
        return {
            "tool_executions": [
                {
                    "execution_id": str(e.execution_id),
                    "tool_call_id": e.tool_call_id,
                    "tool_name": e.tool_name,
                    "argument_hash": e.argument_hash,
                    "mutation_class": e.mutation_class,
                    "state": e.state,
                    "result_ref": e.result_ref,
                    "started_at": (
                        e.started_at.isoformat()
                        if e.started_at is not None
                        else None
                    ),
                    "finished_at": (
                        e.finished_at.isoformat()
                        if e.finished_at is not None
                        else None
                    ),
                }
                for e in executions
            ]
        }

    @app.get("/v1/workspaces/{workspace_id}/runs/{run_id}/telemetry")
    def run_telemetry(workspace_id: str, run_id: str, request: Request):
        account = current_account(request)
        owned_run(account, workspace_id, run_id)
        calls = runs_repository.model_calls_for_run(UUID(run_id))
        aggregated = runs_repository.aggregate_model_calls(UUID(run_id))
        return {
            "aggregate": aggregated,
            "model_calls": [
                {
                    "step": c.step,
                    "phase": c.phase,
                    "input_tokens": c.input_tokens,
                    "output_tokens": c.output_tokens,
                    "total_tokens": c.total_tokens,
                    "finish_reason": c.finish_reason,
                    "tool_calls_requested": c.tool_calls_requested,
                    "request_roundtrip_seconds": c.request_roundtrip_seconds,
                    "tokens_per_second": c.tokens_per_second,
                }
                for c in calls
            ],
        }

    @app.get("/v1/workspaces/{workspace_id}/files/content")
    def file_content(
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

        if not target.is_file():
            raise HTTPException(
                status_code=400,
                detail="path is not a file",
            )
        if target.stat().st_size > 256 * 1024:
            raise HTTPException(
                status_code=413,
                detail="file too large to display",
            )
        try:
            data = target.read_bytes()
        except OSError as error:
            raise HTTPException(
                status_code=500,
                detail="could not read file",
            ) from error
        if b"\x00" in data[:8192]:
            return {
                "path": str(path),
                "binary": True,
                "content": None,
                "size": len(data),
            }
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError:
            return {
                "path": str(path),
                "binary": True,
                "content": None,
                "size": len(data),
            }
        return {
            "path": str(path),
            "binary": False,
            "content": content,
            "size": len(data),
        }

    @app.get("/v1/workspaces/{workspace_id}/git/status")
    def git_status(workspace_id: str, request: Request) -> dict[str, object]:
        account = current_account(request)
        workspace = owned_workspace(account, workspace_id)
        root = workspace_service.resolve_owned_path(
            account.account_id, workspace.workspace_id, "."
        )
        return _git_snapshot(root)

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
