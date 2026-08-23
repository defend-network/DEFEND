"""True AI Copilot agent loop - trust-hardened (M1.4.2, P0-P8, P15-P17).

Bounded PLAN -> CALL -> OBSERVE -> ANSWER loop over the server-side
ToolRegistry. The final VISIBLE answer derives from the VERIFIED structured
claim set - the model cannot smuggle unsupported OEM/STANDARD/NUMERIC claims
through freeform prose. Deterministic-first routing has an explicit state
machine; simple queries never burn an AI call. Provider failure degrades to
the deterministic router.

M1.4.2 changes:
  * ZERO raw-prose fallback (P1): _finalize_agent never exposes the model's
    unverified prose when zero claims survive - render_safe() emits an
    explicit abstention instead.
  * One verified answer pipeline (P2): deterministic routes verify their facts
    through the same claim renderer.
  * Structured model response first (P3), prose extraction as fallback.
  * Evidence facts carry entity/unit/calculator identity (P4/P5).
  * Tool executions get stable evidence IDs (P21).
"""
from __future__ import annotations

import re
import time
import uuid
from datetime import datetime
from typing import Any

from .claims import (
    build_evidence,
    extract_claims_from_prose,
    extract_structured_claims,
    render_safe,
    verify_claims,
)
from .policy import COPILOT_SYSTEM_POLICY_VERSION, model_system_prompt

MAX_TOOL_ITERATIONS = 6
COPILOT_MODE_AGENTIC = "AGENTIC"
COPILOT_MODE_DETERMINISTIC = "DETERMINISTIC_FALLBACK"

# AI-avoidance / routing metrics (thread-safe guard handled at call site)
COUNTERS = {"TOTAL_COPILOT_REQUESTS": 0, "DETERMINISTIC_COMPLETE_REQUESTS": 0,
            "AGENTIC_REQUESTS": 0, "AI_CALLS_AVOIDED": 0, "AI_FALLBACKS": 0}

_COMPLETENESS_STATES = ("COMPLETE", "PARTIAL", "NOT_AVAILABLE", "CONFLICT",
                        "NEEDS_AUTHORITY", "NEEDS_MEASUREMENT")

_CALC_CONCEPT = {
    "CFM": "CFM", "FPM": "FPM", "%": "PERCENT_DESIGN",
    "IN.W.C.": "STATIC_PRESSURE", "IN.W.G.": "STATIC_PRESSURE",
    "RPM": "RPM", "HZ": "HZ", "FT2": "AREA", "IN": "IN",
}


def new_answer_id() -> str:
    return f"ANS-{uuid.uuid4().hex[:12]}"


def new_evidence_id() -> str:
    return f"EVID-{uuid.uuid4().hex[:12]}"


def _calculator_concept(data: dict[str, Any]) -> str | None:
    calc_id = (data.get("calculation_id") or "").lower()
    units = (data.get("units") or "").upper()
    if "percent" in calc_id:
        return "PERCENT_DESIGN"
    return _CALC_CONCEPT.get(units)


def answer_completeness(result: dict[str, Any]) -> str:
    """Explicit AnswerCompleteness (P10): a nonempty facts list containing
    None values is NOT COMPLETE."""
    facts = result.get("facts")
    if result.get("conflict") or any(f.get("label") == "CONFLICT" for f in (facts or [])):
        return "CONFLICT"
    if not facts:
        return "NOT_AVAILABLE"
    if any(f.get("value") is None for f in facts):
        return "PARTIAL"
    if result.get("needs_measurement"):
        return "NEEDS_MEASUREMENT"
    if result.get("needs_authority"):
        return "NEEDS_AUTHORITY"
    return "COMPLETE"


