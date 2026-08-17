"""DEFENDmarkets server entrypoint.

Loads MarketsSettings from the environment, applies migrations, seeds
default risk policies and strategy definitions, attaches the DEFEND
Sports database as a read-only source when configured, and serves the
DEFENDmarkets API on 127.0.0.1:8300 by default.
"""

from __future__ import annotations

import os

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

    sports_database = None
    reader = None
    sports_url = os.environ.get("SPORTS_DATABASE_URL", "").strip()
    if sports_url:
        from defend_sports.db import SportsDatabase
        from defend_markets.sports_adapter import PostgresSportsDataReader

        sports_database = SportsDatabase(sports_url)
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