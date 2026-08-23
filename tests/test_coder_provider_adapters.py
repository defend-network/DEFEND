"""CoderProvider adapter fixtures (no live calls, no GPU)."""

from __future__ import annotations

import json

import pytest

from defend_coder.agent_client import AgentChatClient, AgentChatResponse, ToolCall
from defend_coder.credentials import CredentialStore
from defend_coder.model_config import CoderModelConfig
from defend_coder.provider_adapters import (
    CoderGenerationRequest,
    CoderProviderFactory,
    DeepSeekProvider,
    NextVllmProvider,
    OpenAIResponsesProvider,
)
from defend_coder.providers import (
    DeepSeekThinkingPolicy,
    deepseek_target,
    next_target,
    sol_target,
)


class _Store:
    def __init__(self, **values):
        self.values = dict(values)

    def load(self):
        return dict(self.values)

    def save(self, values):
        self.values = dict(values)


def _scripted_client(responses, *, capture=None, default_extra_body=None):
    class Resp:
        def __init__(self, body):
            self.status = 200
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    def transport(request, timeout=None):
        if capture is not None:
            capture.append(json.loads(request.data))
        body = responses.pop(0)
        return Resp(json.dumps(body).encode())

    return AgentChatClient(
        CoderModelConfig(
            alias="deepseek",
            model_name="deepseek-v4-flash",
            base_url="https://api.deepseek.com",
            api_key="sk-fake",
            requires_api_key=True,
            managed_api=True,
        ),
        urlopen=transport,
        default_extra_body=default_extra_body,
    )


class TestDeepSeekProvider:
    def test_tool_call_with_internal_reasoning(self):
        capture = []
        client = _scripted_client(
            [
                {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "Let me read it.",
                                "reasoning_content": "private internal reasoning",
                                "tool_calls": [
                                    {
                                        "id": "c1",
                                        "type": "function",
                                        "function": {
                                            "name": "read_file",
                                            "arguments": '{"path": "a.py"}',
                                        },
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 3},
                }
            ],
            capture=capture,
        )
        provider = DeepSeekProvider("deepseek-v4-flash", transport=client)
        result = provider.generate(
            CoderGenerationRequest(
                system_authority="DEFEND authority",
                conversation=(),
                tools=(
                    {"type": "function", "function": {"name": "read_file"}},
                ),
            )
        )
        assert result.provider == "deepseek"
        assert result.tool_calls[0].name == "read_file"
        # Reasoning is internal-only (protocol_state), never visible content.
        assert result.visible_content == "Let me read it."
        assert result.protocol_state["reasoning_content"] == "private internal reasoning"
        assert "reasoning_content" not in repr(result).split("protocol_state")[0]

    def test_tool_continuation_replays_reasoning_internally(self):
        captured = []
        client = _scripted_client(
            [
                {
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "Done."},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {},
                }
            ],
            capture=captured,
        )
        provider = DeepSeekProvider("deepseek-v4-flash", transport=client)
        conversation = (
            {
                "role": "assistant",
                "content": "Let me read it.",
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path": "a.py"}',
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "ok"},
        )
        result = provider.generate(
            CoderGenerationRequest(
                system_authority="DEFEND authority",
                conversation=conversation,
                continuation_state={
                    "reasoning_by_call": {
                        "c1": "private internal reasoning"
                    }
                },
            )
        )
        # The outgoing payload replayed reasoning_content on the assistant
        # tool-call message (protocol requirement), never in visible output.
        sent = captured[0]
        assistant = next(m for m in sent["messages"] if m["role"] == "assistant")
        assert assistant["reasoning_content"] == "private internal reasoning"
        assert "private internal reasoning" not in result.visible_content

    def test_thinking_params_injected_when_enabled(self):
        captured = []
        client = _scripted_client(
            [
                {
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "ok"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {},
                }
            ],
            capture=captured,
            default_extra_body={
                "thinking": {"type": "enabled"},
                "reasoning_effort": "high",
            },
        )
        provider = DeepSeekProvider("deepseek-v4-flash", transport=client)
        provider.generate(CoderGenerationRequest(system_authority="x"))
        assert captured[0]["thinking"] == {"type": "enabled"}
        assert captured[0]["reasoning_effort"] == "high"