def classify_pre_route(result: dict[str, Any], question: str | None = None) -> str:
    """Explicit pre-route state machine (P10/P16):
    DETERMINISTIC_COMPLETE / DETERMINISTIC_PARTIAL / AGENT_REQUIRED / NO_ROUTE.

    Completeness is computed from the answer's facts - an answer with
    "RTU-5 supply None CFM" is NOT DETERMINISTIC_COMPLETE.
    """
    tool = result.get("tool")
    words = set(re.findall(r"[a-z]+", (question or "").lower()))
    diagnostic_intent = bool(question) and (
        "why" in words or "low" in words or "high" in words or "trouble" in words
        or "problem" in words or "check" in words or "diagnos" in words)
    if tool == "calculator.*":
        return "DETERMINISTIC_COMPLETE"
    if tool == "plan.query":
        complete = answer_completeness(result) == "COMPLETE"
        if diagnostic_intent:
            return "AGENT_REQUIRED"
        return "DETERMINISTIC_COMPLETE" if complete else "AGENT_REQUIRED"
    if tool == "procedure.start":
        return "DETERMINISTIC_COMPLETE" if result.get("procedure") else "AGENT_REQUIRED"
    if tool == "knowledge.search":
        complete = answer_completeness(result) in ("COMPLETE", "PARTIAL")
        return "DETERMINISTIC_COMPLETE" if complete and result.get("facts") else "AGENT_REQUIRED"
    if tool == "diagnostic.start":
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
        answer = dict(pre_route)
        answer["ai_call_avoided"] = True
        answer["pre_route_state"] = route_state
        answer["copilot_mode"] = COPILOT_MODE_DETERMINISTIC
        answer["completeness"] = answer_completeness(pre_route)
        # P25: deterministic procedure/diagnostic routes must ALSO create
        # durable job-scoped sessions (not just return template data).
        _materialize_deterministic_session(pre_route, registry, answer)
        # one verified answer pipeline (P2): verify deterministic facts
        _verify_deterministic_answer(answer, pre_route)
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
                               state="DETERMINISTIC_COMPLETE",
                               facts=answer.get("facts"))
        return answer

    COUNTERS["AGENTIC_REQUESTS"] += 1
    system = model_system_prompt()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": _structured_context(context, memory) +
         "\n\nQUESTION: " + question},
    ]
    tool_calls: list[dict[str, Any]] = []
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
            _verify_deterministic_answer(answer, answer)
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
        # P9: the provider owns native message serialization. Preserve the
        # assistant tool-call request in provider-native format so tool results
        # match tool calls by the provider's own contract.
        tool_call_msg = getattr(provider, "tool_call_message", None)
        tool_result_msg = getattr(provider, "tool_result_message", None)
        messages.append(tool_call_msg(calls) if tool_call_msg else
                        {"role": "assistant", "content": None, "tool_calls": calls})
        for call_index, call in enumerate(calls, start=1):
            name = call.get("name")
            arguments = call.get("arguments") or {}
            provider_tool_call_id = call.get("id")
            tools_requested += 1
            result = registry.execute(name, arguments)
            if not result.get("ok"):
                tools_rejected += 1
            # P8: SCS evidence id is DISTINCT from the provider tool-call id.
            evidence_id = result.get("evidence_id") or new_evidence_id()
            tool_result_ids.append(evidence_id)
            tool_calls.append({
                "name": name, "arguments": arguments,
                "provider_tool_call_id": provider_tool_call_id,
                "evidence_id": evidence_id,
                "ok": result.get("ok", False),
            })
            if result.get("ok") and result.get("data"):
                _collect_evidence(result, final_facts, calculator_ids, source_ids)
            observation_json = __import__("json").dumps(
                registry.compact_observation(result))
            messages.append(tool_result_msg(provider_tool_call_id, observation_json)
                            if tool_result_msg else
                            {"role": "tool", "content": observation_json})
        if iterations >= MAX_TOOL_ITERATIONS:
            break

    # max iterations: PARTIAL_AGENT_RESULT - never discard gathered evidence
    evidence = build_evidence(final_facts)
    verified = verify_claims(_materialized_claims(final_facts), evidence)["verified"]
    visible = render_safe({"verified": verified, "results": []})
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


