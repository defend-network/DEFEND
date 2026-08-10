from __future__ import annotations

import asyncio

from control_plane import AgentRequest, ControlPlane
from registry import build_default_registry
from ollama_client import OllamaClient
from dev_policy import DevWebPolicy
from execution_protocol import ExecutablePlan, PlanStep, ToolCall


async def main():
    registry = build_default_registry()
    print("Registered tools:", list(registry.keys()))

    async with OllamaClient(model="defend-ai") as model:
        cp = ControlPlane(
            tool_registry=registry,
            model_client=model,
            policy_engine=DevWebPolicy(),
        )

        request = AgentRequest(request_id="doc-1", message="document test")

        # ─────────────────────────────────────────
        # 1) Fetch the BJS PDF
        # ─────────────────────────────────────────
        print("\n" + "=" * 60)
        print("TEST: documents.fetch BJS PDF")
        print("=" * 60)

        fetch_plan = ExecutablePlan(
            objective="fetch bjs pdf",
            steps=[
                PlanStep(
                    id="fetch",
                    call=ToolCall(
                        tool_name="documents.fetch",
                        arguments={
                            "url": "https://bjs.ojp.gov/document/p22st.pdf",
                            "max_bytes": 20_000_000,
                        },
                    ),
                )
            ],
        )

        execution = await cp._execute_plan(fetch_plan, request, "doc-fetch")
        step = execution.steps["fetch"]
        print(f"Status: {step.status.value}")

        if not (step.tool_result and step.tool_result.ok):
            print("Fetch failed:", step.tool_result.error if step.tool_result else None)
            return

        data = step.tool_result.data
        print(f"document_id: {data.document_id}")
        print(f"media_type:  {data.media_type}")
        print(f"pages:       {data.page_count}")
        print(f"bytes:       {data.downloaded_bytes}")
        print(f"title:       {data.title}")

        document_id = data.document_id

        # ─────────────────────────────────────────
        # 2) Read pages 1-3
        # ─────────────────────────────────────────
        print("\n" + "=" * 60)
        print("TEST: documents.read pages 1-3")
        print("=" * 60)

        read_plan = ExecutablePlan(
            objective="read bjs pdf pages",
            steps=[
                PlanStep(
                    id="read",
                    call=ToolCall(
                        tool_name="documents.read",
                        arguments={
                            "document_id": document_id,
                            "page_start": 1,
                            "page_end": 3,
                            "max_chars": 8000,
                        },
                    ),
                )
            ],
        )

        execution2 = await cp._execute_plan(read_plan, request, "doc-read")
        step2 = execution2.steps["read"]
        print(f"Status: {step2.status.value}")

        if step2.tool_result and step2.tool_result.ok:
            out = step2.tool_result.data
            print(f"extracted_chars: {out.extracted_chars}")
            print(f"truncated: {out.truncated}")
            print(f"\nCONTENT PREVIEW:\n{out.content[:1500]}")
        else:
            print("Read failed:", step2.tool_result.error if step2.tool_result else None)


if __name__ == "__main__":
    asyncio.run(main())