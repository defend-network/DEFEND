# live_rag_ingest_test.py
import asyncio
from control_plane import AgentRequest, ControlPlane
from registry import build_default_registry
from ollama_client import OllamaClient
from dev_policy import DevWebPolicy
from execution_protocol import ExecutablePlan, PlanStep, ToolCall

DOC_ID = "doc_27df51c1baea47bb"  # change to a real id on your machine

async def main():
    registry = build_default_registry()
    async with OllamaClient(model="defend-ai") as model:
        cp = ControlPlane(registry, model, policy_engine=DevWebPolicy())
        plan = ExecutablePlan(
            objective="ingest",
            steps=[
                PlanStep(
                    id="ingest",
                    call=ToolCall(
                        tool_name="rag.ingest",
                        arguments={"document_id": DOC_ID, "tags": ["bjs", "prisoners"]},
                    ),
                )
            ],
        )
        req = AgentRequest(request_id="rag-1", message="ingest")
        ex = await cp._execute_plan(plan, req, "rag-ingest")
        step = ex.steps["ingest"]
        print(step.status.value)
        if step.tool_result and step.tool_result.ok:
            print(step.tool_result.data)
        else:
            print(step.tool_result.error if step.tool_result else None)

asyncio.run(main())