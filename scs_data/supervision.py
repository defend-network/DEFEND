"""SCS product supervision manifest (M1.5C-S 16).

A small product-owned supervision contract (product ID, ports, health, open +
setup URLs). Contains NO engineering policy — it exists so Platform can retire
compatibility defaults without owning SCS setup.
"""
from __future__ import annotations

from typing import Any

from shared_platform.application import ApplicationContext


def supervision_manifest(context: ApplicationContext) -> dict[str, Any]:
    return {
        "product_id": "scs",
        "name": "Sunshine Climate Solutions Operations",
        "api_port": context.api_port,
        "web_port": context.web_port,
        "health_url": f"http://127.0.0.1:{context.api_port}/health",
        "open_url": f"http://127.0.0.1:{context.web_port}/",
        "setup_url": f"http://127.0.0.1:{context.web_port}/#setup",
        "supervisor": "scs_owned",
    }
