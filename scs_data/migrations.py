from __future__ import annotations

from datetime import datetime, timezone
import sqlite3

from defend_data.sqlite_utils import transaction


_MIGRATIONS = {
    1: """
        CREATE TABLE IF NOT EXISTS scs_application_metadata (
            singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
            application_id TEXT NOT NULL CHECK(application_id = 'scs')
        );
        INSERT OR IGNORE INTO scs_application_metadata(singleton, application_id)
        VALUES (1, 'scs');
    """,
    2: """
        CREATE TABLE scs_employees (
            employee_id TEXT PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            username TEXT UNIQUE,
            display_name TEXT NOT NULL,
            password_hash TEXT,
            status TEXT NOT NULL CHECK(status IN ('invited','active','disabled')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE scs_employee_roles (
            employee_id TEXT NOT NULL REFERENCES scs_employees(employee_id),
            role TEXT NOT NULL,
            granted_by TEXT NOT NULL,
            granted_at TEXT NOT NULL,
            revoked_at TEXT,
            PRIMARY KEY(employee_id, role, granted_at)
        );
        CREATE UNIQUE INDEX scs_one_active_owner
            ON scs_employee_roles(role) WHERE role='owner' AND revoked_at IS NULL;
        CREATE TABLE scs_invitations (
            invitation_id TEXT PRIMARY KEY,
            employee_id TEXT NOT NULL REFERENCES scs_employees(employee_id),
            token_hash TEXT NOT NULL UNIQUE,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            accepted_at TEXT,
            revoked_at TEXT
        );
        CREATE TABLE scs_invitation_roles (
            invitation_id TEXT NOT NULL REFERENCES scs_invitations(invitation_id),
            role TEXT NOT NULL,
            PRIMARY KEY(invitation_id, role)
        );
        CREATE TABLE scs_sessions (
            session_hash TEXT PRIMARY KEY,
            employee_id TEXT NOT NULL REFERENCES scs_employees(employee_id),
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            revoked_at TEXT
        );
        CREATE TABLE scs_function_history (
            event_id TEXT PRIMARY KEY,
            employee_id TEXT NOT NULL REFERENCES scs_employees(employee_id),
            function_code TEXT NOT NULL,
            assigned_by TEXT NOT NULL,
            effective_at TEXT NOT NULL,
            ended_at TEXT
        );
        CREATE TABLE scs_technician_level_history (
            event_id TEXT PRIMARY KEY,
            employee_id TEXT NOT NULL REFERENCES scs_employees(employee_id),
            level_code TEXT NOT NULL,
            changed_by TEXT NOT NULL,
            effective_at TEXT NOT NULL
        );
        CREATE TABLE scs_audit_events (
            event_id TEXT PRIMARY KEY,
            actor_id TEXT,
            event_type TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id TEXT,
            metadata_json TEXT NOT NULL,
            occurred_at TEXT NOT NULL
        );
    """,
    3: """
        CREATE TABLE scs_customers (
            customer_id TEXT PRIMARY KEY, display_name TEXT NOT NULL,
            legal_name TEXT, customer_type TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('prospect','active','inactive','archived')),
            communication_preferences TEXT NOT NULL DEFAULT '{}', internal_notes TEXT,
            created_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE scs_contacts (
            contact_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES scs_customers(customer_id),
            name TEXT NOT NULL, email TEXT, phone TEXT, purpose TEXT NOT NULL,
            preferences TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'active',
            created_by TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE scs_sites (
            site_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES scs_customers(customer_id),
            name TEXT NOT NULL, service_address TEXT NOT NULL, billing_address TEXT,
            timezone TEXT NOT NULL, access_instructions TEXT,
            status TEXT NOT NULL DEFAULT 'active', created_by TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE scs_equipment (
            equipment_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES scs_customers(customer_id),
            site_id TEXT NOT NULL REFERENCES scs_sites(site_id), equipment_type TEXT NOT NULL,
            manufacturer TEXT, model TEXT, serial_number TEXT, install_date TEXT,
            manufacture_date TEXT, status TEXT NOT NULL, location TEXT, notes TEXT,
            created_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE scs_equipment_history (
            event_id TEXT PRIMARY KEY, equipment_id TEXT NOT NULL REFERENCES scs_equipment(equipment_id),
            snapshot_json TEXT NOT NULL, changed_by TEXT NOT NULL, changed_at TEXT NOT NULL
        );
        CREATE INDEX idx_scs_customers_name ON scs_customers(display_name);
        CREATE INDEX idx_scs_contacts_customer ON scs_contacts(customer_id);
        CREATE INDEX idx_scs_sites_customer ON scs_sites(customer_id);
        CREATE INDEX idx_scs_equipment_customer_site ON scs_equipment(customer_id,site_id);
    """,
}


class ScsMigrator:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def apply(self) -> int:
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS scs_schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )"""
        )
        applied = {
            int(row[0])
            for row in self.conn.execute("SELECT version FROM scs_schema_migrations")
        }
        for version, script in sorted(_MIGRATIONS.items()):
            if version in applied:
                continue
            with transaction(self.conn, immediate=True):
                for statement in script.split(";"):
                    if statement.strip():
                        self.conn.execute(statement)
                self.conn.execute(
                    "INSERT INTO scs_schema_migrations(version, applied_at) VALUES (?, ?)",
                    (version, datetime.now(timezone.utc).isoformat()),
                )
        return self.current_version()

    def current_version(self) -> int:
        row = self.conn.execute("SELECT COALESCE(MAX(version), 0) FROM scs_schema_migrations").fetchone()
        return int(row[0])
