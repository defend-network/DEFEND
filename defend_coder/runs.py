from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import threading
import time
from typing import Any, Callable
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from .agent import CodingAgent, RunLog
from .agent_client import AgentChatClient
from .db import CoderDatabase
from .repositories import WorkspaceRecord
from .telemetry import (
    ModelCallRecord,
    aggregate_model_calls,
    wall_clock_accounting,
)
from .tools import CoderToolkit

_RUN_STATES = frozenset({
    "queued",
    "running",
    "succeeded",
    "partial_success",
    "failed",
    "cancelled",
})
_RUN_TERMINAL = frozenset({
    "succeeded",
    "partial_success",
    "failed",
    "cancelled",
})
_RUN_REASONS = frozenset({
    "unknown",
    "natural_completion",
    "finalized",
    "action_limit",
    "step_limit",  # legacy value, readable but no longer produced
    "wall_clock_limit",
    "model_timeout",
    "model_unavailable",
    "model_error",
    "tool_error",
    "user_cancel",
    "internal_error",
    "invalid_prompt",
})
_RUN_PHASES = frozenset({
    "queued",
    "waiting_for_model",
    "model_generating",
    "executing_tool",
    "waiting_for_model_after_tool",
    "finalizing",
    "completed",
    "failed",
    "cancelled",
})


@dataclass(frozen=True)
class RunRecord:
    run_id: UUID
    workspace_id: UUID
    owner_account_id: UUID
    prompt: str
    status: str
    phase: str
    reason: str
    error: str | None
    created_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True)
class RunMessageRecord:
    message_id: int
    run_id: UUID
    seq: int
    role: str
    content: str | None
    tool_call_id: str | None
    tool_name: str | None
    tool_arguments: dict[str, Any] | list[dict[str, Any]] | None
    tool_result: str | None
    kind: str | None
    ok: bool | None
    created_at: datetime


@dataclass(frozen=True)
class RunDetail:
    run: RunRecord
    messages: tuple[RunMessageRecord, ...]


class RunConflictError(RuntimeError):
    """Another agent run is already active on the same workspace."""


