"""DEFEND AI product-owned application supervision manifest.

The Control Center consumes this manifest as an OPTIONAL supervisor. It never
defines these values, and DEFEND AI remains independently launchable with
Control Center absent. This manifest deliberately exposes NO training, canary,
GPU-rent, or LoRA-promotion authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .settings import DISPLAY_NAME, load_settings

APPLICATION_ID = "defend"


@dataclass(frozen=True)
class SupervisionManifest:
    application_id: str
    display_name: str
    api_port: int
    web_port: int
    model_port: int
    api_launch: tuple[str, ...]
    working_directory: str
    health_url: str
    open_url: str
    setup_url: str
    graceful_stop: str
    data_root: str
    api_mode: str
    ui_launch: tuple[str, ...] = field(default_factory=tuple)


def supervision_manifest() -> SupervisionManifest:
    s = load_settings()
    api_port = s.api_port
    web_port = s.web_port
    return SupervisionManifest(
        application_id=APPLICATION_ID,
        display_name=DISPLAY_NAME,
        api_port=api_port,
        web_port=web_port,
        model_port=s.model_port,
        api_launch=("python", "-m", "defend_ai.api_server"),
        working_directory=".",
        health_url=f"http://127.0.0.1:{api_port}/health",
        open_url=f"http://127.0.0.1:{web_port}",
        setup_url=f"http://127.0.0.1:{api_port}/setup",
        graceful_stop="process signal (SIGINT/SIGTERM) / Ctrl+C",
        data_root=s.data_root,
        api_mode=s.api_mode,
    )


def supervision_dict() -> dict:
    return {
        "application_id": APPLICATION_ID,
        "display_name": DISPLAY_NAME,
        "api_launch": ["python", "-m", "defend_ai.api_server"],
        "api_port": load_settings().api_port,
        "web_port": load_settings().web_port,
        "model_port": load_settings().model_port,
        "working_directory": ".",
        "health_url": f"http://127.0.0.1:{load_settings().api_port}/health",
        "open_url": f"http://127.0.0.1:{load_settings().web_port}",
        "setup_url": f"http://127.0.0.1:{load_settings().api_port}/setup",
        "graceful_stop_contract": "process signal (SIGINT/SIGTERM) / Ctrl+C",
    }
