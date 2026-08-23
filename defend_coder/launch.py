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


def build_launch_manifest() -> LaunchManifest:
    """Product-owned launch manifest (single authority)."""
    return LaunchManifest(
        product_id=PRODUCT_ID,
        api_host=API_HOST,
        api_port=API_PORT,
        ui_host=UI_HOST,
        ui_port=UI_PORT,
        model_forward_port=MODEL_FORWARD_PORT,
        api_command=("python", "-m", "tools.defend_coder_server"),
        ui_command=("node", ".next/standalone/server.js"),
        health_url=f"http://{API_HOST}:{API_PORT}/health",
        open_url=f"http://{UI_HOST}:{UI_PORT}",
    )
