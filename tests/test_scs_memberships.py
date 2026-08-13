from datetime import date

import pytest

from scs_data.config import ScsPaths
from scs_data.customers import ScsCustomerStore
from scs_data.identity import ScsIdentityStore
from scs_data.memberships import ScsMembershipStore
from shared_platform.application import ApplicationContext


@pytest.fixture
def stores(tmp_path):
    context = ApplicationContext("scs", (tmp_path / "SCS_DATA").resolve(), "SCS", "SCS", "scs_employee_session", "https://ai.sunshineclimatesolutions.com", 8100, 3100)
    paths = ScsPaths.from_context(context).ensure()
    identity = ScsIdentityStore(paths.database)
    owner = identity.bootstrap_owner("owner@example.com", "owner", "Owner", "owner-password")
    customers = ScsCustomerStore(identity.conn, identity.audit)
    memberships = ScsMembershipStore(identity.conn, identity.audit)
    yield memberships, customers, identity, owner
    identity.close()


def test_maintenance_member_is_seeded_once_and_revisions_preserve_history(stores):
    memberships, _customers, identity, owner = stores
    initial = memberships.current_plan("maintenance-member")
    assert initial.name == "Maintenance Member"
    assert initial.version == 1
    revised = memberships.revise_plan(owner.employee_id, "maintenance-member", name="Maintenance Member", active=True)
    assert revised.version == 2
    assert memberships.plan_version("maintenance-member", 1).version == 1
    assert identity.conn.execute("SELECT COUNT(*) FROM scs_membership_plan_versions WHERE plan_code='maintenance-member'").fetchone()[0] == 2


def test_enrollment_references_plan_version_and_appends_status_history(stores):
    memberships, customers, identity, owner = stores
    customer = customers.create_customer(owner.employee_id, "Member", "residential")
    enrollment = memberships.enroll(owner.employee_id, customer.customer_id, "maintenance-member", start_date=date(2026, 8, 13))
    assert enrollment.plan_version == 1
    assert enrollment.status == "active"
    memberships.change_status(owner.employee_id, enrollment.enrollment_id, "paused")
    memberships.change_status(owner.employee_id, enrollment.enrollment_id, "active")
    assert memberships.current_enrollment(enrollment.enrollment_id).status == "active"
    assert identity.conn.execute("SELECT COUNT(*) FROM scs_membership_enrollment_events WHERE enrollment_id=?", (enrollment.enrollment_id,)).fetchone()[0] == 3


def test_enrollment_coverage_must_belong_to_same_customer(stores):
    memberships, customers, _identity, owner = stores
    one = customers.create_customer(owner.employee_id, "One", "residential")
    two = customers.create_customer(owner.employee_id, "Two", "residential")
    other_site = customers.add_site(owner.employee_id, two.customer_id, "Other", "2 Main", None, "America/New_York")
    with pytest.raises(ValueError, match="same customer"):
        memberships.enroll(owner.employee_id, one.customer_id, "maintenance-member", start_date=date(2026, 8, 13), covered_site_ids=(other_site.site_id,))


def test_invalid_dates_and_status_transitions_fail(stores):
    memberships, customers, _identity, owner = stores
    customer = customers.create_customer(owner.employee_id, "Member", "residential")
    with pytest.raises(ValueError, match="end date"):
        memberships.enroll(owner.employee_id, customer.customer_id, "maintenance-member", start_date=date(2026, 8, 13), end_date=date(2026, 8, 12))
    enrollment = memberships.enroll(owner.employee_id, customer.customer_id, "maintenance-member", start_date=date(2026, 8, 13))
    memberships.change_status(owner.employee_id, enrollment.enrollment_id, "cancelled")
    with pytest.raises(ValueError, match="terminal"):
        memberships.change_status(owner.employee_id, enrollment.enrollment_id, "active")
