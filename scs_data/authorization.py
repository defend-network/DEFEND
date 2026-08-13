from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Permission(StrEnum):
    VIEW_CUSTOMERS = "view_customers"
    EDIT_CUSTOMERS = "edit_customers"
    VIEW_FINANCIALS = "view_financials"
    EDIT_ESTIMATES = "edit_estimates"
    REVIEW_REPORTS = "review_reports"
    MANAGE_EMPLOYEES = "manage_employees"
    MANAGE_OPERATIONS_ADMINS = "manage_operations_admins"
    VIEW_TECHNICIAN_LEVEL = "view_technician_level"
    MANAGE_TECHNICIAN_LEVEL = "manage_technician_level"
    VIEW_AUDIT = "view_audit"
    VIEW_ALL_JOBS = "view_all_jobs"


@dataclass(frozen=True)
class ScsPrincipal:
    employee_id: str
    roles: tuple[str, ...]
    functions: tuple[str, ...]
    status: str


_ROLE_PERMISSIONS = {
    "operations_admin": {
        Permission.VIEW_CUSTOMERS, Permission.EDIT_CUSTOMERS, Permission.MANAGE_EMPLOYEES,
        Permission.VIEW_TECHNICIAN_LEVEL, Permission.MANAGE_TECHNICIAN_LEVEL,
        Permission.VIEW_AUDIT, Permission.VIEW_ALL_JOBS,
    },
    "billing": {Permission.VIEW_CUSTOMERS, Permission.VIEW_FINANCIALS},
    "estimator": {Permission.VIEW_CUSTOMERS, Permission.EDIT_ESTIMATES},
    "reviewer": {Permission.VIEW_CUSTOMERS, Permission.REVIEW_REPORTS},
    "read_only": {Permission.VIEW_CUSTOMERS},
}
_TECH_MANAGERS = frozenset({"service_manager", "installation_manager"})


class ScsAuthorizer:
    def permissions(self, principal: ScsPrincipal) -> frozenset[Permission]:
        if principal.status != "active":
            return frozenset()
        if "owner" in principal.roles:
            return frozenset(Permission)
        granted: set[Permission] = set()
        for role in principal.roles:
            granted.update(_ROLE_PERMISSIONS.get(role, set()))
        if _TECH_MANAGERS.intersection(principal.functions):
            granted.update({Permission.VIEW_TECHNICIAN_LEVEL, Permission.MANAGE_TECHNICIAN_LEVEL, Permission.VIEW_ALL_JOBS})
        return frozenset(granted)

    def require(self, principal: ScsPrincipal, permission: Permission) -> None:
        if principal.status != "active":
            raise PermissionError("inactive SCS principal")
        if permission not in self.permissions(principal):
            raise PermissionError("SCS permission denied")
