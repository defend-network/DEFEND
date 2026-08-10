from __future__ import annotations

import asyncio
from control_plane import AgentRequest, ControlPlane
from registry import build_default_registry
from ollama_client import OllamaClient


async def main():
    registry = build_default_registry()

    async with OllamaClient(model="defend-ai") as model:  # change tag if different
        # Healthcheck first
        healthy = await model.healthcheck()
        print(f"Ollama healthcheck: {healthy}")
        if not healthy:
            print("Model not found or Ollama not reachable. Fix this first.")
            return

        cp = ControlPlane(
            tool_registry=registry,
            model_client=model,
        )

        tests = [
            ("DIRECT", "What is DEFEND in one sentence?"),
            ("CALCULATOR", "What is 987 * 42?"),
            ("TIME", "What time is it in UTC right now?"),
            ("NO TOOL", "Explain why high-trust societies matter."),
        ]

        for label, message in tests:
            print("\n" + "=" * 60)
            print(f"TEST: {label}")
            print(f"USER: {message}")
            print("-" * 60)

            request = AgentRequest(
                request_id=f"test-{label.lower().replace(' ', '-')}",
                message=message,
            )

            response = await cp.handle(request)

            print(f"ROUTE METADATA: {response.metadata}")
            print(f"\nANSWER:\n{response.content}")

            if response.plan_execution:
                print(f"\nExecution status: {response.plan_execution.status.value}")
                for step_id, step in response.plan_execution.steps.items():
                    print(f"  - {step_id}: {step.status.value}")


if __name__ == "__main__":
    asyncio.run(main())