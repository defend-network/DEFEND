"""DEFENDmarkets server entrypoint.

Loads MarketsSettings from the environment, applies migrations, seeds default
risk policies and strategy definitions, and serves the DEFENDmarkets API on
127.0.0.1:8500 by default.

M4.8.2D: Markets owns its live sports/odds pipeline end-to-end. The reader is
wired to the MARKETS database (migration 0025 tables), not the legacy Sports
database. No legacy application package is imported.
"""

from __future__ import annotations

import uvicorn

from defend_markets.app import MarketsDependencies, build_markets_app
from defend_markets.config import MarketsSettings
from defend_markets.db import MarketsDatabase


def build_default_dependencies() -> MarketsDependencies:
    settings = MarketsSettings.from_env()
    database = MarketsDatabase(settings.database_url)
    database.migrate()

    from defend_markets.repositories import MarketsRepository
    from defend_markets.store import PostgresMarketsStore

    with database.connect() as connection:
        with connection.transaction():
            MarketsRepository().seed_defaults(connection)

    # M4.8.2D: canonical live pipeline reads Markets-owned tables (migration
    # 0025). The legacy Sports DB is not consulted by the canonical runtime.
    from defend_markets.sports_adapter import PostgresSportsDataReader

    reader = PostgresSportsDataReader(database)

    return MarketsDependencies(
        settings=settings,
        database=database,
        sports_database=database,
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
