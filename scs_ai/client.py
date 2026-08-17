from __future__ import annotations

import json
import socket
import ssl
from typing import Any
from urllib import error as url_error
from urllib import request as url_request

from .model_gateway import ProviderProfile


class ModelUnavailableError(RuntimeError):
    """The configured model endpoint could not be reached or answered."""


class ModelTimeoutError(ModelUnavailableError):
    """The model endpoint exceeded its timeout."""


class ModelError(ModelUnavailableError):
    """The model endpoint returned an unusable response."""


class OpenAiCompatibleChatClient:
    """Minimal OpenAI-compatible chat client used by the SCS AI assistant.

    The client only talks to the loopback endpoint carried by the provider
    profile. It never logs prompts, responses, or the API key, and it reports
    every failure as an explicit error type so callers can surface an honest
    model state instead of silently falling back.
    """

    def __init__(
        self,
        profile: ProviderProfile,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 90.0,
        max_tokens: int = 1200,
        urlopen: Any = None,
    ) -> None:
        if not isinstance(profile, ProviderProfile):
            raise TypeError("profile must be a ProviderProfile")
        if not profile.base_url:
            raise ValueError("provider profile requires base_url")
        self._profile = profile
        self._api_key = api_key
        self._timeout = max(1.0, float(timeout_seconds))
        self._max_tokens = max(1, int(max_tokens))
        self._urlopen = urlopen or url_request.urlopen

    @property
    def model_name(self) -> str:
        return self._profile.model_name

    def _endpoint(self) -> str:
        return f"{self._profile.base_url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _payload(self, messages: list[dict[str, str]], temperature: float) -> dict[str, Any]:
        return {
            "model": self._profile.model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": self._max_tokens,
        }

    @staticmethod
    def _response_text(payload: dict[str, Any]) -> str:
        try:
            choices = payload["choices"]
            content = choices[0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ModelError("model response did not contain a message") from None
        if not isinstance(content, str) or not content.strip():
            raise ModelError("model returned an empty message")
        return content.strip()

    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.4,
        timeout_seconds: float | None = None,
    ) -> str:
        body = json.dumps(
            self._payload(messages, temperature)
        ).encode("utf-8")
        request = url_request.Request(
            self._endpoint(),
            data=body,
            headers=self._headers(),
            method="POST",
        )
        timeout = self._timeout if timeout_seconds is None else max(1.0, float(timeout_seconds))
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
        return self._response_text(payload)