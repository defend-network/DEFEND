from __future__ import annotations

from fastapi import FastAPI

from .config import ScsAiSettings
from .model_gateway import ModelGateway
from .tools import ToolRegistry
from .tunnel import TunnelController


def build_scs_ai_app(
    settings: ScsAiSettings,
    *,
    gateway: ModelGateway,
    tunnel: TunnelController,
    tools: ToolRegistry,
) -> FastAPI:
    if not isinstance(settings, ScsAiSettings):
        raise TypeError("settings must be an ScsAiSettings")
    app = FastAPI(title="Sunshine Climate Solutions AI Service", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, object]:
        gateway_status = gateway.status()
        tools_state = tools.state()
        return {
            "ok": True,
            "application_id": "scs",
            "service": "scs-ai",
            "api": {"state": "ready", "port": settings.api_port},
            "model_gateway": {
                "state": gateway_status.state,
                "ready": gateway_status.ready,
                "alias": gateway_status.alias,
                "provider": gateway_status.provider,
            },
            "tools": {"state": tools_state},
        }

    @app.get("/v1/system/status")
    def system_status() -> dict[str, object]:
        gateway_status = gateway.status()
        tunnel_status = tunnel.status()
        return {
            "application_id": "scs",
            "service": "scs-ai",
            "public_origin": settings.public_origin,
            "api": {"state": "ready", "port": settings.api_port},
            "web_port": settings.web_port,
            "model_gateway": {
                "state": gateway_status.state,
                "ready": gateway_status.ready,
                "alias": gateway_status.alias,
                "provider": gateway_status.provider,
                "model_name": gateway_status.model_name,
            },
            "tools": {
                "state": tools.state(),
                "items": [
                    {"name": item.name, "state": item.state, "detail": item.detail}
                    for item in tools.status()
                ],
            },
            "tunnel": {
                "state": tunnel_status.state,
                "enabled": tunnel_status.enabled,
                "pid": tunnel_status.pid,
            },
        }

    return app