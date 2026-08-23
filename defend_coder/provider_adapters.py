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

from dataclasses import dataclass, field
import json
from typing import Any, Callable, Protocol

from .agent_client import (
    AgentChatClient,
    ModelError,
    ModelTimeoutError,
    ModelUnavailableError,
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


class CoderProviderError(RuntimeError):
    """Normalized provider failure taxonomy (adapter boundary)."""


class CoderProviderTimeout(CoderProviderError):
    pass


class CoderProviderUnavailable(CoderProviderError):
    pass


class CoderProviderAuthenticationError(CoderProviderError):
    pass


class CoderProviderRateLimited(CoderProviderError):
    pass


class CoderProviderConfigurationError(CoderProviderError):
    pass


class CoderProviderProtocolError(CoderProviderError):
    pass


def _map_chat_error(error: BaseException) -> CoderProviderError:
    if isinstance(error, ModelTimeoutError):
        return CoderProviderTimeout(str(error))
    if isinstance(error, ModelUnavailableError):
        return CoderProviderUnavailable(str(error))
    if isinstance(error, ModelError):
        return CoderProviderProtocolError(str(error))
    return CoderProviderProtocolError(f"{type(error).__name__}: {error}")


@dataclass(frozen=True)
class ProviderContinuationState:
    """Provider-SCOPED opaque continuation state.

    Private state from provider A is never passed to provider B. The agent
    discards it when the route changes.
    """

    provider_id: str
    model_id: str
    protocol: str
    state: dict[str, Any] = field(default_factory=dict)


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
class CoderUsage:
    """Provider-neutral token usage (adapter-normalized)."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_input_tokens: int | None = None
    reasoning_tokens: int | None = None


class CompletionState(str):
    STOP = "stop"
    TOOL_CALLS = "tool_calls"
    MAX_OUTPUT = "max_output"
    INCOMPLETE = "incomplete"
    CANCELLED = "cancelled"
    ERROR = "error"
    UNKNOWN = "unknown"

    @classmethod
    def from_chat_finish(cls, finish_reason: str | None, has_tools: bool) -> "CompletionState":
        if has_tools:
            return cls.TOOL_CALLS
        reason = (finish_reason or "").casefold()
        if reason in ("stop", "end_turn"):
            return cls.STOP
        if reason in ("length", "max_tokens"):
            return cls.MAX_OUTPUT
        if reason == "tool_calls":
            return cls.TOOL_CALLS
        return cls.UNKNOWN

    @classmethod
    def from_responses_status(cls, status: str | None, has_tools: bool) -> "CompletionState":
        if has_tools:
            return cls.TOOL_CALLS
        if status == "completed":
            return cls.STOP
        if status == "incomplete":
            return cls.INCOMPLETE
        return cls.UNKNOWN


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_chat_usage(raw: dict[str, Any] | None) -> CoderUsage:
    raw = raw or {}
    input_tokens = _int_or_none(raw.get("prompt_tokens")) or 0
    output_tokens = _int_or_none(raw.get("completion_tokens")) or 0
    total_tokens = _int_or_none(raw.get("total_tokens")) or (
        input_tokens + output_tokens
    )
    return CoderUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cached_input_tokens=_int_or_none(raw.get("cached_input_tokens")),
        reasoning_tokens=_int_or_none(raw.get("reasoning_tokens")),
    )


def normalize_responses_usage(raw: dict[str, Any] | None) -> CoderUsage:
    raw = raw or {}
    input_tokens = _int_or_none(raw.get("input_tokens")) or 0
    output_tokens = _int_or_none(raw.get("output_tokens")) or 0
    total_tokens = _int_or_none(raw.get("total_tokens")) or (
        input_tokens + output_tokens
    )
    return CoderUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cached_input_tokens=_int_or_none(raw.get("input_tokens_details", {}).get("cached_tokens")) if isinstance(raw.get("input_tokens_details"), dict) else None,
        reasoning_tokens=_int_or_none(raw.get("output_tokens_details", {}).get("reasoning_tokens")) if isinstance(raw.get("output_tokens_details"), dict) else None,
    )


@dataclass(frozen=True)
class CoderGenerationResult:
    visible_content: str | None
    tool_calls: tuple[ToolCall, ...]
    usage: dict[str, int] | None
    finish_reason: str | None
    provider: str
    model: str
    #: Provider-neutral normalized usage + completion state.
    normalized_usage: CoderUsage = field(default_factory=CoderUsage)
    completion: CompletionState = CompletionState.UNKNOWN
    #: Opaque provider-internal continuation state. NEVER browser/transcript/
    #: checkpoint/telemetry exposed.
    protocol_state: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def content(self) -> str | None:
        return self.visible_content


class CoderProvider(Protocol):
    provider_id: str
    model_id: str
    protocol: str

    def generate(
        self, request: CoderGenerationRequest
    ) -> CoderGenerationResult: ...


class RoutingCoderProvider:
    """Re-resolves the ACTUAL provider before every generation, at the
    normalized CoderProvider boundary (never below it through a concrete
    HTTP client). Used for mid-run owner-approved escalation.
    """

    def __init__(self, resolver: Callable[[], CoderProvider]) -> None:
        self._resolver = resolver

    def _current(self) -> CoderProvider:
        return self._resolver()

    @property
    def provider_id(self) -> str:
        return self._current().provider_id

    @property
    def model_id(self) -> str:
        return self._current().model_id

    @property
    def protocol(self) -> str:
        return self._current().protocol

    def generate(
        self, request: CoderGenerationRequest
    ) -> CoderGenerationResult:
        return self._current().generate(request)


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
    """DeepSeek thinking-mode tool-call continuation.

    Reasoning is bound EXACTLY to the assistant tool turn that produced it
    (by tool_call_id), never broadcast to every historical assistant message
    and never exposed. ``continuation_state["reasoning_by_call"]`` maps
    tool_call_id -> reasoning_content (provider-scoped).
    """
    reasoning_by_call = continuation_state.get("reasoning_by_call") or {}
    if not reasoning_by_call:
        return list(conversation)
    result: list[dict[str, Any]] = []
    for message in conversation:
        tool_calls = (
            message.get("tool_calls")
            if message.get("role") == "assistant"
            else None
        )
        if tool_calls and "reasoning_content" not in message:
            reasoning = next(
                (
                    reasoning_by_call[call["id"]]
                    for call in tool_calls
                    if call.get("id") in reasoning_by_call
                ),
                None,
            )
            if reasoning:
                message = dict(message)
                message["reasoning_content"] = reasoning
        result.append(message)
    return result


class ChatCompletionsProvider:
    """Generic OpenAI-compatible Chat Completions adapter (internal reuse).

    Wraps any AgentChatClient transport, owns reasoning_content replay, and
    emits a normalized CoderGenerationResult. DeepSeek/Next are thin
    subclasses; the transport is never selected as provider authority.
    """

    provider_id = "chat_completions"
    protocol = "chat_completions"

    def __init__(
        self,
        provider_id: str,
        model_id: str,
        *,
        transport: AgentChatClient,
    ) -> None:
        self.provider_id = provider_id
        self.model_id = model_id
        self._transport = transport

    def generate(self, request: CoderGenerationRequest) -> CoderGenerationResult:
        conversation = _inject_reasoning(
            request.conversation, request.continuation_state
        )
        messages = [
            {"role": "system", "content": request.system_authority},
            *conversation,
        ]
        try:
            response = self._transport.chat(
                messages,
                tools=list(request.tools) or None,
                max_tokens=request.max_output_tokens,
                timeout_seconds=request.timeout_seconds,
            )
        except CoderProviderError:
            raise
        except Exception as error:  # noqa: BLE001
            raise _map_chat_error(error) from None
        return CoderGenerationResult(
            visible_content=response.content,
            tool_calls=response.tool_calls,
            usage=response.usage,
            finish_reason=response.finish_reason,
            provider=self.provider_id,
            model=self.model_id,
            normalized_usage=normalize_chat_usage(response.usage),
            completion=CompletionState.from_chat_finish(
                response.finish_reason, bool(response.tool_calls)
            ),
            protocol_state={"reasoning_content": response.reasoning_content},
        )


class DeepSeekProvider(ChatCompletionsProvider):
    provider_id = "deepseek"

    def __init__(self, model_id: str, *, transport: AgentChatClient) -> None:
        super().__init__("deepseek", model_id, transport=transport)


class NextVllmProvider(ChatCompletionsProvider):
    provider_id = "self_hosted"

    def __init__(self, model_id: str, *, transport: AgentChatClient) -> None:
        super().__init__("self_hosted", model_id, transport=transport)


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
        response_id = request.continuation_state.get("response_id")
        call_ids = request.continuation_state.get("call_ids") or []
        payload = {
            "model": self.model_id,
            "instructions": request.system_authority,
            "max_output_tokens": request.max_output_tokens,
        }
        if response_id and call_ids:
            # Continuation: use ONLY the immediately preceding response's
            # function_call_outputs. Locate the MOST RECENT assistant
            # tool-call block, require its call ids to exactly match the
            # expected provider call_ids, and collect only that block's
            # subsequent tool outputs. Historical prior tool results (even a
            # reused call id) never affect the current continuation.
            conversation = list(request.conversation)
            block_idx: int | None = None
            for i in range(len(conversation) - 1, -1, -1):
                m = conversation[i]
                if m.get("role") == "assistant" and m.get("tool_calls"):
                    block_idx = i
                    break
            if block_idx is None:
                raise CoderProviderProtocolError(
                    "no assistant tool-call block for continuation"
                )
            block_call_ids = [
                tc.get("id")
                for tc in conversation[block_idx].get("tool_calls", [])
                if isinstance(tc, dict)
            ]
            if block_call_ids != list(call_ids):
                raise CoderProviderProtocolError(
                    "assistant call ids do not match expected call_ids"
                )
            results_by_call: dict[str, str] = {}
            for m in conversation[block_idx + 1:]:
                if m.get("role") != "tool":
                    continue
                cid = m.get("tool_call_id")
                if cid is None:
                    continue
                if cid not in call_ids:
                    raise CoderProviderProtocolError(
                        f"unexpected tool result for call {cid!r} in the "
                        "current block"
                    )
                if cid in results_by_call:
                    raise CoderProviderProtocolError(
                        f"duplicate tool result for call {cid!r}"
                    )
                results_by_call[cid] = m.get("content") or ""
            tool_outputs = []
            for call_id in call_ids:
                if call_id not in results_by_call:
                    raise CoderProviderProtocolError(
                        f"missing expected function_call_output for "
                        f"{call_id!r}"
                    )
                tool_outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": results_by_call[call_id],
                    }
                )
            payload["previous_response_id"] = response_id
            payload["input"] = tool_outputs
        else:
            payload["input"] = [
                {"role": m["role"], "content": m["content"]}
                for m in request.conversation
                if m.get("role") in ("user", "assistant") and m.get("content")
            ]
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
            normalized_usage=normalize_responses_usage(usage),
            completion=CompletionState.from_responses_status(
                data.get("status"), bool(tool_calls)
            ),
            protocol_state={
                "response_id": data.get("id"),
                "call_ids": [call.id for call in tool_calls],
            },
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
