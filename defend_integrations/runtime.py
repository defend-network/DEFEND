"""Detected runtime values for the Core infrastructure provider cards.

The Setup control plane shows *detected/current* platform values (ports,
public origin, tunnel name, database/schema presence) as read-only context on
the Core cards. This is observation only: nothing here writes configuration,
touches secrets, or changes how the platform is configured. The config store's
``optional_config`` entries remain the override mechanism — the UI renders
them as "configured override" inputs whose placeholder shows the detected
value when no override is set.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

# Core providers that expose detected values, keyed by optional_config name
# where an override input exists. ``public_origin`` / ``tunnel`` are shown as
# detected context even when no override input exists for them.
_CORE_DETECTED: dict[str, tuple[str, ...]] = {
    "origin_defend_ai": ("public_origin", "api_port", "web_port"),
    "origin_defendcoder": ("public_origin",),
    "origin_defendmarkets": ("public_origin", "api_port", "web_port"),
    "origin_scs": ("public_origin", "api_port", "web_port"),
    "cloudflare_tunnel": ("tunnel", "public_origin"),
}


def _schema_version(db_path: Path) -> int | None:
    """Read ``schema_meta.schema_version`` from a product DB, read-only."""
    try:
        connection = sqlite3.connect(
            f"file:{db_path}?mode=ro", uri=True, timeout=1.0
        )
        try:
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key='schema_version'"
            ).fetchone()
        finally:
            connection.close()
    except Exception:
        return None
    if not row:
        return None
    value = row[0]
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def detect_databases(data_root: Path | str) -> list[dict[str, Any]]:
    """List product databases under ``<data_root>/db`` with schema versions."""
    db_dir = Path(data_root) / "db"
    if not db_dir.is_dir():
        return []
    results = []
    for path in sorted(db_dir.glob("*.db")):
        results.append(
            {
                "name": path.name,
                "present": True,
                "schema_version": _schema_version(path),
            }
        )
    return results


def _database_summary(databases: list[dict[str, Any]]) -> str:
    if not databases:
        return "none present"
    return ", ".join(
        f"{item['name'].removesuffix('.db')}"
        + (
            f" (schema {item['schema_version']})"
            if item["schema_version"] is not None
            else ""
        )
        for item in databases
    )


def detect_runtime(
    *,
    data_root: Path | str,
    api_port: str | int,
    web_port: str | int,
    model_port: str | int,
    public_origin: str,
    tunnel: str,
) -> dict[str, dict[str, str]]:
    """Build the per-provider detected map for the Core cards.

    Returns ``{provider_id: {key: value}}``; empty values are omitted so the
    UI never shows blank detected rows.
    """
    databases = detect_databases(data_root)
    providers: dict[str, dict[str, str]] = {}
    for provider_id, keys in _CORE_DETECTED.items():
        values: dict[str, str] = {}
        if "public_origin" in keys and public_origin:
            values["public_origin"] = str(public_origin)
        if "api_port" in keys:
            values["api_port"] = str(api_port)
        if "web_port" in keys:
            values["web_port"] = str(web_port)
        if "tunnel" in keys and tunnel:
            values["tunnel"] = str(tunnel)
        if values:
            providers[provider_id] = values
    providers["postgres_per_product"] = {
        "databases": _database_summary(databases)
    }
    if model_port:
        for provider_id in (
            "origin_defend_ai",
            "origin_defendmarkets",
            "origin_scs",
        ):
            providers.setdefault(provider_id, {})["model_port"] = str(model_port)
    return providers