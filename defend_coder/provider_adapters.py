"""Normalized provider abstraction (CoderProvider) + real adapters.

CodingAgent must consume ``CoderProvider.generate()``, not a concrete HTTP
client. Each adapter owns its protocol (Chat Completions vs Responses),
thinking policy, reasoning replay, tool shape, usage normalization, and
errors. Credentials resolve at call time via the CredentialStore and never
reach the agent. No adapter ever starts GPU compute.

``AgentChatClient`` remains an INTERNAL reusable Chat Completions transport
beneath DeepSeek/Next adapters — it is never selected as provider authority.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from .agent_client import (
    AgentChatClient,
    ToolCall,
)
from .credentials import CredentialStore
from .providers import (
    DeepSeekThinkingPolicy,
    ModelTarget,
    deepseek_target,
    next_target,
    sol_target,
)


@dataclass(frozen=True)
class CoderGenerationRequest:
    system_authority: str
    conversation: tuple[dict[str, Any], ...] = ()
    tools: tuple[dict[str, Any], ...] = ()
    max_output_tokens: int = 4096
    temperature: float = 0.3
    timeout_seconds: float | None = None
    continuation_state: dict[str, Any] = field(default_factory=dict)
    run_metadata: dict[str, Any] = field(default_factory=dict)

    def as_messages(self) -> list[dict[str, Any]]:
        return [{"role": "system", "content": self.system_authority}, *self.conversation]


@dataclass(frozen=True)
class CoderGenerationResult:
    visible_content: str | None
    tool_calls: tuple[ToolCall, ...]
    usage: dict[str, int] | None
    finish_reason: str | None
    provider: str
    model: str
    #: Opaque provider-internal continuation state. NEVER browser/transcript/
    #: checkpoint/telemetry exposed.
    protocol_state: dict[str, Any] = field(default_factory=dict, repr=False)


class CoderProvider(Protocol):
    provider_id: str
    model_id: str
    protocol: str

    def generate(
        self, request: CoderGenerationRequest
    ) -> CoderGenerationResult: ...


def _normalize_tool_calls(
    calls: tuple[ToolCall, ...],
) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "id": call.id,
            "type": "function",
            "function": {
                "name": call.name,
                "arguments": json.dumps(call.arguments),
            },
        }
        for call in calls
    )


def _inject_reasoning(
    conversation: tuple[dict[str, Any], ...],
    continuation_state: dict[str, Any],
) -> list[dict[str, Any]]:
    """DeepSeek thinking-mode tool-call continuation: replay the assistant's
    reasoning_content onto the last assistant tool-call message (internal)."""
    reasoning = continuation_state.get("reasoning_content")
    if not reasoning:
        return list(conversation)
    result: list[dict[str, Any]] = []
    for message in conversation:
        if message.get("role") == "assistant" and message.get("tool_calls"):
            if "reasoning_content" not in message:
                message = dict(message)
                message["reasoning_content"] = reasoning
        result.append(message)
    return result


class DeepSeekProvider:
    provider_id = "deepseek"
    protocol = "chat_completions"

    def __init__(self, model_id: str, *, transport: AgentChatClient) -> None:
        self.model_id = model_id
        self._transport = transport

    def generate(self, request: CoderGenerationRequest) -> CoderGenerationResult:
        conversation = _inject_reasoning(
            request.conversation, request.continuation_state
        )
        messages = [{"role": "system", "content": request.system_authority}, *conversation]
        response = self._transport.chat(
            messages,
            tools=list(request.tools) or None,
            max_tokens=request.max_output_tokens,
            timeout_seconds=request.timeout_seconds,
        )
        return CoderGenerationResult(
            visible_content=response.content,
            tool_calls=response.tool_calls,
            usage=response.usage,
            finish_reason=response.finish_reason,
            provider=self.provider_id,
            model=self.model_id,
            protocol_state={"reasoning_content": response.reasoning_content},
        )


class NextVllmProvider:
    provider_id = "self_hosted"
    protocol = "chat_completions"

    def __init__(self, model_id: str, *, transport: AgentChatClient) -> None:
        self.model_id = model_id
        self._transport = transport

    def generate(self, request: CoderGenerationRequest) -> CoderGenerationResult:
        messages = request.as_messages()
        response = self._transport.chat(
            messages,
            tools=list(request.tools) or None,
            max_tokens=request.max_output_tokens,
            timeout_seconds=request.timeout_seconds,
        )
        return CoderGenerationResult(
            visible_content=response.content,
            tool_calls=response.tool_calls,
            usage=response.usage,
            finish_reason=response.finish_reason,
            provider=self.provider_id,
            model=self.model_id,
            protocol_state={},
        )


class OpenAIResponsesProvider:
    """Sol via the OpenAI Responses API (/v1/responses). No live calls."""

    provider_id = "openai"
    protocol = "responses"

    def __init__(
        self,
        model_id: str,
        *,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        transport: Callable[[bytes], dict[str, Any]] | None = None,
    ) -> None:
        self.model_id = model_id
        self._api_key = api_key
        self._endpoint = base_url.rstrip("/") + "/responses"
        self._transport = transport

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._transport is not None:
            return self._transport(json.dumps(payload).encode("utf-8"))
        import urllib.request

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._endpoint,
            data=body,
            headers={
                "Authorization": "Bearer " + self._api_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))

    def generate(self, request: CoderGenerationRequest) -> CoderGenerationResult:
        payload = {
            "model": self.model_id,
            "instructions": request.system_authority,
            "input": [
                {"role": m["role"], "content": m["content"]}
                for m in request.conversation
            ],
            "max_output_tokens": request.max_output_tokens,
        }
        if request.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "name": tool["function"]["name"],
                    "description": tool["function"].get("description", ""),
                    "parameters": tool["function"].get("parameters", {}),
                }
                for tool in request.tools
            ]
        data = self._post(payload)
        output = data.get("output", []) if isinstance(data, dict) else []
        content: str | None = None
        tool_calls: list[ToolCall] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "message":
                for part in item.get("content", []) or []:
                    if part.get("type") == "output_text":
                        content = part.get("text")
            elif item.get("type") == "function_call":
                tool_calls.append(
                    ToolCall(
                        id=item.get("call_id", "call_0"),
                        name=item.get("name", ""),
                        arguments=json.loads(item.get("arguments") or "{}")
                        if isinstance(item.get("arguments"), str)
                        else (item.get("arguments") or {}),
                    )
                )
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else None
        return CoderGenerationResult(
            visible_content=content,
            tool_calls=tuple(tool_calls),
            usage=usage,
            finish_reason=data.get("status"),
            provider=self.provider_id,
            model=self.model_id,
            protocol_state={"response_id": data.get("id")},
        )


class CoderProviderFactory:
    """Route -> provider adapter. Resolves credentials at call time; never
    starts GPU. Runtime activation is controlled elsewhere (owner escalation).
    """

    def __init__(
        self,
        credentials: CredentialStore,
        *,
        urlopen: Callable[..., Any] | None = None,
        responses_transport: Callable[[bytes], dict[str, Any]] | None = None,
    ) -> None:
        self._credentials = credentials
        self._urlopen = urlopen
        self._responses_transport = responses_transport

    def _chat_transport(
        self,
        target: ModelTarget,
        api_key: str | None,
        *,
        extra_body: dict[str, Any] | None = None,
    ) -> AgentChatClient:
        from .providers import build_client

        return build_client(
            target,
            api_key=api_key,
            urlopen=self._urlopen,
            default_extra_body=extra_body,
        )

    def for_model(self, model: str) -> CoderProvider:
        if model == deepseek_target().model_id:
            key = self._credentials.resolve("deepseek")
            if not key:
                raise ValueError("DeepSeek is not configured")
            target = deepseek_target(availability=True)
            thinking = parse_thinking(self._credentials)
            return DeepSeekProvider(
                model,
                transport=self._chat_transport(
                    target, key, extra_body=thinking.to_request_body()
                ),
            )
        if model == next_target().model_id:
            return NextVllmProvider(
                model,
                transport=self._chat_transport(next_target(), None),
            )
        if model == sol_target().model_id:
            key = self._credentials.resolve("sol")
            if not key:
                raise ValueError("Sol is not configured")
            return OpenAIResponsesProvider(
                model,
                api_key=key,
                transport=self._responses_transport,
            )
        raise ValueError(f"no provider for model {model!r}")


def parse_thinking(credentials: CredentialStore) -> DeepSeekThinkingPolicy:
    from .providers import parse_deepseek_thinking_policy

    # Read the typed policy from the environment (server config), not from
    # the credential store.
    return parse_deepseek_thinking_policy()
