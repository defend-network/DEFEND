"""DEFENDmarkets server entrypoint.

Loads MarketsSettings from the environment, applies migrations, seeds
default risk policies and strategy definitions, attaches a read-only Sports
data source when configured, and serves the DEFENDmarkets API on
127.0.0.1:8500 by default.

M4.8.2C: the canonical Markets runtime no longer imports the legacy
``defend_sports`` application package. The read-only Sports source uses a
Markets-owned psycopg connection (the Sports schema is a separate legacy DB;
Markets owns the read path and any active sports/odds functionality).
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

import uvicorn

from defend_markets.app import MarketsDependencies, build_markets_app
from defend_markets.config import MarketsSettings
from defend_markets.db import MarketsDatabase


@dataclass(frozen=True)
class _MarketsSportsSource:
    """Markets-owned read-only connection to the legacy Sports PostgreSQL DB.

    Replaces the former ``defend_sports.db.SportsDatabase`` dependency so the
    canonical Markets runtime has no app-to-app import. Only ``connect()`` is
    provided (read path); the Sports schema is never migrated or written here.
    """

    database_url: str = field(repr=False)

    @contextmanager
    def connect(self) -> Iterator[Any]:
        try:
            import psycopg
        except ImportError as error:
            raise RuntimeError("psycopg is required for the Markets Sports read source") from error
        with psycopg.connect(self.database_url) as connection:
            yield connection


def build_default_dependencies() -> MarketsDependencies:
    settings = MarketsSettings.from_env()
    database = MarketsDatabase(settings.database_url)
    database.migrate()

    from defend_markets.repositories import MarketsRepository
    from defend_markets.store import PostgresMarketsStore

    with database.connect() as connection:
        with connection.transaction():
            MarketsRepository().seed_defaults(connection)

    sports_database = None
    reader = None
    sports_url = os.environ.get("SPORTS_DATABASE_URL", "").strip()
    if sports_url:
        from defend_markets.sports_adapter import PostgresSportsDataReader

        sports_database = _MarketsSportsSource(sports_url)
        reader = PostgresSportsDataReader(sports_database)

    return MarketsDependencies(
        settings=settings,
        database=database,
        sports_database=sports_database,
        reader=reader,
    )


def main() -> None:
    dependencies = build_default_dependencies()
    app = build_markets_app(dependencies)
    port = dependencies.settings.api_port
    print(f"[DEFENDmarkets] serving on 127.0.0.1:{port} origin={dependencies.settings.public_origin}")
    uvicorn.run(app, host="127.0.0.1", port=port, reload=False)


if __name__ == "__main__":
    main()