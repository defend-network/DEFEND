from dataclasses import dataclass

from fastapi.testclient import TestClient

from scs_api.app import build_scs_app
from scs_data.config import ScsPaths
from scs_data.customers import ScsCustomerStore
from scs_data.identity import ScsIdentityStore
from scs_data.mailer import DeliveryResult
from scs_data.memberships import ScsMembershipStore
from shared_platform.application import ApplicationContext


@dataclass
class NoopMailer:
    def send_invitation(self, *_args): return DeliveryResult(True, "sent")


def test_owner_can_enroll_customer_and_read_only_cannot(tmp_path):
    context = ApplicationContext("scs", (tmp_path / "SCS_DATA").resolve(), "SCS", "SCS", "scs_employee_session", "https://ai.sunshineclimatesolutions.com", 8100, 3100)
    paths = ScsPaths.from_context(context).ensure(); identity = ScsIdentityStore(paths.database)
    owner = identity.bootstrap_owner("owner@example.com", "owner", "Owner", "owner-password")
    customers = ScsCustomerStore(identity.conn, identity.audit); memberships = ScsMembershipStore(identity.conn, identity.audit)
    customer = customers.create_customer(owner.employee_id, "Member", "residential")
    app = build_scs_app(context, identity, NoopMailer(), customers=customers, memberships=memberships)
    with TestClient(app, base_url=context.public_origin) as client:
        client.post("/api/scs/auth/login", json={"identifier": "owner", "password": "owner-password"})
        response = client.post("/api/scs/memberships/enrollments", json={"customer_id": customer.customer_id, "plan_code": "maintenance-member", "start_date": "2026-08-13"})
        assert response.status_code == 201
        assert response.json()["status"] == "active"
        reader = identity.create_active_employee_for_bootstrap(owner.employee_id, "reader@example.com", "reader", "Reader", "reader-password", ("read_only",))
        client.post("/api/scs/auth/login", json={"identifier": "reader", "password": "reader-password"})
        assert client.post("/api/scs/memberships/enrollments", json={"customer_id": customer.customer_id, "plan_code": "maintenance-member", "start_date": "2026-08-13"}).status_code == 403
    identity.close()