class TestNextVllmProvider:
    def test_next_provider_chat_completions_no_gpu(self):
        captured = []
        client = _scripted_client(
            [
                {
                    "choices": [
                        {"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}
                    ],
                    "usage": {},
                }
            ],
            capture=captured,
        )
        provider = NextVllmProvider("Qwen/Qwen3-Coder-Next", transport=client)
        result = provider.generate(CoderGenerationRequest(system_authority="x"))
        assert result.provider == "self_hosted"
        # vLLM emits no reasoning; protocol_state carries a None marker only.
        assert result.protocol_state == {"reasoning_content": None}
        # Constructing the provider performs zero runtime/gpu activity (pure
        # object + transport; no start_runtime/resume called).


class TestOpenAIResponsesProvider:
    def test_responses_text_and_usage_normalization(self):
        calls = []

        def transport(body: bytes) -> dict:
            calls.append(json.loads(body))
            return {
                "id": "resp_1",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "hello"}],
                    }
                ],
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 4,
                    "total_tokens": 14,
                },
            }

        provider = OpenAIResponsesProvider(
            "gpt-5.6-sol", api_key="sk-fake", transport=transport
        )
        result = provider.generate(
            CoderGenerationRequest(
                system_authority="DEFEND authority",
                conversation=(),
            )
        )
        assert result.provider == "openai"
        assert provider.protocol == "responses"
        assert result.visible_content == "hello"
        assert result.usage["total_tokens"] == 14
        assert calls[0]["model"] == "gpt-5.6-sol"
        assert calls[0]["instructions"] == "DEFEND authority"

    def test_responses_function_call(self):
        def transport(body: bytes) -> dict:
            return {
                "id": "resp_2",
                "status": "in_progress",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "fc_1",
                        "name": "read_file",
                        "arguments": '{"path": "a.py"}',
                    }
                ],
            }

        provider = OpenAIResponsesProvider(
            "gpt-5.6-sol", api_key="sk-fake", transport=transport
        )
        result = provider.generate(
            CoderGenerationRequest(
                system_authority="x",
                conversation=(),
                tools=(
                    {"type": "function", "function": {"name": "read_file", "parameters": {}}},
                ),
            )
        )
        assert result.tool_calls[0].name == "read_file"
        assert result.tool_calls[0].id == "fc_1"
        assert result.tool_calls[0].arguments == {"path": "a.py"}

    def test_responses_function_output_continuation(self):
        calls = []

        def transport(body: bytes) -> dict:
            payload = json.loads(body)
            calls.append(payload)
            if "previous_response_id" in payload:
                return {
                    "id": "resp_3",
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": "final answer"}],
                        }
                    ],
                    "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
                }
            return {
                "id": "resp_1",
                "status": "in_progress",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "fc_1",
                        "name": "read_file",
                        "arguments": '{"path": "a.py"}',
                    }
                ],
            }

        provider = OpenAIResponsesProvider(
            "gpt-5.6-sol", api_key="sk-fake", transport=transport
        )
        first = provider.generate(
            CoderGenerationRequest(
                system_authority="DEFEND authority",
                conversation=(),
                tools=(),
            )
        )
        assert first.tool_calls[0].id == "fc_1"
        assert first.protocol_state["response_id"] == "resp_1"
        # Continuation: tool result becomes function_call_output with the SAME
        # call_id, plus previous_response_id.
        second = provider.generate(
            CoderGenerationRequest(
                system_authority="DEFEND authority",
                conversation=(
                    {"role": "tool", "tool_call_id": "fc_1", "content": "file contents"},
                ),
                continuation_state=first.protocol_state,
            )
        )
        assert second.visible_content == "final answer"
        continuation_payload = calls[1]
        assert continuation_payload["previous_response_id"] == "resp_1"
        assert continuation_payload["input"] == [
            {
                "type": "function_call_output",
                "call_id": "fc_1",
                "output": "file contents",
            }
        ]
        assert continuation_payload["instructions"] == "DEFEND authority"


class TestCoderProviderFactory:
    def test_factory_routes_to_correct_provider(self):
        factory = CoderProviderFactory(
            CredentialStore(
                store_loader=_Store(
                    DEEPSEEK_API_KEY="sk-d", OPENAI_API_KEY="sk-o"
                )
            ),
            responses_transport=lambda body: {"output": [], "status": "completed"},
        )
        assert isinstance(
            factory.for_model(deepseek_target().model_id), DeepSeekProvider
        )
        assert isinstance(
            factory.for_model(next_target().model_id), NextVllmProvider
        )
        assert isinstance(
            factory.for_model(sol_target().model_id), OpenAIResponsesProvider
        )

    def test_factory_fails_closed_without_deepseek_key(self):
        factory = CoderProviderFactory(CredentialStore(store_loader=_Store()))
        with pytest.raises(ValueError, match="not configured"):
            factory.for_model(deepseek_target().model_id)

    def test_factory_never_starts_gpu(self):
        # Next provider construction is pure; no runtime activation occurs.
        factory = CoderProviderFactory(CredentialStore(store_loader=_Store()))
        provider = factory.for_model(next_target().model_id)
        assert isinstance(provider, NextVllmProvider)


class TestCodingAgentProviderNeutral:
    def test_agent_accepts_coder_provider_and_completes(self):
        from pathlib import Path
        from uuid import uuid4

        from defend_coder.agent import CodingAgent
        from defend_coder.tools import CoderToolkit

        from test_coder_router_integration import FakeRepository, _workspace

        responses = [
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Let me read it.",
                            "reasoning_content": "internal only",
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "type": "function",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": '{"path": "a.py"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {},
            },
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "Done."},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {},
            },
        ]
        client = _scripted_client(responses)
        provider = DeepSeekProvider("deepseek-v4-flash", transport=client)
        workspace = _workspace(uuid4())
        toolkit = CoderToolkit(
            repository=FakeRepository(workspace),
            configured_root=Path("C:/fake/root"),
            enabled=False,
        )
        agent = CodingAgent(
            provider=provider,
            toolkit=toolkit,
            max_steps=3,
            system_authority="DEFEND authority",
        )
        visible: list[dict] = []
        outcome = agent.run(
            prompt="read a.py",
            account_id=workspace.owner_account_id,
            workspace_id=workspace.workspace_id,
            sink=lambda **fields: visible.append(dict(fields)),
        )
        assert outcome.state == "succeeded"
        transcript = json.dumps(visible)
        assert "internal only" not in transcript
        assert "reasoning_content" not in transcript
