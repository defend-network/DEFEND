from __future__ import annotations

import os
from pathlib import Path

from .app import build_scs_ai_app
from .config import ScsAiSettings
from .model_gateway import ModelGateway
from .tools import ToolRegistry
from .tunnel import EnvTokenSource, FileTokenSource, TunnelController

context = ScsAiSettings.from_env()

token_file = os.environ.get("SCS_AI_TUNNEL_TOKEN_FILE")
if token_file:
    token_source: object = FileTokenSource(Path(token_file))
else:
    token_source = EnvTokenSource()

gateway = ModelGateway(alias=context.model_alias)
tools = ToolRegistry.default()
tunnel = TunnelController(
    context,
    executable=os.environ.get(
        "SCS_AI_CLOUDFLARED_EXE", r"C:\Program Files (x86)\cloudflared\cloudflared.exe"
    ),
    token_source=token_source,
)

app = build_scs_ai_app(context, gateway=gateway, tunnel=tunnel, tools=tools)