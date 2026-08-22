from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator


_MIGRATIONS = (
    (1, Path(__file__).with_name("migrations") / "0001_foundation.sql"),
    (2, Path(__file__).with_name("migrations") / "0002_runs.sql"),
    (3, Path(__file__).with_name("migrations") / "0003_run_phase.sql"),
    (4, Path(__file__).with_name("migrations") / "0004_run_reason.sql"),
    (
        5,
        Path(__file__).with_name("migrations")
        / "0005_completion_state_telemetry.sql",
    ),
    (
        6,
        Path(__file__).with_name("migrations")
        / "0006_run_routing.sql",
    ),
)


@dataclass(frozen=True)
class CoderDatabase:
    database_url: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.database_url, str) or not self.database_url.strip():
            raise ValueError("CODER_DATABASE_URL must be configured")

    @contextmanager
    def connect(self) -> Iterator[Any]:
        try:
            import psycopg
        except ImportError as error:
            raise RuntimeError(
                "psycopg is required for DEFENDcoder PostgreSQL access"
            ) from error

        with psycopg.connect(self.database_url) as connection:
            yield connection

    def migrate(self) -> int:
        with self.connect() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS coder_schema_migrations (
                            version INTEGER PRIMARY KEY CHECK (version > 0),
                            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                        )
                        """
                    )

                    cursor.execute(
                        "SELECT version FROM coder_schema_migrations"
                    )
                    applied = {int(row[0]) for row in cursor.fetchall()}

                    latest = _MIGRATIONS[-1][0]

                    if any(version > latest for version in applied):
                        raise RuntimeError(
                            "DEFENDcoder database schema is newer than "
                            "this application supports"
                        )

                    for version, migration_path in _MIGRATIONS:
                        if version in applied:
                            continue

                        for statement in _migration_statements(migration_path):
                            cursor.execute(statement)

                        cursor.execute(
                            """
                            INSERT INTO coder_schema_migrations(version)
                            VALUES (%s)
                            """,
                            (version,),
                        )

                    return _current_version(cursor)

    def health(self) -> dict[str, object]:
        try:
            with self.connect() as connection:
                with connection.cursor() as cursor:
                    version = _current_version(cursor)
        except Exception:
            return {
                "ok": False,
                "application_id": "coder",
                "schema_version": 0,
                "database": "unavailable",
            }

        return {
            "ok": version >= 1,
            "application_id": "coder",
            "schema_version": version,
            "database": "ready" if version >= 1 else "unavailable",
        }


def _migration_statements(path: Path) -> tuple[str, ...]:
    script = path.read_text(encoding="utf-8")
    return tuple(
        statement.strip()
        for statement in script.split(";")
        if statement.strip()
    )


def _current_version(cursor: Any) -> int:
    cursor.execute(
        "SELECT COALESCE(MAX(version), 0) "
        "FROM coder_schema_migrations"
    )
    row = cursor.fetchone()
    return int(row[0])
