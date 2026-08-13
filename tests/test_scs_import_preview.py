from datetime import datetime, timezone
from dataclasses import dataclass
import base64

import pytest
from fastapi.testclient import TestClient

from scs_api.app import build_scs_app
from scs_data.config import ScsPaths
from scs_data.customers import ScsCustomerStore
from scs_data.identity import ScsIdentityStore
from scs_data.import_preview import preview_customer_csv
from scs_data.mailer import DeliveryResult
from shared_platform.application import ApplicationContext


@pytest.fixture
def customers(tmp_path):
    context = ApplicationContext("scs", (tmp_path / "SCS_DATA").resolve(), "SCS", "SCS", "scs_employee_session", "https://ai.sunshineclimatesolutions.com", 8100, 3100)
    identity = ScsIdentityStore(ScsPaths.from_context(context).ensure().database)
    owner = identity.bootstrap_owner("owner@example.com", "owner", "Owner", "owner-password")
    store = ScsCustomerStore(identity.conn, identity.audit)
    store.create_customer(owner.employee_id, "Acme HVAC", "commercial")
    yield store, identity
    identity.close()


def test_preview_is_advisory_neutralizes_formulas_and_makes_zero_writes(customers):
    store, identity = customers
    before = identity.conn.execute("SELECT COUNT(*) FROM scs_customers").fetchone()[0]
    data = b"Name,Type,Phone\nAcme HVAC,commercial,555-1000\n=HYPERLINK('x'),residential,555-2000\n,commercial,555-3000\n"
    preview = preview_customer_csv(data, {"Name": "display_name", "Type": "customer_type", "Phone": "phone"}, store)
    assert len(preview.matches) == 1
    assert preview.creates[0]["display_name"].startswith("'")
    assert len(preview.rejections) == 1
    assert datetime.fromisoformat(preview.expires_at) > datetime.now(timezone.utc)
    assert identity.conn.execute("SELECT COUNT(*) FROM scs_customers").fetchone()[0] == before


def test_preview_rejects_unsafe_or_unbounded_input(customers):
    store, _identity = customers
    with pytest.raises(ValueError, match="UTF-8"):
        preview_customer_csv(b"\xff", {}, store)
    with pytest.raises(ValueError, match="duplicate"):
        preview_customer_csv(b"Name,Name\na,b\n", {"Name": "display_name"}, store)
    with pytest.raises(ValueError, match="5 MiB"):
        preview_customer_csv(b"x" * (5 * 1024 * 1024 + 1), {}, store)
    too_many_columns = (",".join(f"c{x}" for x in range(101)) + "\n").encode()
    with pytest.raises(ValueError, match="100 columns"):
        preview_customer_csv(too_many_columns, {}, store)


def test_preview_caps_rows_and_cell_size(customers):
    store, _identity = customers
    rows = "Name,Type\n" + "\n".join(f"Customer {x},commercial" for x in range(5001))
    with pytest.raises(ValueError, match="5,000 rows"):
        preview_customer_csv(rows.encode(), {"Name": "display_name", "Type": "customer_type"}, store)
    with pytest.raises(ValueError, match="cell"):
        preview_customer_csv(("Name,Type\n" + "a" * 32769 + ",commercial\n").encode(), {"Name": "display_name"}, store)


@dataclass
class NoopMailer:
    def send_invitation(self, *_args): return DeliveryResult(True, "sent")


def test_preview_api_is_permissioned_and_has_no_commit_endpoint(tmp_path):
    context = ApplicationContext("scs", (tmp_path / "SCS_DATA").resolve(), "SCS", "SCS", "scs_employee_session", "https://ai.sunshineclimatesolutions.com", 8100, 3100)
    identity = ScsIdentityStore(ScsPaths.from_context(context).ensure().database)
    owner = identity.bootstrap_owner("owner@example.com", "owner", "Owner", "owner-password")
    identity.create_active_employee_for_bootstrap(owner.employee_id, "reader@example.com", "reader", "Reader", "reader-password", ("read_only",))
    store = ScsCustomerStore(identity.conn, identity.audit)
    app = build_scs_app(context, identity, NoopMailer(), customers=store)
    payload = {"content_base64": base64.b64encode(b"Name,Type\nNew,commercial\n").decode(), "mapping": {"Name": "display_name", "Type": "customer_type"}}
    with TestClient(app, base_url=context.public_origin) as client:
        client.post("/api/scs/auth/login", json={"identifier": "owner", "password": "owner-password"})
        assert client.post("/api/scs/imports/customers/preview", json=payload).status_code == 200
        assert client.post("/api/scs/imports/customers/commit", json=payload).status_code == 404
        client.post("/api/scs/auth/login", json={"identifier": "reader", "password": "reader-password"})
        assert client.post("/api/scs/imports/customers/preview", json=payload).status_code == 403
    identity.close()
