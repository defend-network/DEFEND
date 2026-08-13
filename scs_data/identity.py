from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import uuid

from defend_data.identity_security import (
    hash_password, new_token, normalize_email, token_hash, verify_password,
)
from defend_data.sqlite_utils import connect_sqlite, transaction

from .audit import ScsAuditStore
from .migrations import ScsMigrator


ROLES = frozenset({"owner", "operations_admin", "billing", "estimator", "reviewer", "read_only"})
FUNCTIONS = frozenset({
    "apprentice", "service_technician", "maintenance_technician", "installation_technician",
    "sales_technician", "salesperson", "tab_technician", "tab_supervisor",
    "service_manager", "installation_manager",
})
TECH_LEVELS = frozenset({"apprentice", "technician_i", "technician_ii", "technician_iii"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class EmployeeRecord:
    employee_id: str
    email: str
    username: str | None
    display_name: str
    status: str
    roles: tuple[str, ...]


@dataclass(frozen=True)
class InvitationRecord:
    invitation_id: str
    employee_id: str
    email: str
    expires_at: str


class ScsIdentityStore:
    def __init__(self, database: Path) -> None:
        self.conn = connect_sqlite(database)
        ScsMigrator(self.conn).apply()
        self.audit = ScsAuditStore(self.conn)

    def close(self) -> None:
        self.conn.close()

    def _roles(self, employee_id: str) -> tuple[str, ...]:
        rows = self.conn.execute(
            "SELECT role FROM scs_employee_roles WHERE employee_id=? AND revoked_at IS NULL ORDER BY role",
            (employee_id,),
        ).fetchall()
        return tuple(row[0] for row in rows)

    def _record(self, employee_id: str) -> EmployeeRecord:
        row = self.conn.execute("SELECT * FROM scs_employees WHERE employee_id=?", (employee_id,)).fetchone()
        if row is None:
            raise KeyError("SCS employee not found")
        return EmployeeRecord(row["employee_id"], row["email"], row["username"], row["display_name"], row["status"], self._roles(employee_id))

    def bootstrap_owner(self, email: str, username: str, display_name: str, password: str) -> EmployeeRecord:
        normalized = normalize_email(email)
        existing = self.conn.execute(
            "SELECT e.employee_id,e.email FROM scs_employees e JOIN scs_employee_roles r ON r.employee_id=e.employee_id WHERE r.role='owner' AND r.revoked_at IS NULL"
        ).fetchone()
        if existing:
            if existing["email"] == normalized:
                return self._record(existing["employee_id"])
            raise ValueError("owner already exists")
        employee_id = "scs_emp_" + uuid.uuid4().hex
        now = _now().isoformat()
        with transaction(self.conn, immediate=True):
            self.conn.execute("INSERT INTO scs_employees VALUES (?,?,?,?,?,?,?,?)", (employee_id, normalized, username, display_name, hash_password(password), "active", now, now))
            self.conn.execute("INSERT INTO scs_employee_roles VALUES (?,?,?,?,NULL)", (employee_id, "owner", employee_id, now))
        self.audit.append(employee_id, "identity.owner_bootstrapped", "employee", employee_id)
        return self._record(employee_id)

    def _assert_actor(self, actor_id: str, *, owner_only: bool = False) -> EmployeeRecord:
        actor = self._record(actor_id)
        allowed = {"owner"} if owner_only else {"owner", "operations_admin"}
        if actor.status != "active" or not allowed.intersection(actor.roles):
            raise PermissionError("active owner or operations admin required")
        return actor

    def invite_employee(self, actor_id: str, email: str, display_name: str, roles: tuple[str, ...], *, expires_at: datetime | None = None) -> tuple[InvitationRecord, str]:
        actor = self._assert_actor(actor_id)
        requested = tuple(sorted(set(roles)))
        if not requested or not set(requested) <= ROLES - {"owner"}:
            raise ValueError("invalid employee roles")
        if "operations_admin" in requested and "owner" not in actor.roles:
            raise PermissionError("owner required for operations admin role")
        normalized = normalize_email(email)
        employee_id = "scs_emp_" + uuid.uuid4().hex
        invitation_id = "scs_inv_" + uuid.uuid4().hex
        raw, hashed = new_token("scsinvite")
        now = _now()
        expiry = expires_at or now + timedelta(days=7)
        with transaction(self.conn, immediate=True):
            self.conn.execute("INSERT INTO scs_employees VALUES (?,?,?,?,?,?,?,?)", (employee_id, normalized, None, display_name, None, "invited", now.isoformat(), now.isoformat()))
            self.conn.execute("INSERT INTO scs_invitations VALUES (?,?,?,?,?,?,NULL,NULL)", (invitation_id, employee_id, hashed, actor_id, now.isoformat(), expiry.astimezone(timezone.utc).isoformat()))
            self.conn.executemany("INSERT INTO scs_invitation_roles VALUES (?,?)", ((invitation_id, role) for role in requested))
        self.audit.append(actor_id, "identity.employee_invited", "employee", employee_id, {"roles": list(requested)})
        return InvitationRecord(invitation_id, employee_id, normalized, expiry.isoformat()), raw

    def activate_invitation(self, raw_token: str, *, username: str, password: str) -> EmployeeRecord:
        row = self.conn.execute("SELECT * FROM scs_invitations WHERE token_hash=?", (token_hash(raw_token),)).fetchone()
        now = _now()
        if row is None or row["accepted_at"] or row["revoked_at"] or datetime.fromisoformat(row["expires_at"]) <= now:
            raise ValueError("invalid invitation")
        roles = [item[0] for item in self.conn.execute("SELECT role FROM scs_invitation_roles WHERE invitation_id=?", (row["invitation_id"],))]
        with transaction(self.conn, immediate=True):
            self.conn.execute("UPDATE scs_employees SET username=?,password_hash=?,status='active',updated_at=? WHERE employee_id=?", (username, hash_password(password), now.isoformat(), row["employee_id"]))
            self.conn.executemany("INSERT INTO scs_employee_roles VALUES (?,?,?,?,NULL)", ((row["employee_id"], role, row["created_by"], now.isoformat()) for role in roles))
            self.conn.execute("UPDATE scs_invitations SET accepted_at=? WHERE invitation_id=?", (now.isoformat(), row["invitation_id"]))
        self.audit.append(row["employee_id"], "identity.invitation_accepted", "employee", row["employee_id"])
        return self._record(row["employee_id"])

    def create_active_employee_for_bootstrap(self, actor_id: str, email: str, username: str, display_name: str, password: str, roles: tuple[str, ...]) -> EmployeeRecord:
        invitation, token = self.invite_employee(actor_id, email, display_name, roles)
        return self.activate_invitation(token, username=username, password=password)

    def authenticate(self, identifier: str, password: str) -> EmployeeRecord | None:
        normalized = identifier.strip().casefold()
        row = self.conn.execute("SELECT * FROM scs_employees WHERE email=? OR lower(username)=?", (normalized, normalized)).fetchone()
        if row is None or row["status"] != "active" or not row["password_hash"] or not verify_password(password, row["password_hash"]):
            return None
        return self._record(row["employee_id"])

    def create_session(self, employee_id: str, *, expires_at: datetime | None = None) -> str:
        employee = self._record(employee_id)
        if employee.status != "active":
            raise PermissionError("inactive employee")
        raw, hashed = new_token("scssession")
        now = _now()
        expiry = expires_at or now + timedelta(hours=12)
        self.conn.execute("INSERT INTO scs_sessions VALUES (?,?,?,?,NULL)", (hashed, employee_id, now.isoformat(), expiry.astimezone(timezone.utc).isoformat()))
        self.conn.commit()
        return raw

    def resolve_session(self, raw_token: str) -> EmployeeRecord | None:
        row = self.conn.execute("SELECT * FROM scs_sessions WHERE session_hash=?", (token_hash(raw_token),)).fetchone()
        if row is None or row["revoked_at"] or datetime.fromisoformat(row["expires_at"]) <= _now():
            return None
        employee = self._record(row["employee_id"])
        return employee if employee.status == "active" else None

    def revoke_session(self, raw_token: str) -> bool:
        result = self.conn.execute("UPDATE scs_sessions SET revoked_at=? WHERE session_hash=? AND revoked_at IS NULL", (_now().isoformat(), token_hash(raw_token)))
        self.conn.commit()
        return result.rowcount == 1

    def set_roles(self, actor_id: str, employee_id: str, roles: tuple[str, ...]) -> EmployeeRecord:
        actor = self._assert_actor(actor_id)
        requested = tuple(sorted(set(roles)))
        if not requested or not set(requested) <= ROLES - {"owner"}:
            raise ValueError("invalid employee roles")
        current = set(self._roles(employee_id))
        if ("operations_admin" in current or "operations_admin" in requested) and "owner" not in actor.roles:
            raise PermissionError("owner required for operations admin role")
        now = _now().isoformat()
        with transaction(self.conn, immediate=True):
            self.conn.execute("UPDATE scs_employee_roles SET revoked_at=? WHERE employee_id=? AND revoked_at IS NULL", (now, employee_id))
            self.conn.executemany("INSERT INTO scs_employee_roles VALUES (?,?,?,?,NULL)", ((employee_id, role, actor_id, now) for role in requested))
        self.audit.append(actor_id, "identity.roles_changed", "employee", employee_id, {"roles": list(requested)})
        return self._record(employee_id)

    def assign_function(self, actor_id: str, employee_id: str, function_code: str) -> None:
        self._assert_actor(actor_id)
        if function_code not in FUNCTIONS:
            raise ValueError("invalid job function")
        if function_code in self.current_functions(employee_id):
            return
        self.conn.execute("INSERT INTO scs_function_history VALUES (?,?,?,?,?,NULL)", ("scs_fun_" + uuid.uuid4().hex, employee_id, function_code, actor_id, _now().isoformat()))
        self.conn.commit()
        self.audit.append(actor_id, "identity.function_assigned", "employee", employee_id, {"function": function_code})

    def current_functions(self, employee_id: str) -> tuple[str, ...]:
        rows = self.conn.execute("SELECT function_code FROM scs_function_history WHERE employee_id=? AND ended_at IS NULL ORDER BY function_code", (employee_id,)).fetchall()
        return tuple(row[0] for row in rows)

    def set_technician_level(self, actor_id: str, employee_id: str, level_code: str) -> None:
        actor = self._record(actor_id)
        functions = set(self.current_functions(actor_id))
        if actor.status != "active" or not ({"owner", "operations_admin"}.intersection(actor.roles) or {"service_manager", "installation_manager"}.intersection(functions)):
            raise PermissionError("technician level manager required")
        if level_code not in TECH_LEVELS:
            raise ValueError("invalid technician level")
        self.conn.execute("INSERT INTO scs_technician_level_history VALUES (?,?,?,?,?)", ("scs_lvl_" + uuid.uuid4().hex, employee_id, level_code, actor_id, _now().isoformat()))
        self.conn.commit()
        self.audit.append(actor_id, "identity.technician_level_changed", "employee", employee_id, {"level": level_code})

    def current_technician_level(self, employee_id: str) -> str | None:
        row = self.conn.execute("SELECT level_code FROM scs_technician_level_history WHERE employee_id=? ORDER BY effective_at DESC, rowid DESC LIMIT 1", (employee_id,)).fetchone()
        return row[0] if row else None
