from __future__ import annotations

from dataclasses import dataclass
import http.client
import json
import socket
import ssl
import time
from typing import Any, Callable
from urllib import error as url_error
from urllib import request as url_request
from urllib.parse import urlsplit

from .model_config import (
    CoderModelConfig,
    DEFAULT_MODEL_CONNECT_TIMEOUT_SECONDS,
    DEFAULT_MODEL_TIMEOUT_SECONDS,
)


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
    usage: dict[str, int] | None = None
    finish_reason: str | None = None


class _HttpClientTransport:
    """Two-phase loopback transport: connect vs generation budgets.

    The connection phase is bounded by the configured connect timeout and
    surfaces as a connection failure; the generation phase is bounded by
    the per-call generation timeout and surfaces as a socket timeout, so
    the client can distinguish an unreachable endpoint from a slow healthy
    decode. The call contract mirrors urlopen: ``(request, timeout=...)``
    returning a context-managed response with ``.read()`` and ``.status``.
    """

    def __init__(self, connect_timeout_seconds: float) -> None:
        self._connect_timeout = float(connect_timeout_seconds)

    def __call__(
        self,
        request: url_request.Request,
        timeout: float | None = None,
    ):
        generation_timeout = max(
            1.0, float(timeout) if timeout is not None
            else DEFAULT_MODEL_TIMEOUT_SECONDS
        )
        parts = urlsplit(request.full_url)
        host = parts.hostname or "127.0.0.1"
        port = parts.port or (443 if parts.scheme == "https" else 80)
        connection_cls = (
            http.client.HTTPSConnection
            if parts.scheme == "https"
            else http.client.HTTPConnection
        )
        connection = connection_cls(
            host, port, timeout=self._connect_timeout
        )
        try:
            connection.connect()
        except socket.timeout:
            raise ConnectionError(
                "model endpoint connection timed out "
                f"after {self._connect_timeout:.0f}s"
            ) from None
        except (OSError, ssl.SSLError) as error:
            raise ConnectionError(
                f"model endpoint connection failed "
                f"({type(error).__name__})"
            ) from None
        try:
            connection.sock.settimeout(generation_timeout)
            path = parts.path or "/"
            if parts.query:
                path = f"{path}?{parts.query}"
            connection.request(
                "POST",
                path,
                body=request.data,
                headers=dict(request.headers),
            )
            response = connection.getresponse()
            body = response.read()
        except socket.timeout:
            raise
        finally:
            connection.close()
        return _HttpResponse(body, response.status, parts.scheme)


class _HttpResponse:
    def __init__(self, body: bytes, status: int, scheme: str) -> None:
        self._body = body
        self.status = status
        self._scheme = scheme

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class AgentChatClient:
    """Minimal OpenAI-compatible chat client with function-calling support.

    Talks only to the loopback endpoint from the model config. Never logs
    prompts, responses, or the API key; every failure surfaces as an
    explicit error type so the agent reports an honest model state instead
    of silently falling back.

    Timeout policy (one authoritative source, ``CoderModelConfig``): the
    generation budget defaults to ``CODER_MODEL_TIMEOUT_SECONDS`` and the
    connection budget to ``CODER_MODEL_CONNECT_TIMEOUT_SECONDS``. A slow
    healthy decode raises ``ModelTimeoutError`` only after the full
    generation budget; an unreachable endpoint raises
    ``ModelUnavailableError`` after the much smaller connection budget.
    """

    def __init__(
        self,
        config: CoderModelConfig,
        *,
        timeout_seconds: float | None = None,
        connect_timeout_seconds: float | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        urlopen: Any = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not isinstance(config, CoderModelConfig):
            raise TypeError("config must be a CoderModelConfig")
        if not config.base_url:
            raise ValueError("model config requires base_url")
        self._config = config
        self._timeout = max(
            1.0,
            float(
                timeout_seconds
                if timeout_seconds is not None
                else config.timeout_seconds
            ),
        )
        self._connect_timeout = max(
            1.0,
            float(
                connect_timeout_seconds
                if connect_timeout_seconds is not None
                else config.connect_timeout_seconds
            ),
        )
        self._max_tokens = max(1, int(max_tokens))
        self._temperature = float(temperature)
        if urlopen is None:
            self._urlopen = _HttpClientTransport(self._connect_timeout)
        else:
            self._urlopen = urlopen
        self._clock = clock

    @property
    def model_name(self) -> str:
        return self._config.model_name

    @property
    def provider(self) -> str:
        return "openai_compatible"

    @property
    def timeout_seconds(self) -> float:
        return self._timeout

    @property
    def connect_timeout_seconds(self) -> float:
        return self._connect_timeout

    @property
    def max_tokens(self) -> int:
        return self._max_tokens

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
    def _parse_message(
        message: dict[str, Any],
        usage: dict[str, Any] | None = None,
        finish_reason: str | None = None,
    ) -> AgentChatResponse:
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
            usage=usage if isinstance(usage, dict) else None,
            finish_reason=finish_reason or None,
        )

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        timeout_seconds: float | None = None,
        max_tokens: int | None = None,
        on_request_started: Callable[[], None] | None = None,
    ) -> AgentChatResponse:
        payload: dict[str, Any] = {
            "model": self._config.model_name,
            "messages": messages,
            "temperature": self._temperature,
            "max_tokens": (
                max(1, int(max_tokens))
                if max_tokens is not None
                else self._max_tokens
            ),
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
        generation_timeout = (
            self._timeout
            if timeout_seconds is None
            else max(1.0, float(timeout_seconds))
        )
        deadline = self._clock() + generation_timeout
        if on_request_started is not None:
            on_request_started()
        try:
            response = self._urlopen(request, timeout=generation_timeout)
        except socket.timeout:
            raise ModelTimeoutError(
                f"model request timed out after {generation_timeout:.0f}s"
            ) from None
        except url_error.HTTPError as error:
            raise ModelError(
                f"model endpoint returned HTTP {error.code}"
            ) from None
        except (ConnectionError, url_error.URLError, OSError,
                ssl.SSLError) as error:
            raise ModelUnavailableError(
                f"model endpoint unreachable ({type(error).__name__})"
            ) from None
        try:
            with response:
                raw = response.read()
        except socket.timeout:
            raise ModelTimeoutError(
                f"model request timed out after {generation_timeout:.0f}s"
            ) from None
        except (ConnectionError, url_error.URLError, OSError,
                ssl.SSLError) as error:
            raise ModelUnavailableError(
                f"model endpoint unreachable ({type(error).__name__})"
            ) from None
        if (
            isinstance(raw, bytes)
            and self._clock() > deadline
        ):
            raise ModelTimeoutError(
                f"model request timed out after {generation_timeout:.0f}s"
            ) from None
        if not isinstance(raw, bytes):
            raw = str(raw).encode("utf-8")
        status = getattr(response, "status", 200)
        if status >= 400:
            raise ModelError(
                f"model endpoint returned HTTP {status}"
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
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            usage = None
        finish_reason = None
        try:
            finish_reason = str(choices[0].get("finish_reason") or "")
        except (KeyError, IndexError, TypeError, AttributeError):
            finish_reason = None
        return self._parse_message(message, usage, finish_reason)