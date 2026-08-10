from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

from model_types import ChatMessage, GenerationOptions, ModelResponse


T = TypeVar("T", bound=BaseModel)


class ModelClientError(Exception):
    pass


class ModelUnavailableError(ModelClientError):
    pass


class ModelNotFoundError(ModelClientError):
    pass


class ModelTimeoutError(ModelClientError):
    pass


class StructuredOutputError(ModelClientError):
    pass


class ModelProtocolError(ModelClientError):
    pass


class ModelClient(Protocol):
    async def generate(
        self,
        *,
        messages: list[ChatMessage],
        options: GenerationOptions | None = None,
    ) -> ModelResponse:
        ...

    async def generate_structured(
        self,
        *,
        messages: list[ChatMessage],
        schema: type[T],
        options: GenerationOptions | None = None,
    ) -> tuple[T, ModelResponse]:
        ...

    async def healthcheck(self) -> bool:
        ...

    async def close(self) -> None:
        ...