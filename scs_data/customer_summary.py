from __future__ import annotations

from dataclasses import dataclass
import sqlite3


@dataclass(frozen=True)
class MetricValue:
    state: str
    value: int | float | None


@dataclass(frozen=True)
class CustomerSummary:
    customer_id: str
    site_count: int
    equipment_count: int
    job_count: int
    active_membership_count: int
    total_spend: MetricValue
    average_payment_days: MetricValue


class ScsCustomerSummaryService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def for_customer(self, customer_id: str) -> CustomerSummary:
        if self.conn.execute("SELECT 1 FROM scs_customers WHERE customer_id=?", (customer_id,)).fetchone() is None:
            raise KeyError("customer not found")
        count = lambda table: int(self.conn.execute(f"SELECT COUNT(*) FROM {table} WHERE customer_id=?", (customer_id,)).fetchone()[0])
        active_memberships = int(self.conn.execute("""SELECT COUNT(*) FROM scs_membership_enrollments e
            WHERE e.customer_id=? AND (SELECT status FROM scs_membership_enrollment_events v
            WHERE v.enrollment_id=e.enrollment_id ORDER BY occurred_at DESC,rowid DESC LIMIT 1)='active'""", (customer_id,)).fetchone()[0])
        unavailable = MetricValue("not_available", None)
        return CustomerSummary(customer_id, count("scs_sites"), count("scs_equipment"), count("scs_jobs"), active_memberships, unavailable, unavailable)
