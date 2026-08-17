from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from .chat import ScsAssistant


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=40)
    job_context: str | None = Field(default=None, max_length=8000)


def build_chat_router(assistant: ScsAssistant) -> APIRouter:
    if not isinstance(assistant, ScsAssistant):
        raise TypeError("assistant must be an ScsAssistant")
    router = APIRouter()

    @router.post("/v1/chat")
    async def chat(request: ChatRequest, response: Response) -> dict[str, object]:
        outcome = await assistant.answer(
            request.message,
            history=[turn.model_dump() for turn in request.history],
            job_context=request.job_context,
        )
        if outcome.state != "answered":
            response.status_code = 503
        return {
            "state": outcome.state,
            "reply": outcome.reply,
            "model": outcome.model_name,
            "provider": outcome.provider,
            "detail": outcome.detail,
        }

    return router