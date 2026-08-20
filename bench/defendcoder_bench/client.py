"""Deterministic scripted bench client.

Implements AgentChatClient so the bench can drive the real CodingAgent
loop without a model (P14: no paid compute). The scripted client is also
the calibration baseline for live-model runs: any live run that performs
worse than the scripted transcript on the same task indicates a model or
prompt regression (P11/P12).
"""

from __future__ import annotations

from defend_coder.agent_client import (
    AgentChatClient,
    AgentChatResponse,
    ToolCall,
)
from defend_coder.model_config import CoderModelConfig


class ScriptedBenchClient(AgentChatClient):
    """Replays a task script: tool-call turns followed by a text turn.

    The script entries are {'tool': name, 'arguments': {...}} dicts and
    finally a {'text': '...'} entry. generation_tokens can be attached
    to any entry to simulate large model generations for metrics.
    """

    def __init__(self, script: list[dict]):
        super().__init__(
            CoderModelConfig(
                alias="bench-scripted",
                model_name="scripted://local",
                base_url="http://127.0.0.1:8001/v1",
            )
        )
        self.script = [dict(item) for item in script]
        self.requests: list[dict] = []
        self.generation_tokens = 0

    def chat(self, messages, tools=None, **kwargs):
        self.requests.append({"messages": messages, "tools": tools})
        if kwargs.get("on_request_started") is not None:
            kwargs["on_request_started"]()
        item = self.script.pop(0)
        self.generation_tokens += int(item.get("generation_tokens", 0))
        usage = item.get("usage")
        usage_payload = None
        if isinstance(usage, dict):
            output = int(usage.get("output", 0))
            input_tokens = int(usage.get("input", 0))
            usage_payload = {
                "prompt_tokens": input_tokens,
                "completion_tokens": output,
                "total_tokens": input_tokens + output,
            }
        finish_reason = item.get("finish_reason")
        if "tool" in item:
            return AgentChatResponse(
                content=None,
                tool_calls=(
                    ToolCall(
                        id=f"bench_call_{len(self.requests)}",
                        name=item["tool"],
                        arguments=dict(item["arguments"]),
                    ),
                ),
                usage=usage_payload,
                finish_reason=finish_reason or "tool_calls",
            )
        return AgentChatResponse(
            content=item.get("text", "Done."),
            tool_calls=(),
            usage=usage_payload,
            finish_reason=finish_reason or "stop",
        )