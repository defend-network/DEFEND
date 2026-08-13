from dataclasses import dataclass

from fastapi.testclient import TestClient

from scs_api.app import build_scs_app
from scs_data.customers import ScsCustomerStore
from scs_data.identity import ScsIdentityStore
from scs_data.mailer import DeliveryResult
from scs_data.config import ScsPaths
from shared_platform.application import ApplicationContext


@dataclass
class NoopMailer:
    def send_invitation(self, email, activation_url):
        return DeliveryResult(True, "sent")


def setup_api(tmp_path):
    context = ApplicationContext("scs", (tmp_path / "SCS_DATA").resolve(), "SCS", "SCS", "scs_employee_session", "https://ai.sunshineclimatesolutions.com", 8100, 3100)
    paths = ScsPaths.from_context(context).ensure()
    identity = ScsIdentityStore(paths.database)
    owner = identity.bootstrap_owner("owner@example.com", "owner", "Owner", "owner-password")
    customers = ScsCustomerStore(identity.conn, identity.audit)
    app = build_scs_app(context, identity, NoopMailer(), customers=customers)
    return TestClient(app, base_url=context.public_origin), identity, owner


def test_customer_routes_require_auth_and_create_nested_records(tmp_path):
    client, identity, _owner = setup_api(tmp_path)
    assert client.get("/api/scs/customers").status_code == 401
    assert client.post("/api/scs/auth/login", json={"identifier": "owner", "password": "owner-password"}).status_code == 200
    created = client.post("/api/scs/customers", json={"display_name": "Customer", "customer_type": "commercial"})
    assert created.status_code == 201
    customer_id = created.json()["customer_id"]
    site = client.post(f"/api/scs/customers/{customer_id}/sites", json={"name": "Site", "service_address": "1 Main", "timezone": "America/New_York"})
    assert site.status_code == 201
    detail = client.get(f"/api/scs/customers/{customer_id}")
    assert detail.status_code == 200
    assert detail.json()["sites"][0]["name"] == "Site"
    client.close(); identity.close()


def test_read_only_employee_cannot_mutate_customers(tmp_path):
    client, identity, owner = setup_api(tmp_path)
    worker = identity.create_active_employee_for_bootstrap(owner.employee_id, "reader@example.com", "reader", "Reader", "reader-password", ("read_only",))
    assert client.post("/api/scs/auth/login", json={"identifier": "reader", "password": "reader-password"}).status_code == 200
    denied = client.post("/api/scs/customers", json={"display_name": "No", "customer_type": "commercial"})
    assert denied.status_code == 403
    assert "sqlite" not in denied.text.casefold()
    client.close(); identity.close()
