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
