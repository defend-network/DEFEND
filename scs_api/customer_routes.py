from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from scs_data.authorization import Permission, ScsAuthorizer, ScsPrincipal
from scs_data.customers import ScsCustomerStore
from scs_data.identity import EmployeeRecord, ScsIdentityStore
from scs_data.customer_summary import ScsCustomerSummaryService
from shared_platform.application import ApplicationContext


class CustomerInput(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    customer_type: str


class SiteInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    service_address: str = Field(min_length=1, max_length=500)
    billing_address: str | None = Field(default=None, max_length=500)
    timezone: str = Field(min_length=1, max_length=80)

class ContactInput(BaseModel):
    name: str = Field(min_length=1, max_length=200); email: str | None = None; phone: str | None = None; purpose: str = Field(min_length=1, max_length=80)

class EquipmentInput(BaseModel):
    site_id: str; equipment_type: str = Field(min_length=1, max_length=100); manufacturer: str | None = None; model: str | None = None; serial_number: str | None = None


def build_customer_router(context: ApplicationContext, identity: ScsIdentityStore, customers: ScsCustomerStore) -> APIRouter:
    router = APIRouter(prefix="/api/scs/customers")
    authorizer = ScsAuthorizer()

    def principal(request: Request) -> tuple[EmployeeRecord, ScsPrincipal]:
        raw = request.cookies.get(context.session_cookie)
        employee = identity.resolve_session(raw) if raw else None
        if employee is None: raise HTTPException(status_code=401, detail="Authentication required")
        functions = identity.current_functions(employee.employee_id)
        return employee, ScsPrincipal(employee.employee_id, employee.roles, functions, employee.status)

    def require(permission: Permission):
        def dependency(pair=Depends(principal)):
            employee, actor = pair
            try: authorizer.require(actor, permission)
            except PermissionError: raise HTTPException(status_code=403, detail="Permission denied") from None
            return employee
        return dependency

    @router.get("")
    def search(q: str = "", employee=Depends(require(Permission.VIEW_CUSTOMERS))):
        return {"customers": [asdict(item) for item in customers.search_customers(q)]}

    @router.post("", status_code=status.HTTP_201_CREATED)
    def create(body: CustomerInput, employee=Depends(require(Permission.EDIT_CUSTOMERS))):
        try: item = customers.create_customer(employee.employee_id, body.display_name, body.customer_type)
        except ValueError as error: raise HTTPException(status_code=400, detail=str(error)) from None
        return asdict(item)

    @router.get("/{customer_id}")
    def detail(customer_id: str, employee=Depends(require(Permission.VIEW_CUSTOMERS))):
        try: item = customers.get_customer(customer_id)
        except KeyError: raise HTTPException(status_code=404, detail="Customer not found") from None
        identity.audit.append(employee.employee_id, "customer.read", "customer", customer_id)
        return {"customer": asdict(item.customer), "contacts": [asdict(x) for x in item.contacts], "sites": [asdict(x) for x in item.sites], "equipment": [asdict(x) for x in item.equipment]}

    @router.post("/{customer_id}/sites", status_code=status.HTTP_201_CREATED)
    def add_site(customer_id: str, body: SiteInput, employee=Depends(require(Permission.EDIT_CUSTOMERS))):
        try: item = customers.add_site(employee.employee_id, customer_id, body.name, body.service_address, body.billing_address, body.timezone)
        except KeyError: raise HTTPException(status_code=404, detail="Customer not found") from None
        return asdict(item)

    @router.post("/{customer_id}/contacts", status_code=status.HTTP_201_CREATED)
    def add_contact(customer_id: str, body: ContactInput, employee=Depends(require(Permission.EDIT_CUSTOMERS))):
        try: return asdict(customers.add_contact(employee.employee_id, customer_id, name=body.name, email=body.email, phone=body.phone, purpose=body.purpose))
        except KeyError: raise HTTPException(status_code=404, detail="Customer not found") from None

    @router.post("/{customer_id}/equipment", status_code=status.HTTP_201_CREATED)
    def add_equipment(customer_id: str, body: EquipmentInput, employee=Depends(require(Permission.EDIT_CUSTOMERS))):
        try: return asdict(customers.add_equipment(employee.employee_id, customer_id, body.site_id, equipment_type=body.equipment_type, manufacturer=body.manufacturer, model=body.model, serial_number=body.serial_number))
        except KeyError: raise HTTPException(status_code=404, detail="Customer not found") from None
        except ValueError as error: raise HTTPException(status_code=400, detail=str(error)) from None

    @router.get("/{customer_id}/summary")
    def summary(customer_id: str, employee=Depends(require(Permission.VIEW_CUSTOMERS))):
        try: return asdict(ScsCustomerSummaryService(identity.conn).for_customer(customer_id))
        except KeyError: raise HTTPException(status_code=404, detail="Customer not found") from None

    @router.post("/{customer_id}/archive", status_code=status.HTTP_204_NO_CONTENT)
    def archive(customer_id: str, employee=Depends(require(Permission.EDIT_CUSTOMERS))):
        try: customers.archive_customer(employee.employee_id, customer_id)
        except KeyError: raise HTTPException(status_code=404, detail="Customer not found") from None

    return router
