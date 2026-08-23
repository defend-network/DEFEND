"""DEFENDcoder product launch contract (single product authority).

Control Center is an OPTIONAL supervisor. It may READ this manifest to launch
the canonical API/UI and read health; it must NOT independently redefine ports,
models, runtime policy, or provider settings. Environment variables (parsed by
``defend_coder.config.CoderSettings``) remain the canonical settings source.
"""

from __future__ import annotations

from dataclasses import dataclass

API_PORT = 8301
UI_PORT = 3301
MODEL_FORWARD_PORT = 8403

API_HOST = "127.0.0.1"
UI_HOST = "127.0.0.1"

PRODUCT_ID = "DEFENDCODER"


@dataclass(frozen=True)
class LaunchManifest:
    product_id: str
    api_host: str
    api_port: int
    ui_host: str
    ui_port: int
    model_forward_port: int
    api_command: tuple[str, ...]
    ui_command: tuple[str, ...]
    health_url: str
    open_url: str


def build_launch_manifest(settings: object | None = None) -> LaunchManifest:
    """Product-owned launch manifest. Derives from the canonical product
    settings (single authority) — never a second hardcoded constants table."""
    if settings is None:
        from .config import CoderSettings

        settings = CoderSettings(database_url="")
    api_host = getattr(settings, "host", API_HOST)
    api_port = getattr(settings, "port", API_PORT)
    ui_host = getattr(settings, "ui_host", UI_HOST)
    ui_port = getattr(settings, "ui_port", UI_PORT)
    model_forward_port = getattr(settings, "model_forward_port", MODEL_FORWARD_PORT)
    return LaunchManifest(
        product_id=PRODUCT_ID,
        api_host=api_host,
        api_port=api_port,
        ui_host=ui_host,
        ui_port=ui_port,
        model_forward_port=model_forward_port,
        api_command=("python", "-m", "tools.defend_coder_server"),
        ui_command=("node", ".next/standalone/server.js"),
        health_url=f"http://{api_host}:{api_port}/health",
        open_url=f"http://{ui_host}:{ui_port}",
    )
