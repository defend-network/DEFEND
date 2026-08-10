from __future__ import annotations

import asyncio

from control_plane import AgentRequest, ControlPlane
from registry import build_default_registry
from ollama_client import OllamaClient
from dev_policy import DevWebPolicy
from execution_protocol import ExecutablePlan, PlanStep, ToolCall


async def main():
    registry = build_default_registry()
    print("Tools:", list(registry.keys()))

    async with OllamaClient(model="defend-ai") as model:
        cp = ControlPlane(
            tool_registry=registry,
            model_client=model,
            policy_engine=DevWebPolicy(),
        )

        plan = ExecutablePlan(
            objective="query knowledge",
            steps=[
                PlanStep(
                    id="q",
                    call=ToolCall(
                        tool_name="rag.query",
                        arguments={
                            "query": "Black and White adult imprisonment rates per 100,000",
                            "document_ids": ["doc_27df51c1baea47bb"],
                            "limit": 5,
                        },
                    ),
                )
            ],
        )

        req = AgentRequest(request_id="rag-q1", message="query")
        ex = await cp._execute_plan(plan, req, "rag-query")
        step = ex.steps["q"]
        print("Status:", step.status.value)

        if step.tool_result and step.tool_result.ok:
            data = step.tool_result.data
            print("Hits:", len(data.hits))
            for i, h in enumerate(data.hits):
                print(f"\n[{i}] score={h.final_score:.4f} page={h.page} doc={h.document_id}")
                print(h.text[:400])
        else:
            print(step.tool_result.error if step.tool_result else None)


if __name__ == "__main__":
    asyncio.run(main())