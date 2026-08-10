from __future__ import annotations

import json
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from model_client import (
    ModelClientError,
    ModelNotFoundError,
    ModelProtocolError,
    ModelTimeoutError,
    ModelUnavailableError,
    StructuredOutputError,
)
from model_types import (
    ChatMessage,
    GenerationOptions,
    ModelResponse,
    ModelUsage,
)


T = TypeVar("T", bound=BaseModel)


class OllamaClient:
    def __init__(
        self,
        *,
        model: str,
        base_url: str = "http://127.0.0.1:11434",
        timeout_seconds: float = 600.0,
        keep_alive: str = "15m",
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.keep_alive = keep_alive
        self._client = httpx.AsyncClient(timeout=timeout_seconds)

    async def __aenter__(self) -> "OllamaClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def healthcheck(self) -> bool:
    	try:
        	resp = await self._client.get(f"{self.base_url}/api/tags")
        	resp.raise_for_status()
        	data = resp.json()
        	models = data.get("models", [])

        	# Debug print so we can see exact names
        	print("Installed models:", [m.get("name") for m in models])

        	target = self.model.lower().removesuffix(":latest")
        	return any(
            		target in (m.get("name") or "").lower()
            		or target in (m.get("model") or "").lower()
            		for m in models
        	)
    	except Exception as e:
        	print(f"Healthcheck error: {e}")
        	return False

    async def generate(
        self,
        *,
        messages: list[ChatMessage],
        options: GenerationOptions | None = None,
    ) -> ModelResponse:
        options = options or GenerationOptions()

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.model_dump(mode="json") for m in messages],
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": options.temperature,
            },
        }

        if options.max_tokens is not None:
            payload["options"]["num_predict"] = options.max_tokens
        if options.top_p is not None:
            payload["options"]["top_p"] = options.top_p
        if options.seed is not None:
            payload["options"]["seed"] = options.seed

        # Explicitly disable thinking for control-plane calls unless requested
        if options.think is not False:
            payload["think"] = options.think
        else:
            payload["think"] = False

        data = await self._post_chat(payload)
        return self._to_model_response(data)

    async def generate_structured(
        self,
        *,
        messages: list[ChatMessage],
        schema: type[T],
        options: GenerationOptions | None = None,
    ) -> tuple[T, ModelResponse]:
        # Structured orchestration should be deterministic by default
        options = options or GenerationOptions(temperature=0.0)

        schema_json = schema.model_json_schema()

        # Ground the model + let Ollama enforce the schema
        grounded_messages = list(messages)
        grounded_messages.insert(
            0,
            ChatMessage(
                role="system",
                content=(
                    "You must respond with ONLY valid JSON that matches the provided schema. "
                    "No markdown, no commentary, no extra keys."
                ),
            ),
        )

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.model_dump(mode="json") for m in grounded_messages],
            "stream": False,
            "format": schema_json,          # native Ollama schema enforcement
            "keep_alive": self.keep_alive,
            "think": False,
            "options": {
                "temperature": options.temperature,
            },
        }

        if options.max_tokens is not None:
            payload["options"]["num_predict"] = options.max_tokens

        data = await self._post_chat(payload)
        response = self._to_model_response(data)

        try:
            validated = schema.model_validate_json(response.content)
        except (ValidationError, json.JSONDecodeError) as e:
            raise StructuredOutputError(
                f"Model did not return valid {schema.__name__}: {e}\n"
                f"Raw content:\n{response.content}"
            ) from e

        return validated, response

    async def _post_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            resp = await self._client.post(
                f"{self.base_url}/api/chat",
                json=payload,
            )
        except httpx.TimeoutException as e:
            raise ModelTimeoutError(str(e)) from e
        except httpx.HTTPError as e:
            raise ModelUnavailableError(str(e)) from e

        if resp.status_code == 404:
            raise ModelNotFoundError(
                f"Model or endpoint not found: {self.model}"
            )
        if resp.status_code == 429:
            raise ModelUnavailableError("Ollama rate limited the request")
        if resp.status_code >= 500:
            raise ModelUnavailableError(
                f"Ollama server error {resp.status_code}: {resp.text}"
            )
        if resp.status_code >= 400:
            raise ModelProtocolError(
                f"Ollama client error {resp.status_code}: {resp.text}"
            )

        return resp.json()

    def _to_model_response(self, data: dict[str, Any]) -> ModelResponse:
        message = data.get("message") or {}
        content = message.get("content", "")

        return ModelResponse(
            content=content,
            model=data.get("model", self.model),
            backend="ollama",
            finish_reason=data.get("done_reason"),
            usage=ModelUsage(
                prompt_tokens=data.get("prompt_eval_count"),
                completion_tokens=data.get("eval_count"),
                total_duration_ns=data.get("total_duration"),
                load_duration_ns=data.get("load_duration"),
                prompt_eval_duration_ns=data.get("prompt_eval_duration"),
                eval_duration_ns=data.get("eval_duration"),
            ),
            metadata={
                "raw_done": data.get("done"),
                "created_at": data.get("created_at"),
            },
        )