from datetime import date

import pytest

from scs_data.authorization import ScsPrincipal
from scs_data.config import ScsPaths
from scs_data.customers import ScsCustomerStore
from scs_data.identity import ScsIdentityStore
from scs_data.jobs import JOB_TYPES, ScsJobStore
from shared_platform.application import ApplicationContext


@pytest.fixture
def stores(tmp_path):
    context = ApplicationContext("scs", (tmp_path / "SCS_DATA").resolve(), "SCS", "SCS", "scs_employee_session", "https://ai.sunshineclimatesolutions.com", 8100, 3100)
    identity = ScsIdentityStore(ScsPaths.from_context(context).ensure().database)
    owner = identity.bootstrap_owner("owner@example.com", "owner", "Owner", "owner-password")
    worker = identity.create_active_employee_for_bootstrap(owner.employee_id, "tech@example.com", "tech", "Tech", "tech-password", ("read_only",))
    customer_store = ScsCustomerStore(identity.conn, identity.audit)
    customer = customer_store.create_customer(owner.employee_id, "Customer", "commercial")
    site = customer_store.add_site(owner.employee_id, customer.customer_id, "Main", "1 Main", None, "America/New_York")
    jobs = ScsJobStore(identity.conn, identity.audit)
    yield jobs, identity, owner, worker, customer, site
    identity.close()


def test_all_approved_job_types_and_customer_site_ownership(stores):
    jobs, identity, owner, _worker, customer, site = stores
    assert JOB_TYPES == frozenset({"hvac-service", "preventive-maintenance", "installation-replacement", "warranty-callback", "sales-estimate", "tab-testing", "tab-reporting", "commissioning-support", "internal-non-billable"})
    other = ScsCustomerStore(identity.conn, identity.audit).create_customer(owner.employee_id, "Other", "residential")
    with pytest.raises(ValueError, match="same customer"):
        jobs.create_job(owner.employee_id, other.customer_id, site.site_id, "hvac-service", job_date=date(2026, 8, 13))
    with pytest.raises(ValueError, match="job type"):
        jobs.create_job(owner.employee_id, customer.customer_id, site.site_id, "made-up", job_date=date(2026, 8, 13))


def test_status_visits_assignments_and_employee_scope_are_durable(stores):
    jobs, _identity, owner, worker, customer, site = stores
    job = jobs.create_job(owner.employee_id, customer.customer_id, site.site_id, "hvac-service", job_date=date(2026, 8, 13))
    jobs.change_status(owner.employee_id, job.job_id, "scheduled")
    jobs.change_status(owner.employee_id, job.job_id, "in-progress")
    assert jobs.status_history(job.job_id) == ("new", "scheduled", "in-progress")
    jobs.add_visit(owner.employee_id, job.job_id, work_performed="Diagnosed", findings="Failed capacitor")
    jobs.add_visit(owner.employee_id, job.job_id, work_performed="Repaired", findings="Operational")
    assignment = jobs.assign(owner.employee_id, job.job_id, worker.employee_id, "lead-technician")
    ordinary = ScsPrincipal(worker.employee_id, worker.roles, (), worker.status)
    assert [item.job_id for item in jobs.visible_jobs(ordinary)] == [job.job_id]
    jobs.end_assignment(owner.employee_id, assignment.assignment_id)
    assert jobs.visible_jobs(ordinary) == ()
    manager = ScsPrincipal(owner.employee_id, owner.roles, (), owner.status)
    assert [item.job_id for item in jobs.visible_jobs(manager)] == [job.job_id]


def test_note_visibility_is_enforced(stores):
    jobs, _identity, owner, worker, customer, site = stores
    job = jobs.create_job(owner.employee_id, customer.customer_id, site.site_id, "hvac-service", job_date=date(2026, 8, 13))
    jobs.assign(owner.employee_id, job.job_id, worker.employee_id, "technician")
    jobs.add_note(owner.employee_id, job.job_id, "general", "operational")
    jobs.add_note(owner.employee_id, job.job_id, "manager", "management-only")
    jobs.add_note(owner.employee_id, job.job_id, "invoice", "billing-only")
    ordinary = ScsPrincipal(worker.employee_id, worker.roles, (), worker.status)
    assert [note.body for note in jobs.visible_notes(ordinary, job.job_id)] == ["general"]
    assert len(jobs.visible_notes(ScsPrincipal(owner.employee_id, owner.roles, (), owner.status), job.job_id)) == 3


def test_controlled_classifications_and_age_derivation(stores):
    jobs, _identity, owner, _worker, customer, site = stores
    tab = jobs.create_job(owner.employee_id, customer.customer_id, site.site_id, "tab-testing", job_date=date(2026, 8, 13))
    with pytest.raises(ValueError, match="TAB"):
        jobs.classify(owner.employee_id, tab.job_id, "potential-member", source="manual")
    service = jobs.create_job(owner.employee_id, customer.customer_id, site.site_id, "hvac-service", job_date=date(2026, 8, 13))
    assert jobs.derive_age_classification(service.job_id, date(2023, 8, 13), confirmed=True) == "system-age-0-3"
    assert jobs.derive_age_classification(service.job_id, date(2020, 8, 12), confirmed=True) == "system-age-4-7"
    assert jobs.derive_age_classification(service.job_id, date(2018, 8, 13), confirmed=True) == "system-age-8-plus"
    assert jobs.derive_age_classification(service.job_id, None, confirmed=False) is None
    jobs.classify(owner.employee_id, service.job_id, "system-age-0-3", source="confirmed-equipment-date")
    jobs.classify(owner.employee_id, service.job_id, "system-age-8-plus", source="confirmed-equipment-date")
    assert jobs.current_classifications(service.job_id) == ("system-age-8-plus",)
