from __future__ import annotations

import asyncio
import json
from pathlib import Path

from control_plane import AgentRequest, ControlPlane
from registry import build_default_registry
from ollama_client import OllamaClient
from dev_policy import DevWebPolicy
from execution_protocol import ExecutablePlan, PlanStep, ToolCall


EVAL_PATH = Path("evals/retrieval_v001.jsonl")
MODES = ["semantic", "lexical", "hybrid"]
LIMIT = 5

# Pages that contain real US imprisonment-rate answers in the current BJS pack.
# Used only for negative queries: retrieving these is a false positive.
DEFAULT_FORBIDDEN_PAGES = {2, 13, 14, 21, 25}


def load_evals():
    rows = []
    raw = EVAL_PATH.read_text(encoding="utf-8-sig")
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def pages_from_hits(hits) -> list[int | None]:
    return [h.page for h in hits]


def recall_at_k(got_pages, relevant, k, *, negative=False, forbidden_pages=None):
    top = [p for p in got_pages[:k] if p is not None]
    if negative:
        forbidden = set(forbidden_pages or [])
        if not forbidden:
            return 1.0
        return 0.0 if any(p in forbidden for p in top) else 1.0
    if not relevant:
        return 1.0
    return 1.0 if any(p in relevant for p in top) else 0.0


def answer_hit_at_k(got_pages, answer_pages, k, *, negative=False, forbidden_pages=None):
    top = [p for p in got_pages[:k] if p is not None]
    if negative:
        forbidden = set(forbidden_pages or [])
        if not forbidden:
            return 1.0
        return 0.0 if any(p in forbidden for p in top) else 1.0
    if not answer_pages:
        return 1.0
    return 1.0 if any(p in answer_pages for p in top) else 0.0


def mrr(got_pages, relevant, *, negative=False, forbidden_pages=None):
    if negative:
        forbidden = set(forbidden_pages or [])
        for p in got_pages:
            if p in forbidden:
                return 0.0
        return 1.0
    if not relevant:
        return 1.0
    for i, p in enumerate(got_pages):
        if p in relevant:
            return 1.0 / (i + 1)
    return 0.0


async def run_query(cp: ControlPlane, query: str, document_ids: list[str], mode: str):
    plan = ExecutablePlan(
        objective=query,
        steps=[
            PlanStep(
                id="q",
                call=ToolCall(
                    tool_name="rag.query",
                    arguments={
                        "query": query,
                        "document_ids": document_ids,
                        "limit": LIMIT,
                        "mode": mode,
                    },
                ),
            )
        ],
    )
    req = AgentRequest(request_id=f"eval-{mode}", message=query)
    ex = await cp._execute_plan(plan, req, f"eval-{mode}")
    step = ex.steps["q"]
    if not (step.tool_result and step.tool_result.ok):
        return []
    return step.tool_result.data.hits


async def consistency_check(cp: ControlPlane, query: str, document_id: str, mode: str = "hybrid"):
    hits_rag = await run_query(cp, query, [document_id], mode)

    plan = ExecutablePlan(
        objective="docsearch",
        steps=[
            PlanStep(
                id="ds",
                call=ToolCall(
                    tool_name="documents.search",
                    arguments={
                        "document_id": document_id,
                        "query": query,
                        "limit": LIMIT,
                        "mode": mode,
                    },
                ),
            )
        ],
    )
    req = AgentRequest(request_id="cons", message=query)
    ex = await cp._execute_plan(plan, req, "cons")
    step = ex.steps["ds"]
    hits_ds = step.tool_result.data.hits if step.tool_result and step.tool_result.ok else []

    rag_pages = pages_from_hits(hits_rag)
    ds_pages = pages_from_hits(hits_ds)
    same = rag_pages == ds_pages
    return same, rag_pages, ds_pages


async def main():
    evals = load_evals()
    registry = build_default_registry()

    async with OllamaClient(model="defend-ai") as model:
        cp = ControlPlane(registry, model, policy_engine=DevWebPolicy())

        print(f"Loaded {len(evals)} eval items\n")

        summary = {
            mode: {
                "recall@1": [],
                "recall@3": [],
                "recall@5": [],
                "answer@1": [],
                "answer@3": [],
                "mrr": [],
            }
            for mode in MODES
        }

        for item in evals:
            q = item["query"]
            doc_ids = item["document_ids"]
            kind = item.get("kind", "")
            is_neg = kind == "negative"

            relevant = set(item.get("acceptable_pages") or item.get("expected_pages") or [])
            answer_pages = set(item.get("answer_bearing_pages") or [])
            forbidden = set(item.get("forbidden_pages") or DEFAULT_FORBIDDEN_PAGES) if is_neg else set()

            print(f"Q[{item['id']}] ({kind}): {q}")

            for mode in MODES:
                hits = await run_query(cp, q, doc_ids, mode)
                pages = pages_from_hits(hits)

                r1 = recall_at_k(pages, relevant, 1, negative=is_neg, forbidden_pages=forbidden)
                r3 = recall_at_k(pages, relevant, 3, negative=is_neg, forbidden_pages=forbidden)
                r5 = recall_at_k(pages, relevant, 5, negative=is_neg, forbidden_pages=forbidden)
                a1 = answer_hit_at_k(pages, answer_pages, 1, negative=is_neg, forbidden_pages=forbidden)
                a3 = answer_hit_at_k(pages, answer_pages, 3, negative=is_neg, forbidden_pages=forbidden)
                rr = mrr(pages, relevant, negative=is_neg, forbidden_pages=forbidden)

                summary[mode]["recall@1"].append(r1)
                summary[mode]["recall@3"].append(r3)
                summary[mode]["recall@5"].append(r5)
                summary[mode]["answer@1"].append(a1)
                summary[mode]["answer@3"].append(a3)
                summary[mode]["mrr"].append(rr)

                print(
                    f"  {mode:9} pages={pages[:5]}  "
                    f"R@1={r1:.0f} R@3={r3:.0f} A@1={a1:.0f} A@3={a3:.0f} MRR={rr:.2f}"
                )
            print()

        print("=" * 60)
        print("SUMMARY")
        for mode in MODES:
            s = summary[mode]
            n = max(len(s["recall@3"]), 1)

            def avg(key):
                return sum(s[key]) / n

            print(
                f"{mode:9}  R@1={avg('recall@1'):.2f}  R@3={avg('recall@3'):.2f}  "
                f"R@5={avg('recall@5'):.2f}  A@1={avg('answer@1'):.2f}  "
                f"A@3={avg('answer@3'):.2f}  MRR={avg('mrr'):.2f}"
            )

        print("\n" + "=" * 60)
        print("CONSISTENCY: documents.search == rag.query")
        same, rag_pages, ds_pages = await consistency_check(
            cp,
            query="Black adult imprisonment rate 2023",
            document_id="doc_27df51c1baea47bb",
            mode="hybrid",
        )
        print(f"match={same}")
        print(f"rag.query pages:         {rag_pages}")
        print(f"documents.search pages:  {ds_pages}")


if __name__ == "__main__":
    asyncio.run(main())