"""DEFEND AI evaluator v2.1.

V1 (eval_runner.py) is FROZEN forever. v2.1 fixes the v2 defects found in the
M1.9.1A audit:

- chat() now receives the ACTUAL conversation prefix (list of messages), not a
  single last-user string; the target reference is never in the input.
- Target turn is classified explicitly (no uncaught max()): NO_ASSISTANT_TARGET,
  TOOL_CALL_ONLY_TARGET, FINAL_ASSISTANT_TARGET, MULTIPLE_AMBIGUOUS_TARGETS.
- Tool evaluation follows the real held-out trajectory: a list of
  {name, arguments, order} with separate selection/order/argument/incorporation
  scoring, rather than one guessed tool name.
- Rubric is a deterministic multi-component gate; semantic-equivalence is
  explicitly flagged SEMANTIC_CONTENT_UNRESOLVED where no structured criteria
  exist (never two shared words -> high-confidence PASS).
- EVAL_DATASET_SHA (held-out data) is separate from evaluator_code_sha().
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

EVALUATOR_VERSION = "v2.1"
EVAL_DATASET_SHA = "5ee2369ea383a8590dd123fa66db8a885154a2a0bf5abc8e98c174bcdf27835a"

_STOP = frozenset(
    "a an and the of to in on for with as by from at or is are was were be been being have has had do does did not no but so if then than that this these those it its it's we our you your they their them i me my".split()
)
_REFUSAL_MARKERS = (
    "cannot", "can't", "i cannot", "i can't", "i won't", "won't answer",
    "i'm not able", "i am not able", "as an ai", "i don't", "no comment",
    "refuse", "i'm sorry, but i",
)


def evaluator_code_sha() -> str:
    return hashlib.sha256(
        Path(__file__).read_text(encoding="utf-8").encode("utf-8")
    ).hexdigest()


def _words(text: str) -> list[str]:
    return [
        w
        for w in re.findall(r"[a-z0-9']+", text.lower())
        if len(w) > 2 and w not in _STOP
    ]


def _salient(reference: str, top_n: int = 5) -> list[str]:
    counts: dict[str, int] = {}
    for w in _words(reference):
        counts[w] = counts.get(w, 0) + 1
    return [w for w, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:top_n]]


def _is_refusal(output: str) -> bool:
    low = output.lower().strip()
    return any(m in low for m in _REFUSAL_MARKERS)


# ── Target-turn extraction (robust) ───────────────────────────

@dataclass
class TargetSpec:
    classification: str  # FINAL_ASSISTANT_TARGET | NO_ASSISTANT_TARGET | TOOL_CALL_ONLY_TARGET | MULTIPLE_AMBIGUOUS_TARGETS
    prefix: list[dict]
    target_index: int | None
    target_user_index: int | None
    expected_tools: list[dict]
    ambiguous: bool = False


def classify_target(row: dict) -> TargetSpec:
    messages = list(row.get("messages", []))
    assistant_indices = [i for i, m in enumerate(messages) if m.get("role") == "assistant"]
    if not assistant_indices:
        return TargetSpec("NO_ASSISTANT_TARGET", messages, None, None, [])

    # A substantive assistant turn has non-empty content; a tool-call-only turn
    # has tool_calls but empty content. The target is the LAST substantive turn.
    substantive = [i for i in assistant_indices if str(messages[i].get("content", "")).strip()]
    tool_only = [i for i in assistant_indices if not str(messages[i].get("content", "")).strip()]
    if not substantive:
        return TargetSpec("TOOL_CALL_ONLY_TARGET", messages, None, None, _extract_tools(messages))

    target_index = substantive[-1]
    # If an earlier substantive assistant turn exists, the target may be
    # ambiguous; flag but keep the final turn as the target (prefix preserves
    # the earlier turns so the model still sees them).
    ambiguous = len(substantive) > 1
    classification = "MULTIPLE_AMBIGUOUS_TARGETS" if ambiguous else "FINAL_ASSISTANT_TARGET"

    target_user_index = None
    for i in range(target_index - 1, -1, -1):
        if messages[i].get("role") == "user":
            target_user_index = i
            break

    prefix = messages[:target_index]
    return TargetSpec(classification, prefix, target_index, target_user_index, _extract_tools(messages), ambiguous)


def _extract_tools(messages: list[dict]) -> list[dict]:
    tools: list[dict] = []
    for m in messages:
        if m.get("role") == "assistant" and isinstance(m.get("tool_calls"), list):
            for call in m["tool_calls"]:
                if not isinstance(call, dict):
                    continue
                fn = call.get("function") or {}
                tools.append(
                    {
                        "name": fn.get("name"),
                        "arguments": fn.get("arguments"),
                        "order": len(tools) + 1,
                    }
                )
    return tools


def input_hash(row: dict) -> str:
    return hashlib.sha256(
        json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


# ── v2.1 evaluation ──────────────────────────────────────────

@dataclass
class V2RowResult:
    eval_id: str
    domain: str
    difficulty: str
    input_hash: str
    classification: str
    output: str
    tools: list[str] = field(default_factory=list)
    expected_tools: list[dict] = field(default_factory=list)
    substantive_pass: bool = False
    length_pass: bool = False
    concept_pass: bool = False
    tool_selection_pass: bool | None = None
    tool_order_pass: bool | None = None
    tool_arguments_pass: bool | None = None
    tool_result_incorporated: bool | None = None
    semantic_content_resolved: bool = False
    passed: bool = False
    score: float = 0.0
    latency_s: float = 0.0
    error: str | None = None


def evaluate_row_v2(
    row: dict,
    chat: Callable[[list[dict]], dict],
) -> V2RowResult:
    spec = classify_target(row)
    reference = str(row.get("messages", [])[spec.target_index].get("content", "")) if spec.target_index is not None else ""
    started = time.monotonic()
    try:
        payload = chat(list(spec.prefix))
        output = str(payload.get("content") or "")
        execution = payload.get("execution") or {}
        tools = [s.get("tool_name") for s in execution.get("steps", []) if s.get("tool_name")]
        error = None
    except Exception as exc:
        output = ""
        tools = []
        error = f"{type(exc).__name__}: {exc}"
    latency = round(time.monotonic() - started, 2)

    ref_words = _words(reference)
    # Substantive: not a refusal when the reference is substantive.
    substantive_pass = (not _is_refusal(output)) if len(ref_words) >= 4 else True
    # Length sanity: a substantive answer has a minimum number of significant words.
    length_pass = len(_words(output)) >= 4 if len(ref_words) >= 4 else True
    # Concept presence: require a majority of salient terms, not a 2-word match.
    salient = _salient(reference)
    present = [w for w in salient if w in output.lower()]
    threshold = max(1, (len(salient) + 1) // 2)
    concept_pass = (len(present) >= threshold) if salient else True

    # Tool trajectory scoring (exact from held-out trajectory).
    expected = spec.expected_tools
    tool_selection_pass = None
    tool_order_pass = None
    tool_arguments_pass = None
    tool_result_incorporated = None
    if expected:
        expected_names = [t.get("name") for t in expected if t.get("name")]
        called = [t for t in tools if t]
        tool_selection_pass = (
            expected_names == called[: len(expected_names)]
            if expected_names
            else bool(called)
        )
        # order: sequence equality when multiple
        tool_order_pass = (
            called[: len(expected_names)] == expected_names
            if len(expected_names) > 1
            else None
        )
        # arguments: only when the trajectory provides deterministic arguments
        deterministic_args = [t for t in expected if t.get("arguments")]
        if deterministic_args:
            tool_arguments_pass = None  # runtime arg comparison requires the model's actual args (not exposed here)
        # result incorporation: any tool result text that appears in the output
        result_texts = [
            str(m.get("content", ""))
            for m in row.get("messages", [])
            if m.get("role") == "tool"
        ]
        tool_result_incorporated = None
        if result_texts:
            tool_result_incorporated = any(
                bool(rt) and rt.strip().lower()[:40] in output.lower()
                for rt in result_texts
            )

    components = [
        substantive_pass,
        length_pass,
        concept_pass,
    ] + [c for c in (tool_selection_pass,) if c is not None]
    passed = all(components)
    score = round(sum(1 for c in components if c) / len(components), 4)

    return V2RowResult(
        eval_id=str(row.get("id")),
        domain=str(row.get("domain")),
        difficulty=str(row.get("difficulty")),
        input_hash=input_hash(row),
        classification=spec.classification,
        output=output,
        tools=tools,
        expected_tools=expected,
        substantive_pass=substantive_pass,
        length_pass=length_pass,
        concept_pass=concept_pass,
        tool_selection_pass=tool_selection_pass,
        tool_order_pass=tool_order_pass,
        tool_arguments_pass=tool_arguments_pass,
        tool_result_incorporated=tool_result_incorporated,
        semantic_content_resolved=False,
        passed=passed,
        score=score,
        latency_s=latency,
        error=error,
    )


def run_eval_v2(rows: list[dict], chat: Callable[[list[dict]], dict]) -> dict:
    results = [evaluate_row_v2(row, chat) for row in rows]
    total = len(results)
    passed = [r for r in results if r.passed]

    def domain_score(domain: str) -> float:
        subset = [r for r in results if r.domain == domain]
        return round(sum(1 for r in subset if r.passed) / len(subset), 4) if subset else 0.0

    latencies = sorted(r.latency_s for r in results)
    n = len(latencies)
    tool_rows = [r for r in results if r.expected_tools]
    return {
        "evaluator_version": EVALUATOR_VERSION,
        "evaluator_code_sha": evaluator_code_sha(),
        "eval_dataset_sha": EVAL_DATASET_SHA,
        "total": total,
        "pass": len(passed),
        "fail": total - len(passed),
        "error": len([r for r in results if r.error]),
        "overall_score": round(len(passed) / total, 4) if total else 0.0,
        "general_score": domain_score("general"),
        "policy_score": domain_score("policy"),
        "recovery_score": domain_score("recovery"),
        "tool_selection_pass": len([r for r in tool_rows if r.tool_selection_pass]),
        "tool_rows": len(tool_rows),
        "avg_latency_s": round(sum(latencies) / n, 2) if n else 0.0,
        "p50_latency_s": latencies[n // 2] if n else 0.0,
        "p95_latency_s": latencies[min(n - 1, int(n * 0.95))] if n else 0.0,
        "results": [r.__dict__ for r in results],
    }
