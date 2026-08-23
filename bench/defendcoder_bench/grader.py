"""Benchmark scoring (P6-P9).

Quality gates (P9) per task:
- gate_completed: the agent finished with a terminal non-failure state
- gate_reason: the terminal reason is a clean completion
- gate_files: every expected file exists and contains the required text
- gate_forbidden: every protected file is byte-identical to the fixture
- gate_inspect: all required tokens appear in the final assistant text
- gate_no_errors: no tool call returned an error

Tool-efficiency metrics (P8): total calls, duplicates (same tool+args
seen before), no-progress calls (consecutive identical), recovery calls
(immediately after an error), useful calls (ok and not a duplicate).

Targeted-edit vs full-rewrite rate (P7): a write/edit to an existing
file counts as a targeted edit when >=50% of its lines also existed in
the original file; otherwise it is a full rewrite.
"""

from __future__ import annotations

import difflib
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .runner import BenchRunResult


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

_FINAL_STATES = frozenset({"succeeded", "succeeded_with_warnings"})
_CLEAN_REASONS = frozenset({"natural_completion", "finalized"})
_EDIT_TOOLS = frozenset({"write_file", "edit_file"})


@dataclass
class TaskScore:
    task_id: str
    task_class: str
    outcome_state: str | None
    reason: str | None
    steps: int
    phases: list[str] = field(default_factory=list)
    gates: dict[str, bool] = field(default_factory=dict)
    passed: bool = False
    failures: list[str] = field(default_factory=list)
    total_tool_calls: int = 0
    unique_tools: int = 0
    duplicate_calls: int = 0
    no_progress_calls: int = 0
    recovery_calls: int = 0
    useful_calls: int = 0
    error_calls: int = 0
    targeted_edits: int = 0
    full_rewrites: int = 0
    generation_tokens: int = 0
    elapsed_seconds: float = 0.0


def _final_assistant_text(events: list[dict[str, Any]]) -> str:
    parts = [
        str(event.get("content") or "")
        for event in events
        if event.get("role") == "assistant" and event.get("content")
    ]
    return "\n".join(parts)


def _event_lines(event: dict[str, Any], workspace: Path) -> str:
    content = str(event.get("content") or "")
    tool_result = str(event.get("tool_result") or "")
    if event.get("role") == "tool":
        return tool_result
    if content:
        return content
    return ""


def _is_targeted_edit(
    event: dict[str, Any],
    original_files: dict[str, str],
    workspace: Path,
) -> bool:
    """Classify a file write against the pre-run state (P7).

    Compares the final file on disk against the fixture original: a
    targeted edit preserves at least half of the original lines.
    Newly created files are neither targeted edits nor rewrites.
    """
    arguments = event.get("tool_arguments") or {}
    relative = str(arguments.get("path") or "")
    if not relative:
        return True
    original = original_files.get(relative)
    if original is None:
        return True
    target = workspace / relative
    if not target.is_file():
        return False
    final = target.read_text(encoding="utf-8")
    if final == original:
        return True
    old_lines = original.splitlines()
    final_lines = final.splitlines()
    if not old_lines:
        return False
    kept = sum(
        1
        for line in old_lines
        if line in final_lines
    )
    return kept / len(old_lines) >= 0.5


def score_task(
    result: BenchRunResult,
    *,
    original_hashes: dict[str, str],
    original_files: dict[str, str] | None = None,
) -> TaskScore:
    task = result.task
    gates: dict[str, bool] = {
        "gate_completed": bool(
            result.outcome
            and result.outcome.state in _FINAL_STATES
        ),
        "gate_reason": bool(
            result.outcome and result.outcome.reason in _CLEAN_REASONS
        ),
        "gate_no_errors": bool(result.error is None),
    }

    workspace = result.workspace
    assert workspace is not None

    gates["gate_files"] = True
    for relative, required in task.expected.items():
        target = workspace / relative
        if not target.is_file():
            gates["gate_files"] = False
            break
        content = target.read_text(encoding="utf-8")
        if not all(token in content for token in required):
            gates["gate_files"] = False
            break

    gates["gate_forbidden"] = True
    for relative in task.forbidden:
        target = workspace / relative
        current = (
            target.read_text(encoding="utf-8")
            if target.is_file()
            else None
        )
        expected = original_hashes.get(relative)
        if current is None or expected is None:
            gates["gate_forbidden"] = False
            break

        if _content_hash(current) != expected:
            gates["gate_forbidden"] = False
            break

    original_files = original_files or result.original_files

    final_text = _final_assistant_text(result.events)
    gates["gate_inspect"] = all(
        token in final_text for token in task.inspect_required
    )

    error_calls = sum(
        1 for event in result.events if event.get("ok") is False
    )
    if error_calls > result.expected_error_calls:
        gates["gate_no_errors"] = False

    passed = all(gates.values())
    failures = [
        name.replace("gate_", "") for name, ok in gates.items() if not ok
    ]

    tool_events = [
        event
        for event in result.events
        if event.get("role") == "tool"
    ]
    seen: set[tuple[str, str]] = set()
    previous_key: tuple[str, str] | None = None
    duplicate_calls = 0
    no_progress_calls = 0
    recovery_calls = 0
    useful_calls = 0
    targeted_edits = 0
    full_rewrites = 0

    for index, event in enumerate(tool_events):
        name = str(event.get("tool_name") or "")
        arguments = event.get("tool_arguments") or {}
        key = (name, _arguments_key(arguments))
        is_duplicate = key in seen
        if is_duplicate:
            duplicate_calls += 1
        else:
            seen.add(key)
        if key == previous_key:
            no_progress_calls += 1
        previous_key = key
        ok = event.get("ok") is True
        if ok and not is_duplicate:
            useful_calls += 1
        if not ok and index + 1 < len(tool_events):
            recovery_calls += 1
        if ok and name in _EDIT_TOOLS:
            relative = str(
                (event.get("tool_arguments") or {}).get("path") or ""
            )
            if relative in original_files:
                if _is_targeted_edit(
                    event, original_files, workspace
                ):
                    targeted_edits += 1
                else:
                    full_rewrites += 1

    unique_tools = len(
        {str(event.get("tool_name") or "") for event in tool_events}
    )

    return TaskScore(
        task_id=task.id,
        task_class=task.task_class,
        outcome_state=(
            result.outcome.state if result.outcome else None
        ),
        reason=result.outcome.reason if result.outcome else None,
        steps=result.outcome.steps if result.outcome else 0,
        phases=result.phases,
        gates=gates,
        passed=passed,
        failures=failures,
        total_tool_calls=len(tool_events),
        unique_tools=unique_tools,
        duplicate_calls=duplicate_calls,
        no_progress_calls=no_progress_calls,
        recovery_calls=recovery_calls,
        useful_calls=useful_calls,
        error_calls=error_calls,
        targeted_edits=targeted_edits,
        full_rewrites=full_rewrites,
        generation_tokens=result.generation_tokens,
        elapsed_seconds=result.elapsed_seconds,
    )


def _arguments_key(arguments: dict[str, Any]) -> str:
    return repr(sorted((key, str(value)) for key, value in arguments.items()))