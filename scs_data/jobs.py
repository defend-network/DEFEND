from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import sqlite3
import uuid

from defend_data.sqlite_utils import transaction

from .audit import ScsAuditStore
from .authorization import Permission, ScsAuthorizer, ScsPrincipal, require_actor


JOB_TYPES = frozenset({
    "hvac-service", "preventive-maintenance", "installation-replacement",
    "warranty-callback", "sales-estimate", "tab-testing", "tab-reporting",
    "commissioning-support", "internal-non-billable",
})
JOB_STATUSES = frozenset({"new", "scheduled", "in-progress", "on-hold", "completed", "cancelled"})
NOTE_VISIBILITIES = frozenset({"operational", "management-only", "billing-only", "future-customer-safe"})
AGE_CODES = frozenset({"system-age-0-3", "system-age-4-7", "system-age-8-plus"})
CLASSIFICATION_CODES = frozenset({"new-customer", "potential-member"}) | AGE_CODES | JOB_TYPES


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Job:
    job_id: str; customer_id: str; site_id: str; job_type: str; job_date: str; status: str; priority: str


@dataclass(frozen=True)
class JobVisit:
    visit_id: str; job_id: str; work_performed: str; findings: str | None; recommendations: str | None; readings_summary: str | None


@dataclass(frozen=True)
class JobAssignment:
    assignment_id: str; job_id: str; employee_id: str; assignment_role: str; effective_at: str; ended_at: str | None


@dataclass(frozen=True)
class JobNote:
    note_id: str; job_id: str; body: str; visibility: str; author_id: str; created_at: str


