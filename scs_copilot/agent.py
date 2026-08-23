"""True AI Copilot agent loop - trust-hardened (M1.4.1, P0-P6, P15-P17,
P49-P56).

Bounded PLAN -> CALL -> OBSERVE -> ANSWER loop over the server-side
ToolRegistry. The final VISIBLE answer derives from the VERIFIED structured
claim set - the model cannot smuggle unsupported OEM/STANDARD/NUMERIC claims
through freeform prose. Deterministic-first routing has an explicit state
machine; simple queries never burn an AI call. Provider failure degrades to
the deterministic router. Every substantial answer persists a safe AnswerTrace
(no chain-of-thought).
"""
from __future__ import annotations

import re
import time
import uuid
from datetime import datetime
from typing import Any

from .claims import build_evidence, extract_claims_from_prose, render_visible, verify_claims
from .policy import COPILOT_SYSTEM_POLICY_VERSION, model_system_prompt

MAX_TOOL_ITERATIONS = 6
COPILOT_MODE_AGENTIC = "AGENTIC"
COPILOT_MODE_DETERMINISTIC = "DETERMINISTIC_FALLBACK"

# AI-avoidance / routing metrics
COUNTERS = {"TOTAL_COPILOT_REQUESTS": 0, "DETERMINISTIC_COMPLETE_REQUESTS": 0,
            "AGENTIC_REQUESTS": 0, "AI_CALLS_AVOIDED": 0, "AI_FALLBACKS": 0}


def new_answer_id() -> str:
    return f"ANS-{uuid.uuid4().hex[:12]}"


def classify_pre_route(result: dict[str, Any], question: str | None = None) -> str:
    """Explicit pre-route state machine (P16):
    DETERMINISTIC_COMPLETE / DETERMINISTIC_PARTIAL / AGENT_REQUIRED / NO_ROUTE."""
    tool = result.get("tool")
    words = set(re.findall(r"[a-z]+", (question or "").lower()))
    diagnostic_intent = bool(question) and (
        "why" in words or "low" in words or "high" in words or "trouble" in words
        or "problem" in words or "check" in words or "diagnos" in words)
    if tool == "calculator.*":
        return "DETERMINISTIC_COMPLETE"
    if tool == "plan.query":
        if diagnostic_intent:
            return "AGENT_REQUIRED"
        return "DETERMINISTIC_COMPLETE" if result.get("facts") else "AGENT_REQUIRED"
    if tool == "procedure.start":
        return "DETERMINISTIC_COMPLETE" if result.get("procedure") else "AGENT_REQUIRED"
    if tool == "knowledge.search":
        return "DETERMINISTIC_COMPLETE" if result.get("facts") else "AGENT_REQUIRED"
    if tool == "diagnostic.start":
        # diagnostics need evidence synthesis across tools (acceptance F)
        return "DETERMINISTIC_PARTIAL"
    if tool is None and not result.get("answer"):
        return "NO_ROUTE"
    return "AGENT_REQUIRED"


