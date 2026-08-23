"""DEFENDcoder context engine + durable checkpoint compaction (P19/P20).

The harness never dumps a whole repository into a prompt. It maintains a
bounded, deterministic run context: RepoMap-style relevant files, current
diff/test state, open failures, and a durable TaskCheckpoint used for safe
compaction and continuation across model escalation / browser reload.

Checkpoints contain structured facts only — never hidden reasoning_content,
never secrets.
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

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


def _estimate_tokens(messages: Iterable[Mapping[str, Any]]) -> int:
    """Deterministic token estimate (char/4 heuristic, no tokenizer)."""
    total = 0
    for message in messages:
        text = ""
        if isinstance(message, Mapping):
            content = message.get("content")
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                text = " ".join(
                    part.get("text", "")
                    for part in content
                    if isinstance(part, Mapping)
                )
        total += max(1, len(text) // 4)
    return total


@dataclass(frozen=True)
class ContextBudgetDecision:
    """Outcome of a budget check: run as-is, or compact first."""

    allow: bool
    estimated_tokens: int
    limit_tokens: int
    compact: bool = False


class ContextBudgetManager:
    """Bounded context budget with protocol-safe compaction triggers.

    Budgets are estimates only (char/4) — they bound the conversation, never
    a provider-reported truth. Compaction folds the durable checkpoint into a
    single system-adjacent message and drops stale tool chatter; it never
    rewrites the stable authority prefix.
    """

    def __init__(
        self,
        *,
        limit_tokens: int,
        reserve_tokens: int = 0,
        compaction_ratio: float = 0.8,
    ) -> None:
        if limit_tokens < 1:
            raise ValueError("limit_tokens must be positive")
        self._limit = int(limit_tokens)
        self._reserve = int(reserve_tokens)
        self._ratio = float(compaction_ratio)

    @property
    def limit_tokens(self) -> int:
        return self._limit

    def estimate(self, messages: Iterable[Mapping[str, Any]]) -> int:
        return _estimate_tokens(messages)

    def decide(
        self,
        messages: Iterable[Mapping[str, Any]],
        incoming_tokens: int = 0,
    ) -> ContextBudgetDecision:
        estimated = self.estimate(messages) + max(0, incoming_tokens)
        available = self._limit - self._reserve
        if estimated > available:
            return ContextBudgetDecision(
                allow=False,
                estimated_tokens=estimated,
                limit_tokens=self._limit,
                compact=True,
            )
        if estimated > int(self._limit * self._ratio):
            return ContextBudgetDecision(
                allow=True,
                estimated_tokens=estimated,
                limit_tokens=self._limit,
                compact=True,
            )
        return ContextBudgetDecision(
            allow=True,
            estimated_tokens=estimated,
            limit_tokens=self._limit,
        )


@dataclass(frozen=True)
class StructuredEvent:
    kind: str
    detail: Mapping[str, Any] = field(default_factory=dict)


class RunContextCoordinator:
    """Owns the bounded conversation queue + budget + durable checkpoint.

    The coordinator never dumps a whole repository; it maintains a bounded
    conversation and folds durable progress into the checkpoint before
    compaction. It emits structured events (no hidden reasoning, no secrets).
    """

    def __init__(
        self,
        *,
        checkpoint: TaskCheckpoint,
        budget: ContextBudgetManager,
        max_conversation_messages: int = 24,
    ) -> None:
        self._checkpoint = checkpoint
        self._budget = budget
        self._max_messages = int(max_conversation_messages)
        self._conversation: deque[dict[str, Any]] = deque()
        self._events: list[StructuredEvent] = []

    @property
    def checkpoint(self) -> TaskCheckpoint:
        return self._checkpoint

    @property
    def budget(self) -> ContextBudgetManager:
        return self._budget

    def events(self) -> tuple[StructuredEvent, ...]:
        return tuple(self._events)

    def emit(self, kind: str, **detail: Any) -> None:
        self._events.append(StructuredEvent(kind=kind, detail=dict(detail)))

    def add(self, message: Mapping[str, Any]) -> None:
        self._conversation.append(dict(message))
        while len(self._conversation) > self._max_messages:
            self._conversation.popleft()

    def conversation(self) -> list[dict[str, Any]]:
        return list(self._conversation)

    def update_checkpoint(self, checkpoint: TaskCheckpoint) -> None:
        self._checkpoint = checkpoint

    def compact(self) -> None:
        """Protocol-safe compaction: fold progress into the checkpoint and
        keep only a bounded recent slice of the conversation. The stable
        authority prefix is never part of this conversation queue, so it is
        never rewritten here."""
        self._checkpoint = TaskCheckpoint(
            objective=self._checkpoint.objective,
            workspace=self._checkpoint.workspace,
            current_task=self._checkpoint.current_task,
            completed=self._checkpoint.completed,
            current_failure=self._checkpoint.current_failure,
            relevant_files=self._checkpoint.relevant_files,
            latest_tests=self._checkpoint.latest_tests,
            attempts=self._checkpoint.attempts,
            constraints=self._checkpoint.constraints,
            next_action=self._checkpoint.next_action,
            branch=self._checkpoint.branch,
            head=self._checkpoint.head,
            dirty_files=self._checkpoint.dirty_files,
            identity_version=self._checkpoint.identity_version,
            model_route=self._checkpoint.model_route,
            pending_approvals=self._checkpoint.pending_approvals,
        )
        keep = max(2, self._max_messages // 2)
        while len(self._conversation) > keep:
            self._conversation.popleft()
        self.emit("context_compacted", messages_retained=len(self._conversation))
