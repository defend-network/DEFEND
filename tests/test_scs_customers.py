import pytest

from scs_data.customers import ScsCustomerStore
from scs_data.identity import ScsIdentityStore
from scs_data.config import ScsPaths
from shared_platform.application import ApplicationContext


@pytest.fixture
def stores(tmp_path):
    context = ApplicationContext("scs", (tmp_path / "SCS_DATA").resolve(), "SCS", "SCS", "scs_employee_session", "https://ai.sunshineclimatesolutions.com", 8100, 3100)
    paths = ScsPaths.from_context(context).ensure()
    identity = ScsIdentityStore(paths.database)
    owner = identity.bootstrap_owner("owner@example.com", "owner", "Owner", "owner-password")
    customers = ScsCustomerStore(identity.conn, identity.audit)
    yield customers, identity, owner
    identity.close()


def test_customer_supports_multiple_contacts_sites_and_separate_billing_address(stores):
    store, _identity, owner = stores
    customer = store.create_customer(owner.employee_id, display_name="Acme Properties", customer_type="commercial")
    first = store.add_contact(owner.employee_id, customer.customer_id, name="Alex", email="alex@example.com", purpose="operations")
    second = store.add_contact(owner.employee_id, customer.customer_id, name="Pat", email="pat@example.com", purpose="billing")
    site = store.add_site(
        owner.employee_id, customer.customer_id, name="Plant 1",
        service_address="100 Service Rd", billing_address="PO Box 200", timezone="America/New_York",
    )

    detail = store.get_customer(customer.customer_id)
    assert {item.contact_id for item in detail.contacts} == {first.contact_id, second.contact_id}
    assert detail.sites[0].site_id == site.site_id
    assert detail.sites[0].service_address != detail.sites[0].billing_address


def test_equipment_is_scoped_to_customer_and_site_and_preserves_history(stores):
    store, _identity, owner = stores
    one = store.create_customer(owner.employee_id, "One", "residential")
    two = store.create_customer(owner.employee_id, "Two", "commercial")
    site = store.add_site(owner.employee_id, one.customer_id, "Home", "1 Main St", None, "America/New_York")
    with pytest.raises(ValueError, match="same customer"):
        store.add_equipment(owner.employee_id, two.customer_id, site.site_id, equipment_type="split_system", manufacturer="Carrier", model="A", serial_number="S1")

    equipment = store.add_equipment(owner.employee_id, one.customer_id, site.site_id, equipment_type="split_system", manufacturer="Carrier", model="A", serial_number="S1")
    store.update_equipment(owner.employee_id, equipment.equipment_id, status="inactive", notes="Replaced")
    assert store.get_equipment(equipment.equipment_id).status == "inactive"
    assert store.equipment_history_count(equipment.equipment_id) == 2


def test_customer_archive_is_non_destructive_and_search_is_bounded(stores):
    store, _identity, owner = stores
    customer = store.create_customer(owner.employee_id, "Archive Me", "residential")
    store.archive_customer(owner.employee_id, customer.customer_id)
    assert store.get_customer(customer.customer_id).customer.status == "archived"
    for index in range(15):
        store.create_customer(owner.employee_id, f"Search {index}", "commercial")
    assert len(store.search_customers("Search", limit=5)) == 5
    with pytest.raises(ValueError, match="limit"):
        store.search_customers("Search", limit=201)


def test_customer_mutations_are_audited_without_note_content(stores):
    store, identity, owner = stores
    customer = store.create_customer(owner.employee_id, "Audited", "commercial", internal_notes="private customer note")
    rows = identity.conn.execute("SELECT event_type,metadata_json FROM scs_audit_events WHERE target_id=?", (customer.customer_id,)).fetchall()
    assert rows[-1]["event_type"] == "customer.created"
    assert "private customer note" not in rows[-1]["metadata_json"]
