from dataclasses import replace

import pytest

from scs_data.authorization import Permission, ScsAuthorizer, ScsPrincipal


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
