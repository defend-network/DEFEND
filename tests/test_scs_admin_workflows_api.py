from dataclasses import dataclass

from fastapi.testclient import TestClient

from scs_api.app import build_scs_app
from scs_data.config import ScsPaths
from scs_data.customers import ScsCustomerStore
from scs_data.identity import ScsIdentityStore
from scs_data.jobs import ScsJobStore
from scs_data.mailer import DeliveryResult
from scs_data.memberships import ScsMembershipStore
from shared_platform.application import ApplicationContext


@dataclass
class NoopMailer:
    def send_invitation(self, *_args): return DeliveryResult(True, "sent")


def test_owner_can_complete_customer_job_and_employee_admin_workflows(tmp_path):
    context = ApplicationContext("scs", (tmp_path / "SCS_DATA").resolve(), "SCS", "SCS", "scs_employee_session", "https://ai.sunshineclimatesolutions.com", 8100, 3100)
    identity = ScsIdentityStore(ScsPaths.from_context(context).ensure().database)
    owner = identity.bootstrap_owner("owner@example.com", "owner", "Owner", "owner-password")
    tech = identity.create_active_employee_for_bootstrap(owner.employee_id, "tech@example.com", "tech", "Tech", "tech-password", ("read_only",))
    identity.assign_function(owner.employee_id, tech.employee_id, "service_technician")
    customers = ScsCustomerStore(identity.conn, identity.audit); jobs = ScsJobStore(identity.conn, identity.audit)
    app = build_scs_app(context, identity, NoopMailer(), customers=customers, memberships=ScsMembershipStore(identity.conn, identity.audit), jobs=jobs)
    with TestClient(app, base_url=context.public_origin) as client:
        client.post("/api/scs/auth/login", json={"identifier":"owner","password":"owner-password"})
        customer = client.post("/api/scs/customers", json={"display_name":"API Customer","customer_type":"commercial"}).json()
        contact = client.post(f"/api/scs/customers/{customer['customer_id']}/contacts", json={"name":"Pat","email":"pat@example.com","purpose":"billing"})
        assert contact.status_code == 201
        site = client.post(f"/api/scs/customers/{customer['customer_id']}/sites", json={"name":"Main","service_address":"1 Main","timezone":"America/New_York"}).json()
        equipment = client.post(f"/api/scs/customers/{customer['customer_id']}/equipment", json={"site_id":site["site_id"],"equipment_type":"rtu","manufacturer":"Carrier"})
        assert equipment.status_code == 201
        job = client.post("/api/scs/jobs", json={"customer_id":customer["customer_id"],"site_id":site["site_id"],"job_type":"hvac-service","job_date":"2026-08-13"}).json()
        assert client.post(f"/api/scs/jobs/{job['job_id']}/assignments", json={"employee_id":tech.employee_id,"assignment_role":"technician"}).status_code == 201
        assert client.post(f"/api/scs/jobs/{job['job_id']}/status", json={"status":"scheduled"}).status_code == 200
        assert client.post(f"/api/scs/jobs/{job['job_id']}/visits", json={"work_performed":"Inspected"}).status_code == 201
        assert client.post(f"/api/scs/jobs/{job['job_id']}/notes", json={"body":"Dispatch note","visibility":"operational"}).status_code == 201
        assert client.post(f"/api/scs/jobs/{job['job_id']}/classifications", json={"code":"potential-member","source":"manual"}).status_code == 204
        employees = client.get("/api/scs/admin/employees")
        assert employees.status_code == 200 and len(employees.json()["employees"]) == 2
        assert client.put(f"/api/scs/admin/employees/{tech.employee_id}/roles", json={"roles":["reviewer"]}).status_code == 200
        assert client.post(f"/api/scs/admin/employees/{tech.employee_id}/functions", json={"function_code":"maintenance_technician"}).status_code == 204
        assert client.put(f"/api/scs/admin/employees/{tech.employee_id}/technician-level", json={"level_code":"technician_i"}).status_code == 204
        assert client.put(f"/api/scs/admin/employees/{tech.employee_id}/status", json={"status":"disabled"}).status_code == 204
        assert client.get(f"/api/scs/customers/{customer['customer_id']}/summary").json()["total_spend"]["state"] == "not_available"
        assert client.post(f"/api/scs/customers/{customer['customer_id']}/archive").status_code == 204
    identity.close()


def test_ordinary_employee_cannot_use_manager_mutation_endpoints(tmp_path):
    context = ApplicationContext("scs", (tmp_path / "SCS_DATA").resolve(), "SCS", "SCS", "scs_employee_session", "https://ai.sunshineclimatesolutions.com", 8100, 3100)
    identity = ScsIdentityStore(ScsPaths.from_context(context).ensure().database)
    owner = identity.bootstrap_owner("owner@example.com", "owner", "Owner", "owner-password")
    reader = identity.create_active_employee_for_bootstrap(owner.employee_id, "reader@example.com", "reader", "Reader", "reader-password", ("read_only",))
    customers=ScsCustomerStore(identity.conn,identity.audit);jobs=ScsJobStore(identity.conn,identity.audit)
    app=build_scs_app(context,identity,NoopMailer(),customers=customers,jobs=jobs)
    with TestClient(app,base_url=context.public_origin) as client:
        client.post("/api/scs/auth/login",json={"identifier":"reader","password":"reader-password"})
        assert client.post("/api/scs/customers",json={"display_name":"No","customer_type":"commercial"}).status_code==403
        assert client.post("/api/scs/jobs",json={"customer_id":"x","site_id":"x","job_type":"hvac-service","job_date":"2026-08-13"}).status_code==403
        assert client.get("/api/scs/admin/employees").status_code==403
    identity.close()
