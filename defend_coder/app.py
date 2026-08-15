from __future__ import annotations

import secrets
from typing import Callable

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .auth import (
    AuthError,
    AuthService,
    AuthenticatedAccount,
)
from .config import CoderSettings
from .db import CoderDatabase
from .repositories import CoderRepository


SESSION_COOKIE = "defendcoder_session"
CSRF_COOKIE = "defendcoder_csrf"


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1)
    role: str


class WorkspaceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    workspace_root: str = Field(min_length=1)
    repository_url: str | None = None
    default_branch: str | None = None


def _account_dict(account: AuthenticatedAccount) -> dict[str, object]:
    return {
        "account_id": str(account.account_id),
        "username": account.username,
        "email": account.email,
        "role": account.role,
        "is_active": account.is_active,
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


def build_coder_app(
    *,
    settings: CoderSettings,
    db: CoderDatabase,
    auth: AuthService,
    runtime_status: Callable[[], dict[str, object]],
) -> FastAPI:
    app = FastAPI(
        title="DEFENDcoder API",
        version="1.0",
        docs_url=None,
        redoc_url=None,
    )

    repository = CoderRepository(db)

    def current_account(request: Request) -> AuthenticatedAccount:
        token = request.cookies.get(SESSION_COOKIE)

        if not token:
            raise HTTPException(
                status_code=401,
                detail="invalid session",
            )

        try:
            return auth.authenticate_session(token)
        except AuthError:
            raise HTTPException(
                status_code=401,
                detail="invalid session",
            ) from None

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

    return app
