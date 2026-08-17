from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .calculations_routes import build_calculations_router
from .chat import ScsAssistant
from .chat_routes import build_chat_router
from .config import ScsAiSettings
from .model_gateway import ModelGateway
from .office.toolkit import OfficeToolkit
from .office_routes import build_office_router
from .tools import ToolRegistry
from .tunnel import TunnelController

_SCS_WEB_ORIGINS = (
    "http://127.0.0.1:3100",
    "http://localhost:3100",
    "http://127.0.0.1:3300",
    "http://localhost:3300",
)


def build_scs_ai_app(
    settings: ScsAiSettings,
    *,
    gateway: ModelGateway,
    tunnel: TunnelController,
    tools: ToolRegistry,
    assistant: ScsAssistant | None = None,
    office_toolkit: OfficeToolkit | None = None,
) -> FastAPI:
    if not isinstance(settings, ScsAiSettings):
        raise TypeError("settings must be an ScsAiSettings")
    app = FastAPI(title="Sunshine Climate Solutions AI Service", version="0.1.0")

    origins = [*_SCS_WEB_ORIGINS, settings.public_origin]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    app.include_router(build_calculations_router())
    if assistant is not None:
        app.include_router(build_chat_router(assistant))
    if office_toolkit is not None:
        office_toolkit.ensure_workspace()
    app.include_router(build_office_router(office_toolkit))

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
        chat_status = assistant.status if assistant is not None else gateway_status
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
            "chat": {
                "available": assistant is not None,
                "state": chat_status.state,
            },
            "calculations": {"enabled": True},
            "office": {
                "state": "ready" if office_toolkit is not None else "not_configured"
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