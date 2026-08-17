from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import threading
from typing import Any, Callable
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from .agent import CodingAgent, RunLog
from .agent_client import AgentChatClient
from .db import CoderDatabase
from .repositories import WorkspaceRecord
from .tools import CoderToolkit

_RUN_STATES = frozenset({"queued", "running", "succeeded", "failed"})
_RUN_TERMINAL = frozenset({"succeeded", "failed"})


@dataclass(frozen=True)
class RunRecord:
    run_id: UUID
    workspace_id: UUID
    owner_account_id: UUID
    prompt: str
    status: str
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
    ) -> None:
        if status not in _RUN_STATES:
            raise ValueError(f"invalid run status {status!r}")
        with self._db.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE coder_runs
                    SET status = %s,
                        error = %s,
                        finished_at = CASE
                            WHEN %s THEN now()
                            ELSE finished_at
                        END
                    WHERE run_id = %s
                    """,
                    (
                        status,
                        error,
                        status in _RUN_TERMINAL,
                        run_id,
                    ),
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
    ) -> None:
        if not isinstance(client, AgentChatClient):
            raise TypeError("client must be an AgentChatClient")
        if not callable(toolkit_factory):
            raise TypeError("toolkit_factory must be callable")
        self._repository = repository
        self._client = client
        self._toolkit_factory = toolkit_factory
        self._log = log or (lambda _line: None)
        self._max_steps = max(1, int(max_steps))

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

        thread = threading.Thread(
            target=self._execute,
            args=(run.run_id, workspace, prompt),
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
    ) -> None:
        run_log = RunLog()
        toolkit = self._toolkit_factory(run_log.tail)
        agent = CodingAgent(
            client=self._client,
            toolkit=toolkit,
            log=run_log.append,
            max_steps=self._max_steps,
        )
        seq_lock = threading.Lock()
        seq_counter = 0

        def sink(**fields: Any) -> None:
            nonlocal seq_counter
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
            )
            return

        if outcome.state == "succeeded":
            self._repository.update_run_status(
                run_id,
                status="succeeded",
                error=outcome.error,
            )
        else:
            self._repository.update_run_status(
                run_id,
                status="failed",
                error=outcome.error,
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