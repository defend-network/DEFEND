from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import sqlite3
import uuid

from defend_data.sqlite_utils import transaction

from .audit import ScsAuditStore
from .authorization import Permission, require_actor


def _now() -> str: return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class MembershipPlan:
    plan_code: str; version: int; name: str; active: bool; effective_at: str


@dataclass(frozen=True)
class MembershipEnrollment:
    enrollment_id: str; customer_id: str; plan_code: str; plan_version: int
    status: str; start_date: str; end_date: str | None


class ScsMembershipStore:
    def __init__(self, conn: sqlite3.Connection, audit: ScsAuditStore) -> None:
        self.conn = conn; self.audit = audit

    def current_plan(self, plan_code: str) -> MembershipPlan:
        row = self.conn.execute("SELECT * FROM scs_membership_plan_versions WHERE plan_code=? ORDER BY version DESC LIMIT 1", (plan_code,)).fetchone()
        if row is None: raise KeyError("membership plan not found")
        return self._plan(row)

    def plan_version(self, plan_code: str, version: int) -> MembershipPlan:
        row = self.conn.execute("SELECT * FROM scs_membership_plan_versions WHERE plan_code=? AND version=?", (plan_code, version)).fetchone()
        if row is None: raise KeyError("membership plan version not found")
        return self._plan(row)

    def revise_plan(self, actor_id: str, plan_code: str, *, name: str, active: bool, effective_at: date | None = None) -> MembershipPlan:
        require_actor(self.conn, actor_id, Permission.EDIT_CUSTOMERS)
        current = self.current_plan(plan_code); version = current.version + 1; now = _now()
        self.conn.execute("INSERT INTO scs_membership_plan_versions VALUES (?,?,?,?,?,?,?)", (plan_code, version, name, int(active), (effective_at or date.today()).isoformat(), actor_id, now))
        self.conn.commit(); self.audit.append(actor_id, "membership.plan_revised", "membership_plan", plan_code, {"version": version, "active": active})
        return self.plan_version(plan_code, version)

    def enroll(self, actor_id: str, customer_id: str, plan_code: str, *, start_date: date, end_date: date | None = None, covered_site_ids: tuple[str, ...] = (), covered_equipment_ids: tuple[str, ...] = ()) -> MembershipEnrollment:
        require_actor(self.conn, actor_id, Permission.EDIT_CUSTOMERS)
        if end_date is not None and end_date < start_date: raise ValueError("membership end date must not precede start date")
        if self.conn.execute("SELECT 1 FROM scs_customers WHERE customer_id=?", (customer_id,)).fetchone() is None: raise KeyError("customer not found")
        plan = self.current_plan(plan_code)
        for site_id in covered_site_ids:
            row = self.conn.execute("SELECT customer_id FROM scs_sites WHERE site_id=?", (site_id,)).fetchone()
            if row is None or row[0] != customer_id: raise ValueError("membership coverage must belong to the same customer")
        for equipment_id in covered_equipment_ids:
            row = self.conn.execute("SELECT customer_id FROM scs_equipment WHERE equipment_id=?", (equipment_id,)).fetchone()
            if row is None or row[0] != customer_id: raise ValueError("membership coverage must belong to the same customer")
        enrollment_id = "scs_mem_" + uuid.uuid4().hex; now = _now()
        with transaction(self.conn, immediate=True):
            self.conn.execute("INSERT INTO scs_membership_enrollments VALUES (?,?,?,?,?,?,?,?)", (enrollment_id, customer_id, plan_code, plan.version, start_date.isoformat(), end_date.isoformat() if end_date else None, actor_id, now))
            self.conn.executemany("INSERT INTO scs_membership_coverage(enrollment_id,site_id,equipment_id) VALUES (?,?,NULL)", ((enrollment_id, value) for value in covered_site_ids))
            self.conn.executemany("INSERT INTO scs_membership_coverage(enrollment_id,site_id,equipment_id) VALUES (?,NULL,?)", ((enrollment_id, value) for value in covered_equipment_ids))
            self._insert_event(enrollment_id, "active", actor_id, now)
        self.audit.append(actor_id, "membership.enrolled", "membership_enrollment", enrollment_id, {"plan_code": plan_code, "plan_version": plan.version})
        return self.current_enrollment(enrollment_id)

    def change_status(self, actor_id: str, enrollment_id: str, status: str) -> MembershipEnrollment:
        require_actor(self.conn, actor_id, Permission.EDIT_CUSTOMERS)
        if status not in {"active", "paused", "expired", "cancelled"}: raise ValueError("invalid membership status")
        current = self.current_enrollment(enrollment_id)
        if current.status in {"expired", "cancelled"}: raise ValueError("terminal membership status cannot transition")
        self._insert_event(enrollment_id, status, actor_id, _now()); self.conn.commit()
        self.audit.append(actor_id, "membership.status_changed", "membership_enrollment", enrollment_id, {"status": status})
        return self.current_enrollment(enrollment_id)

    def current_enrollment(self, enrollment_id: str) -> MembershipEnrollment:
        row = self.conn.execute("""SELECT e.*,v.status FROM scs_membership_enrollments e
            JOIN scs_membership_enrollment_events v ON v.enrollment_id=e.enrollment_id
            WHERE e.enrollment_id=? ORDER BY v.occurred_at DESC,v.rowid DESC LIMIT 1""", (enrollment_id,)).fetchone()
        if row is None: raise KeyError("membership enrollment not found")
        return MembershipEnrollment(row["enrollment_id"], row["customer_id"], row["plan_code"], row["plan_version"], row["status"], row["start_date"], row["end_date"])

    def _insert_event(self, enrollment_id: str, status: str, actor_id: str, when: str) -> None:
        self.conn.execute("INSERT INTO scs_membership_enrollment_events VALUES (?,?,?,?,?)", ("scs_mev_" + uuid.uuid4().hex, enrollment_id, status, actor_id, when))

    @staticmethod
    def _plan(row) -> MembershipPlan:
        return MembershipPlan(row["plan_code"], row["version"], row["name"], bool(row["active"]), row["effective_at"])
