from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Literal

from .client import (
    ModelError,
    ModelTimeoutError,
    ModelUnavailableError,
    OpenAiCompatibleChatClient,
)
from .model_gateway import GatewayStatus, ModelGateway

ChatState = Literal[
    "answered",
    "model_unavailable",
    "model_timeout",
    "model_error",
    "not_configured",
]

_SYSTEM_PROMPT = (
    "You are the SCS AI field assistant for Sunshine Climate Solutions, a "
    "commercial HVAC and testing/balancing (TAB) company. You help employees "
    "with service diagnostics, TAB workflows, equipment and job notes, report "
    "drafting, and HVAC calculations. Rules: answer from HVAC/TAB best "
    "practice and general industry knowledge only; never invent customer, "
    "job, equipment, or reading facts; distinguish confirmed facts from "
    "suggestions; flag measurements you cannot verify; keep answers practical "
    "for a technician in the field; do not give safety or compliance "
    "certifications; defer money decisions to approved SCS estimates and "
    "invoices. Prefer concise, structured answers with the key numbers up "
    "front."
)

_MAX_HISTORY_TURNS = 12
_MAX_TURN_CHARS = 1600
_MAX_CONTEXT_CHARS = 2400


@dataclass(frozen=True)
class ChatOutcome:
    state: ChatState
    reply: str | None = None
    model_name: str | None = None
    provider: str | None = None
    detail: str | None = None


class ScsAssistant:
    """SCS-context chat over the configured language model gateway.

    There is no fallback model: when the gateway is not configured, missing a
    required key, or unreachable, the assistant reports that exact state.
    """

    def __init__(self, gateway: ModelGateway) -> None:
        if not isinstance(gateway, ModelGateway):
            raise TypeError("gateway must be a ModelGateway")
        self._gateway = gateway

    @property
    def status(self) -> GatewayStatus:
        return self._gateway.status()

    def _messages(
        self,
        message: str,
        history: list[dict[str, str]],
        job_context: str | None,
    ) -> list[dict[str, str]]:
        system = _SYSTEM_PROMPT
        if job_context and job_context.strip():
            context = job_context.strip()[:_MAX_CONTEXT_CHARS]
            system += (
                "\n\nCurrent SCS job/customer context (grounding data only, "
                "do not invent beyond it):\n" + context
            )
        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        for turn in history[-_MAX_HISTORY_TURNS:]:
            role = turn.get("role")
            if role not in {"user", "assistant"}:
                continue
            content = str(turn.get("content") or "")[:_MAX_TURN_CHARS].strip()
            if content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": message.strip()[:_MAX_TURN_CHARS]})
        return messages

    async def answer(
        self,
        message: str,
        history: list[dict[str, str]] | None = None,
        job_context: str | None = None,
    ) -> ChatOutcome:
        if not isinstance(message, str) or not message.strip():
            return ChatOutcome(
                state="model_error", detail="empty message rejected"
            )
        status = self._gateway.status()
        if status.state != "configured" or not status.ready:
            return ChatOutcome(
                state="not_configured"
                if status.state == "not_configured"
                else "model_unavailable",
                model_name=status.model_name,
                provider=status.provider,
                detail=(
                    "Model not configured"
                    if status.state == "not_configured"
                    else "Model is configured but not ready"
                ),
            )
        client = self._gateway.client()
        if not isinstance(client, OpenAiCompatibleChatClient):
            return ChatOutcome(
                state="model_unavailable",
                model_name=status.model_name,
                provider=status.provider,
                detail="Model client is not available",
            )
        messages = self._messages(message, history or [], job_context)
        try:
            reply = await asyncio.to_thread(client.generate, messages)
        except ModelTimeoutError as error:
            return ChatOutcome(
                state="model_timeout",
                model_name=client.model_name,
                provider=status.provider,
                detail=str(error),
            )
        except (ModelError, ModelUnavailableError) as error:
            return ChatOutcome(
                state="model_error",
                model_name=client.model_name,
                provider=status.provider,
                detail=str(error),
            )
        return ChatOutcome(
            state="answered",
            reply=reply,
            model_name=client.model_name,
            provider=status.provider,
        )