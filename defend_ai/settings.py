"""DEFEND AI product-owned settings authority.

Control Center may READ these values; it never DEFINES them. There is no
fallback to Control Center settings for product runtime authority.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PRODUCT_ID = "DEFEND_AI"
DISPLAY_NAME = "DEFEND AI"

API_PORT_DEFAULT = 8000
WEB_PORT_DEFAULT = 3000
MODEL_PORT_DEFAULT = 8001


@dataclass(frozen=True)
class DefendAISettings:
    api_port: int
    web_port: int
    model_port: int
    data_root: str
    api_mode: str
    public_web_origin: str


def _default_data_root() -> str:
    configured = os.getenv("DEFEND_DATA_ROOT", "").strip()
    if configured:
        return configured
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return str(Path(base) / "DEFEND" / "data")
    return str(Path.cwd() / ".defend-data")


def load_settings() -> DefendAISettings:
    return DefendAISettings(
        api_port=int(os.getenv("DEFEND_API_PORT", str(API_PORT_DEFAULT))),
        web_port=int(os.getenv("DEFEND_UI_PORT", str(WEB_PORT_DEFAULT))),
        model_port=int(os.getenv("DEFEND_MODEL_PORT", str(MODEL_PORT_DEFAULT))),
        data_root=_default_data_root(),
        api_mode=os.getenv("DEFEND_API_MODE", "defend-ai").strip().lower(),
        public_web_origin=os.getenv("DEFEND_PUBLIC_WEB_ORIGIN", "").strip(),
    )
