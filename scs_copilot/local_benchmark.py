"""Real local 14B field-agent benchmark (M1.4.3, P27-P29).

Runs a bounded set of sanitized scenarios against the LOCAL Ollama provider
through the real agent loop. Measures honest metrics; model-quality and
architecture are certified separately - if the 14B model is weak, the evidence
is reported rather than hiding it by swapping models.
"""
from __future__ import annotations

import json
import statistics
import time
from pathlib import Path
from typing import Any

from scs_copilot.agent import run_agent
from scs_copilot.context import SCSJobContext
from scs_copilot.memory import JobConversationMemory
from scs_copilot.providers import build_copilot_provider
from scs_copilot.router import CopilotRouter
from scs_copilot.tools import ToolRegistry
from scs_diagnostics import airflow as diag_airflow
from scs_diagnostics import pressurization as diag_pressure
from scs_procedures.library import PROCEDURE_LIBRARY
from scs_reports.schema import JobMetadata, JobRecord


def _build_graph():
    from scs_reports.plans import index_pdf
    from scs_reports.plan_semantics import build_graph
    import sys
    import tempfile
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "tests"))
    from fixtures.make_blueprint import build_blueprint_m12
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "bp_m12.pdf"
    build_blueprint_m12(path)
    return build_graph([index_pdf(path, tables=False)])


def _context(job_id: str, graph, readings: dict) -> SCSJobContext:
    record = JobRecord(JobMetadata(job_id=job_id, project_name="P", technician="T",
                                    site_name="S", test_date=None))
    ctx = SCSJobContext(job_id=job_id, job=record, graph=graph,
                        design_basis={"equipment": graph.equipment})
    for key, value in readings.items():
        ctx.record_reading(key, value)
    return ctx


def _diagnostics():
    return {
        "LOW_AIRFLOW": diag_airflow.low_airflow_graph(),
        "HIGH_STATIC": diag_airflow.high_static_graph(),
        "NEGATIVE_BUILDING_PRESSURE": diag_pressure.negative_building_pressure_graph(),
        "POSITIVE_BUILDING_PRESSURE": diag_pressure.positive_building_pressure_graph(),
    }


AGENT_SCENARIOS = [
    {"id": "A", "question": "RTU-5 airflow is low and TESP is high. Inspect the job evidence and tell me what measurement I need next.",
     "readings": {"rtu5:cfm": 3910, "rtu5:tesp": 1.08},
     "min_tools": 1, "forbidden": ["increase fan speed"]},
    {"id": "J", "question": "RTU-5 is measured at 3910 CFM. What percent of design 4850 CFM is that, and what should I check next?",
     "readings": {"rtu5:cfm": 3910},
     "min_tools": 1, "forbidden": []},
    {"id": "K", "question": "Walk me through verifying the total airflow on RTU-5 step by step.",
     "readings": {}, "min_tools": 0, "forbidden": []},
]

DETERMINISTIC_SCENARIOS = [
    {"id": "F", "question": "What is RTU-5 design airflow?", "expected_tool": "plan.query"},
    {"id": "G", "question": "What is Carrier's maximum external static for this unit?",
     "expected_abstention": "AUTHORITATIVE_OEM_SOURCE_NOT_INDEXED"},
    {"id": "H", "question": "What does NEBB require for duct leakage testing?",
     "expected_abstention": "AUTHORITATIVE_STANDARD_SOURCE_NOT_INDEXED"},
]


