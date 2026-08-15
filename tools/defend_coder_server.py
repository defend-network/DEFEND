"""Local/control-plane entrypoint for the DEFENDcoder API.

Startup:
CoderSettings -> PostgreSQL -> migrations -> repository -> authentication
-> FastAPI -> uvicorn.

The model runtime remains a separate service. This API does not expose vLLM
directly to browser clients.
"""

from __future__ import annotations

import sys

import uvicorn

from defend_coder.app import build_coder_app
from defend_coder.auth import AuthService
from defend_coder.config import CoderSettings
from defend_coder.db import CoderDatabase
from defend_coder.repositories import CoderRepository


def runtime_status() -> dict[str, object]:
    """Truthful placeholder until Control Center binds the model runtime."""

    return {
        "state": "not_connected",
        "provider": None,
        "model": None,
    }


def main() -> None:
    settings = CoderSettings.from_env()

    database = CoderDatabase(settings.database_url)

    try:
        database.migrate()
    except Exception as error:
        print(
            "DEFENDcoder migration failed: "
            f"{type(error).__name__}: {error}",
            file=sys.stderr,
        )
        raise SystemExit(1) from error

    repository = CoderRepository(database)
    auth = AuthService(repository)

    app = build_coder_app(
        settings=settings,
        db=database,
        auth=auth,
        runtime_status=runtime_status,
    )

    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
