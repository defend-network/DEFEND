"""True AI Copilot agent loop (M1.4, P0, P5-P7, H2, H10, H13).

Bounded PLAN -> CALL -> OBSERVE -> CALL -> OBSERVE -> ANSWER loop over the
server-side ToolRegistry. The reasoning model proposes tool calls; the server
validates and executes them. Deterministic calculators stay authoritative.
When no reasoning provider is available (or it fails), the loop degrades to
the M1.3 deterministic CopilotRouter (COPILOT_MODE=DETERMINISTIC_FALLBACK).

Every substantial answer persists a safe AnswerTrace (answer_id, policy
version, tool calls, tool-result ids, source ids, calculator ids, claim
verification) - never private chain-of-thought.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .policy import COPILOT_SYSTEM_POLICY_VERSION, model_system_prompt
from .verify import verify_answer

MAX_TOOL_ITERATIONS = 6
COPILOT_MODE_AGENTIC = "AGENTIC"
COPILOT_MODE_DETERMINISTIC = "DETERMINISTIC_FALLBACK"


def _compact_context(context, memory) -> str:
    lines = [f"Active job: {context.job_id if context else 'n/a'}"]
    if memory:
        packet = memory.context_packet()
        if packet["readings"]:
            lines.append("Known field readings: " + json.dumps(packet["readings"])[:500])
        if packet["answered_questions"]:
            lines.append("Already answered: " + "; ".join(packet["answered_questions"]))
    if context and context.design_basis:
        equipment = context.design_basis.get("equipment", [])[:3]
        if equipment:
            lines.append("Design basis (first units): " + json.dumps(equipment)[:500])
    return "\n".join(lines)


def run_agent(question: str, *, provider, registry, context, memory,
              deterministic_router, answer_id: str | None = None) -> dict[str, Any]:
    """Bounded agent loop; returns an answer + safe trace.

    H11: queries the deterministic router can fully answer (calculator,
    plan/design, procedure, basic diagnostic) never burn an AI call.
    """
    answer_id = answer_id or f"ANS-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    tools = registry.schemas()
    system = model_system_prompt()

    # deterministic-first: skip the model when routing is clearly sufficient
    deterministic_only = {"calculator.*", "plan.query", "procedure.start",
                          "knowledge.search"}
    pre_route = deterministic_router.route(question)
    if pre_route.get("tool") in deterministic_only and not pre_route.get("facts", []) \
            or pre_route.get("tool") == "calculator.*":
        answer = pre_route
        answer["ai_call_avoided"] = True
        answer["copilot_mode"] = COPILOT_MODE_DETERMINISTIC
        trace = {
            "answer_id": answer_id,
            "job_id": context.job_id if context else None,
            "copilot_mode": COPILOT_MODE_DETERMINISTIC,
            "system_policy_version": COPILOT_SYSTEM_POLICY_VERSION,
            "tool_calls": [], "tool_result_ids": [], "source_ids": [],
            "calculator_ids": [], "finish_reason": "deterministic_first",
            "ai_call_avoided": True,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        answer["trace"] = trace
        answer["answer_id"] = answer_id
        if memory:
            memory.record_turn(question, answer, answer_id=answer_id)
        return answer

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": _compact_context(context, memory) +
         "\n\nQUESTION: " + question},
    ]
    tool_calls: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    tool_result_ids: list[str] = []
    source_ids: list[str] = []
    calculator_ids: list[str] = []
    final_facts: list[dict[str, Any]] = []
    iterations = 0

    while iterations < MAX_TOOL_ITERATIONS:
        iterations += 1
        response = provider.complete(messages, tools=tools)
        finish = response.get("finish_reason")
        if finish in ("unconfigured", "timeout", "provider_http_error", "error") \
                or response.get("error"):
            # graceful fallback: deterministic router (H10)
            answer = deterministic_router.route(question)
            return _finalize(question, answer, context, memory, answer_id,
                             COPILOT_MODE_DETERMINISTIC, tool_calls, tool_result_ids,
                             source_ids, calculator_ids, final_facts,
                             reason=f"provider_fallback:{finish}")
        calls = response.get("tool_calls") or []
        if not calls:
            content = response.get("content") or ""
            claims = _claims_from_facts(final_facts, content)
            verification = verify_answer(claims)
            return _finalize(question, {"tool": "agent", "answer": content,
                                        "facts": claims,
                                        "verification": verification},
                             context, memory, answer_id, COPILOT_MODE_AGENTIC,
                             tool_calls, tool_result_ids, source_ids,
                             calculator_ids, final_facts, reason=finish)
        for call_index, call in enumerate(calls, start=1):
            name = call.get("name")
            arguments = call.get("arguments") or {}
            tool_calls.append({"name": name, "arguments": arguments})
            result = registry.execute(name, arguments)
            tool_result_ids.append(f"T{iterations}_{call_index}_{name}")
            observations.append(result)
            if result.get("ok") and result.get("data"):
                _collect_evidence(result, final_facts, calculator_ids, source_ids)
            if name == "job.readings" and memory:
                for key, entries in (result.get("data") or {}).items():
                    for entry in entries:
                        memory.record_reading(key, entry.get("value"),
                                              source=entry.get("source", "field"))
            messages.append({"role": "user",
                             "content": f"TOOL RESULT {name}: {json.dumps(result)[:800]}"})
        if iterations >= MAX_TOOL_ITERATIONS:
            break
    # max iterations reached -> synthesize from observations
    answer = deterministic_router.route(question)
    answer["note"] = "max tool iterations reached; synthesized from tool observations"
    return _finalize(question, answer, context, memory, answer_id, COPILOT_MODE_AGENTIC,
                     tool_calls, tool_result_ids, source_ids, calculator_ids,
                     final_facts, reason="max_iterations")


def _collect_evidence(result, final_facts, calculator_ids, source_ids):
    data = result.get("data")
    if not data:
        return
    if isinstance(data, dict):
        if data.get("formula_id"):
            calculator_ids.append(data["formula_id"])
            final_facts.append({"label": "CALCULATED", "concept": "CALCULATED",
                                "value": data.get("result"),
                                "unit": data.get("units"),
                                "citation": {"formula": data["formula_id"]}})
        if data.get("design"):
            for key, value in data["design"].items():
                final_facts.append({"label": "DESIGN", "concept": f"DESIGN_{key}",
                                    "value": value,
                                    "citation": {"source_type": "PROJECT_SCHEDULE"}})
        if data.get("source_id"):
            source_ids.append(data["source_id"])
        if data.get("identity"):
            final_facts.append({"label": "OEM", "concept": "OEM_IDENTITY",
                                "value": data["identity"].get("resolution"),
                                "citation": {"source_type": "OEM_IOM"}})


def _claims_from_facts(facts, content):
    claims = list(facts)
    if content and not any(c.get("concept") == "ANSWER" for c in claims):
        claims.append({"label": "INFERRED", "concept": "ANSWER",
                       "value": content[:200], "inference": True})
    return claims


def _finalize(question, answer, context, memory, answer_id, mode, tool_calls,
              tool_result_ids, source_ids, calculator_ids, final_facts, reason):
    if memory:
        memory.record_turn(question, answer, answer_id=answer_id)
    trace = {
        "answer_id": answer_id,
        "job_id": context.job_id if context else None,
        "copilot_mode": mode,
        "system_policy_version": COPILOT_SYSTEM_POLICY_VERSION,
        "tool_calls": tool_calls,
        "tool_result_ids": tool_result_ids,
        "source_ids": source_ids,
        "calculator_ids": calculator_ids,
        "finish_reason": reason,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    answer["copilot_mode"] = mode
    answer["trace"] = trace
    answer["answer_id"] = answer_id
    return answer