def run_agent(question: str, *, provider, registry, context, memory,
              deterministic_router, answer_id: str | None = None) -> dict[str, Any]:
    """Bounded agent loop; returns an answer + safe trace."""
    COUNTERS["TOTAL_COPILOT_REQUESTS"] += 1
    answer_id = answer_id or new_answer_id()
    tools = registry.schemas()

    pre_route = deterministic_router.route(question)
    route_state = classify_pre_route(pre_route, question)
    if route_state == "DETERMINISTIC_COMPLETE":
        COUNTERS["DETERMINISTIC_COMPLETE_REQUESTS"] += 1
        COUNTERS["AI_CALLS_AVOIDED"] += 1
        answer = pre_route
        answer["ai_call_avoided"] = True
        answer["pre_route_state"] = route_state
        answer["copilot_mode"] = COPILOT_MODE_DETERMINISTIC
        answer["trace"] = {
            "answer_id": answer_id, "job_id": context.job_id if context else None,
            "copilot_mode": COPILOT_MODE_DETERMINISTIC,
            "system_policy_version": COPILOT_SYSTEM_POLICY_VERSION,
            "tool_calls": [], "tool_result_ids": [], "source_ids": [],
            "calculator_ids": [], "finish_reason": "deterministic_complete",
            "ai_call_avoided": True,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        answer["answer_id"] = answer_id
        if memory:
            memory.record_turn(question, answer, answer_id=answer_id,
                               state="DETERMINISTIC_COMPLETE")
        return answer

    COUNTERS["AGENTIC_REQUESTS"] += 1
    system = model_system_prompt()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": _structured_context(context, memory) +
         "\n\nQUESTION: " + question},
    ]
    tool_calls: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    tool_result_ids: list[str] = []
    source_ids: list[str] = []
    calculator_ids: list[str] = []
    final_facts: list[dict[str, Any]] = []
    iterations = 0
    provider_calls = 0
    provider_latency_ms = 0
    tools_requested = 0
    tools_rejected = 0

    while iterations < MAX_TOOL_ITERATIONS:
        iterations += 1
        provider_calls += 1
        started = time.time()
        response = provider.complete(messages, tools=tools)
        provider_latency_ms += int((time.time() - started) * 1000)
        finish = response.get("finish_reason")
        if finish in ("unconfigured", "timeout", "provider_http_error", "error") \
                or response.get("error"):
            COUNTERS["AI_FALLBACKS"] += 1
            answer = deterministic_router.route(question)
            return _finalize(question, answer, context, memory, answer_id,
                             COPILOT_MODE_DETERMINISTIC, tool_calls, tool_result_ids,
                             source_ids, calculator_ids, final_facts,
                             reason=f"provider_fallback:{finish}",
                             route_state=route_state,
                             quality={"tool_iterations": iterations,
                                      "tools_requested": tools_requested,
                                      "tools_rejected": tools_rejected,
                                      "provider_calls": provider_calls,
                                      "provider_latency_ms": provider_latency_ms})
        calls = response.get("tool_calls") or []
        if not calls:
            content = response.get("content") or ""
            return _finalize_agent(question, content, context, memory, answer_id,
                                   tool_calls, tool_result_ids, source_ids,
                                   calculator_ids, final_facts, finish,
                                   route_state=route_state,
                                   quality={"tool_iterations": iterations,
                                            "tools_requested": tools_requested,
                                            "tools_rejected": tools_rejected,
                                            "provider_calls": provider_calls,
                                            "provider_latency_ms": provider_latency_ms,
                                            "model": response.get("model"),
                                            "provider": response.get("provider")})
        for call_index, call in enumerate(calls, start=1):
            name = call.get("name")
            arguments = call.get("arguments") or {}
            tools_requested += 1
            tool_calls.append({"name": name, "arguments": arguments})
            result = registry.execute(name, arguments)
            if not result.get("ok"):
                tools_rejected += 1
            tool_result_ids.append(f"T{iterations}_{call_index}_{name}")
            observations.append(result)
            if result.get("ok") and result.get("data"):
                _collect_evidence(result, final_facts, calculator_ids, source_ids)
            messages.append({"role": "user",
                             "content": "TOOL RESULT: " +
                             __import__("json").dumps(
                                 registry.compact_observation(result))})
        if iterations >= MAX_TOOL_ITERATIONS:
            break

    # max iterations: PARTIAL_AGENT_RESULT - never discard gathered evidence
    evidence = build_evidence(final_facts)
    verified = verify_claims(_materialized_claims(final_facts), evidence)["verified"]
    visible = render_visible(verified, next_actions=[])
    return _finalize(question, {
        "tool": "agent",
        "completion_reason": "max_iterations",
        "pre_route_state": route_state,
        "answer": visible or "PARTIAL_AGENT_RESULT: gathered " +
                  str(len(final_facts)) + " facts; unresolved question; next best action needed.",
        "facts": verified,
        "next_actions": [],
        "questions": [],
    }, context, memory, answer_id, COPILOT_MODE_AGENTIC,
        tool_calls, tool_result_ids, source_ids, calculator_ids, final_facts,
        reason="max_iterations",
        route_state=route_state,
        quality={"tool_iterations": iterations,
                 "tools_requested": tools_requested, "tools_rejected": tools_rejected,
                 "provider_calls": provider_calls,
                 "provider_latency_ms": provider_latency_ms})


