"""DEFENDcoder context engine + durable checkpoint compaction (P19/P20).

The harness never dumps a whole repository into a prompt. It maintains a
bounded, deterministic run context: RepoMap-style relevant files, current
diff/test state, open failures, and a durable TaskCheckpoint used for safe
compaction and continuation across model escalation / browser reload.

Checkpoints contain structured facts only — never hidden reasoning_content,
never secrets.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

CHECKPOINT_FIELDS = (
    "OBJECTIVE",
    "WORKSPACE",
    "CURRENT_TASK",
    "COMPLETED",
    "CURRENT_FAILURE",
    "RELEVANT_FILES",
    "LATEST_TESTS",
    "ATTEMPTS",
    "CONSTRAINTS",
    "NEXT_ACTION",
    "BRANCH",
    "HEAD",
    "DIRTY_FILES",
    "IDENTITY_VERSION",
    "MODEL_ROUTE",
    "PENDING_APPROVALS",
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class TaskCheckpoint:
    """Durable, structured run checkpoint (no reasoning, no secrets)."""

    objective: str = ""
    workspace: str = ""
    current_task: str = ""
    completed: tuple[str, ...] = ()
    current_failure: str | None = None
    relevant_files: tuple[str, ...] = ()
    latest_tests: tuple[str, ...] = ()
    attempts: int = 0
    constraints: tuple[str, ...] = ()
    next_action: str | None = None
    branch: str | None = None
    head: str | None = None
    dirty_files: tuple[str, ...] = ()
    identity_version: str | None = None
    model_route: str | None = None
    pending_approvals: tuple[str, ...] = ()
    updated_at: datetime = field(default_factory=utc_now)

    def as_public_dict(self) -> dict[str, object]:
        public = asdict(self)
        public["updated_at"] = self.updated_at.isoformat()
        return public


def build_checkpoint(
    *,
    objective: str,
    workspace: str,
    current_task: str = "",
    completed: tuple[str, ...] = (),
    current_failure: str | None = None,
    relevant_files: tuple[str, ...] = (),
    latest_tests: tuple[str, ...] = (),
    attempts: int = 0,
    constraints: tuple[str, ...] = (),
    next_action: str | None = None,
    branch: str | None = None,
    head: str | None = None,
    dirty_files: tuple[str, ...] = (),
    identity_version: str | None = None,
    model_route: str | None = None,
    pending_approvals: tuple[str, ...] = (),
) -> TaskCheckpoint:
    if not objective.strip():
        raise ValueError("checkpoint objective must not be empty")
    if attempts < 0:
        raise ValueError("attempts must be non-negative")
    return TaskCheckpoint(
        objective=objective,
        workspace=workspace,
        current_task=current_task,
        completed=tuple(completed),
        current_failure=current_failure,
        relevant_files=tuple(relevant_files),
        latest_tests=tuple(latest_tests),
        attempts=int(attempts),
        constraints=tuple(constraints),
        next_action=next_action,
        branch=branch,
        head=head,
        dirty_files=tuple(dirty_files),
        identity_version=identity_version,
        model_route=model_route,
        pending_approvals=tuple(pending_approvals),
    )


def checkpoint_to_prompt(checkpoint: TaskCheckpoint) -> str:
    """Deterministic durable-checkpoint block (stable field order)."""
    lines: list[str] = []
    lines.append(f"OBJECTIVE: {checkpoint.objective}")
    if checkpoint.workspace:
        lines.append(f"WORKSPACE: {checkpoint.workspace}")
    lines.append(f"CURRENT_TASK: {checkpoint.current_task or '-'}")
    lines.append(
        "COMPLETED: " + ("; ".join(checkpoint.completed) if checkpoint.completed else "-")
    )
    lines.append(f"CURRENT_FAILURE: {checkpoint.current_failure or '-'}")
    lines.append(
        "RELEVANT_FILES: "
        + ("; ".join(checkpoint.relevant_files) if checkpoint.relevant_files else "-")
    )
    lines.append(
        "LATEST_TESTS: "
        + ("; ".join(checkpoint.latest_tests) if checkpoint.latest_tests else "-")
    )
    lines.append(f"ATTEMPTS: {checkpoint.attempts}")
    lines.append(
        "CONSTRAINTS: "
        + ("; ".join(checkpoint.constraints) if checkpoint.constraints else "-")
    )
    lines.append(f"NEXT_ACTION: {checkpoint.next_action or '-'}")
    if checkpoint.branch:
        lines.append(f"BRANCH: {checkpoint.branch}")
    if checkpoint.head:
        lines.append(f"HEAD: {checkpoint.head}")
    if checkpoint.dirty_files:
        lines.append(
            "DIRTY_FILES: " + "; ".join(checkpoint.dirty_files)
        )
    if checkpoint.identity_version:
        lines.append(f"IDENTITY_VERSION: {checkpoint.identity_version}")
    if checkpoint.model_route:
        lines.append(f"MODEL_ROUTE: {checkpoint.model_route}")
    if checkpoint.pending_approvals:
        lines.append(
            "PENDING_APPROVALS: " + "; ".join(checkpoint.pending_approvals)
        )
    return "\n".join(lines)


@dataclass(frozen=True)
class RunContext:
    """Bounded context bundle fed AFTER the stable identity prefix."""

    checkpoint: TaskCheckpoint
    repo_map: tuple[str, ...] = ()
    recent_tool_results: tuple[str, ...] = ()
    current_diff_summary: str | None = None
    test_state: str | None = None
    open_failures: tuple[str, ...] = ()

    def as_context_text(self) -> str:
        sections: list[str] = []
        if self.repo_map:
            sections.append(
                "[REPO MAP]\n" + "\n".join(self.repo_map)
            )
        if self.recent_tool_results:
            sections.append(
                "[RECENT TOOL RESULTS]\n"
                + "\n".join(self.recent_tool_results)
            )
        if self.current_diff_summary:
            sections.append("[CURRENT DIFF]\n" + self.current_diff_summary)
        if self.test_state:
            sections.append("[TEST STATE]\n" + self.test_state)
        if self.open_failures:
            sections.append(
                "[OPEN FAILURES]\n" + "\n".join(self.open_failures)
            )
        return "\n\n".join(sections)


def compact_run_context(
    run_context: RunContext,
    *,
    max_recent_tool_results: int = 5,
) -> RunContext:
    """Bounded compaction: keep the durable checkpoint + a small recent slice."""
    recent = run_context.recent_tool_results[-max_recent_tool_results:]
    return RunContext(
        checkpoint=run_context.checkpoint,
        repo_map=tuple(run_context.repo_map)[: max_recent_tool_results * 2],
        recent_tool_results=recent,
        current_diff_summary=run_context.current_diff_summary,
        test_state=run_context.test_state,
        open_failures=tuple(run_context.open_failures),
    )


def compose_checkpoint_context(
    checkpoint: TaskCheckpoint,
    run_context: RunContext | None = None,
) -> str:
    """Compose checkpoint + bounded context for the PromptComposer's
    dynamic section (stable prefix stays untouched for provider caching)."""
    from .identity import compose_run_context

    dynamic = run_context.as_context_text() if run_context is not None else ""
    return compose_run_context(
        checkpoint=checkpoint_to_prompt(checkpoint),
        task=dynamic or None,
    )
