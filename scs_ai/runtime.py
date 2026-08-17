from __future__ import annotations

import os
from pathlib import Path

from .app import build_scs_ai_app
from .chat import ScsAssistant
from .client import OpenAiCompatibleChatClient
from .config import ScsAiSettings
from .model_gateway import ModelGateway
from .office.toolkit import OfficeToolkit
from .providers import load_model_config
from .tools import ToolRegistry
from .tunnel import EnvTokenSource, FileTokenSource, TunnelController

context = ScsAiSettings.from_env()

token_file = os.environ.get("SCS_AI_TUNNEL_TOKEN_FILE")
if token_file:
    token_source: object = FileTokenSource(Path(token_file))
else:
    token_source = EnvTokenSource()

model_config = load_model_config()
client_factory = (
    (lambda profile, *, api_key: OpenAiCompatibleChatClient(profile, api_key=api_key))
    if model_config.base_url
    else None
)
gateway = ModelGateway(
    alias=model_config.alias,
    providers=model_config.providers(),
    api_key=model_config.api_key,
    client_factory=client_factory,
)
assistant = ScsAssistant(gateway)
tools = ToolRegistry.default()
tunnel = TunnelController(
    context,
    executable=os.environ.get(
        "SCS_AI_CLOUDFLARED_EXE", r"C:\Program Files (x86)\cloudflared\cloudflared.exe"
    ),
    token_source=token_source,
)

office_root = os.environ.get("SCS_AI_OFFICE_ROOT")
office_toolkit = OfficeToolkit(office_root) if office_root else None

app = build_scs_ai_app(
    context,
    gateway=gateway,
    tunnel=tunnel,
    tools=tools,
    assistant=assistant,
    office_toolkit=office_toolkit,
)