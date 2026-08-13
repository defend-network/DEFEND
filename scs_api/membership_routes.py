from __future__ import annotations

from dataclasses import asdict
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from scs_data.authorization import Permission, ScsAuthorizer, ScsPrincipal
from scs_data.identity import EmployeeRecord, ScsIdentityStore
from scs_data.memberships import ScsMembershipStore
from shared_platform.application import ApplicationContext


class EnrollmentInput(BaseModel):
    customer_id: str = Field(min_length=1)
    plan_code: str = Field(min_length=1)
    start_date: date
    end_date: date | None = None
    covered_site_ids: tuple[str, ...] = ()
    covered_equipment_ids: tuple[str, ...] = ()


def build_membership_router(
    context: ApplicationContext,
    identity: ScsIdentityStore,
    memberships: ScsMembershipStore,
) -> APIRouter:
    router = APIRouter(prefix="/api/scs/memberships")
    authorizer = ScsAuthorizer()

    def require_editor(request: Request) -> EmployeeRecord:
        raw = request.cookies.get(context.session_cookie)
        employee = identity.resolve_session(raw) if raw else None
        if employee is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        principal = ScsPrincipal(
            employee.employee_id,
            employee.roles,
            identity.current_functions(employee.employee_id),
            employee.status,
        )
        try:
            authorizer.require(principal, Permission.EDIT_CUSTOMERS)
        except PermissionError:
            raise HTTPException(status_code=403, detail="Permission denied") from None
        return employee

    @router.post("/enrollments", status_code=status.HTTP_201_CREATED)
    def enroll(body: EnrollmentInput, employee=Depends(require_editor)):
        try:
            enrollment = memberships.enroll(
                employee.employee_id,
                body.customer_id,
                body.plan_code,
                start_date=body.start_date,
                end_date=body.end_date,
                covered_site_ids=body.covered_site_ids,
                covered_equipment_ids=body.covered_equipment_ids,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from None
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from None
        return asdict(enrollment)

    return router
