from __future__ import annotations

import asyncio

from control_plane import AgentRequest, ControlPlane
from registry import build_default_registry
from ollama_client import OllamaClient
from dev_policy import DevWebPolicy


async def main():
    registry = build_default_registry()
    print("Tools:", list(registry.keys()))

    async with OllamaClient(model="defend-ai") as model:
        cp = ControlPlane(
            tool_registry=registry,
            model_client=model,
            policy_engine=DevWebPolicy(),
        )

        request = AgentRequest(
            request_id="research-live-1",
            message=(
                "Find official BJS statistics on Black and White adult imprisonment "
                "rates in the United States and cite the sources."
            ),
        )

        response = await cp.handle(request)

        print("\nROUTE:", response.metadata)
        print("\nANSWER:\n", response.content)

        if response.plan_execution:
            print("\nEXECUTION:", response.plan_execution.status.value)
            for sid, step in response.plan_execution.steps.items():
                print(f"  - {sid}: {step.status.value}")


if __name__ == "__main__":
    asyncio.run(main())