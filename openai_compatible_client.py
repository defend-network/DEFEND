"""OpenAI-compatible chat client (vLLM, llama.cpp server, etc.)."""

from __future__ import annotations

import json
from typing import Any, Type, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from model_client import (
    ModelNotFoundError,
    ModelProtocolError,
    ModelTimeoutError,
    ModelUnavailableError,
    StructuredOutputError,
)
from model_types import (
    ChatMessage,
    GenerationOptions,
    MessageRole,
    ModelResponse,
    ModelUsage,
)

T = TypeVar("T", bound=BaseModel)


class OpenAICompatibleModelClient:
    """vLLM / any OpenAI Chat Completions compatible server."""

    def __init__(
        self,
        model: str,
        base_url: str = "http://127.0.0.1:8001/v1",
        api_key: str | None = None,
        timeout_seconds: float = 600.0,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or "EMPTY"
        self.timeout_seconds = timeout_seconds
        self._client = httpx.AsyncClient(timeout=timeout_seconds)

    async def __aenter__(self) -> "OpenAICompatibleModelClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _messages_payload(self, messages: list[ChatMessage]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            role = m.role.value if isinstance(m.role, MessageRole) else str(m.role)
            out.append({"role": role, "content": m.content})
        return out

    async def healthcheck(self) -> bool:
        try:
            r = await self._client.get(
                f"{self.base_url}/models",
                headers=self._headers(),
            )
            if not (200 <= r.status_code < 300):
                return False
            data = r.json()
            models = data.get("data") or []
            # Prefer exact model id match; if list empty, treat 2xx as reachable only when no ids
            ids = [
                str(m.get("id", ""))
                for m in models
                if isinstance(m, dict)
            ]
            if not ids:
                return True  # some servers omit list body but answered 200
            return self.model in ids or any(
                self.model.endswith(i) or i.endswith(self.model) for i in ids
            )
        except Exception:
            return False

    async def generate(
        self,
        messages: list[ChatMessage],
        options: GenerationOptions | None = None,
    ) -> ModelResponse:
        options = options or GenerationOptions()
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._messages_payload(messages),
            "temperature": options.temperature,
            "stream": False,
        }
        if options.max_tokens is not None:
            payload["max_tokens"] = options.max_tokens
        if options.top_p is not None:
            payload["top_p"] = options.top_p
        if options.seed is not None:
            payload["seed"] = options.seed
        data = await self._post_chat(payload)
        return self._to_model_response(data)

    async def generate_structured(
        self,
        messages: list[ChatMessage],
        schema: Type[T],
        options: GenerationOptions | None = None,
    ) -> tuple[T, ModelResponse]:
        options = options or GenerationOptions(temperature=0.0)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._messages_payload(messages),
            "temperature": 0.0 if options is None else options.temperature,
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "schema": schema.model_json_schema(),
                },
            },
        }
        if options and options.max_tokens is not None:
            payload["max_tokens"] = options.max_tokens
        try:
            data = await self._post_chat(payload)
        except ModelProtocolError:
            schema_hint = json.dumps(schema.model_json_schema())[:4000]
            msgs = list(messages) + [
                ChatMessage(
                    role=MessageRole.USER,
                    content=f"Respond with ONLY valid JSON matching this schema:\n{schema_hint}",
                )
            ]
            payload.pop("response_format", None)
            payload["messages"] = self._messages_payload(msgs)
            data = await self._post_chat(payload)
        response = self._to_model_response(data)
        try:
            validated = schema.model_validate_json(response.content)
        except (ValidationError, json.JSONDecodeError) as e:
            raise StructuredOutputError(
                f"Model did not return valid {schema.__name__}: {e}\nRaw:\n{response.content}"
            ) from e
        return validated, response

    async def _post_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            resp = await self._client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            )
        except httpx.TimeoutException as e:
            raise ModelTimeoutError(str(e)) from e
        except httpx.HTTPError as e:
            raise ModelUnavailableError(str(e)) from e
        if resp.status_code == 404:
            raise ModelNotFoundError(f"Model or endpoint not found: {self.model}")
        if resp.status_code == 429:
            raise ModelUnavailableError("Upstream rate limited the request")
        if resp.status_code >= 500:
            raise ModelUnavailableError(f"Upstream server error {resp.status_code}: {resp.text[:500]}")
        if resp.status_code >= 400:
            raise ModelProtocolError(f"Upstream client error {resp.status_code}: {resp.text[:500]}")
        return resp.json()

    def _to_model_response(self, data: dict[str, Any]) -> ModelResponse:
        choices = data.get("choices") or []
        content = ""
        finish = None
        if choices:
            msg = choices[0].get("message") or {}
            content = msg.get("content") or ""
            finish = choices[0].get("finish_reason")
        usage_raw = data.get("usage") or {}
        return ModelResponse(
            content=content,
            model=data.get("model", self.model),
            backend="openai_compatible",
            finish_reason=finish,
            usage=ModelUsage(
                prompt_tokens=usage_raw.get("prompt_tokens"),
                completion_tokens=usage_raw.get("completion_tokens"),
            ),
            metadata={"id": data.get("id"), "created": data.get("created")},
        )
