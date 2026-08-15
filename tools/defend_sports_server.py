"""Local/control-plane entrypoint for the DEFEND Sports API service.

Startup sequence: SportsSettings.from_env() -> SportsDatabase -> migrations
-> build_sports_app() -> uvicorn on the configured loopback port.
"""

from __future__ import annotations

import sys

import uvicorn

from defend_sports.app import build_sports_app
from defend_sports.config import SportsSettings
from defend_sports.db import SportsDatabase

_DEFAULT_HOST = "127.0.0.1"


def main() -> None:
    settings = SportsSettings.from_env()
    database = SportsDatabase(settings.database_url)
    try:
        database.migrate()
    except Exception as error:
        print(
            f"DEFEND Sports migration failed: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        raise SystemExit(1) from error

    app = build_sports_app(settings, database)
    uvicorn.run(app, host=_DEFAULT_HOST, port=settings.api_port, log_level="info")


if __name__ == "__main__":
    main()