def _materialize_deterministic_session(pre_route: dict[str, Any],
                                       registry, answer: dict[str, Any]) -> None:
    """Create durable job-scoped sessions for deterministic procedure/
    diagnostic routes (P25) so they survive restart like agentic sessions.

    P11: session durability is only ever claimed when registry execution
    actually returned ``ok`` - a silent failure must not be represented as a
    durable session.
    """
    tool = pre_route.get("tool")
    answer["session_durable"] = False
    if tool not in ("procedure.start", "diagnostic.start"):
        return
    memory_backing = getattr(registry, "memory", None) is not None
    try:
        if tool == "procedure.start":
            procedure_id = (pre_route.get("procedure") or {}).get("procedure_id")
            if procedure_id:
                result = registry.execute("procedure.start", {"procedure_id": procedure_id})
                if result.get("ok"):
                    answer["procedure"] = result.get("data")
                    # P3: durable only when a real memory backing exists to
                    # hold the session for the persistence path.
                    answer["session_durable"] = memory_backing
        elif tool == "diagnostic.start":
            graph_id = (pre_route.get("graph") or {}).get("graph_id")
            if graph_id:
                result = registry.execute("diagnostic.start", {"graph_id": graph_id})
                if result.get("ok"):
                    answer["graph"] = result.get("data")
                    answer["session_durable"] = memory_backing
    except Exception:
        answer["session_durable"] = False


def _verify_deterministic_answer(answer: dict[str, Any], pre_route: dict[str, Any]) -> None:
    """Run deterministic facts through the SAME claim renderer (P2/P14)."""
    facts = pre_route.get("facts") or []
    evidence = build_evidence(facts)
    claims = _materialized_claims(facts)
    verification = verify_claims(claims, evidence)
    answer["verification"] = verification
    answer["verified_claims"] = verification["verified"]
    # a blocked technical claim must not remain asserted in the deterministic
    # answer string (P14): if everything is blocked and the answer holds a
    # technical assertion, replace with a safe abstention.
    if verification["CLAIMS_BLOCKED"] > 0 and not verification["verified"]:
        safe = render_safe(verification)
        if safe.strip():
            answer["answer"] = safe


