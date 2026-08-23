"""SCSCopilotModelProvider boundary (M1.4, P1, P2, H9-H10).

The application code never hard-depends on a vendor. Providers return a typed
response (messages/context, tool calls, visible answer, usage metadata, finish
reason, provider/model identity). The LOCAL Ollama provider needs no
credentials; an unconfigured provider keeps the deterministic fallback active.
No secrets in logs/traces/client payloads.
"""
from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from typing import Any

import requests

_OLLAMA_ENDPOINT = os.environ.get("SCS_OLLAMA_ENDPOINT", "http://127.0.0.1:11434")
_OLLAMA_MODEL = os.environ.get("SCS_COPILOT_MODEL", "qwen2.5:14b-instruct-q4_K_M")


class SCSCopilotModelProvider(ABC):
    provider_name: str
    privacy_class: str = "LOCAL_PRIVATE"  # LOCAL_PRIVATE | EXTERNAL_MANAGED (P48)

    @abstractmethod
    def complete(self, messages: list[dict[str, Any]], *,
                 tools: list[dict[str, Any]] | None = None,
                 timeout: float = 90.0) -> dict[str, Any]:
        """Return {content, tool_calls, finish_reason, usage, model, provider}."""


class OllamaCopilotProvider(SCSCopilotModelProvider):
    """Local Ollama reasoning provider - no credentials, no external upload."""

    provider_name = "ollama_local"

    def __init__(self, model: str = _OLLAMA_MODEL, *,
                 endpoint: str = _OLLAMA_ENDPOINT) -> None:
        self.model = model
        self._endpoint = endpoint.rstrip("/")

    def _available(self) -> bool:
        try:
            return requests.get(f"{self._endpoint}/api/tags", timeout=3).status_code == 200
        except Exception:
            return False

    def complete(self, messages, *, tools=None, timeout=90.0) -> dict[str, Any]:
        payload = {"model": self.model, "messages": messages, "stream": False,
                   "keep_alive": "5m"}
        if tools:
            payload["tools"] = tools
        try:
            response = requests.post(f"{self._endpoint}/api/chat", json=payload,
                                     timeout=timeout)
            if response.status_code != 200:
                return self._failed("provider_http_error")
            data = response.json()
            message = data.get("message", {})
            return {
                "content": message.get("content") or "",
                "tool_calls": [
                    {"name": tc.get("function", {}).get("name"),
                     "arguments": tc.get("function", {}).get("arguments", {})}
                    for tc in (message.get("tool_calls") or [])
                    if tc.get("function", {}).get("name")
                ],
                "finish_reason": data.get("done_reason") or "stop",
                "usage": {"prompt_tokens": data.get("prompt_eval_count"),
                          "completion_tokens": data.get("eval_count")},
                "model": self.model, "provider": self.provider_name,
            }
        except requests.Timeout:
            return self._failed("timeout")
        except Exception as error:
            return self._failed(type(error).__name__)

    def _failed(self, reason: str) -> dict[str, Any]:
        return {"content": "", "tool_calls": [], "finish_reason": reason,
                "usage": {}, "model": self.model, "provider": self.provider_name,
                "error": reason}


class UnconfiguredCopilotProvider(SCSCopilotModelProvider):
    provider_name = "unconfigured"

    def complete(self, messages, *, tools=None, timeout=90.0) -> dict[str, Any]:
        return {"content": "", "tool_calls": [], "finish_reason": "unconfigured",
                "usage": {}, "model": None, "provider": self.provider_name,
                "error": "no reasoning model configured"}


def build_copilot_provider() -> SCSCopilotModelProvider:
    """Pick the agent model provider from SCS_COPILOT_MODEL_PROVIDER.

    ollama (default local) -> local Ollama reasoning model (no credentials).
    unset/other           -> Unconfigured (deterministic fallback remains).
    """
    provider = os.environ.get("SCS_COPILOT_MODEL_PROVIDER", "ollama").strip().lower()
    if provider in ("ollama", "local"):
        instance = OllamaCopilotProvider()
        if instance._available():
            return instance
        return UnconfiguredCopilotProvider()
    return UnconfiguredCopilotProvider()
