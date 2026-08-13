from __future__ import annotations

from dataclasses import asdict
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from scs_data.authorization import Permission, ScsAuthorizer, ScsPrincipal
from scs_data.identity import EmployeeRecord, ScsIdentityStore
from shared_platform.application import ApplicationContext

class RolesInput(BaseModel): roles: tuple[str, ...] = Field(min_length=1)
class FunctionInput(BaseModel): function_code: str
class LevelInput(BaseModel): level_code: str
class EmployeeStatusInput(BaseModel): status: str

def build_employee_router(context: ApplicationContext, identity: ScsIdentityStore) -> APIRouter:
    router = APIRouter(prefix="/api/scs/admin/employees"); authorizer = ScsAuthorizer()
    def require(permission: Permission):
        def dep(request: Request) -> EmployeeRecord:
            raw=request.cookies.get(context.session_cookie); employee=identity.resolve_session(raw) if raw else None
            if employee is None: raise HTTPException(status_code=401,detail="Authentication required")
            actor=ScsPrincipal(employee.employee_id,employee.roles,identity.current_functions(employee.employee_id),employee.status)
            try: authorizer.require(actor,permission)
            except PermissionError: raise HTTPException(status_code=403,detail="Permission denied") from None
            return employee
        return dep
    @router.get("")
    def employees(actor=Depends(require(Permission.MANAGE_EMPLOYEES))): return {"employees":[asdict(x) for x in identity.list_employees(actor.employee_id)]}
    @router.put("/{employee_id}/roles")
    def roles(employee_id:str,body:RolesInput,actor=Depends(require(Permission.MANAGE_EMPLOYEES))):
        try:return asdict(identity.set_roles(actor.employee_id,employee_id,body.roles))
        except PermissionError:raise HTTPException(status_code=403,detail="Permission denied") from None
        except (ValueError,KeyError):raise HTTPException(status_code=400,detail="Roles could not be changed") from None
    @router.post("/{employee_id}/functions",status_code=status.HTTP_204_NO_CONTENT)
    def function(employee_id:str,body:FunctionInput,actor=Depends(require(Permission.MANAGE_EMPLOYEES))):
        try:identity.assign_function(actor.employee_id,employee_id,body.function_code)
        except (ValueError,KeyError):raise HTTPException(status_code=400,detail="Function could not be assigned") from None
    @router.put("/{employee_id}/technician-level",status_code=status.HTTP_204_NO_CONTENT)
    def level(employee_id:str,body:LevelInput,actor=Depends(require(Permission.MANAGE_TECHNICIAN_LEVEL))):
        try:identity.set_technician_level(actor.employee_id,employee_id,body.level_code)
        except (ValueError,KeyError,PermissionError):raise HTTPException(status_code=400,detail="Technician level could not be changed") from None
    @router.put("/{employee_id}/status",status_code=status.HTTP_204_NO_CONTENT)
    def employee_status(employee_id:str,body:EmployeeStatusInput,actor=Depends(require(Permission.MANAGE_EMPLOYEES))):
        try:identity.set_status(actor.employee_id,employee_id,body.status)
        except PermissionError:raise HTTPException(status_code=403,detail="Permission denied") from None
        except (ValueError,KeyError):raise HTTPException(status_code=400,detail="Status could not be changed") from None
    return router