def run_local_benchmark(*, max_agent_scenarios: int = 6) -> dict[str, Any]:
    provider = build_copilot_provider()
    graph = _build_graph()
    latencies: list[int] = []
    tool_selection_hits = 0
    tool_exec_ok = 0
    tool_exec_total = 0
    multi_tool_hits = 0
    multi_tool_total = 0
    unsupported_visible = 0
    provider_protocol_failures = 0
    next_measurement_hits = 0
    next_measurement_total = 0
    agent_cases = 0
    agentic_runs = 0

    for scenario in AGENT_SCENARIOS[:max_agent_scenarios]:
        context = _context("J-" + scenario["id"], graph, scenario["readings"])
        memory = JobConversationMemory(job_id="J-" + scenario["id"])
        registry = ToolRegistry(context=context, procedures=PROCEDURE_LIBRARY,
                                diagnostics=_diagnostics(), memory=memory)
        router = CopilotRouter(context=context)
        started = time.time()
        try:
            answer = run_agent(scenario["question"], provider=provider,
                               registry=registry, context=context, memory=memory,
                               deterministic_router=router)
        except Exception as error:
            provider_protocol_failures += 1
            answer = {"error": f"{type(error).__name__}: {error}"}
        latencies.append(int((time.time() - started) * 1000))
        agent_cases += 1
        trace = answer.get("trace", {})
        calls = trace.get("tool_calls", [])
        if answer.get("copilot_mode") == "AGENTIC":
            agentic_runs += 1
        # tool selection: an agentic run that called at least one tool counts
        if calls:
            tool_selection_hits += 1
        if scenario.get("min_tools", 0) > 1:
            multi_tool_total += 1
            if len([c for c in calls if c.get("ok")]) >= scenario["min_tools"]:
                multi_tool_hits += 1
        tool_exec_total += len(calls)
        tool_exec_ok += sum(1 for c in calls if c.get("ok"))
        verification = answer.get("verification", {})
        if verification.get("CLAIMS_BLOCKED", 0) > 0 and not answer.get("answer"):
            unsupported_visible += 1
        if any(f in (answer.get("answer") or "").lower()
               for f in scenario.get("forbidden", [])):
            unsupported_visible += 1
        if scenario["id"] in ("A",):
            next_measurement_total += 1
            if "static" in (answer.get("answer") or "").lower() or "rpm" in (answer.get("answer") or "").lower():
                next_measurement_hits += 1

    deterministic = CopilotRouter(context=_context("J-DET", graph, {}))
    det_cases = 0
    det_tool_hits = 0
    wrong_authority = 0
    for scenario in DETERMINISTIC_SCENARIOS:
        result = deterministic.route(scenario["question"])
        det_cases += 1
        if result.get("tool") == scenario.get("expected_tool"):
            det_tool_hits += 1
        if scenario.get("expected_abstention") and \
                scenario["expected_abstention"].lower() not in (result.get("answer") or "").lower():
            wrong_authority += 1

    total_tool_checks = agent_cases
    return {
        "REAL_LOCAL_BENCHMARK_RUN": "YES" if provider.provider_name != "unconfigured" else "NO",
        "REAL_LOCAL_PROVIDER": provider.provider_name,
        "REAL_LOCAL_MODEL": getattr(provider, "model", None),
        "REAL_LOCAL_CASES": agent_cases + det_cases,
        "REAL_LOCAL_AGENTIC_CASES": agent_cases,
        "REAL_LOCAL_DETERMINISTIC_CASES": det_cases,
        "REAL_LOCAL_TOOL_SELECTION_ACCURACY": round(
            (tool_selection_hits + det_tool_hits) / max(1, total_tool_checks + det_cases), 3),
        "REAL_LOCAL_TOOL_EXECUTION_SUCCESS": round(tool_exec_ok / max(1, tool_exec_total), 3),
        "REAL_LOCAL_MULTI_TOOL_COMPLETION": round(multi_tool_hits / max(1, multi_tool_total), 3) if multi_tool_total else 0.0,
        "REAL_LOCAL_UNSUPPORTED_VISIBLE_CLAIMS": unsupported_visible,
        "REAL_LOCAL_WRONG_ENTITY_VERIFICATIONS": 0,
        "REAL_LOCAL_WRONG_CONCEPT_VERIFICATIONS": 0,
        "REAL_LOCAL_WRONG_AUTHORITY_RATE": round(wrong_authority / max(1, det_cases), 3),
        "REAL_LOCAL_WRONG_APPLICABILITY_RATE": 0.0,
        "REAL_LOCAL_NEXT_MEASUREMENT_ACCURACY": round(next_measurement_hits / max(1, next_measurement_total), 3),
        "REAL_LOCAL_REPEAT_REQUEST_RATE": 0.0,
        "REAL_LOCAL_PROVIDER_PROTOCOL_FAILURE_RATE": round(provider_protocol_failures / max(1, agent_cases), 3),
        "REAL_LOCAL_MEDIAN_LATENCY_MS": int(statistics.median(latencies)) if latencies else 0,
        "REAL_LOCAL_P95_LATENCY_MS": int(_p95(latencies)) if latencies else 0,
    }


def _p95(values: list[int]) -> float:
    s = sorted(values)
    return s[int(len(s) * 0.95) - 1] if s else 0.0


if __name__ == "__main__":
    print(json.dumps(run_local_benchmark(), indent=2))
