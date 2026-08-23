"""DEFENDmarkets product-owned supervision/launch contract (M4.8.2C-R).

The single authority for how DEFENDmarkets is launched and supervised. Derived
directly from ``defend_markets.config.MarketsSettings`` — there is no competing
second settings table.

Control Center (or any future platform integration) MAY consume this manifest
to launch/health-check/stop the product as an optional supervisor. It MUST NOT
author the values here, and MUST NOT define its own competing Markets
settings/ports/process specs.

This module deliberately contains NO quant policy, M5 settings, risk policy,
sports-provider policy, or financial policy. Those remain product internals
under ``defend_markets``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from defend_markets.config import MarketsSettings

PRODUCT_ID = "markets"
DISPLAY_NAME = "DEFENDmarkets"
API_HOST = "127.0.0.1"
UI_HOST = "127.0.0.1"
API_MODULE = "tools.defend_markets_server"
UI_DIRECTORY_NAME = "defendmarkets-ui"
UI_ENTRYPOINT = ".next/standalone/server.js"


@dataclass(frozen=True)
class MarketsLaunchManifest:
    """Product-owned launch/supervision contract derived from MarketsSettings."""

    product_id: str
    display_name: str
    api_host: str
    api_port: int
    ui_host: str
    ui_port: int
    public_origin: str
    api_working_directory: Path
    ui_working_directory: Path

    @property
    def api_health_url(self) -> str:
        return f"http://{self.api_host}:{self.api_port}/health"

    @property
    def ui_health_url(self) -> str:
        # Same-origin proxy health probe served by the standalone UI.
        return f"http://{self.ui_host}:{self.ui_port}/markets-health"

    @property
    def open_url(self) -> str:
        return f"http://{self.ui_host}:{self.ui_port}/markets"

    def api_argv(self, python_executable: str) -> tuple[str, ...]:
        return (python_executable, "-m", API_MODULE)

    def ui_argv(self) -> tuple[str, ...]:
        return ("node", UI_ENTRYPOINT)

    def api_environment(self) -> dict[str, str]:
        """Environment the API child requires. Derived from MarketsSettings.

        Only the product-owned MARKETS_* keys are produced here; secrets (DB
        URL) are pulled from the caller's existing environment, never invented.
        """
        import os

        return {
            "MARKETS_API_PORT": str(self.api_port),
            "MARKETS_WEB_PORT": str(self.ui_port),
            "MARKETS_PUBLIC_ORIGIN": self.public_origin,
        }

    def ui_environment(self) -> dict[str, str]:
        return {
            "HOSTNAME": self.ui_host,
            "PORT": str(self.ui_port),
            "NODE_ENV": "production",
            "MARKETS_INTERNAL_API_ORIGIN": f"http://{self.api_host}:{self.api_port}",
        }


def build_manifest(
    repository: Path,
    settings: MarketsSettings | None = None,
) -> MarketsLaunchManifest:
    """Build the product-owned launch manifest from MarketsSettings."""
    resolved = settings or MarketsSettings.from_env()
    root = Path(repository).resolve()
    return MarketsLaunchManifest(
        product_id=PRODUCT_ID,
        display_name=DISPLAY_NAME,
        api_host=API_HOST,
        api_port=resolved.api_port,
        ui_host=UI_HOST,
        ui_port=resolved.web_port,
        public_origin=resolved.public_origin,
        api_working_directory=root,
        ui_working_directory=root / UI_DIRECTORY_NAME,
    )
