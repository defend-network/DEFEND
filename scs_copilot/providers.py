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
import uuid
from abc import ABC, abstractmethod
from typing import Any

import requests

_OLLAMA_ENDPOINT = os.environ.get("SCS_OLLAMA_ENDPOINT", "http://127.0.0.1:11434")
_OLLAMA_MODEL = os.environ.get("SCS_COPILOT_MODEL", "qwen2.5:14b-instruct-q4_K_M")


def _normalize_arguments(arguments: Any) -> dict[str, Any]:
    """Safely normalize model/provider tool arguments (P67): accept dict or
    serialized JSON; never eval arbitrary strings."""
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


def new_provider_tool_call_id() -> str:
    return f"ptc-{uuid.uuid4().hex[:12]}"


class SCSCopilotModelProvider(ABC):
    provider_name: str
    privacy_class: str = "LOCAL_PRIVATE"  # LOCAL_PRIVATE | EXTERNAL_MANAGED (P48)

    @abstractmethod
    def complete(self, messages: list[dict[str, Any]], *,
                 tools: list[dict[str, Any]] | None = None,
                 timeout: float = 90.0) -> dict[str, Any]:
        """Return {content, tool_calls, finish_reason, usage, model, provider}.

        Each tool_call is {name, arguments, id} where ``id`` is the PROVIDER
        tool-call id (P8) - distinct from any SCS evidence id."""

    def tool_result_message(self, tool_call_id: str | None,
                            content: str) -> dict[str, Any]:
        """Serialize a tool result into the provider's NATIVE message format
        (P9). The provider owns this serialization; the agent loop must not
        assume a normalized dict is valid Ollama syntax."""
        return {"role": "tool", "content": content}

    def tool_call_message(self, tool_calls: list[dict[str, Any]]) -> dict[str, Any]:
        """Serialize internal tool-call records into the provider's NATIVE
        assistant message format (P9)."""
        return {"role": "assistant", "content": None,
                "tool_calls": [{"function": {"name": tc["name"],
                                             "arguments": tc.get("arguments", {})},
                                "id": tc.get("id")} for tc in tool_calls]}


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
            tool_calls = []
            for tc in (message.get("tool_calls") or []):
                fn = tc.get("function", {}) or {}
                name = fn.get("name")
                if not name:
                    continue
                provider_id = tc.get("id") or new_provider_tool_call_id()
                tool_calls.append({
                    "name": name,
                    "arguments": _normalize_arguments(fn.get("arguments", {})),
                    "id": provider_id,
                })
            return {
                "content": message.get("content") or "",
                "tool_calls": tool_calls,
                "finish_reason": data.get("done_reason") or "stop",
                "usage": {"prompt_tokens": data.get("prompt_eval_count"),
                          "completion_tokens": data.get("eval_count")},
                "model": self.model, "provider": self.provider_name,
            }
        except requests.Timeout:
            return self._failed("timeout")
        except Exception as error:
            return self._failed(type(error).__name__)

    def tool_result_message(self, tool_call_id: str | None,
                            content: str) -> dict[str, Any]:
        """Ollama native tool result: role 'tool' + content. The provider
        tool-call id is preserved when available (P8/P17); Ollama matches by
        position and ignores the extra field if unsupported."""
        message = {"role": "tool", "content": content}
        if tool_call_id:
            message["tool_call_id"] = tool_call_id
        return message

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
