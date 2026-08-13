from dataclasses import replace

import pytest

from scs_data.authorization import Permission, ScsAuthorizer, ScsPrincipal
from scs_data.config import ScsPaths
from scs_data.customers import ScsCustomerStore
from scs_data.identity import ScsIdentityStore
from shared_platform.application import ApplicationContext


def principal(*, roles=(), functions=()):
    return ScsPrincipal("scs_emp_test", tuple(roles), tuple(functions), "active")


def test_authorization_is_deny_by_default_and_owner_has_every_permission():
    authorizer = ScsAuthorizer()
    with pytest.raises(PermissionError):
        authorizer.require(principal(roles=("read_only",)), Permission.MANAGE_EMPLOYEES)
    for permission in Permission:
        authorizer.require(principal(roles=("owner",)), permission)


def test_multiple_roles_union_permissions_without_granting_owner_actions():
    actor = principal(roles=("billing", "estimator"))
    auth = ScsAuthorizer()
    auth.require(actor, Permission.VIEW_FINANCIALS)
    auth.require(actor, Permission.EDIT_ESTIMATES)
    with pytest.raises(PermissionError):
        auth.require(actor, Permission.MANAGE_OPERATIONS_ADMINS)


@pytest.mark.parametrize("roles,functions", [
    (("owner",), ()),
    (("operations_admin",), ()),
    ((), ("service_manager",)),
    ((), ("installation_manager",)),
])
def test_approved_management_group_can_view_and_change_technician_level(roles, functions):
    actor = principal(roles=roles, functions=functions)
    auth = ScsAuthorizer()
    auth.require(actor, Permission.VIEW_TECHNICIAN_LEVEL)
    auth.require(actor, Permission.MANAGE_TECHNICIAN_LEVEL)


def test_technicians_and_other_managers_cannot_view_technician_level():
    auth = ScsAuthorizer()
    for actor in (
        principal(functions=("service_technician",)),
        principal(roles=("billing",)),
        principal(functions=("tab_supervisor",)),
    ):
        with pytest.raises(PermissionError):
            auth.require(actor, Permission.VIEW_TECHNICIAN_LEVEL)


def test_inactive_principal_is_always_denied():
    with pytest.raises(PermissionError, match="inactive"):
        ScsAuthorizer().require(
            replace(principal(roles=("owner",)), status="disabled"),
            Permission.VIEW_CUSTOMERS,
        )
def test_domain_mutations_reject_bare_unauthorized_employee(tmp_path):
    context = ApplicationContext("scs", (tmp_path / "SCS_DATA").resolve(), "SCS", "SCS", "scs_employee_session", "https://ai.sunshineclimatesolutions.com", 8100, 3100)
    identity = ScsIdentityStore(ScsPaths.from_context(context).ensure().database)
    owner = identity.bootstrap_owner("owner@example.com", "owner", "Owner", "owner-password")
    customers = ScsCustomerStore(identity.conn, identity.audit)
    reader = identity.create_active_employee_for_bootstrap(owner.employee_id, "reader2@example.com", "reader2", "Reader", "reader-password", ("read_only",))
    with pytest.raises(PermissionError):
        customers.create_customer(reader.employee_id, "Forbidden", "commercial")
    identity.close()
