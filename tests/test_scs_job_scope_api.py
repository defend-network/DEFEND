from dataclasses import dataclass
from datetime import date

from fastapi.testclient import TestClient

from scs_api.app import build_scs_app
from scs_data.config import ScsPaths
from scs_data.customers import ScsCustomerStore
from scs_data.identity import ScsIdentityStore
from scs_data.jobs import ScsJobStore
from scs_data.mailer import DeliveryResult
from shared_platform.application import ApplicationContext


@dataclass
class NoopMailer:
    def send_invitation(self, *_args): return DeliveryResult(True, "sent")


def test_job_api_reuses_assignment_scope_for_list_and_detail(tmp_path):
    context = ApplicationContext("scs", (tmp_path / "SCS_DATA").resolve(), "SCS", "SCS", "scs_employee_session", "https://ai.sunshineclimatesolutions.com", 8100, 3100)
    identity = ScsIdentityStore(ScsPaths.from_context(context).ensure().database)
    owner = identity.bootstrap_owner("owner@example.com", "owner", "Owner", "owner-password")
    one = identity.create_active_employee_for_bootstrap(owner.employee_id, "one@example.com", "one", "One", "one-password", ("read_only",))
    two = identity.create_active_employee_for_bootstrap(owner.employee_id, "two@example.com", "two", "Two", "two-password", ("read_only",))
    customers = ScsCustomerStore(identity.conn, identity.audit)
    customer = customers.create_customer(owner.employee_id, "Customer", "commercial")
    site = customers.add_site(owner.employee_id, customer.customer_id, "Main", "1 Main", None, "America/New_York")
    jobs = ScsJobStore(identity.conn, identity.audit)
    visible = jobs.create_job(owner.employee_id, customer.customer_id, site.site_id, "hvac-service", job_date=date(2026, 8, 13))
    hidden = jobs.create_job(owner.employee_id, customer.customer_id, site.site_id, "tab-testing", job_date=date(2026, 8, 13))
    jobs.assign(owner.employee_id, visible.job_id, one.employee_id, "technician")
    jobs.assign(owner.employee_id, hidden.job_id, two.employee_id, "tab-technician")
    app = build_scs_app(context, identity, NoopMailer(), customers=customers, jobs=jobs)
    with TestClient(app, base_url=context.public_origin) as client:
        client.post("/api/scs/auth/login", json={"identifier": "one", "password": "one-password"})
        response = client.get("/api/scs/jobs")
        assert [item["job_id"] for item in response.json()["jobs"]] == [visible.job_id]
        assert client.get(f"/api/scs/jobs/{visible.job_id}").status_code == 200
        assert client.get(f"/api/scs/jobs/{hidden.job_id}").status_code == 404
    identity.close()
