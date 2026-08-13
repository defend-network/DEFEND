from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import sqlite3
import uuid

from defend_data.sqlite_utils import json_dumps

from .audit import ScsAuditStore
from .authorization import Permission, require_actor


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Customer:
    customer_id: str; display_name: str; customer_type: str; status: str


@dataclass(frozen=True)
class Contact:
    contact_id: str; customer_id: str; name: str; email: str | None; purpose: str


@dataclass(frozen=True)
class Site:
    site_id: str; customer_id: str; name: str; service_address: str; billing_address: str | None; timezone: str


@dataclass(frozen=True)
class Equipment:
    equipment_id: str; customer_id: str; site_id: str; equipment_type: str
    manufacturer: str | None; model: str | None; serial_number: str | None
    status: str; notes: str | None


@dataclass(frozen=True)
class CustomerDetail:
    customer: Customer
    contacts: tuple[Contact, ...]
    sites: tuple[Site, ...]
    equipment: tuple[Equipment, ...]


class ScsCustomerStore:
    def __init__(self, conn: sqlite3.Connection, audit: ScsAuditStore) -> None:
        self.conn = conn; self.audit = audit

    def create_customer(self, actor_id: str, display_name: str, customer_type: str, *, legal_name: str | None = None, internal_notes: str | None = None) -> Customer:
        require_actor(self.conn, actor_id, Permission.EDIT_CUSTOMERS)
        if customer_type not in {"residential", "commercial", "government", "internal"}:
            raise ValueError("invalid customer type")
        if not display_name.strip(): raise ValueError("display name is required")
        customer_id = "scs_cus_" + uuid.uuid4().hex
        now = _now()
        self.conn.execute("INSERT INTO scs_customers VALUES (?,?,?,?,?,'{}',?,?,?,?)", (customer_id, display_name.strip(), legal_name, customer_type, "active", internal_notes, actor_id, now, now))
        self.conn.commit()
        self.audit.append(actor_id, "customer.created", "customer", customer_id, {"customer_type": customer_type})
        return Customer(customer_id, display_name.strip(), customer_type, "active")

    def add_contact(self, actor_id: str, customer_id: str, *, name: str, email: str | None, purpose: str, phone: str | None = None) -> Contact:
        require_actor(self.conn, actor_id, Permission.EDIT_CUSTOMERS)
        self._customer_row(customer_id)
        contact_id = "scs_con_" + uuid.uuid4().hex
        self.conn.execute("INSERT INTO scs_contacts(contact_id,customer_id,name,email,phone,purpose,created_by,created_at) VALUES (?,?,?,?,?,?,?,?)", (contact_id, customer_id, name, email, phone, purpose, actor_id, _now()))
        self.conn.commit(); self.audit.append(actor_id, "contact.created", "contact", contact_id, {"customer_id": customer_id})
        return Contact(contact_id, customer_id, name, email, purpose)

    def add_site(self, actor_id: str, customer_id: str, name: str, service_address: str, billing_address: str | None, timezone: str, access_instructions: str | None = None) -> Site:
        require_actor(self.conn, actor_id, Permission.EDIT_CUSTOMERS)
        self._customer_row(customer_id)
        site_id = "scs_site_" + uuid.uuid4().hex
        self.conn.execute("INSERT INTO scs_sites(site_id,customer_id,name,service_address,billing_address,timezone,access_instructions,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?)", (site_id, customer_id, name, service_address, billing_address, timezone, access_instructions, actor_id, _now()))
        self.conn.commit(); self.audit.append(actor_id, "site.created", "site", site_id, {"customer_id": customer_id})
        return Site(site_id, customer_id, name, service_address, billing_address, timezone)

    def add_equipment(self, actor_id: str, customer_id: str, site_id: str, *, equipment_type: str, manufacturer: str | None = None, model: str | None = None, serial_number: str | None = None, status: str = "active", notes: str | None = None) -> Equipment:
        require_actor(self.conn, actor_id, Permission.EDIT_CUSTOMERS)
        self._customer_row(customer_id)
        site = self.conn.execute("SELECT customer_id FROM scs_sites WHERE site_id=?", (site_id,)).fetchone()
        if site is None or site[0] != customer_id: raise ValueError("equipment and site must belong to the same customer")
        equipment_id = "scs_eq_" + uuid.uuid4().hex; now = _now()
        self.conn.execute("INSERT INTO scs_equipment(equipment_id,customer_id,site_id,equipment_type,manufacturer,model,serial_number,status,notes,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (equipment_id, customer_id, site_id, equipment_type, manufacturer, model, serial_number, status, notes, actor_id, now, now))
        item = Equipment(equipment_id, customer_id, site_id, equipment_type, manufacturer, model, serial_number, status, notes)
        self._equipment_event(item, actor_id, now); self.conn.commit()
        self.audit.append(actor_id, "equipment.created", "equipment", equipment_id, {"customer_id": customer_id, "site_id": site_id})
        return item

    def update_equipment(self, actor_id: str, equipment_id: str, *, status: str, notes: str | None = None) -> Equipment:
        require_actor(self.conn, actor_id, Permission.EDIT_CUSTOMERS)
        old = self.get_equipment(equipment_id); now = _now()
        self.conn.execute("UPDATE scs_equipment SET status=?,notes=?,updated_at=? WHERE equipment_id=?", (status, notes, now, equipment_id))
        item = Equipment(old.equipment_id, old.customer_id, old.site_id, old.equipment_type, old.manufacturer, old.model, old.serial_number, status, notes)
        self._equipment_event(item, actor_id, now); self.conn.commit()
        self.audit.append(actor_id, "equipment.updated", "equipment", equipment_id, {"status": status})
        return item

    def _equipment_event(self, item: Equipment, actor_id: str, when: str) -> None:
        self.conn.execute("INSERT INTO scs_equipment_history VALUES (?,?,?,?,?)", ("scs_eqh_" + uuid.uuid4().hex, item.equipment_id, json_dumps(asdict(item)), actor_id, when))

    def equipment_history_count(self, equipment_id: str) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM scs_equipment_history WHERE equipment_id=?", (equipment_id,)).fetchone()[0]

    def archive_customer(self, actor_id: str, customer_id: str) -> None:
        require_actor(self.conn, actor_id, Permission.EDIT_CUSTOMERS)
        self._customer_row(customer_id); self.conn.execute("UPDATE scs_customers SET status='archived',updated_at=? WHERE customer_id=?", (_now(), customer_id)); self.conn.commit()
        self.audit.append(actor_id, "customer.archived", "customer", customer_id)

    def search_customers(self, query: str, *, limit: int = 50) -> tuple[Customer, ...]:
        if not 1 <= limit <= 200: raise ValueError("search limit must be in 1..200")
        rows = self.conn.execute("SELECT * FROM scs_customers WHERE display_name LIKE ? ORDER BY display_name LIMIT ?", (f"%{query.strip()}%", limit)).fetchall()
        return tuple(self._customer(item) for item in rows)

    def get_customer(self, customer_id: str) -> CustomerDetail:
        customer = self._customer(self._customer_row(customer_id))
        contacts = tuple(Contact(row["contact_id"], row["customer_id"], row["name"], row["email"], row["purpose"]) for row in self.conn.execute("SELECT * FROM scs_contacts WHERE customer_id=? ORDER BY created_at", (customer_id,)))
        sites = tuple(Site(row["site_id"], row["customer_id"], row["name"], row["service_address"], row["billing_address"], row["timezone"]) for row in self.conn.execute("SELECT * FROM scs_sites WHERE customer_id=? ORDER BY created_at", (customer_id,)))
        equipment = tuple(self._equipment(row) for row in self.conn.execute("SELECT * FROM scs_equipment WHERE customer_id=? ORDER BY created_at", (customer_id,)))
        return CustomerDetail(customer, contacts, sites, equipment)

    def get_equipment(self, equipment_id: str) -> Equipment:
        row = self.conn.execute("SELECT * FROM scs_equipment WHERE equipment_id=?", (equipment_id,)).fetchone()
        if row is None: raise KeyError("equipment not found")
        return self._equipment(row)

    def _customer_row(self, customer_id: str):
        row = self.conn.execute("SELECT * FROM scs_customers WHERE customer_id=?", (customer_id,)).fetchone()
        if row is None: raise KeyError("customer not found")
        return row

    @staticmethod
    def _customer(row) -> Customer: return Customer(row["customer_id"], row["display_name"], row["customer_type"], row["status"])
    @staticmethod
    def _equipment(row) -> Equipment: return Equipment(row["equipment_id"], row["customer_id"], row["site_id"], row["equipment_type"], row["manufacturer"], row["model"], row["serial_number"], row["status"], row["notes"])