class ScsJobStore:
    def __init__(self, conn: sqlite3.Connection, audit: ScsAuditStore) -> None:
        self.conn = conn
        self.audit = audit

    def create_job(self, actor_id: str, customer_id: str, site_id: str, job_type: str, *, job_date: date, priority: str = "normal", requested_scope: str | None = None, discipline: str | None = None) -> Job:
        require_actor(self.conn, actor_id, Permission.MANAGE_JOBS)
        if job_type not in JOB_TYPES:
            raise ValueError("invalid job type")
        row = self.conn.execute("SELECT customer_id FROM scs_sites WHERE site_id=?", (site_id,)).fetchone()
        if row is None or row[0] != customer_id:
            raise ValueError("job site must belong to the same customer")
        job_id = "scs_job_" + uuid.uuid4().hex
        now = _now()
        with transaction(self.conn, immediate=True):
            self.conn.execute("INSERT INTO scs_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (job_id, customer_id, site_id, job_type, job_date.isoformat(), requested_scope, priority, discipline, None, None, actor_id, now))
            self._status_event(job_id, "new", actor_id, now)
        self.audit.append(actor_id, "job.created", "job", job_id, {"job_type": job_type})
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> Job:
        row = self.conn.execute("""SELECT j.*,s.status FROM scs_jobs j JOIN scs_job_status_events s ON s.job_id=j.job_id
            WHERE j.job_id=? ORDER BY s.occurred_at DESC,s.rowid DESC LIMIT 1""", (job_id,)).fetchone()
        if row is None:
            raise KeyError("job not found")
        return Job(row["job_id"], row["customer_id"], row["site_id"], row["job_type"], row["job_date"], row["status"], row["priority"])

    def change_status(self, actor_id: str, job_id: str, status: str) -> Job:
        self._require_job_worker(actor_id, job_id)
        self.get_job(job_id)
        if status not in JOB_STATUSES:
            raise ValueError("invalid job status")
        self._status_event(job_id, status, actor_id, _now())
        self.conn.commit()
        self.audit.append(actor_id, "job.status_changed", "job", job_id, {"status": status})
        return self.get_job(job_id)

    def status_history(self, job_id: str) -> tuple[str, ...]:
        self.get_job(job_id)
        return tuple(row[0] for row in self.conn.execute("SELECT status FROM scs_job_status_events WHERE job_id=? ORDER BY occurred_at,rowid", (job_id,)))

    def add_visit(self, actor_id: str, job_id: str, *, work_performed: str, findings: str | None = None, recommendations: str | None = None, readings_summary: str | None = None) -> JobVisit:
        self._require_job_worker(actor_id, job_id)
        self.get_job(job_id)
        visit_id = "scs_vis_" + uuid.uuid4().hex
        self.conn.execute("INSERT INTO scs_job_visits VALUES (?,?,?,?,?,?,?,?,?,?)", (visit_id, job_id, work_performed, findings, recommendations, readings_summary, None, None, actor_id, _now()))
        self.conn.commit()
        self.audit.append(actor_id, "job.visit_added", "job", job_id, {"visit_id": visit_id})
        return JobVisit(visit_id, job_id, work_performed, findings, recommendations, readings_summary)

    def assign(self, actor_id: str, job_id: str, employee_id: str, assignment_role: str) -> JobAssignment:
        require_actor(self.conn, actor_id, Permission.MANAGE_JOBS)
        self.get_job(job_id)
        if self.conn.execute("SELECT 1 FROM scs_employees WHERE employee_id=? AND status='active'", (employee_id,)).fetchone() is None:
            raise ValueError("active employee required")
        assignment_id = "scs_asn_" + uuid.uuid4().hex
        now = _now()
        self.conn.execute("INSERT INTO scs_job_assignments VALUES (?,?,?,?,?,?,NULL)", (assignment_id, job_id, employee_id, assignment_role, actor_id, now))
        self.conn.commit()
        self.audit.append(actor_id, "job.assigned", "job", job_id, {"employee_id": employee_id, "assignment_role": assignment_role})
        return JobAssignment(assignment_id, job_id, employee_id, assignment_role, now, None)

    def end_assignment(self, actor_id: str, assignment_id: str) -> None:
        require_actor(self.conn, actor_id, Permission.MANAGE_JOBS)
        now = _now()
        result = self.conn.execute("UPDATE scs_job_assignments SET ended_at=? WHERE assignment_id=? AND ended_at IS NULL", (now, assignment_id))
        self.conn.commit()
        if result.rowcount != 1:
            raise KeyError("active assignment not found")
        self.audit.append(actor_id, "job.assignment_ended", "assignment", assignment_id)

    def visible_jobs(self, principal: ScsPrincipal) -> tuple[Job, ...]:
        if Permission.VIEW_ALL_JOBS in ScsAuthorizer().permissions(principal):
            rows = self.conn.execute("SELECT job_id FROM scs_jobs ORDER BY job_date,created_at").fetchall()
        else:
            rows = self.conn.execute("""SELECT DISTINCT j.job_id FROM scs_jobs j JOIN scs_job_assignments a ON a.job_id=j.job_id
                WHERE a.employee_id=? AND a.ended_at IS NULL ORDER BY j.job_date,j.created_at""", (principal.employee_id,)).fetchall()
        return tuple(self.get_job(row[0]) for row in rows)

    def visible_job(self, principal: ScsPrincipal, job_id: str) -> Job:
        if not any(item.job_id == job_id for item in self.visible_jobs(principal)):
            raise KeyError("job not found")
        return self.get_job(job_id)

    def add_note(self, actor_id: str, job_id: str, body: str, visibility: str) -> JobNote:
        principal = self._require_job_worker(actor_id, job_id)
        if visibility in {"management-only", "billing-only"} and Permission.MANAGE_JOBS not in ScsAuthorizer().permissions(principal):
            raise PermissionError("restricted note visibility")
        self.get_job(job_id)
        if visibility not in NOTE_VISIBILITIES:
            raise ValueError("invalid note visibility")
        note_id = "scs_note_" + uuid.uuid4().hex
        now = _now()
        self.conn.execute("INSERT INTO scs_job_notes VALUES (?,?,?,?,?,?)", (note_id, job_id, body, visibility, actor_id, now))
        self.conn.commit()
        self.audit.append(actor_id, "job.note_added", "job", job_id, {"note_id": note_id, "visibility": visibility})
        return JobNote(note_id, job_id, body, visibility, actor_id, now)

    def visible_notes(self, principal: ScsPrincipal, job_id: str) -> tuple[JobNote, ...]:
        self.visible_job(principal, job_id)
        permissions = ScsAuthorizer().permissions(principal)
        allowed = {"operational", "future-customer-safe"}
        if "owner" in principal.roles or "operations_admin" in principal.roles or {"service_manager", "installation_manager"}.intersection(principal.functions):
            allowed.add("management-only")
        if Permission.VIEW_FINANCIALS in permissions:
            allowed.add("billing-only")
        placeholders = ",".join("?" for _ in allowed)
        rows = self.conn.execute(f"SELECT * FROM scs_job_notes WHERE job_id=? AND visibility IN ({placeholders}) ORDER BY created_at,rowid", (job_id, *sorted(allowed))).fetchall()
        return tuple(JobNote(row["note_id"], row["job_id"], row["body"], row["visibility"], row["author_id"], row["created_at"]) for row in rows)

    def visible_visits(self, principal: ScsPrincipal, job_id: str) -> tuple[JobVisit, ...]:
        self.visible_job(principal, job_id)
        rows = self.conn.execute(
            "SELECT * FROM scs_job_visits WHERE job_id=? ORDER BY rowid", (job_id,)
        ).fetchall()
        return tuple(
            JobVisit(
                row["visit_id"], row["job_id"], row["work_performed"],
                row["findings"], row["recommendations"], row["readings_summary"],
            )
            for row in rows
        )

    def classify(self, actor_id: str, job_id: str, code: str, *, source: str) -> None:
        require_actor(self.conn, actor_id, Permission.MANAGE_JOBS)
        job = self.get_job(job_id)
        if code not in CLASSIFICATION_CODES:
            raise ValueError("invalid classification")
        if code == "potential-member" and job.job_type in {"tab-testing", "tab-reporting"}:
            raise ValueError("potential-member is invalid for TAB-only jobs")
        now = _now()
        with transaction(self.conn, immediate=True):
            if code in AGE_CODES:
                for old in AGE_CODES:
                    if old != code and old in self.current_classifications(job_id):
                        self._classification_event(job_id, old, False, source, actor_id, now)
            if code not in self.current_classifications(job_id):
                self._classification_event(job_id, code, True, source, actor_id, now)
        self.audit.append(actor_id, "job.classified", "job", job_id, {"code": code, "source": source})

    def current_classifications(self, job_id: str) -> tuple[str, ...]:
        self.get_job(job_id)
        rows = self.conn.execute("""SELECT e.code,e.active FROM scs_job_classification_events e
            WHERE e.job_id=? AND e.rowid=(SELECT MAX(x.rowid) FROM scs_job_classification_events x WHERE x.job_id=e.job_id AND x.code=e.code)
            ORDER BY e.code""", (job_id,)).fetchall()
        return tuple(row["code"] for row in rows if row["active"])

    def derive_age_classification(self, job_id: str, source_date: date | None, *, confirmed: bool) -> str | None:
        if not confirmed or source_date is None:
            return None
        job_date = date.fromisoformat(self.get_job(job_id).job_date)
        if source_date > job_date:
            return None
        years = job_date.year - source_date.year - ((job_date.month, job_date.day) < (source_date.month, source_date.day))
        if years <= 3:
            return "system-age-0-3"
        if years <= 7:
            return "system-age-4-7"
        return "system-age-8-plus"

    def _status_event(self, job_id: str, status: str, actor_id: str, when: str) -> None:
        self.conn.execute("INSERT INTO scs_job_status_events VALUES (?,?,?,?,?)", ("scs_jse_" + uuid.uuid4().hex, job_id, status, actor_id, when))

    def _classification_event(self, job_id: str, code: str, active: bool, source: str, actor_id: str, when: str) -> None:
        self.conn.execute("INSERT INTO scs_job_classification_events VALUES (?,?,?,?,?,?,?)", ("scs_jcl_" + uuid.uuid4().hex, job_id, code, int(active), source, actor_id, when))

    def _require_job_worker(self, actor_id: str, job_id: str) -> ScsPrincipal:
        principal = require_actor(self.conn, actor_id, Permission.WORK_ASSIGNED_JOBS) if actor_id else None
        permissions = ScsAuthorizer().permissions(principal)
        if Permission.MANAGE_JOBS in permissions:
            return principal
        assigned = self.conn.execute("SELECT 1 FROM scs_job_assignments WHERE job_id=? AND employee_id=? AND ended_at IS NULL", (job_id, actor_id)).fetchone()
        if assigned is None:
            raise PermissionError("active job assignment required")
        return principal
