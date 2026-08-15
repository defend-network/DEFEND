"""DEFEND Sports FastAPI application factory and V1 system endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from defend_sports.config import SportsSettings
from defend_sports.db import SportsDatabase


def build_sports_app(settings: SportsSettings, db: SportsDatabase) -> FastAPI:
    """Build the independent DEFEND Sports API application.

    No global database connections are created here; every request opens
    its own connection through the injected ``SportsDatabase``.
    """
    app = FastAPI(title="DEFEND Sports API", version="0.1.0")
    app.state.settings = settings

    @app.get("/health")
    def health() -> dict[str, object]:
        return db.health()

    @app.get("/v1/system/sources")
    def system_sources() -> dict[str, object]:
        return _source_status(db)

    return app


def _source_status(db: SportsDatabase) -> dict[str, object]:
    """Operational provider/source health summary; never raw payloads."""
    try:
        with db.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT p.provider_name, p.source_key, p.display_name, p.is_active,
                           h.status, h.observed_at,
                           (SELECT count(*) FROM raw_provider_events r
                             WHERE r.source_id = p.source_id),
                           (SELECT count(*) FROM odds_snapshots o
                             WHERE o.source_id = p.source_id)
                    FROM provider_sources p
                    LEFT JOIN LATERAL (
                        SELECT status, observed_at
                        FROM provider_health h
                        WHERE h.source_id = p.source_id
                        ORDER BY h.provider_health_id DESC
                        LIMIT 1
                    ) h ON TRUE
                    ORDER BY p.provider_name, p.source_key
                    """
                )
                rows = cursor.fetchall()
    except Exception:
        return {
            "ok": False,
            "application_id": "sports",
            "database": "unavailable",
            "sources": [],
        }

    sources: list[dict[str, Any]] = []
    for provider_name, source_key, display_name, is_active, status, observed_at, raw_events, odds_snapshots in rows:
        source: dict[str, Any] = {
            "provider_name": provider_name,
            "source_key": source_key,
            "display_name": display_name,
            "is_active": bool(is_active),
            "raw_events": int(raw_events),
            "odds_snapshots": int(odds_snapshots),
        }
        if status is not None:
            source["latest_health"] = {
                "status": status,
                "observed_at": observed_at,
            }
        sources.append(source)

    return {
        "ok": True,
        "application_id": "sports",
        "database": "ready",
        "sources": sources,
    }