def _materialized_claims(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    claims = []
    for index, fact in enumerate(facts, start=1):
        claims.append({
            "claim_id": f"EVIDENCE-{index:02d}",
            "claim_type": fact.get("label", "CALCULATED"),
            "concept": fact.get("concept"), "value": fact.get("value"),
            "unit": fact.get("unit"), "assertion_text": str(fact.get("value")),
            "evidence_refs": [], "calculator_ref": (fact.get("citation") or {}).get("formula"),
            "source_refs": [(fact.get("citation") or {}).get("source_id")] if fact.get("citation") else [],
            "inference": fact.get("label") == "INFERRED",
            "applicability": "UNKNOWN", "confidence": "HIGH",
            "label": fact.get("label"),
        })
    return claims


def _finalize_agent(question, content, context, memory, answer_id, tool_calls,
                    tool_result_ids, source_ids, calculator_ids, final_facts,
                    finish, *, route_state, quality=None):
    """Verify claims extracted from the model's visible prose; the visible
    answer derives from the verified set. Tool-gathered evidence facts are
    surfaced in the answer.facts alongside verified prose claims."""
    evidence = build_evidence(final_facts)
    claims = extract_claims_from_prose(content, evidence)
    verification = verify_claims(claims, evidence)
    visible = render_visible(verification["verified"], next_actions=[],
                             questions=[])
    answer = {
        "tool": "agent", "pre_route_state": route_state,
        "answer": visible if visible else content,
        "facts": verification["verified"] + list(final_facts),
        "verification": verification,
        "next_actions": [], "questions": [],
    }
    return _finalize(question, answer, context, memory, answer_id,
                     COPILOT_MODE_AGENTIC, tool_calls, tool_result_ids,
                     source_ids, calculator_ids, final_facts, reason=finish,
                     route_state=route_state, quality=quality)


def _structured_context(context, memory) -> str:
    """Bounded, structured context packet (P49-P50): no raw JSON truncation."""
    lines = [f"Active job: {context.job_id if context else 'n/a'}"]
    if memory:
        packet = memory.context_packet()
        readings = []
        for key, entries in list(packet["readings"].items())[:12]:
            if entries:
                last = entries[-1]
                readings.append(f"{key}={last.get('value')} ({last.get('stage')})")
        if readings:
            lines.append("Latest readings: " + "; ".join(readings))
        if packet.get("open_measurements"):
            lines.append("Open measurement requests: " + "; ".join(
                k for k, v in packet["open_measurements"].items()
                if v.get("state") == "OPEN"))
        if packet.get("answered_questions"):
            lines.append("Answered: " + "; ".join(packet["answered_questions"][-4:]))
    if context and context.design_basis:
        equipment = context.design_basis.get("equipment", [])[:2]
        if equipment:
            lines.append("Active equipment design: " + "; ".join(
                f"{e.get('tag')} supply {e.get('supply_cfm')} CFM" for e in equipment))
    return "\n".join(lines)


def _collect_evidence(result, final_facts, calculator_ids, source_ids):
    data = result.get("data")
    if not data:
        return
    if isinstance(data, dict):
        if data.get("formula_id"):
            calculator_ids.append(data["formula_id"])
            final_facts.append({"label": "CALCULATED", "concept": "CALCULATED",
                                "value": data.get("result"), "unit": data.get("units"),
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


def _finalize(question, answer, context, memory, answer_id, mode, tool_calls,
              tool_result_ids, source_ids, calculator_ids, final_facts, reason,
              *, route_state=None, quality=None):
    if memory:
        memory.record_turn(question, answer, answer_id=answer_id,
                           state=mode, facts=answer.get("facts"))
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
        "pre_route_state": route_state,
        "quality": quality or {},
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    verification = answer.get("verification") or {}
    trace["verified_claim_ids"] = [c.get("claim_id") for c in (answer.get("facts") or [])]
    trace["blocked_claim_ids"] = [r["claim_id"] for r in verification.get("results", [])
                                  if r.get("verdict") == "BLOCKED"]
    trace["downgraded_claim_ids"] = [r["claim_id"] for r in verification.get("results", [])
                                     if r.get("verdict") == "DOWNGRADED"]
    answer["copilot_mode"] = mode
    answer["trace"] = trace
    answer["answer_id"] = answer_id
    return answer
