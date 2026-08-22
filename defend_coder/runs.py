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
from .agent_client import (
    AgentChatClient,
    RoutingAgentClient,
)
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
    "awaiting_escalation_approval",
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


@dataclass(frozen=True)
class RunRouting:
    """Per-run model routing (additive; never a process-global)."""

    run_id: UUID
    requested_mode: str = "AUTO"
    selected_tier: str = "DEEPSEEK"
    selected_model: str = "deepseek"
    selected_provider: str | None = None
    route_reason: str | None = None
    escalated_from: str | None = None
    escalation_approved_at: object | None = None
    escalation_approved_by: str | None = None

    def as_public_dict(self) -> dict[str, object]:
        return {
            "requested_mode": self.requested_mode,
            "selected_tier": self.selected_tier,
            "selected_model": self.selected_model,
            "selected_provider": self.selected_provider,
            "route_reason": self.route_reason,
            "escalated_from": self.escalated_from,
            "escalation_approved_at": (
                self.escalation_approved_at.isoformat()
                if self.escalation_approved_at is not None
                else None
            ),
            "escalation_approved_by": self.escalation_approved_by,
        }


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


    def set_run_routing(
        self,
        run_id: UUID,
        *,
        requested_mode: str,
        selected_tier: str,
        selected_model: str,
        selected_provider: str | None,
        route_reason: str | None = None,
        escalated_from: str | None = None,
        escalation_approved_at: object | None = None,
        escalation_approved_by: str | None = None,
    ) -> None:
        """Persist the per-run model routing (additive, never global)."""
        with self._db.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE coder_runs
                    SET requested_mode = %s,
                        selected_tier = %s,
                        selected_model = %s,
                        selected_provider = %s,
                        route_reason = %s,
                        escalated_from = %s,
                        escalation_approved_at = %s,
                        escalation_approved_by = %s
                    WHERE run_id = %s
                    """,
                    (
                        requested_mode,
                        selected_tier,
                        selected_model,
                        selected_provider,
                        route_reason,
                        escalated_from,
                        escalation_approved_at,
                        escalation_approved_by,
                        run_id,
                    ),
                )

    def get_run_routing(self, run_id: UUID) -> RunRouting | None:
        with self._db.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        requested_mode,
                        selected_tier,
                        selected_model,
                        selected_provider,
                        route_reason,
                        escalated_from,
                        escalation_approved_at,
                        escalation_approved_by
                    FROM coder_runs
                    WHERE run_id = %s
                    """,
                    (run_id,),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        return RunRouting(
            run_id=run_id,
            requested_mode=row["requested_mode"],
            selected_tier=row["selected_tier"],
            selected_model=row["selected_model"],
            selected_provider=row["selected_provider"],
            route_reason=row["route_reason"],
            escalated_from=row["escalated_from"],
            escalation_approved_at=row["escalation_approved_at"],
            escalation_approved_by=row["escalation_approved_by"],
        )

    def create_escalation_proposal(
        self,
        run_id: UUID,
        proposal: object,
    ) -> None:
        """Persist a pending EscalationProposal for owner interaction."""
        with self._db.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO coder_escalation_proposals(
                        proposal_id,
                        run_id,
                        from_model,
                        to_model,
                        reason_code,
                        human_summary,
                        evidence,
                        attempt_count,
                        tests_failed,
                        estimated_incremental_cost,
                        target_runtime_state,
                        requires_gpu_resume,
                        status,
                        created_at,
                        expires_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        proposal.proposal_id,
                        run_id,
                        proposal.from_model,
                        proposal.to_model,
                        str(proposal.reason_code.value),
                        proposal.human_summary,
                        Jsonb(list(proposal.evidence)),
                        proposal.attempt_count,
                        proposal.tests_failed,
                        proposal.estimated_incremental_cost,
                        proposal.target_runtime_state,
                        proposal.requires_gpu_resume,
                        "pending",
                        proposal.created_at,
                        proposal.expires_at,
                    ),
                )

    def list_escalation_proposals(
        self,
        run_id: UUID,
    ) -> tuple[dict[str, object], ...]:
        with self._db.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        proposal_id,
                        from_model,
                        to_model,
                        reason_code,
                        human_summary,
                        evidence,
                        attempt_count,
                        tests_failed,
                        estimated_incremental_cost,
                        target_runtime_state,
                        requires_gpu_resume,
                        status,
                        created_at,
                        expires_at,
                        approved_at,
                        approved_by
                    FROM coder_escalation_proposals
                    WHERE run_id = %s
                    ORDER BY created_at DESC
                    """,
                    (run_id,),
                )
                rows = cursor.fetchall()
        proposals: list[dict[str, object]] = []
        for row in rows:
            evidence = row["evidence"] or []
            proposals.append(
                {
                    "proposal_id": row["proposal_id"],
                    "from_model": row["from_model"],
                    "to_model": row["to_model"],
                    "reason_code": row["reason_code"],
                    "human_summary": row["human_summary"],
                    "evidence": list(evidence) if isinstance(evidence, list) else [],
                    "attempt_count": row["attempt_count"],
                    "tests_failed": row["tests_failed"],
                    "estimated_incremental_cost": (
                        row["estimated_incremental_cost"]
                    ),
                    "target_runtime_state": row["target_runtime_state"],
                    "requires_gpu_resume": row["requires_gpu_resume"],
                    "status": row["status"],
                    "created_at": (
                        row["created_at"].isoformat()
                        if row["created_at"] is not None
                        else None
                    ),
                    "expires_at": (
                        row["expires_at"].isoformat()
                        if row["expires_at"] is not None
                        else None
                    ),
                    "approved_at": (
                        row["approved_at"].isoformat()
                        if row["approved_at"] is not None
                        else None
                    ),
                    "approved_by": row["approved_by"],
                }
            )
        return tuple(proposals)

    def update_escalation_proposal_status(
        self,
        run_id: UUID,
        proposal_id: str,
        *,
        status: str,
        approved_by: str | None = None,
        approved_at: object | None = None,
    ) -> bool:
        if status not in ("pending", "approved", "denied", "expired"):
            raise ValueError(f"invalid proposal status {status!r}")
        with self._db.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE coder_escalation_proposals
                    SET status = %s,
                        approved_at = %s,
                        approved_by = %s
                    WHERE run_id = %s AND proposal_id = %s
                    """,
                    (
                        status,
                        approved_at,
                        approved_by,
                        run_id,
                        proposal_id,
                    ),
                )
                return cursor.rowcount == 1


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
        client_resolver: Callable[[object], AgentChatClient] | None = None,
        proposal_factory: Callable[[object, object], object | None] | None = None,
    ) -> None:
        if not isinstance(client, AgentChatClient):
            raise TypeError("client must be an AgentChatClient")
        if not callable(toolkit_factory):
            raise TypeError("toolkit_factory must be callable")
        self._repository = repository
        self._client = client
        self._client_resolver = client_resolver
        self._proposal_factory = proposal_factory
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

    def start_existing(
        self,
        *,
        run_id: UUID,
        workspace: WorkspaceRecord,
        prompt: str,
    ) -> None:
        """Start the worker for an ALREADY-created, ALREADY-routed run.

        Routing is persisted by the caller BEFORE this returns, so the
        worker's per-run client resolution sees the selected backend.
        """
        self._repository.update_run_status(run_id, status="running")
        cancel_event = threading.Event()
        self._cancel_events[run_id] = cancel_event
        thread = threading.Thread(
            target=self._execute,
            args=(run_id, workspace, prompt, cancel_event),
            name=f"coder-run-{run_id}",
            daemon=True,
        )
        thread.start()

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

    def _resolve_client(self, run_id: UUID) -> AgentChatClient:
        """Per-run provider dispatch: the ACTUAL client comes from the
        persisted routing, never a process-global model.

        When a ``client_resolver`` is configured, the run executes through a
        delegating client that re-reads the run's routing before EVERY
        generation call, so an owner-approved escalation changes the real
        provider mid-run (DeepSeek -> Next -> Sol) without restarting.
        """
        if self._client_resolver is None:
            return self._client

        def resolve() -> AgentChatClient:
            routing = self._repository.get_run_routing(run_id)
            return self._client_resolver(routing)

        return RoutingAgentClient(resolve)

    def _execute(
        self,
        run_id: UUID,
        workspace: WorkspaceRecord,
        prompt: str,
        cancel_event: threading.Event,
    ) -> None:
        run_log = RunLog()
        toolkit = self._toolkit_factory(run_log.tail)
        client = self._resolve_client(run_id)
        agent = CodingAgent(
            client=client,
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
            # Quality failure path: a grounded escalation proposal may be
            # created, but it NEVER switches the model or starts compute.
            if self._proposal_factory is not None:
                try:
                    proposal = self._proposal_factory(run_id, outcome)
                except Exception as error:  # noqa: BLE001
                    self._log(
                        f"run {run_id}: proposal evaluation failed: {error!r}"
                    )
                    proposal = None
                if proposal is not None:
                    self._repository.create_escalation_proposal(
                        run_id, proposal
                    )
                    self._repository.update_run_phase(
                        run_id, "awaiting_escalation_approval"
                    )
                    self._repository.append_message(
                        run_id,
                        role="log",
                        content=(
                            "Escalation proposal awaiting owner approval; "
                            "the run did not change models."
                        ),
                        kind="log",
                        ok=True,
                    )
                    self._log(
                        f"run {run_id}: escalation proposal "
                        f"{proposal.proposal_id} awaiting approval"
                    )
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