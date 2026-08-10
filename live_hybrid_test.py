from __future__ import annotations

import asyncio
from control_plane import AgentRequest, ControlPlane
from registry import build_default_registry
from ollama_client import OllamaClient
from dev_policy import DevWebPolicy
from execution_protocol import ExecutablePlan, PlanStep, ToolCall

DOC = "doc_27df51c1baea47bb"


async def run_mode(cp, mode: str):
    plan = ExecutablePlan(
        objective=mode,
        steps=[
            PlanStep(
                id="q",
                call=ToolCall(
                    tool_name="rag.query",
                    arguments={
                        "query": "Table 13 Black imprisonment rate 1,218",
                        "document_ids": [DOC],
                        "limit": 3,
                        "mode": mode,
                    },
                ),
            )
        ],
    )
    req = AgentRequest(request_id=mode, message=mode)
    ex = await cp._execute_plan(plan, req, mode)
    step = ex.steps["q"]
    print(f"\n=== {mode} ===", step.status.value)
    if step.tool_result and step.tool_result.ok:
        for i, h in enumerate(step.tool_result.data.hits):
            print(f"[{i}] final={h.final_score:.4f} page={h.page} v={h.vector_score} l={h.lexical_score}")
            print(h.text[:220].replace("\n", " "))
    else:
        print(step.tool_result.error if step.tool_result else None)


async def main():
    registry = build_default_registry()
    print("Tools:", list(registry.keys()))
    async with OllamaClient(model="defend-ai") as model:
        cp = ControlPlane(registry, model, policy_engine=DevWebPolicy())
        for mode in ("semantic", "lexical", "hybrid"):
            await run_mode(cp, mode)

        # documents.search façade
        plan = ExecutablePlan(
            objective="docsearch",
            steps=[
                PlanStep(
                    id="ds",
                    call=ToolCall(
                        tool_name="documents.search",
                        arguments={
                            "document_id": DOC,
                            "query": "Black adults per 100,000",
                            "limit": 3,
                            "mode": "hybrid",
                        },
                    ),
                )
            ],
        )
        req = AgentRequest(request_id="ds", message="ds")
        ex = await cp._execute_plan(plan, req, "ds")
        step = ex.steps["ds"]
        print("\n=== documents.search ===", step.status.value)
        if step.tool_result and step.tool_result.ok:
            for i, h in enumerate(step.tool_result.data.hits):
                print(f"[{i}] page={h.page} score={h.final_score:.4f}")
                print(h.text[:220].replace("\n", " "))


if __name__ == "__main__":
    asyncio.run(main())