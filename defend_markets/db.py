from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator


_MIGRATIONS = (
    (1, Path(__file__).with_name("migrations") / "0001_markets_foundation.sql"),
    (2, Path(__file__).with_name("migrations") / "0002_markets_feeds.sql"),
    (3, Path(__file__).with_name("migrations") / "0003_decision_model.sql"),
    (4, Path(__file__).with_name("migrations") / "0004_markets_prediction.sql"),
    (5, Path(__file__).with_name("migrations") / "0005_markets_rating_history.sql"),
    (6, Path(__file__).with_name("migrations") / "0006_forward_market.sql"),
    (7, Path(__file__).with_name("migrations") / "0007_shadow_evaluation.sql"),
    (8, Path(__file__).with_name("migrations") / "0008_markets_quant_director.sql"),
    (9, Path(__file__).with_name("migrations") / "0009_markets_quant_research.sql"),
    (10, Path(__file__).with_name("migrations") / "0010_markets_quant_reviews.sql"),
)


@dataclass(frozen=True)
class MarketsDatabase:
    database_url: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.database_url, str) or not self.database_url.strip():
            raise ValueError("MARKETS_DATABASE_URL must be configured")

    @contextmanager
    def connect(self) -> Iterator[Any]:
        try:
            import psycopg
        except ImportError as error:
            raise RuntimeError("psycopg is required for DEFENDmarkets PostgreSQL access") from error

        with psycopg.connect(self.database_url) as connection:
            yield connection

    def migrate(self) -> int:
        with self.connect() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS market_schema_migrations (
                            version INTEGER PRIMARY KEY CHECK (version > 0),
                            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                        )
                        """
                    )
                    cursor.execute("SELECT version FROM market_schema_migrations")
                    applied_versions = {int(row[0]) for row in cursor.fetchall()}

                    latest_known_version = _MIGRATIONS[-1][0]
                    if any(version > latest_known_version for version in applied_versions):
                        raise RuntimeError(
                            "Markets database schema is newer than this application supports"
                        )

                    for version, migration_path in _MIGRATIONS:
                        if version in applied_versions:
                            continue
                        for statement in _migration_statements(migration_path):
                            cursor.execute(statement)
                        cursor.execute(
                            "INSERT INTO market_schema_migrations(version) VALUES (%s)",
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
                "application_id": "markets",
                "schema_version": 0,
                "database": "unavailable",
            }
        return {
            "ok": schema_version >= 1,
            "application_id": "markets",
            "schema_version": schema_version,
            "database": "ready" if schema_version >= 1 else "unavailable",
        }


def _migration_statements(path: Path) -> tuple[str, ...]:
    script = path.read_text(encoding="utf-8")
    return tuple(statement.strip() for statement in script.split(";") if statement.strip())


def _current_version(cursor: Any) -> int:
    cursor.execute("SELECT COALESCE(MAX(version), 0) FROM market_schema_migrations")
    row = cursor.fetchone()
    return int(row[0])