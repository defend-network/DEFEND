from __future__ import annotations

import asyncio

from control_plane import AgentRequest, ControlPlane
from registry import build_default_registry
from ollama_client import OllamaClient
from dev_policy import DevWebPolicy
from execution_protocol import ExecutablePlan, PlanStep, ToolCall


async def main():
    registry = build_default_registry()

    async with OllamaClient(model="defend-ai") as model:
        cp = ControlPlane(
            tool_registry=registry,
            model_client=model,
            policy_engine=DevWebPolicy(),
        )

        request = AgentRequest(
            request_id="sel-1",
            message="official BJS imprisonment rates by race",
        )

        # Step 1: search
        search_plan = ExecutablePlan(
            objective=request.message,
            steps=[
                PlanStep(
                    id="search",
                    call=ToolCall(
                        tool_name="web.search",
                        arguments={
                            "query": "BJS prisoners 2022 imprisonment rates by race site:bjs.ojp.gov",
                            "limit": 6,
                        },
                    ),
                )
            ],
        )

        execution = await cp._execute_plan(search_plan, request, "sel-search")
        step = execution.steps["search"]
        if not (step.tool_result and step.tool_result.ok):
            print("Search failed")
            return

        results = step.tool_result.data.results
        candidate_map = {r.source_id: r for r in results}

        print(f"Search returned {len(results)} results")
        for r in results:
            print(f"  [{r.rank}] {r.media_type_hint:8} {r.domain} | {r.title[:70]}")

        # Step 2: model selects (IDs only)
        selection = await cp._select_sources(
            objective=request.message,
            results=results,
        )

        if not selection:
            print("Selection failed")
            return

        print("\nSelection:")
        for c in selection.choices:
            cand = candidate_map.get(c.source_id)
            print(f"  {c.action:10} {c.reason}")
            print(f"    id={c.source_id}")
            print(f"    url={cand.url if cand else 'UNKNOWN'}")

        # Step 3: Control Plane resolves URLs authoritatively
        for i, choice in enumerate(selection.choices):
            if choice.action == "skip":
                continue

            cand = candidate_map.get(choice.source_id)
            if cand is None:
                print(f"\nSkipping unknown source_id: {choice.source_id}")
                continue

            tool_name = (
                "documents.fetch" if choice.action == "fetch_pdf" else "web.fetch"
            )
            args = (
                {"url": cand.url, "max_bytes": 20_000_000}
                if choice.action == "fetch_pdf"
                else {"url": cand.url, "max_chars": 6000}
            )

            plan = ExecutablePlan(
                objective=f"fetch selected {i}",
                steps=[
                    PlanStep(
                        id=f"fetch_{i}",
                        call=ToolCall(tool_name=tool_name, arguments=args),
                    )
                ],
            )
            ex = await cp._execute_plan(plan, request, f"sel-fetch-{i}")
            st = ex.steps[f"fetch_{i}"]
            print(f"\n{tool_name} → {st.status.value}")
            if st.tool_result and st.tool_result.ok:
                data = st.tool_result.data
                if tool_name == "documents.fetch":
                    print(f"  document_id={data.document_id} pages={data.page_count}")
                else:
                    preview = (data.content or "")[:300]
                    print(f"  preview: {preview}")


if __name__ == "__main__":
    asyncio.run(main())