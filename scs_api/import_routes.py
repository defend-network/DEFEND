from __future__ import annotations

import base64
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from scs_data.authorization import Permission, ScsAuthorizer, ScsPrincipal
from scs_data.customers import ScsCustomerStore
from scs_data.identity import ScsIdentityStore
from scs_data.import_preview import preview_customer_csv
from shared_platform.application import ApplicationContext


class CsvPreviewInput(BaseModel):
    content_base64: str
    mapping: dict[str, str]


def build_import_router(context: ApplicationContext, identity: ScsIdentityStore, customers: ScsCustomerStore) -> APIRouter:
    router = APIRouter(prefix="/api/scs/imports")
    authorizer = ScsAuthorizer()

    @router.post("/customers/preview")
    def preview(body: CsvPreviewInput, request: Request):
        raw = request.cookies.get(context.session_cookie)
        employee = identity.resolve_session(raw) if raw else None
        if employee is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        principal = ScsPrincipal(employee.employee_id, employee.roles, identity.current_functions(employee.employee_id), employee.status)
        try:
            authorizer.require(principal, Permission.EDIT_CUSTOMERS)
            data = base64.b64decode(body.content_base64, validate=True)
            result = preview_customer_csv(data, body.mapping, customers)
        except PermissionError:
            raise HTTPException(status_code=403, detail="Permission denied") from None
        except (ValueError, TypeError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from None
        identity.audit.append(employee.employee_id, "customer_import.previewed", "import_preview", result.preview_id, {"creates": len(result.creates), "matches": len(result.matches), "rejections": len(result.rejections)})
        return asdict(result)

    return router
