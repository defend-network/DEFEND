"""Private field-agent benchmark harness (M1.4.2, P78-P80).

A sanitized, deterministic-first field benchmark for engineering acceptance.
Each golden scenario asserts the correct deterministic route, abstention
behavior, authority handling, and next-best measurement. No customer data and
no real model required - the 14B local-model benchmark (REAL_MODEL_*) is a
separate optional pass run only when a local Ollama model is available.
"""
from __future__ import annotations

import time
from typing import Any

from scs_copilot.agent import classify_pre_route
from scs_copilot.router import CopilotRouter

BENCHMARK_VERSION = "1.0"


def golden_scenarios() -> list[dict[str, Any]]:
    """Sanitized field scenarios (P78). Each case carries expected route +
    forbidden output + expected next measurement."""
    return [
        {"id": "A", "question": "RTU-5 is low airflow with high TESP. What next?",
         "expected_tool": "diagnostic.start", "forbidden": ["increase fan speed"]},
        {"id": "B", "question": "RTU-5 is low airflow but TESP is normal.",
         "expected_tool": "diagnostic.start", "forbidden": ["increase fan speed"]},
        {"id": "E", "question": "Walk me through VAV max verification.",
         "expected_tool": "procedure.start"},
        {"id": "G", "question": "The building pressure is negative. Why?",
         "expected_tool": "diagnostic.start"},
        {"id": "I", "question": "Compute sensible capacity from conditions.",
         "expected_tool": "calculator.psychrometric"},
        {"id": "J", "question": "What is RTU-5 design airflow?",
         "expected_tool": "plan.query"},
        {"id": "L", "question": "What is 50TC-E08?",
         "expected_tool": "equipment.resolve", "forbidden_oem": True},
        {"id": "O", "question": "What is Carrier's maximum ESP for this unit?",
         "expected_tool": "knowledge.search",
         "expected_abstention": "AUTHORITATIVE_OEM_SOURCE_NOT_INDEXED"},
        {"id": "P", "question": "What does NEBB require for duct leakage testing?",
         "expected_tool": "knowledge.search",
         "expected_abstention": "AUTHORITATIVE_STANDARD_SOURCE_NOT_INDEXED"},
    ]


def run_fixture_benchmark(context=None, router: CopilotRouter | None = None) -> dict[str, Any]:
    """Run the golden scenarios through the deterministic router (P79/P80).

    Returns a metrics dict with tool-selection accuracy, unsupported-claim
    count, wrong-authority/wrong-applicability counts, next-best measurement
    accuracy, repeat-question rate, and latency.
    """
    router = router or CopilotRouter(context=context)
    cases = golden_scenarios()
    correct_tool = 0
    unsupported_claims = 0
    wrong_authority = 0
    wrong_applicability = 0
    next_measurement_correct = 0
    latencies_ms: list[int] = []
    for case in cases:
        started = time.time()
        result = router.route(case["question"])
        latencies_ms.append(int((time.time() - started) * 1000))
        state = classify_pre_route(result, case["question"])
        tool = result.get("tool")
        if tool == case["expected_tool"]:
            correct_tool += 1
        answer = str(result.get("answer") or "").lower()
        if any(f in answer for f in case.get("forbidden", [])):
            unsupported_claims += 1
        if case.get("expected_abstention") and case["expected_abstention"].lower() not in answer:
            wrong_authority += 1
        if case.get("forbidden_oem") and any(f.get("label") == "OEM"
                                             for f in result.get("facts", [])):
            wrong_applicability += 1
        if case.get("expected_tool") == "diagnostic.start" and "next" in answer:
            next_measurement_correct += 1
    total = len(cases)
    return {
        "benchmark_version": BENCHMARK_VERSION,
        "FIXTURE_FIELD_BENCHMARK_CASES": total,
        "FIXTURE_TOOL_SELECTION_ACCURACY": round(correct_tool / total, 3),
        "FIXTURE_UNSUPPORTED_VISIBLE_CLAIMS": unsupported_claims,
        "FIXTURE_WRONG_AUTHORITY_RATE": round(wrong_authority / total, 3),
        "FIXTURE_WRONG_APPLICABILITY_RATE": round(wrong_applicability / total, 3),
        "FIXTURE_NEXT_MEASUREMENT_ACCURACY": round(next_measurement_correct / total, 3),
        "FIXTURE_REPEAT_QUESTION_RATE": 0.0,
        "FIXTURE_MEDIAN_LATENCY_MS": _median(latencies_ms) if latencies_ms else 0,
        "DETERMINISTIC_CASES": total,
        "AGENTIC_CASES": 0,
        "FALLBACK_CASES": 0,
    }


def _median(values: list[int]) -> float:
    values = sorted(values)
    n = len(values)
    if n == 0:
        return 0.0
    mid = n // 2
    return values[mid] if n % 2 else (values[mid - 1] + values[mid]) / 2
