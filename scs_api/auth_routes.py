from __future__ import annotations

import sqlite3
from collections import defaultdict, deque
from time import monotonic
from typing import Any

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from scs_data.identity import EmployeeRecord, ScsIdentityStore
from scs_data.authorization import ScsAuthorizer, ScsPrincipal
from scs_data.mailer import invitation_activation_url
from shared_platform.application import ApplicationContext


class LoginInput(BaseModel):
    identifier: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class ActivationInput(BaseModel):
    token: str = Field(min_length=1, max_length=512)
    username: str = Field(min_length=2, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=1024)


class InvitationInput(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=160)
    roles: list[str] = Field(min_length=1, max_length=6)


def _employee(employee: EmployeeRecord, identity: ScsIdentityStore) -> dict[str, Any]:
    principal = ScsPrincipal(employee.employee_id, employee.roles, identity.current_functions(employee.employee_id), employee.status)
    return {
        "employee_id": employee.employee_id,
        "email": employee.email,
        "username": employee.username,
        "display_name": employee.display_name,
        "status": employee.status,
        "roles": list(employee.roles),
        "permissions": sorted(value.value for value in ScsAuthorizer().permissions(principal)),
    }


def build_auth_router(context: ApplicationContext, identity: ScsIdentityStore, mailer: Any) -> APIRouter:
    if context.application_id != "scs":
        raise ValueError("SCS auth router requires SCS context")
    router = APIRouter(prefix="/api/scs")
    cookie_name = context.session_cookie
    attempts: dict[str, deque[float]] = defaultdict(deque)

    def current_employee(request: Request) -> EmployeeRecord:
        raw = request.cookies.get(cookie_name)
        employee = identity.resolve_session(raw) if raw else None
        if employee is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        return employee

    def manager(employee: EmployeeRecord = Depends(current_employee)) -> EmployeeRecord:
        if not {"owner", "operations_admin"}.intersection(employee.roles):
            raise HTTPException(status_code=403, detail="Permission denied")
        return employee

    @router.post("/auth/login")
    def login(body: LoginInput, response: Response, request: Request):
        key = f"{request.client.host if request.client else 'unknown'}:{body.identifier.strip().casefold()}"
        now = monotonic(); window = attempts[key]
        while window and window[0] < now - 60: window.popleft()
        if len(window) >= 10:
            raise HTTPException(status_code=429, detail="Invalid credentials")
        employee = identity.authenticate(body.identifier, body.password)
        if employee is None:
            window.append(now)
            identity.audit.append(None, "auth.login_failed", "employee", None)
            raise HTTPException(status_code=401, detail="Invalid credentials")
        raw = identity.create_session(employee.employee_id)
        response.set_cookie(cookie_name, raw, secure=True, httponly=True, samesite="lax", path="/")
        identity.audit.append(employee.employee_id, "auth.login_succeeded", "employee", employee.employee_id)
        attempts.pop(key, None)
        return {"employee": _employee(employee, identity)}

    @router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
    def logout(request: Request, response: Response):
        raw = request.cookies.get(cookie_name)
        if raw:
            identity.revoke_session(raw)
        response.delete_cookie(cookie_name, secure=True, httponly=True, samesite="lax", path="/")

    @router.get("/auth/session")
    def session(employee: EmployeeRecord = Depends(current_employee)):
        return {"employee": _employee(employee, identity)}

    @router.post("/auth/activate")
    def activate(body: ActivationInput):
        try:
            employee = identity.activate_invitation(body.token, username=body.username, password=body.password)
        except (KeyError, ValueError, sqlite3.IntegrityError):
            raise HTTPException(status_code=400, detail="Invalid or expired invitation") from None
        return {"employee": _employee(employee, identity)}

    def deliver(invitation, raw_token: str) -> dict[str, Any]:
        url = invitation_activation_url(context.public_origin, raw_token)
        result = mailer.send_invitation(invitation.email, url)
        output = {"invitation_id": invitation.invitation_id, "delivery": result.status}
        if not result.ok:
            output["manual_activation_url"] = url
        return output

    @router.post("/admin/invitations", status_code=status.HTTP_201_CREATED)
    def invite(body: InvitationInput, employee: EmployeeRecord = Depends(manager)):
        try:
            invitation, raw = identity.invite_employee(
                employee.employee_id, body.email, body.display_name, tuple(body.roles)
            )
        except PermissionError:
            raise HTTPException(status_code=403, detail="Permission denied") from None
        except (ValueError, sqlite3.IntegrityError):
            raise HTTPException(status_code=400, detail="Invitation could not be created") from None
        return deliver(invitation, raw)

    @router.post("/admin/invitations/{invitation_id}/retry")
    def retry(invitation_id: str, employee: EmployeeRecord = Depends(manager)):
        try:
            invitation, raw = identity.regenerate_invitation(employee.employee_id, invitation_id)
        except (KeyError, ValueError):
            raise HTTPException(status_code=400, detail="Invitation is not retryable") from None
        return deliver(invitation, raw)

    @router.post("/admin/invitations/{invitation_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
    def revoke(invitation_id: str, employee: EmployeeRecord = Depends(manager)):
        if not identity.revoke_invitation(employee.employee_id, invitation_id):
            raise HTTPException(status_code=404, detail="Invitation not found")

    return router
