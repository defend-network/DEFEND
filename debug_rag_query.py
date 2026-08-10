import asyncio
from control_plane import AgentRequest, ControlPlane
from registry import build_default_registry
from ollama_client import OllamaClient
from dev_policy import DevWebPolicy
from execution_protocol import ExecutablePlan, PlanStep, ToolCall

async def main():
    registry = build_default_registry()
    async with OllamaClient(model="defend-ai") as model:
        cp = ControlPlane(registry, model, policy_engine=DevWebPolicy())
        plan = ExecutablePlan(
            objective="debug",
            steps=[
                PlanStep(
                    id="q",
                    call=ToolCall(
                        tool_name="rag.query",
                        arguments={
                            "query": "Black adult imprisonment rate 2023",
                            "document_ids": ["doc_27df51c1baea47bb"],
                            "limit": 5,
                            "mode": "semantic",
                        },
                    ),
                )
            ],
        )
        req = AgentRequest(request_id="dbg", message="dbg")
        ex = await cp._execute_plan(plan, req, "dbg")
        step = ex.steps["q"]
        print("status:", step.status.value)
        if step.tool_result:
            print("ok:", step.tool_result.ok)
            if step.tool_result.ok:
                print("hits:", len(step.tool_result.data.hits))
                for h in step.tool_result.data.hits[:3]:
                    print(h.page, h.text[:120].replace("\n", " "))
            else:
                print("error:", step.tool_result.error)

asyncio.run(main())