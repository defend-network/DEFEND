"""DEFEND AI orchestration regressions: multi-tool routing and tool traces."""

from __future__ import annotations

import asyncio
import json

from control_plane import AgentRequest, ControlPlane
from registry import build_default_registry
from model_types import ChatMessage, MessageRole, ModelResponse, GenerationOptions


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


def test_calculation_then_time_routes_to_planner():
    cp = _build_cp(SpyClient())
    request = AgentRequest(
        request_id="r",
        message="First compute 3*4, then tell me today's date and time using the time tool.",
    )

    decision = asyncio.run(cp.classify(request))

    assert decision.route.value == "COMPLEX"
    assert decision.reason_code == "multi_tool_request"


def test_planning_prompt_injects_registered_tool_schemas():
    spy = SpyClient()
    cp = _build_cp(spy)
    request = AgentRequest(
        request_id="r", message="First compute 3*4, then tell me the current time"
    )

    asyncio.run(cp._ask_for_plan(request))

    assert spy.captured_system_prompts
    system = spy.captured_system_prompts[0]
    assert '"name": "calculator.evaluate"' in system
    assert '"name": "time.now"' in system
    payload = json.loads(system[system.index("Available tools:") + len("Available tools:"):])
    names = {entry["name"] for entry in payload}
    assert "calculator.evaluate" in names
    assert "time.now" in names
