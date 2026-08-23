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


def _message_payload(message: Mapping[str, Any]) -> str:
    """Serialized payload actually sent to a provider for one message.

    Includes tool-call names + arguments (assistant) and tool results (tool
    role), so a giant apply_patch/run_command argument is never counted as
    ~zero merely because ``content`` is empty.
    """
    parts: list[str] = []
    content = message.get("content")
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, Mapping) and part.get("text"):
                parts.append(str(part["text"]))
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        for call in tool_calls:
            if isinstance(call, Mapping):
                fn = call.get("function") if isinstance(call.get("function"), Mapping) else {}
                parts.append(str(fn.get("name", "")))
                parts.append(str(fn.get("arguments", "")))
    if message.get("role") == "tool":
        parts.append(str(message.get("tool_call_id", "")))
    return "\n".join(parts)


def _estimate_tokens(messages: Iterable[Mapping[str, Any]]) -> int:
    """Deterministic conservative token estimate (char/4, no tokenizer)."""
    total = 0
    for message in messages:
        if isinstance(message, Mapping):
            total += max(1, len(_message_payload(message)) // 4)
        else:
            total += max(1, len(str(message)) // 4)
    return total


def estimate_tool_schemas(tools: Iterable[Any]) -> int:
    """Approximate request cost of the tool schema block (repeated per call)."""
    import json

    total = 0
    for tool in tools:
        try:
            total += max(1, len(json.dumps(tool, sort_keys=True, default=str)) // 4)
        except Exception:  # noqa: BLE001
            total += max(1, len(str(tool)) // 4)
    return total


@dataclass(frozen=True)
class ContextBudgetConfig:
    """Per-provider/model context contract (configured, not measured)."""

    context_window_tokens: int
    output_reserve_tokens: int = 8192
    protocol_reserve_tokens: int = 512
    compaction_ratio: float = 0.8
    measured: bool = False


#: Conservative configured context windows (NOT measured per provider).
_CONTEXT_WINDOW_TOKENS: dict[str, int] = {
    "deepseek": 131_072,
    "self_hosted": 131_072,
    "openai": 200_000,
}
_DEFAULT_CONTEXT_WINDOW_TOKENS = 131_072


def resolve_context_budget(
    provider: str,
    model: str | None = None,
    *,
    output_reserve_tokens: int = 8192,
) -> ContextBudgetManager:
    window = _CONTEXT_WINDOW_TOKENS.get(
        (provider or "").lower(), _DEFAULT_CONTEXT_WINDOW_TOKENS
    )
    return ContextBudgetManager(
        limit_tokens=window,
        output_reserve_tokens=output_reserve_tokens,
        protocol_reserve_tokens=512,
        compaction_ratio=0.8,
        measured=False,
    )


@dataclass(frozen=True)
class ContextBudgetDecision:
    """Outcome of a budget check: run, compact, or hard-fail."""

    allow: bool
    estimated_tokens: int
    limit_tokens: int
    compact: bool = False
    hard_overflow: bool = False


class ContextBudgetManager:
    """Bounded context budget with protocol-safe compaction triggers.

    Budgets are conservative estimates (char/4 + tool args/results/schemas +
    output reserve) — they bound the request, never a provider-reported truth.
    Compaction applies only to dynamic run context; the stable authority
    prefix is never compacted (it is not part of the conversation queue).
    """

    def __init__(
        self,
        *,
        limit_tokens: int,
        reserve_tokens: int = 0,
        output_reserve_tokens: int = 0,
        protocol_reserve_tokens: int = 0,
        compaction_ratio: float = 0.8,
        measured: bool = False,
    ) -> None:
        if limit_tokens < 1:
            raise ValueError("limit_tokens must be positive")
        self._limit = int(limit_tokens)
        self._reserve = int(reserve_tokens)
        self._output_reserve = int(output_reserve_tokens)
        self._protocol_reserve = int(protocol_reserve_tokens)
        self._ratio = float(compaction_ratio)
        self._measured = bool(measured)

    @property
    def limit_tokens(self) -> int:
        return self._limit

    @property
    def measured(self) -> bool:
        return self._measured

    def estimate(self, messages: Iterable[Mapping[str, Any]]) -> int:
        return _estimate_tokens(messages)

    def decide(
        self,
        messages: Iterable[Mapping[str, Any]],
        *,
        tools: Iterable[Any] = (),
        output_tokens: int = 0,
        incoming_tokens: int = 0,
    ) -> ContextBudgetDecision:
        estimated = (
            self.estimate(messages)
            + estimate_tool_schemas(tools)
            + max(0, int(output_tokens))
            + self._protocol_reserve
            + max(0, incoming_tokens)
        )
        available = self._limit - self._reserve
        if estimated > available:
            return ContextBudgetDecision(
                allow=False,
                estimated_tokens=estimated,
                limit_tokens=self._limit,
                compact=True,
                hard_overflow=True,
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

    An assistant tool-call turn plus all of its tool results form an ATOMIC
    protocol block: compaction never splits a block, and never compacts while
    a tool round is pending.
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
        self._pending_tool_results = 0

    @property
    def checkpoint(self) -> TaskCheckpoint:
        return self._checkpoint

    @property
    def budget(self) -> ContextBudgetManager:
        return self._budget

    @property
    def pending_tool_round(self) -> bool:
        return self._pending_tool_results > 0

    def events(self) -> tuple[StructuredEvent, ...]:
        return tuple(self._events)

    def emit(self, kind: str, **detail: Any) -> None:
        self._events.append(StructuredEvent(kind=kind, detail=dict(detail)))

    def add(self, message: Mapping[str, Any]) -> None:
        role = message.get("role")
        if role == "assistant":
            tool_calls = message.get("tool_calls") or []
            self._pending_tool_results += len(tool_calls)
        elif role == "tool":
            self._pending_tool_results = max(0, self._pending_tool_results - 1)
        self._conversation.append(dict(message))

    def conversation(self) -> list[dict[str, Any]]:
        return list(self._conversation)

    def update_checkpoint(self, checkpoint: TaskCheckpoint) -> None:
        self._checkpoint = checkpoint

    def _safe_cut(self) -> int:
        """Index of the first message that must be retained (never split a
        protocol block, never compact a pending tool round)."""
        items = list(self._conversation)
        n = len(items)
        if n <= 2:
            return 0
        if self._pending_tool_results > 0:
            # Keep the opening assistant tool-call turn of the pending round.
            for i in range(n - 1, -1, -1):
                if (
                    items[i].get("role") == "assistant"
                    and items[i].get("tool_calls")
                ):
                    return i
            return 0
        keep = max(2, self._max_messages // 2)
        cut = max(0, n - keep)
        while cut < n and items[cut].get("role") == "tool":
            cut += 1
        return cut

    def compact(self) -> None:
        """Protocol-safe compaction of dynamic context only.

        The durable checkpoint must be persisted by the caller BEFORE this
        call (checkpoint-before-drop). This only drops stale, COMPLETE
        protocol blocks and never the stable authority prefix (which is not
        in this queue).
        """
        cut = self._safe_cut()
        for _ in range(cut):
            self._conversation.popleft()
        self.emit("context_compacted", messages_retained=len(self._conversation))
