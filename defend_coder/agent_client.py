from __future__ import annotations

from dataclasses import dataclass
import json
import socket
import ssl
from typing import Any
from urllib import error as url_error
from urllib import request as url_request

from .model_config import CoderModelConfig


class ModelUnavailableError(RuntimeError):
    """The configured model endpoint could not be reached or answered."""


class ModelTimeoutError(ModelUnavailableError):
    """The model endpoint exceeded its timeout."""


class ModelError(ModelUnavailableError):
    """The model endpoint returned an unusable response."""


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class AgentChatResponse:
    content: str | None
    tool_calls: tuple[ToolCall, ...]


class AgentChatClient:
    """Minimal OpenAI-compatible chat client with function-calling support.

    Talks only to the loopback endpoint from the model config. Never logs
    prompts, responses, or the API key; every failure surfaces as an
    explicit error type so the agent reports an honest model state instead
    of silently falling back.
    """

    def __init__(
        self,
        config: CoderModelConfig,
        *,
        timeout_seconds: float = 180.0,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        urlopen: Any = None,
    ) -> None:
        if not isinstance(config, CoderModelConfig):
            raise TypeError("config must be a CoderModelConfig")
        if not config.base_url:
            raise ValueError("model config requires base_url")
        self._config = config
        self._timeout = max(1.0, float(timeout_seconds))
        self._max_tokens = max(1, int(max_tokens))
        self._temperature = float(temperature)
        self._urlopen = urlopen or url_request.urlopen

    @property
    def model_name(self) -> str:
        return self._config.model_name

    @property
    def provider(self) -> str:
        return "openai_compatible"

    def _endpoint(self) -> str:
        return f"{self._config.base_url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        return headers

    @staticmethod
    def _parse_arguments(raw: str) -> dict[str, Any]:
        if not isinstance(raw, str) or not raw.strip():
            return {}
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {"_raw_arguments": raw}
        if not isinstance(parsed, dict):
            return {"_raw_arguments": raw}
        return parsed

    @staticmethod
    def _parse_message(message: dict[str, Any]) -> AgentChatResponse:
        try:
            content = message.get("content")
        except (KeyError, TypeError) as error:
            raise ModelError(
                "model response did not contain a message"
            ) from None

        if content is not None and not isinstance(content, str):
            content = None

        tool_calls: list[ToolCall] = []
        raw_calls = message.get("tool_calls") or []
        for raw in raw_calls:
            if not isinstance(raw, dict):
                continue
            function = raw.get("function") or {}
            if not isinstance(function, dict):
                continue
            name = function.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            tool_calls.append(
                ToolCall(
                    id=str(raw.get("id") or f"call_{len(tool_calls)}"),
                    name=name.strip(),
                    arguments=AgentChatClient._parse_arguments(
                        function.get("arguments") or "{}"
                    ),
                )
            )
        return AgentChatResponse(
            content=content,
            tool_calls=tuple(tool_calls),
        )

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> AgentChatResponse:
        payload: dict[str, Any] = {
            "model": self._config.model_name,
            "messages": messages,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        body = json.dumps(payload).encode("utf-8")
        request = url_request.Request(
            self._endpoint(),
            data=body,
            headers=self._headers(),
            method="POST",
        )
        timeout = (
            self._timeout
            if timeout_seconds is None
            else max(1.0, float(timeout_seconds))
        )
        try:
            with self._urlopen(request, timeout=timeout) as response:
                raw = response.read()
        except socket.timeout:
            raise ModelTimeoutError(
                f"model request timed out after {timeout:.0f}s"
            ) from None
        except url_error.HTTPError as error:
            raise ModelError(
                f"model endpoint returned HTTP {error.code}"
            ) from None
        except (url_error.URLError, OSError, ssl.SSLError) as error:
            raise ModelUnavailableError(
                f"model endpoint unreachable ({type(error).__name__})"
            ) from None
        try:
            payload = json.loads(raw.decode("utf-8", errors="replace"))
        except (ValueError, UnicodeDecodeError):
            raise ModelError("model returned invalid JSON") from None
        if not isinstance(payload, dict):
            raise ModelError("model returned a non-object response")
        try:
            choices = payload["choices"]
            message = choices[0]["message"]
        except (KeyError, IndexError, TypeError) as error:
            raise ModelError(
                "model response did not contain a message"
            ) from None
        if not isinstance(message, dict):
            raise ModelError("model response did not contain a message")
        return self._parse_message(message)