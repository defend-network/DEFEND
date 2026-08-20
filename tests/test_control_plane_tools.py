"""Regression: ControlPlane must inject registered tool schemas into model tool-selection
and planning prompts. Without injection the model hallucinates tool names and every
model-initiated tool call silently falls back to a direct answer."""

from __future__ import annotations

import asyncio
import json

from control_plane import AgentRequest, ControlPlane
from registry import build_default_registry
from model_types import ChatMessage, MessageRole, ModelResponse, GenerationOptions, ModelUsage


class SpyClient:
    def __init__(self):
        self.captured_system_prompts: list[str] = []

    async def generate(
        self,
        *,
        messages: list[ChatMessage],
        options: GenerationOptions | None = None,
    ) -> ModelResponse:
        self._capture(messages)
        return ModelResponse(content="OK", model="spy", backend="spy")

    async def generate_structured(
        self,
        *,
        messages: list[ChatMessage],
        schema,
        options: GenerationOptions | None = None,
    ):
        self._capture(messages)
        return schema.model_validate({}), None

    def _capture(self, messages: list[ChatMessage]) -> None:
        for message in messages:
            if message.role == MessageRole.SYSTEM:
                self.captured_system_prompts.append(message.content)

    async def healthcheck(self) -> bool:
        return True

    async def close(self) -> None:
        pass


def _build_cp(spy: SpyClient) -> ControlPlane:
    registry = build_default_registry(memory_manager=None, embedding_client=None)
    return ControlPlane(tool_registry=registry, model_client=spy, policy_engine=None)


def test_tool_selection_prompt_injects_registered_tool_schemas():
    spy = SpyClient()
    cp = _build_cp(spy)
    request = AgentRequest(request_id="r", message="Calculate 12*34")

    asyncio.run(cp._ask_for_tool_call(request))

    assert spy.captured_system_prompts, "model received no system message"
    system = spy.captured_system_prompts[0]
    assert '"name": "calculator.evaluate"' in system
    assert '"name": "web.search"' in system
    assert '"name": "rag.query"' in system
    payload = json.loads(system[system.index("Available tools:") + len("Available tools:"):])
    names = {entry["name"] for entry in payload}
    assert "calculator.evaluate" in names
    assert all(entry["input_schema"] for entry in payload)


def test_planning_prompt_injects_registered_tool_schemas():
    spy = SpyClient()
    cp = _build_cp(spy)
    request = AgentRequest(request_id="r", message="Multiply 3 by 4 then add 2")

    asyncio.run(cp._ask_for_plan(request))

    assert spy.captured_system_prompts, "model received no system message"
    system = spy.captured_system_prompts[0]
    assert '"name": "calculator.evaluate"' in system
    payload = json.loads(system[system.index("Available tools:") + len("Available tools:"):])
    names = {entry["name"] for entry in payload}
    assert "web.fetch" in names
    assert "documents.read" in names


def test_compile_rejects_hallucinated_tool_name():
    cp = _build_cp(SpyClient())
    try:
        cp._compile_tool_call(tool_name="calculator", arguments={})
    except ValueError:
        return
    raise AssertionError("hallucinated tool name must raise ValueError")