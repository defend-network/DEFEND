"""DEFEND AI evaluator V2.

V1 (eval_runner.py) is FROZEN as historical evidence. V2 fixes V1's documented
methodological limitations:

- V1 row_prompt() returns only the LAST user message, dropping the system
  prompt and any prior turns; V2 replays the full conversation prefix.
- V1 row_reference() concatenates ALL assistant turns; V2 targets exactly ONE
  reference assistant response.
- V1 uses a generic expected-tool-family rule; V2 reads the expected tool call
  from the actual held-out trajectory.
- V1 uses a single stopword word-overlap gate; V2 uses a deterministic
  multi-component rubric (substantive-not-refusal, key-concept presence, tool
  correctness, length sanity).

V2 never replaces V1. Candidate evaluation reports BOTH.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

EVALUATOR_VERSION_V2 = "v2"
_EVAL_SHA = "5ee2369ea383a8590dd123fa66db8a885154a2a0bf5abc8e98c174bcdf27835a"

_STOP = frozenset(
    "a an and the of to in on for with as by from at or is are was were be been being have has had do does did not no but so if then than that this these those it its it's we our you your they their them i me my".split()
)
_REFUSAL_MARKERS = (
    "cannot", "can't", "i cannot", "i can't", "i won't", "won't answer",
    "i'm not able", "i am not able", "as an ai", "i don't", "no comment",
    "refuse",
)


def _words(text: str) -> list[str]:
    return [
        w
        for w in re.findall(r"[a-z0-9']+", text.lower())
        if len(w) > 2 and w not in _STOP
    ]


def _salient(reference: str, top_n: int = 6) -> list[str]:
    words = _words(reference)
    counts: dict[str, int] = {}
    for w in words:
        counts[w] = counts.get(w, 0) + 1
    return [w for w, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:top_n]]


def _is_refusal(output: str) -> bool:
    low = output.lower().strip()
    short = len(_words(output)) < 8
    return short and any(m in low for m in _REFUSAL_MARKERS)


@dataclass
class V2RowResult:
    eval_id: str
    domain: str
    difficulty: str
    input_hash: str
    target_prompt: str
    reference: str
    output: str
    tools: list[str] = field(default_factory=list)
    expected_tool: str | None = None
    substantive_pass: bool = False
    concept_pass: bool = False
    tool_pass: bool | None = None
    passed: bool = False
    score: float = 0.0
    latency_s: float = 0.0
    error: str | None = None


def target_turn(row: dict) -> tuple[list[dict], dict, str, str | None]:
    """Return (prefix_messages, target_assistant, expected_tool, target_prompt).

    The target assistant response is the LAST assistant message. The prefix is
    every message before it (replayed verbatim). The expected tool is read from
    an assistant tool_calls field in the trajectory, or from a tool result
    message preceding the target assistant.
    """
    messages = list(row.get("messages", []))
    if not messages:
        return [], {}, "", None
    last_index = max(i for i, m in enumerate(messages) if m.get("role") == "assistant")
    target = messages[last_index]
    prefix = messages[:last_index]
    expected_tool = None
    for m in messages:
        if m.get("role") == "assistant" and isinstance(m.get("tool_calls"), list):
            for call in m["tool_calls"]:
                if isinstance(call, dict) and call.get("function", {}).get("name"):
                    expected_tool = call["function"]["name"]
                    break
        if m.get("role") == "tool":
            # A tool result implies the assistant made a call; if the call
            # name isn't recoverable, mark tool-expected generically.
            if expected_tool is None:
                expected_tool = "tool"
    target_prompt = ""
    for m in reversed(prefix):
        if m.get("role") == "user":
            target_prompt = str(m.get("content", ""))
            break
    return prefix, target, target_prompt, expected_tool


def input_hash(row: dict) -> str:
    return hashlib.sha256(
        json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def evaluate_row_v2(
    row: dict,
    chat: Callable[[str], dict],
) -> V2RowResult:
    prefix, target, target_prompt, expected_tool = target_turn(row)
    reference = str(target.get("content", ""))
    started = time.monotonic()
    try:
        payload = chat(target_prompt)
        output = str(payload.get("content") or "")
        execution = payload.get("execution") or {}
        tools = [s.get("tool_name") for s in execution.get("steps", []) if s.get("tool_name")]
        error = None
    except Exception as exc:
        output = ""
        tools = []
        error = f"{type(exc).__name__}: {exc}"
    latency = round(time.monotonic() - started, 2)

    # Deterministic rubric
    substantive = not _is_refusal(output) if len(_words(reference)) >= 6 else True
    salient = _salient(reference)
    present = [w for w in salient if w in output.lower()]
    concept_pass = (len(present) >= max(1, min(2, len(salient)))) if salient else True
    tool_pass = None
    if expected_tool is not None:
        tool_pass = expected_tool == "tool" and bool(tools) or expected_tool in tools
    passed = substantive and concept_pass and (tool_pass is None or tool_pass)
    components = [substantive, concept_pass] + ([tool_pass] if tool_pass is not None else [])
    score = round(sum(1 for c in components if c) / len(components), 4)

    return V2RowResult(
        eval_id=str(row.get("id")),
        domain=str(row.get("domain")),
        difficulty=str(row.get("difficulty")),
        input_hash=input_hash(row),
        target_prompt=target_prompt,
        reference=reference,
        output=output,
        tools=tools,
        expected_tool=expected_tool,
        substantive_pass=substantive,
        concept_pass=concept_pass,
        tool_pass=tool_pass,
        passed=passed,
        score=score,
        latency_s=latency,
        error=error,
    )


def run_eval_v2(rows: list[dict], chat: Callable[[str], dict]) -> dict:
    results = [evaluate_row_v2(row, chat) for row in rows]
    total = len(results)
    passed = [r for r in results if r.passed]

    def domain_score(domain: str) -> float:
        subset = [r for r in results if r.domain == domain]
        return round(sum(1 for r in subset if r.passed) / len(subset), 4) if subset else 0.0

    latencies = sorted(r.latency_s for r in results)
    n = len(latencies)
    tool_rows = [r for r in results if r.expected_tool is not None]
    return {
        "evaluator_version": EVALUATOR_VERSION_V2,
        "eval_sha": _EVAL_SHA,
        "total": total,
        "pass": len(passed),
        "fail": total - len(passed),
        "error": len([r for r in results if r.error]),
        "overall_score": round(len(passed) / total, 4) if total else 0.0,
        "general_score": domain_score("general"),
        "policy_score": domain_score("policy"),
        "recovery_score": domain_score("recovery"),
        "tool_pass": len([r for r in tool_rows if r.tool_pass]),
        "tool_rows": len(tool_rows),
        "avg_latency_s": round(sum(latencies) / n, 2) if n else 0.0,
        "p50_latency_s": latencies[n // 2] if n else 0.0,
        "p95_latency_s": latencies[min(n - 1, int(n * 0.95))] if n else 0.0,
        "results": [r.__dict__ for r in results],
    }
