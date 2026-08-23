"""DEFEND AI product-owned application supervision manifest.

The Control Center consumes this manifest as an OPTIONAL supervisor. It never
defines these values, and DEFEND AI remains independently launchable with
Control Center absent. This manifest deliberately exposes NO training, canary,
GPU-rent, or LoRA-promotion authority.
"""

from __future__ import annotations

from .settings import DISPLAY_NAME, PRODUCT_ID, load_settings


def supervision_manifest() -> dict:
    s = load_settings()
    api_port = s.api_port
    web_port = s.web_port
    return {
        "product_id": PRODUCT_ID,
        "display_name": DISPLAY_NAME,
        "api_command": ["python", "api_server.py"],
        "working_directory": ".",
        "api_port": api_port,
        "web_port": web_port,
        "model_port": s.model_port,
        "health_url": f"http://127.0.0.1:{api_port}/health",
        "open_url": f"http://127.0.0.1:{web_port}",
        "setup_url": f"http://127.0.0.1:{api_port}/setup",
        "graceful_stop_contract": "process signal (SIGINT/SIGTERM) / Ctrl+C",
        "data_root": s.data_root,
        "api_mode": s.api_mode,
    }