class RunsRepository:
    def __init__(self, db: CoderDatabase) -> None:
        self._db = db

    def create_run(
        self,
        *,
        workspace: WorkspaceRecord,
        prompt: str,
    ) -> RunRecord:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt is required")
        run_id = uuid4()
        with self._db.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO coder_runs(
                        run_id,
                        workspace_id,
                        owner_account_id,
                        prompt,
                        status
                    )
                    VALUES (%s, %s, %s, %s, 'queued')
                    RETURNING
                        run_id,
                        workspace_id,
                        owner_account_id,
                        prompt,
                        status,
                        phase,
                        reason,
                        error,
                        created_at,
                        finished_at
                    """,
                    (
                        run_id,
                        workspace.workspace_id,
                        workspace.owner_account_id,
                        prompt,
                    ),
                )
                return _run(cursor.fetchone())

    def get_active_run_for_workspace(
        self,
        workspace_id: UUID,
    ) -> RunRecord | None:
        with self._db.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        run_id,
                        workspace_id,
                        owner_account_id,
                        prompt,
                        status,
                        phase,
                        reason,
                        error,
                        created_at,
                        finished_at
                    FROM coder_runs
                    WHERE workspace_id = %s
                        AND status IN ('queued', 'running')
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (workspace_id,),
                )
                row = cursor.fetchone()
        return _run(row) if row else None

    def get_run(self, run_id: UUID) -> RunRecord | None:
        with self._db.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        run_id,
                        workspace_id,
                        owner_account_id,
                        prompt,
                        status,
                        phase,
                        reason,
                        error,
                        created_at,
                        finished_at
                    FROM coder_runs
                    WHERE run_id = %s
                    """,
                    (run_id,),
                )
                row = cursor.fetchone()
        return _run(row) if row else None

    def update_run_status(
        self,
        run_id: UUID,
        *,
        status: str,
        error: str | None = None,
        reason: str = "unknown",
    ) -> None:
        if status not in _RUN_STATES:
            raise ValueError(f"invalid run status {status!r}")
        if reason not in _RUN_REASONS:
            raise ValueError(f"invalid run reason {reason!r}")
        with self._db.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE coder_runs
                    SET status = %s,
                        error = %s,
                        reason = %s,
                        finished_at = CASE
                            WHEN %s THEN now()
                            ELSE finished_at
                        END
                    WHERE run_id = %s
                    """,
                    (
                        status,
                        error,
                        reason,
                        status in _RUN_TERMINAL,
                        run_id,
                    ),
                )
                if status in _RUN_TERMINAL:
                    cursor.execute(
                        """
                        UPDATE coder_runs
                        SET phase = CASE
                            WHEN %s = 'succeeded' THEN 'completed'
                            WHEN %s = 'cancelled' THEN 'cancelled'
                            ELSE 'failed'
                        END
                        WHERE run_id = %s
                        """,
                        (status, status, run_id),
                    )

    def update_run_phase(self, run_id: UUID, phase: str) -> None:
        if phase not in _RUN_PHASES:
            raise ValueError(f"invalid run phase {phase!r}")
        with self._db.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE coder_runs
                    SET phase = %s
                    WHERE run_id = %s
                    """,
                    (phase, run_id),
                )

    def list_runs_for_workspace(
        self,
        workspace_id: UUID,
        *,
        limit: int = 50,
    ) -> tuple[RunRecord, ...]:
        limit = max(1, min(int(limit), 200))
        with self._db.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        run_id,
                        workspace_id,
                        owner_account_id,
                        prompt,
                        status,
                        phase,
                        reason,
                        error,
                        created_at,
                        finished_at
                    FROM coder_runs
                    WHERE workspace_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (workspace_id, limit),
                )
                rows = cursor.fetchall()
        return tuple(_run(row) for row in rows)

    def messages_for_run(self, run_id: UUID) -> tuple[RunMessageRecord, ...]:
        with self._db.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        message_id,
                        run_id,
                        seq,
                        role,
                        content,
                        tool_call_id,
                        tool_name,
                        tool_arguments,
                        tool_result,
                        kind,
                        ok,
                        created_at
                    FROM coder_run_messages
                    WHERE run_id = %s
                    ORDER BY seq
                    """,
                    (run_id,),
                )
                rows = cursor.fetchall()
        return tuple(_message(row) for row in rows)

    def append_message(
        self,
        run_id: UUID,
        *,
        role: str,
        content: str | None,
        tool_call_id: str | None = None,
        tool_name: str | None = None,
        tool_arguments: Any = None,
        tool_result: str | None = None,
        kind: str | None = None,
        ok: bool | None = None,
    ) -> None:
        with self._db.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COALESCE(MAX(seq), 0) + 1
                    FROM coder_run_messages
                    WHERE run_id = %s
                    """,
                    (run_id,),
                )
                seq = int(cursor.fetchone()[0])
                cursor.execute(
                    """
                    INSERT INTO coder_run_messages(
                        run_id,
                        seq,
                        role,
                        content,
                        tool_call_id,
                        tool_name,
                        tool_arguments,
                        tool_result,
                        kind,
                        ok
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        run_id,
                        seq,
                        role,
                        content,
                        tool_call_id,
                        tool_name,
                        Jsonb(tool_arguments) if tool_arguments is not None else None,
                        tool_result,
                        kind,
                        ok,
                    ),
                )

    def record_model_call(
        self,
        run_id: UUID,
        record: ModelCallRecord,
    ) -> None:
        with self._db.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO coder_model_calls(
                        run_id,
                        step,
                        phase,
                        started_at,
                        finished_at,
                        input_tokens,
                        output_tokens,
                        total_tokens,
                        finish_reason,
                        max_tokens_requested,
                        tool_calls_requested,
                        assistant_visible_chars,
                        assistant_visible_tokens,
                        context_tokens,
                        remaining_action_budget,
                        request_roundtrip_seconds,
                        generation_seconds,
                        tokens_per_second,
                        error_class
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        run_id,
                        record.step,
                        record.phase,
                        record.started_at,
                        record.finished_at,
                        record.input_tokens,
                        record.output_tokens,
                        record.total_tokens,
                        record.finish_reason,
                        record.max_tokens_requested,
                        record.tool_calls_requested,
                        record.assistant_visible_chars,
                        record.assistant_visible_tokens,
                        record.context_tokens,
                        record.remaining_action_budget,
                        record.request_roundtrip_seconds,
                        record.generation_seconds,
                        record.tokens_per_second,
                        record.error_class,
                    ),
                )

    def model_calls_for_run(
        self,
        run_id: UUID,
    ) -> tuple[ModelCallRecord, ...]:
        with self._db.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        step,
                        phase,
                        started_at,
                        finished_at,
                        request_roundtrip_seconds,
                        input_tokens,
                        output_tokens,
                        total_tokens,
                        finish_reason,
                        max_tokens_requested,
                        tool_calls_requested,
                        assistant_visible_chars,
                        assistant_visible_tokens,
                        context_tokens,
                        remaining_action_budget,
                        generation_seconds,
                        tokens_per_second,
                        error_class
                    FROM coder_model_calls
                    WHERE run_id = %s
                    ORDER BY step, started_at
                    """,
                    (run_id,),
                )
                rows = cursor.fetchall()
        return tuple(_model_call(row) for row in rows)

    def aggregate_model_calls(
        self,
        run_id: UUID,
    ) -> dict[str, object]:
        return aggregate_model_calls(
            list(self.model_calls_for_run(run_id))
        )

    def record_wall_clock_accounting(
        self,
        run_id: UUID,
        accounting: dict[str, object],
    ) -> None:
        with self._db.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE coder_runs
                    SET accounting = %s
                    WHERE run_id = %s
                    """,
                    (Jsonb(accounting), run_id),
                )

    def wall_clock_accounting(
        self,
        run_id: UUID,
        *,
        persistence_seconds: float | None = None,
    ) -> dict[str, object]:
        """Derive the P2B decomposition from persisted timestamps.

        Queue wait: created_at -> first message. Tool execution: each
        assistant message that requested tools to the tool result that
        answered it. Model requests: the client-measured round-trips in
        coder_model_calls. Persistence must be supplied by the runner
        (measured locally); NULL leaves it unattributed.
        """
        with self._db.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        created_at,
                        finished_at
                    FROM coder_runs
                    WHERE run_id = %s
                    """,
                    (run_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    return {}
                created_at, finished_at = row
                cursor.execute(
                    """
                    SELECT created_at
                    FROM coder_run_messages
                    WHERE run_id = %s
                    ORDER BY seq
                    LIMIT 1
                    """,
                    (run_id,),
                )
                first_message = cursor.fetchone()
                cursor.execute(
                    """
                    SELECT
                        created_at,
                        tool_call_id
                    FROM coder_run_messages
                    WHERE run_id = %s
                        AND role = 'assistant'
                        AND tool_arguments IS NOT NULL
                        AND jsonb_typeof(tool_arguments) = 'array'
                        AND jsonb_array_length(tool_arguments) > 0
                    ORDER BY seq
                    """,
                    (run_id,),
                )
                assistant_rows = cursor.fetchall()
                cursor.execute(
                    """
                    SELECT
                        created_at,
                        tool_call_id
                    FROM coder_run_messages
                    WHERE run_id = %s
                        AND role = 'tool'
                    ORDER BY seq
                    """,
                    (run_id,),
                )
                tool_rows = cursor.fetchall()
                cursor.execute(
                    """
                    SELECT COALESCE(SUM(request_roundtrip_seconds), 0.0)
                    FROM coder_model_calls
                    WHERE run_id = %s
                    """,
                    (run_id,),
                )
                roundtrip = float(cursor.fetchone()[0])

        if created_at is None:
            return {}
        now = finished_at or created_at
        total = max(
            0.0,
            (now - created_at).total_seconds(),
        )
        queue_wait = (
            (first_message[0] - created_at).total_seconds()
            if first_message is not None
            else None
        )
        tool_results = {
            str(tool_call_id): tool_time
            for tool_time, tool_call_id in tool_rows
            if tool_call_id is not None
        }
        tool_execution = sum(
            max(
                0.0,
                (
                    tool_results.get(str(call_id), tool_time) - tool_time
                ).total_seconds(),
            )
            for tool_time, call_id in assistant_rows
        )
        return wall_clock_accounting(
            list(self.model_calls_for_run(run_id)),
            run_seconds=total,
            queue_wait_seconds=(
                round(queue_wait, 3) if queue_wait is not None else None
            ),
            tool_execution_seconds=round(tool_execution, 3),
            finalization_seconds=None,
            persistence_seconds=persistence_seconds,
        )


class RunRunner:
    """Owns the worker thread that executes a single agent run."""

    def __init__(
        self,
        *,
        repository: RunsRepository,
        client: AgentChatClient,
        toolkit_factory: Callable[[Callable[[int], str]], CoderToolkit],
        log: Callable[[str], None] | None = None,
        max_steps: int = 12,
        max_loop_seconds: float = 2400.0,
        finalization_enabled: bool = True,
        finalization_timeout_seconds: float = 600.0,
        phase_max_tokens: dict[str, int] | None = None,
    ) -> None:
        if not isinstance(client, AgentChatClient):
            raise TypeError("client must be an AgentChatClient")
        if not callable(toolkit_factory):
            raise TypeError("toolkit_factory must be callable")
        self._repository = repository
        self._client = client
        self._toolkit_factory = toolkit_factory
        self._log = log or (lambda _line: None)
        self._max_steps = max(1, min(100, int(max_steps)))
        self._max_loop_seconds = max(30.0, float(max_loop_seconds))
        self._finalization_enabled = bool(finalization_enabled)
        self._finalization_timeout = max(
            30.0, min(3600.0, float(finalization_timeout_seconds))
        )
        self._cancel_events: dict[UUID, threading.Event] = {}
        self._phase_max_tokens: dict[str, int] | None = phase_max_tokens

    @property
    def policy(self) -> dict[str, object]:
        """Safe, secret-free effective agent policy (P3 diagnostics)."""
        return {
            "max_steps": self._max_steps,
            "max_loop_seconds": self._max_loop_seconds,
            "finalization_enabled": self._finalization_enabled,
            "finalization_timeout_seconds": self._finalization_timeout,
            "model_timeout_seconds": self._client.timeout_seconds,
            "connect_timeout_seconds": self._client.connect_timeout_seconds,
            "max_tokens": self._client.max_tokens,
        }

    def cancel(self, run_id: UUID) -> None:
        """Request cancellation of an active run (honored at step boundaries)."""
        event = self._cancel_events.get(run_id)
        if event is None:
            raise KeyError(f"run {run_id} is not active on this server")
        event.set()

    def start(
        self,
        *,
        workspace: WorkspaceRecord,
        prompt: str,
    ) -> RunRecord:
        active = self._repository.get_active_run_for_workspace(
            workspace.workspace_id
        )
        if active is not None:
            raise RunConflictError(
                "an agent run is already active for this workspace"
            )

        run = self._repository.create_run(
            workspace=workspace,
            prompt=prompt,
        )
        self._repository.update_run_status(run.run_id, status="running")
        cancel_event = threading.Event()
        self._cancel_events[run.run_id] = cancel_event

        thread = threading.Thread(
            target=self._execute,
            args=(run.run_id, workspace, prompt, cancel_event),
            name=f"coder-run-{run.run_id}",
            daemon=True,
        )
        thread.start()
        return run

    def _execute(
        self,
        run_id: UUID,
        workspace: WorkspaceRecord,
        prompt: str,
        cancel_event: threading.Event,
    ) -> None:
        run_log = RunLog()
        toolkit = self._toolkit_factory(run_log.tail)
        agent = CodingAgent(
            client=self._client,
            toolkit=toolkit,
            log=run_log.append,
            max_steps=self._max_steps,
            max_loop_seconds=self._max_loop_seconds,
            finalization_enabled=self._finalization_enabled,
            finalization_timeout_seconds=self._finalization_timeout,
            phase_sink=lambda phase: self._repository.update_run_phase(
                run_id, phase
            ),
            cancelled=cancel_event.is_set,
            telemetry_sink=lambda record: self._repository.record_model_call(
                run_id, record
            ),
            phase_max_tokens=self._phase_max_tokens,
        )
        seq_lock = threading.Lock()
        seq_counter = 0
        persistence_seconds = 0.0
        persistence_lock = threading.Lock()

        def sink(**fields: Any) -> None:
            nonlocal seq_counter, persistence_seconds
            started = time.monotonic()
            with seq_lock:
                seq_counter += 1
            role = fields.get("role") or "log"
            self._repository.append_message(
                run_id,
                role=role,
                content=fields.get("content"),
                tool_call_id=fields.get("tool_call_id"),
                tool_name=fields.get("tool_name"),
                tool_arguments=fields.get("tool_calls"),
                tool_result=fields.get("tool_result"),
                kind=fields.get("kind"),
                ok=fields.get("ok"),
            )
            with persistence_lock:
                persistence_seconds += time.monotonic() - started
            log_line = _format_log_line(fields)
            run_log.append(log_line)
            self._log(f"run {run_id}: {log_line}")

        try:
            outcome = agent.run(
                prompt=prompt,
                account_id=workspace.owner_account_id,
                workspace_id=workspace.workspace_id,
                sink=sink,
            )
        except Exception as error:
            self._log(f"run {run_id}: unexpected failure: {error!r}")
            self._repository.append_message(
                run_id,
                role="log",
                content=(
                    "agent crashed unexpectedly; the run was stopped "
                    "safely."
                ),
                kind="log",
                ok=False,
            )
            self._repository.update_run_status(
                run_id,
                status="failed",
                error="internal agent failure",
                reason="internal_error",
            )
            return
        finally:
            self._cancel_events.pop(run_id, None)

        if outcome.state in ("succeeded", "partial_success"):
            self._repository.update_run_status(
                run_id,
                status=outcome.state,
                error=outcome.error,
                reason=outcome.reason
                or (
                    "natural_completion"
                    if outcome.state == "succeeded"
                    else "action_limit"
                ),
            )
        elif outcome.state == "cancelled":
            self._repository.update_run_status(
                run_id,
                status="cancelled",
                error=outcome.error,
                reason=outcome.reason or "user_cancel",
            )
            self._repository.update_run_phase(run_id, "cancelled")
        else:
            self._repository.update_run_status(
                run_id,
                status="failed",
                error=outcome.error,
                reason=outcome.reason or "internal_error",
            )
        try:
            accounting = self._repository.wall_clock_accounting(
                run_id,
                persistence_seconds=persistence_seconds,
            )
            if accounting:
                self._repository.record_wall_clock_accounting(
                    run_id, accounting
                )
        except Exception as error:  # noqa: BLE001
            self._log(
                f"run {run_id}: wall-clock accounting failed: {error!r}"
            )
        self._log(f"run {run_id}: finished with state {outcome.state}")


def _format_log_line(fields: dict[str, Any]) -> str:
    role = fields.get("role")
    if role == "assistant":
        if fields.get("tool_calls"):
            names = ", ".join(
                str(call.get("name"))
                for call in fields.get("tool_calls", [])
            )
            return f"assistant -> calling: {names}"
        return f"assistant: {fields.get('content') or ''}"
    if role == "tool":
        status = "ok" if fields.get("ok") is not False else "error"
        return (
            f"tool {fields.get('tool_name')} "
            f"({fields.get('kind')}) [{status}]"
        )
    return f"{role}: {fields.get('content') or ''}"


def _run(row) -> RunRecord:
    return RunRecord(*row)


def _message(row) -> RunMessageRecord:
    raw = list(row)
    tool_arguments = raw[7]
    if isinstance(tool_arguments, str):
        try:
            tool_arguments = json.loads(tool_arguments)
        except ValueError:
            tool_arguments = None
    raw[7] = tool_arguments
    return RunMessageRecord(*raw)


def _model_call(row) -> ModelCallRecord:
    return ModelCallRecord(
        step=int(row[0]),
        phase=str(row[1]),
        started_at=row[2],
        finished_at=row[3],
        request_roundtrip_seconds=float(row[4]),
        input_tokens=_optional_int(row[5]),
        output_tokens=_optional_int(row[6]),
        total_tokens=_optional_int(row[7]),
        finish_reason=row[8],
        max_tokens_requested=int(row[9]),
        tool_calls_requested=int(row[10]),
        assistant_visible_chars=int(row[11]),
        assistant_visible_tokens=_optional_int(row[12]),
        context_tokens=_optional_int(row[13]),
        remaining_action_budget=_optional_int(row[14]),
        generation_seconds=_optional_float(row[15]),
        tokens_per_second=_optional_float(row[16]),
        error_class=row[17],
    )


def _optional_int(value) -> int | None:
    return int(value) if value is not None else None


def _optional_float(value) -> float | None:
    return float(value) if value is not None else None