def _materialized_claims(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    claims = []
    for index, fact in enumerate(facts, start=1):
        citation = fact.get("citation") or {}
        claims.append({
            "claim_id": f"EVIDENCE-{index:02d}",
            "claim_type": fact.get("label", "CALCULATED"),
            "concept": fact.get("concept"), "value": fact.get("value"),
            "unit": fact.get("unit"), "assertion_text": str(fact.get("value")),
            "entity_id": fact.get("entity_id"),
            "evidence_refs": [fact.get("evidence_id")] if fact.get("evidence_id") else [],
            "calculator_ref": citation.get("formula"),
            "source_refs": [citation.get("source_id")] if citation.get("source_id") else [],
            "inference": fact.get("label") == "INFERRED",
            "applicability": fact.get("applicability", "UNKNOWN"),
            "confidence": fact.get("confidence", "HIGH"),
            "label": fact.get("label"),
        })
    return claims


def _finalize_agent(question, content, context, memory, answer_id, tool_calls,
                    tool_result_ids, source_ids, calculator_ids, final_facts,
                    finish, *, route_state, quality=None):
    """Verify claims extracted from the model's visible response. The visible
    answer derives from the verified set - NEVER from raw model prose (P1)."""
    evidence = build_evidence(final_facts)
    structured = extract_structured_claims(content, evidence)
    claims = structured if structured is not None else extract_claims_from_prose(content, evidence)
    verification = verify_claims(claims, evidence)
    visible = render_safe(verification, next_actions=[], questions=[])
    answer = {
        "tool": "agent", "pre_route_state": route_state,
        "answer": visible,
        "facts": verification["verified"] + list(final_facts),
        "verification": verification,
        "next_actions": [], "questions": [],
    }
    return _finalize(question, answer, context, memory, answer_id,
                     COPILOT_MODE_AGENTIC, tool_calls, tool_result_ids,
                     source_ids, calculator_ids, final_facts, reason=finish,
                     route_state=route_state, quality=quality)


def _structured_context(context, memory) -> str:
    """Bounded, structured context packet (P49-P50/P63-P64): no raw JSON cut."""
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
        if packet.get("active_entity"):
            lines.append("Active entity: " + str(packet["active_entity"]))
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
    evidence_id = result.get("evidence_id") or new_evidence_id()
    if isinstance(data, dict):
        if data.get("formula_id") is not None or data.get("calculation_id") is not None:
            calculator_ids.append(data.get("formula_id") or data.get("calculation_id"))
            final_facts.append({"label": "CALCULATED",
                                "concept": _calculator_concept(data),
                                "value": data.get("result"), "unit": data.get("units"),
                                "evidence_id": evidence_id,
                                "citation": {"formula": data.get("formula_id") or data.get("calculation_id")}})
        if data.get("design"):
            for key, value in data["design"].items():
                final_facts.append({"label": "DESIGN",
                                    "concept": f"DESIGN_{key}",
                                    "value": value, "unit": _design_unit(key),
                                    "entity_id": data.get("equipment_id"),
                                    "evidence_id": evidence_id,
                                    "citation": {"source_type": "PROJECT_SCHEDULE"}})
        if data.get("readings"):
            for key, entry in (data["readings"] if isinstance(data["readings"], dict) else {}).items():
                if isinstance(entry, dict):
                    final_facts.append({"label": "FIELD", "concept": f"FIELD_{key}",
                                        "value": entry.get("value"),
                                        "unit": entry.get("unit"),
                                        "entity_id": entry.get("equipment_id") or entry.get("entity_id"),
                                        "instrument_id": entry.get("instrument_id"),
                                        "stage": entry.get("stage"),
                                        "evidence_id": evidence_id,
                                        "citation": {"source_type": "FIELD_MEASUREMENT"}})
                else:
                    final_facts.append({"label": "FIELD", "concept": f"FIELD_{key}",
                                        "value": entry, "evidence_id": evidence_id,
                                        "citation": {"source_type": "FIELD_MEASUREMENT"}})
        if result.get("tool") == "job.readings" and isinstance(data, dict):
            for key, entry in data.items():
                if isinstance(entry, dict):
                    final_facts.append({"label": "FIELD", "concept": entry.get("concept") or f"FIELD_{key}",
                                        "value": entry.get("value"), "unit": entry.get("unit"),
                                        "entity_id": entry.get("equipment_id") or entry.get("entity_id"),
                                        "instrument_id": entry.get("instrument_id"),
                                        "stage": entry.get("stage"),
                                        "evidence_id": evidence_id,
                                        "citation": {"source_type": "FIELD_MEASUREMENT"}})
                else:
                    final_facts.append({"label": "FIELD", "concept": f"FIELD_{key}",
                                        "value": entry, "evidence_id": evidence_id,
                                        "citation": {"source_type": "FIELD_MEASUREMENT"}})
        if data.get("source_id"):
            source_ids.append(data["source_id"])
        if data.get("graph_id") and isinstance(data.get("causes"), list):
            # P22: capture real DiagnosticSession state as verification evidence
            final_facts.append({"label": "DIAGNOSTIC", "concept": "DIAGNOSTIC",
                                "value": data.get("graph_id"),
                                "evidence_id": evidence_id,
                                "diagnostic": data})
        if data.get("identity"):
            identity = data["identity"]
            resolution = identity.get("resolution")
            # P14: a decoder result is never presented as verified OEM fact.
            if resolution == "EXACT_MODEL_REFERENCE":
                label, concept = "INFERRED_IDENTITY", "INFERRED_IDENTITY"
            elif resolution == "FAMILY_LEVEL_REFERENCE":
                label, concept = "DECODED_FAMILY", "DECODED_FAMILY"
            else:
                label, concept = "UNKNOWN", "UNKNOWN_MODEL_IDENTITY"
            final_facts.append({"label": label, "concept": concept,
                                "value": identity.get("product_family") or identity.get("model_exact"),
                                "entity_id": identity.get("model_exact"),
                                "evidence_id": evidence_id,
                                "citation": None})


def _design_unit(key: str) -> str | None:
    upper = (key or "").upper()
    if "CFM" in upper:
        return "CFM"
    if "ESP" in upper or "STATIC" in upper:
        return "IN.W.C."
    if "RPM" in upper:
        return "RPM"
    return None


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
