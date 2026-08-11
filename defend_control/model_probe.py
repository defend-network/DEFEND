from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import time
from typing import Protocol
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .types import ModelReady


_MAX_RESPONSE_BYTES = 64 * 1024


@dataclass(frozen=True)
class ProbeResponse:
    status_code: int
    body: bytes


class _Transport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json: object | None,
        timeout: float,
        max_response_bytes: int,
    ) -> ProbeResponse: ...


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self, request, file_pointer, code, message, headers, new_url
    ):
        return None


class _UrllibTransport:
    def __init__(self) -> None:
        self._opener = build_opener(_NoRedirectHandler())

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json: object | None,
        timeout: float,
        max_response_bytes: int,
    ) -> ProbeResponse:
        payload = None
        if json is not None:
            payload = globals()["json"].dumps(
                json, separators=(",", ":")
            ).encode("utf-8")
        request = Request(url, data=payload, headers=headers, method=method)
        try:
            with self._opener.open(request, timeout=timeout) as response:
                body = response.read(max_response_bytes + 1)
                status = int(getattr(response, "status", 200))
        except HTTPError as error:
            try:
                body = error.read(max_response_bytes + 1)
                status = int(error.code)
            finally:
                error.close()
        if len(body) > max_response_bytes:
            raise ValueError("response exceeds 64 KiB")
        return ProbeResponse(status, body)


class ModelProbeError(RuntimeError):
    """A safe vLLM readiness failure with no response content."""


class ModelProbe:
    def __init__(
        self,
        *,
        transport: _Transport | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._transport = transport or _UrllibTransport()
        self._monotonic = monotonic
        self._sleep = sleep

    def __repr__(self) -> str:
        return "ModelProbe()"

    @staticmethod
    def _base_url(value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("model base URL must use loopback")
        parsed = urlsplit(value)
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or parsed.port != 8001
            or parsed.path.rstrip("/") != "/v1"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("model base URL must use loopback 127.0.0.1:8001/v1")
        return "http://127.0.0.1:8001/v1"

    def _request(
        self,
        method: str,
        url: str,
        token: str,
        body: object | None,
        timeout: float,
    ) -> ProbeResponse:
        try:
            response = self._transport.request(
                method,
                url,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {token}",
                    **({"Content-Type": "application/json"} if body is not None else {}),
                },
                json=body,
                timeout=timeout,
                max_response_bytes=_MAX_RESPONSE_BYTES,
            )
        except Exception as error:
            raise ModelProbeError(
                f"vLLM readiness request failed ({type(error).__name__})"
            ) from None
        if len(response.body) > _MAX_RESPONSE_BYTES:
            raise ModelProbeError("vLLM readiness response exceeded 64 KiB")
        return response

    @staticmethod
    def _json(response: ProbeResponse) -> object | None:
        if not 200 <= response.status_code < 300:
            return None
        try:
            return json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None

    def wait_ready(
        self,
        base_url: str,
        api_key: str,
        model: str = "defend-ai",
        *,
        timeout_seconds: float = 300.0,
        poll_interval_seconds: float = 2.0,
        cancelled: Callable[[], bool] | None = None,
    ) -> ModelReady:
        base = self._base_url(base_url)
        if not isinstance(api_key, str) or not api_key:
            raise ValueError("vLLM API key must be a non-empty string")
        if model != "defend-ai":
            raise ValueError("served vLLM model alias must be defend-ai")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not 0 < float(timeout_seconds) <= 300
            or isinstance(poll_interval_seconds, bool)
            or not isinstance(poll_interval_seconds, (int, float))
            or not 0 <= float(poll_interval_seconds) <= 30
        ):
            raise ValueError("vLLM probe timing is invalid")
        deadline = self._monotonic() + float(timeout_seconds)
        models_url = f"{base}/models"
        while True:
            if cancelled is not None and cancelled():
                raise ModelProbeError("vLLM readiness was cancelled")
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                raise ModelProbeError("vLLM readiness timed out after 300 seconds")
            response = self._request(
                "GET", models_url, api_key, None, min(30.0, remaining)
            )
            document = self._json(response)
            models = document.get("data") if isinstance(document, Mapping) else None
            if isinstance(models, list) and any(
                isinstance(candidate, Mapping) and candidate.get("id") == model
                for candidate in models
            ):
                break
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                raise ModelProbeError("vLLM readiness timed out after 300 seconds")
            self._sleep(min(float(poll_interval_seconds), remaining))

        remaining = deadline - self._monotonic()
        if remaining <= 0:
            raise ModelProbeError("vLLM readiness timed out after 300 seconds")
        response = self._request(
            "POST",
            f"{base}/chat/completions",
            api_key,
            {
                "model": model,
                "messages": [
                    {"role": "user", "content": "Reply with READY only"}
                ],
                "temperature": 0,
                "max_tokens": 8,
            },
            min(30.0, remaining),
        )
        if self._monotonic() >= deadline:
            raise ModelProbeError("vLLM readiness timed out after 300 seconds")
        document = self._json(response)
        choices = document.get("choices") if isinstance(document, Mapping) else None
        content = None
        if isinstance(choices, list) and choices:
            first = choices[0]
            message = first.get("message") if isinstance(first, Mapping) else None
            content = message.get("content") if isinstance(message, Mapping) else None
        if not isinstance(content, str) or not content.strip():
            raise ModelProbeError("vLLM generation probe did not return content")
        return ModelReady(model, "openai_compatible", base)
