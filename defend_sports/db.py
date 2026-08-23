from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator


_MIGRATIONS = (
    (1, Path(__file__).with_name("migrations") / "0001_foundation.sql"),
    (2, Path(__file__).with_name("migrations") / "0002_quota_discovery.sql"),
    (3, Path(__file__).with_name("migrations") / "0003_backfill.sql"),
    (4, Path(__file__).with_name("migrations") / "0004_raw_provider_uniqueness.sql"),
)


@dataclass(frozen=True)
class SportsDatabase:
    database_url: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.database_url, str) or not self.database_url.strip():
            raise ValueError("SPORTS_DATABASE_URL must be configured")

    @contextmanager
    def connect(self) -> Iterator[Any]:
        try:
            import psycopg
        except ImportError as error:
            raise RuntimeError("psycopg is required for DEFEND Sports PostgreSQL access") from error

        with psycopg.connect(self.database_url) as connection:
            yield connection

    def migrate(self) -> int:
        with self.connect() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS sports_schema_migrations (
                            version INTEGER PRIMARY KEY CHECK (version > 0),
                            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                        )
                        """
                    )
                    cursor.execute("SELECT version FROM sports_schema_migrations")
                    applied_versions = {int(row[0]) for row in cursor.fetchall()}

                    latest_known_version = _MIGRATIONS[-1][0]
                    if any(version > latest_known_version for version in applied_versions):
                        raise RuntimeError(
                            "Sports database schema is newer than this application supports"
                        )

                    for version, migration_path in _MIGRATIONS:
                        if version in applied_versions:
                            continue
                        for statement in _migration_statements(migration_path):
                            cursor.execute(statement)
                        cursor.execute(
                            "INSERT INTO sports_schema_migrations(version) VALUES (%s)",
                            (version,),
                        )

                    return _current_version(cursor)

    def health(self) -> dict[str, object]:
        try:
            with self.connect() as connection:
                with connection.cursor() as cursor:
                    schema_version = _current_version(cursor)
        except Exception:
            return {
                "ok": False,
                "application_id": "sports",
                "schema_version": 0,
                "database": "unavailable",
            }
        return {
            "ok": schema_version >= 1,
            "application_id": "sports",
            "schema_version": schema_version,
            "database": "ready" if schema_version >= 1 else "unavailable",
        }


def _migration_statements(path: Path) -> tuple[str, ...]:
    script = path.read_text(encoding="utf-8")
    return tuple(statement.strip() for statement in script.split(";") if statement.strip())


def _current_version(cursor: Any) -> int:
    cursor.execute("SELECT COALESCE(MAX(version), 0) FROM sports_schema_migrations")
    row = cursor.fetchone()
    return int(row[0])
