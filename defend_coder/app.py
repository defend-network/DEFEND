from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
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
from .db import CoderDatabase
from .repositories import CoderRepository, WorkspaceRecord
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

        try:
            run = runner.start(
                workspace=workspace,
                prompt=payload.prompt,
            )
        except RunConflictError as error:
            raise HTTPException(
                status_code=409,
                detail=str(error),
            ) from None

        return {"run": _run_dict(run)}

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
