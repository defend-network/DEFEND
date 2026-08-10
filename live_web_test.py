from __future__ import annotations

import asyncio

from control_plane import AgentRequest, ControlPlane
from registry import build_default_registry
from ollama_client import OllamaClient
from dev_policy import DevWebPolicy
from execution_protocol import (
    ExecutablePlan,
    PlanStep,
    ToolCall,
)


async def main():
    registry = build_default_registry()
    print("Registered tools:", list(registry.keys()))

    async with OllamaClient(model="defend-ai") as model:
        healthy = await model.healthcheck()
        print(f"Ollama healthcheck: {healthy}")
        if not healthy:
            return

        cp = ControlPlane(
            tool_registry=registry,
            model_client=model,
            policy_engine=DevWebPolicy(),
        )

        # ─────────────────────────────────────────
        # Test 1: plain web.search
        # ─────────────────────────────────────────
        print("\n" + "=" * 60)
        print("TEST 1: web.search")
        print("=" * 60)

        search_plan = ExecutablePlan(
            objective="search test",
            steps=[
                PlanStep(
                    id="search",
                    call=ToolCall(
                        tool_name="web.search",
                        arguments={
                            "query": "BJS adult imprisonment rates by race 2022",
                            "limit": 5,
                        },
                    ),
                ),
            ],
        )

        request = AgentRequest(request_id="web-1", message="search test")
        execution = await cp._execute_plan(search_plan, request, "trace-search")

        print(f"Status: {execution.status.value}")
        step = execution.steps["search"]
        print(f"Step status: {step.status.value}")

        if step.tool_result and step.tool_result.ok:
            results = step.tool_result.data.results
            print(f"Got {len(results)} results")
            for i, r in enumerate(results[:3]):
                print(f"  [{i}] {r.title}")
                print(f"      {r.url}")
        else:
            print("Search failed:", step.tool_result.error if step.tool_result else "no result")

        # ─────────────────────────────────────────
        # Test 2: search → ValueRef → fetch
        # ─────────────────────────────────────────
        print("\n" + "=" * 60)
        print("TEST 2: web.search → ValueRef → web.fetch")
        print("=" * 60)

        dag_plan = ExecutablePlan(
            objective="search then fetch first result",
            steps=[
                PlanStep(
                    id="search",
                    call=ToolCall(
                        tool_name="web.search",
                        arguments={
                            "query": "site:bjs.ojp.gov imprisonment rates by race",
                            "limit": 3,
                        },
                    ),
                ),
                PlanStep(
                    id="fetch",
                    call=ToolCall(
                        tool_name="web.fetch",
                        arguments={
                            "url": {
                                "$ref": {
                                    "step_id": "search",
                                    "path": "data.results.0.url",
                                }
                            },
                            "max_chars": 5000,
                        },
                    ),
                    depends_on=["search"],
                ),
            ],
        )

        request2 = AgentRequest(request_id="web-2", message="dag test")
        execution2 = await cp._execute_plan(dag_plan, request2, "trace-dag")

        print(f"Plan status: {execution2.status.value}")
        for sid, s in execution2.steps.items():
            print(f"  - {sid}: {s.status.value}")

        fetch_step = execution2.steps.get("fetch")
        if fetch_step and fetch_step.tool_result and fetch_step.tool_result.ok:
            data = fetch_step.tool_result.data
            print(f"\nFetched: {data.final_url}")
            print(f"Title: {data.title}")
            print(f"Bytes: {data.downloaded_bytes}")
            print(f"Truncated: {data.truncated}")
            print(f"Content preview:\n{data.content[:400]}...")
        else:
            err = fetch_step.tool_result.error if fetch_step and fetch_step.tool_result else None
            print("Fetch failed:", err)

        # ─────────────────────────────────────────
        # Test 3: SSRF should be blocked
        # ─────────────────────────────────────────
        print("\n" + "=" * 60)
        print("TEST 3: SSRF rejection (localhost)")
        print("=" * 60)

        ssrf_plan = ExecutablePlan(
            objective="ssrf test",
            steps=[
                PlanStep(
                    id="ssrf",
                    call=ToolCall(
                        tool_name="web.fetch",
                        arguments={"url": "http://127.0.0.1:11434/api/tags"},
                    ),
                ),
            ],
        )

        request3 = AgentRequest(request_id="web-3", message="ssrf test")
        execution3 = await cp._execute_plan(ssrf_plan, request3, "trace-ssrf")
        step3 = execution3.steps["ssrf"]
        print(f"Status: {step3.status.value}")
        if step3.tool_result and not step3.tool_result.ok:
            print(f"Correctly blocked: {step3.tool_result.error.message}")
        else:
            print("WARNING: localhost was not blocked")

        # ─────────────────────────────────────────
        # Test 4: Model-driven research
        # ─────────────────────────────────────────
        print("\n" + "=" * 60)
        print("TEST 4: Model-driven research")
        print("=" * 60)

        request4 = AgentRequest(
            request_id="research-1",
            message=(
                "Find recent official statistics on Black and White adult imprisonment "
                "rates in the United States. Prefer primary government sources. "
                "Summarize the key numbers and cite the sources."
            ),
        )

        response = await cp.handle(request4)
        print(f"Route: {response.metadata}")
        print(f"\nANSWER:\n{response.content}")

        if response.plan_execution:
            print(f"\nExecution: {response.plan_execution.status.value}")
            for sid, step in response.plan_execution.steps.items():
                print(f"  - {sid}: {step.status.value}")


if __name__ == "__main__":
    asyncio.run(main())