from datetime import date

from scs_data.config import ScsPaths
from scs_data.customer_summary import ScsCustomerSummaryService
from scs_data.customers import ScsCustomerStore
from scs_data.identity import ScsIdentityStore
from scs_data.jobs import ScsJobStore
from scs_data.memberships import ScsMembershipStore
from shared_platform.application import ApplicationContext


def test_summary_uses_authoritative_counts_and_explicit_unavailable_financials(tmp_path):
    context = ApplicationContext("scs", (tmp_path / "SCS_DATA").resolve(), "SCS", "SCS", "scs_employee_session", "https://ai.sunshineclimatesolutions.com", 8100, 3100)
    identity = ScsIdentityStore(ScsPaths.from_context(context).ensure().database)
    owner = identity.bootstrap_owner("owner@example.com", "owner", "Owner", "owner-password")
    customers = ScsCustomerStore(identity.conn, identity.audit)
    customer = customers.create_customer(owner.employee_id, "Summary", "commercial")
    site = customers.add_site(owner.employee_id, customer.customer_id, "One", "1 Main", None, "America/New_York")
    customers.add_equipment(owner.employee_id, customer.customer_id, site.site_id, equipment_type="rtu", manufacturer="Carrier", model="A", serial_number="S")
    ScsJobStore(identity.conn, identity.audit).create_job(owner.employee_id, customer.customer_id, site.site_id, "hvac-service", job_date=date(2026, 8, 13))
    ScsMembershipStore(identity.conn, identity.audit).enroll(owner.employee_id, customer.customer_id, "maintenance-member", start_date=date(2026, 8, 13))
    summary = ScsCustomerSummaryService(identity.conn).for_customer(customer.customer_id)
    assert (summary.site_count, summary.equipment_count, summary.job_count, summary.active_membership_count) == (1, 1, 1, 1)
    assert summary.total_spend.state == "not_available" and summary.total_spend.value is None
    assert summary.average_payment_days.state == "not_available" and summary.average_payment_days.value is None
    identity.close()
