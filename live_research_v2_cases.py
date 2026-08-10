from __future__ import annotations

import asyncio
from control_plane import AgentRequest, ControlPlane
from registry import build_default_registry
from ollama_client import OllamaClient
from dev_policy import DevWebPolicy


CASES = [
    {
        "id": "case1_good_primary",
        "message": (
            "Find official BJS statistics on Black and White adult imprisonment "
            "rates in the United States and cite the sources."
        ),
        "expect_research_status_in": {"verified", "partial"},
        "min_evidence": 1,
    },
    {
        "id": "case2_blocked_then_recover",
        "message": (
            "Find official U.S. government statistics on illegal immigration "
            "or southwest border encounters in the most recent year available. "
            "Prefer CBP, DHS, or other primary federal sources. "
            "Summarize the key numbers and cite the sources."
        ),
        "expect_research_status_in": {"verified", "partial"},
        "min_evidence": 1,
        # recovery may or may not increment depending on batch order
    },
    {
        "id": "case5_insufficient",
        "message": (
            "Find official statistics for the Canadian southwest border "
            "encounter rate under CBP jurisdiction for fiscal year 2099 "
            "and cite the primary table."
        ),
        "expect_research_status_in": {"insufficient_evidence", "partial"},
        "min_evidence": 0,
        "forbid_invented": True,
    },
]


async def run_case(cp: ControlPlane, case: dict) -> dict:
    req = AgentRequest(request_id=case["id"], message=case["message"])
    resp = await cp.handle(req)
    meta = resp.metadata or {}
    status = meta.get("research_status")
    evidence_count = meta.get("evidence_count", 0)
    outcomes = meta.get("source_outcomes", [])

    ok_status = status in case["expect_research_status_in"]
    ok_evidence = evidence_count >= case.get("min_evidence", 0)

    invented = False
    if case.get("forbid_invented"):
        # crude guard: if insufficient and answer asserts a precise FY2099 rate, fail
        low = (resp.content or "").lower()
        if status == "insufficient_evidence" and any(
            x in low for x in ["per 100,000", "exactly", "fy2099", "fiscal year 2099 rate"]
        ):
            # only flag if it sounds like a concrete fabricated stat claim
            if any(ch.isdigit() for ch in resp.content):
                invented = True

    passed = ok_status and ok_evidence and not invented

    return {
        "id": case["id"],
        "passed": passed,
        "research_status": status,
        "evidence_count": evidence_count,
        "recovery_attempts": meta.get("recovery_attempts"),
        "search_rounds": meta.get("search_rounds"),
        "source_outcomes": outcomes,
        "answer_preview": (resp.content or "")[:400],
    }


async def main():
    registry = build_default_registry()
    async with OllamaClient(model="defend-ai") as model:
        cp = ControlPlane(registry, model, policy_engine=DevWebPolicy())
        print("Tools:", list(registry.keys()))
        print()

        results = []
        for case in CASES:
            print("=" * 64)
            print("CASE:", case["id"])
            print("Q:", case["message"][:120], "...")
            r = await run_case(cp, case)
            results.append(r)
            print("PASS:" if r["passed"] else "FAIL:", r["passed"])
            print("research_status:", r["research_status"])
            print("evidence_count:", r["evidence_count"])
            print("recovery_attempts:", r["recovery_attempts"])
            print("search_rounds:", r["search_rounds"])
            print("ANSWER:", r["answer_preview"])
            print()

        passed = sum(1 for r in results if r["passed"])
        print("=" * 64)
        print(f"SUMMARY: {passed}/{len(results)} passed")


if __name__ == "__main__":
    asyncio.run(main())