from __future__ import annotations

import asyncio
from control_plane import AgentRequest, ControlPlane
from registry import build_default_registry
from dev_policy import DevWebPolicy
from execution_protocol import ExecutablePlan, PlanStep, ToolCall
from ollama_client import OllamaClient


TARGETS = [
    "http://127.0.0.1/",
    "http://127.0.0.1:80/",
    "https://127.0.0.1/",
    "http://localhost/",
    "http://192.168.1.1/",
    "http://10.0.0.1/",
    "http://172.16.0.1/",
    "http://[::1]/",
]


async def main():
    registry = build_default_registry()
    cp = ControlPlane(
        tool_registry=registry,
        model_client=None,
        policy_engine=DevWebPolicy(),
    )

    request = AgentRequest(request_id="ssrf", message="ssrf probe")

    print("SSRF destination tests (all should be blocked):\n")
    for url in TARGETS:
        plan = ExecutablePlan(
            objective="ssrf",
            steps=[
                PlanStep(
                    id="fetch",
                    call=ToolCall(
                        tool_name="web.fetch",
                        arguments={"url": url},
                    ),
                )
            ],
        )
        execution = await cp._execute_plan(plan, request, "ssrf-trace")
        step = execution.steps["fetch"]
        status = step.status.value
        msg = ""
        if step.tool_result and step.tool_result.error:
            msg = step.tool_result.error.message
        print(f"{status:10}  {url}")
        if msg:
            print(f"           → {msg}")


if __name__ == "__main__":
    asyncio.run(main())