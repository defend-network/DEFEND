"""DEFEND AI held-out evaluator (frozen v1).

Deterministic scoring only: each eval row's reference assistant answer is
compared to the model output by stopword-filtered word overlap. Tool rows also
require the expected tool family to have been invoked. No subjective grading.

Freeze rule: do not change scoring rules after the first baseline is captured.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

EVALUATOR_VERSION = "v1"
_EVAL_SHA = "5ee2369ea383a8590dd123fa66db8a885154a2a0bf5abc8e98c174bcdf27835a"

_STOP = frozenset(
    "a an and the of to in on for with as by from at or is are was were be been being have has had do does did not no but so if then than that this these those it its it's we our you your they their them i me my".split()
)


def _words(text: str) -> set[str]:
    return {
        w
        for w in re.findall(r"[a-z0-9']+", text.lower())
        if len(w) > 2 and w not in _STOP
    }


def _overlap(reference: str, output: str) -> float:
    ref = _words(reference)
    out = _words(output)
    if not ref:
        return 0.0
    return len(ref & out) / len(ref)


@dataclass
class EvalRowResult:
    eval_id: str
    domain: str
    difficulty: str
    input_hash: str
    prompt: str
    reference: str
    output: str
    tools: list[str] = field(default_factory=list)
    expected_tool_row: bool = False
    score: float = 0.0
    passed: bool = False
    latency_s: float = 0.0
    error: str | None = None


def load_eval_rows(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            assert row.get("id"), "eval row missing id"
            rows.append(row)
    return rows


def row_prompt(row: dict) -> str:
    for message in reversed(row.get("messages", [])):
        if message.get("role") == "user":
            return str(message.get("content", ""))
    return ""


def row_reference(row: dict) -> tuple[str, list[str]]:
    parts = [str(m.get("content", "")) for m in row.get("messages", []) if m.get("role") == "assistant"]
    roles = [m.get("role") for m in row.get("messages", [])]
    expected_tools = ["time.now", "calculator.evaluate"] if "tool" in roles else []
    return "\n".join(parts), expected_tools


def input_hash(row: dict) -> str:
    return hashlib.sha256(
        json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def evaluate_row(
    row: dict,
    chat: Callable[[str], dict],
    *,
    overlap_threshold: float = 0.25,
) -> EvalRowResult:
    prompt = row_prompt(row)
    reference, expected_tools = row_reference(row)
    expected_tool_row = "tool" in {m.get("role") for m in row.get("messages", [])}
    started = time.monotonic()
    try:
        payload = chat(prompt)
        output = str(payload.get("content") or "")
        execution = payload.get("execution") or {}
        tools = [s.get("tool_name") for s in execution.get("steps", []) if s.get("tool_name")]
        error = None
    except Exception as exc:
        output = ""
        tools = []
        error = f"{type(exc).__name__}: {exc}"
    latency = round(time.monotonic() - started, 2)
    score = _overlap(reference, output)
    passed = score >= overlap_threshold
    if expected_tool_row and not any(t in tools for t in expected_tools):
        passed = False
    return EvalRowResult(
        eval_id=str(row.get("id")),
        domain=str(row.get("domain")),
        difficulty=str(row.get("difficulty")),
        input_hash=input_hash(row),
        prompt=prompt,
        reference=reference,
        output=output,
        tools=tools,
        expected_tool_row=expected_tool_row,
        score=round(score, 4),
        passed=passed,
        latency_s=latency,
        error=error,
    )


def run_eval(rows: list[dict], chat: Callable[[str], dict]) -> dict:
    results = [evaluate_row(row, chat) for row in rows]
    total = len(results)
    passed = [r for r in results if r.passed]
    failed = [r for r in results if not r.passed]
    errors = [r for r in results if r.error]

    def domain_score(domain: str) -> float:
        subset = [r for r in results if r.domain == domain]
        if not subset:
            return 0.0
        return round(sum(1 for r in subset if r.passed) / len(subset), 4)

    latencies = sorted(r.latency_s for r in results)
    n = len(latencies)
    p50 = latencies[n // 2] if n else 0.0
    p95 = latencies[min(n - 1, int(n * 0.95))] if n else 0.0
    avg = round(sum(latencies) / n, 2) if n else 0.0

    tool_rows = [r for r in results if r.expected_tool_row]
    return {
        "evaluator_version": EVALUATOR_VERSION,
        "eval_sha": _EVAL_SHA,
        "total": total,
        "pass": len(passed),
        "fail": len(failed),
        "error": len(errors),
        "overall_score": round(len(passed) / total, 4) if total else 0.0,
        "general_score": domain_score("general"),
        "policy_score": domain_score("policy"),
        "recovery_score": domain_score("recovery"),
        "tool_pass": len([r for r in tool_rows if r.passed]),
        "tool_rows": len(tool_rows),
        "avg_latency_s": avg,
        "p50_latency_s": p50,
        "p95_latency_s": p95,
        "results": [r.__dict__ for r in results],
    }
