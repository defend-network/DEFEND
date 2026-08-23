"""Durable tool-execution ledger (run-scoped, restart-safe).

Each execution has a server-generated ``execution_id`` UUID; the
provider-generated ``tool_call_id`` is unique only within a run. States:
REQUESTED / RUNNING / SUCCEEDED / FAILED / UNKNOWN_AFTER_INTERRUPTION.

SUCCEEDED mutations are never automatically re-run after restart. A
RUNNING mutating execution that died is UNKNOWN_AFTER_INTERRUPTION and must
not be blindly repeated.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any
from uuid import UUID, uuid4

from psycopg.rows import dict_row

from .db import CoderDatabase

TOOL_STATE_REQUESTED = "REQUESTED"
TOOL_STATE_RUNNING = "RUNNING"
TOOL_STATE_SUCCEEDED = "SUCCEEDED"
TOOL_STATE_FAILED = "FAILED"
TOOL_STATE_UNKNOWN = "UNKNOWN_AFTER_INTERRUPTION"

MUTATION_CLASS_READ_ONLY = "read_only"
MUTATION_CLASS_MUTATING = "mutating"

#: Tools whose side effects must never be silently re-executed after restart.
MUTATING_TOOLS = frozenset(
    {
        "write_file",
        "edit_file",
        "delete_file",
        "run_tests",
        "run_command",
        "git_commit",
        "git_checkout",
        "git_merge",
        "git_push",
        "apply_patch",
    }
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def mutation_class_for(tool_name: str) -> str:
    return (
        MUTATION_CLASS_MUTATING
        if tool_name in MUTATING_TOOLS
        else MUTATION_CLASS_READ_ONLY
    )


def argument_hash(arguments: dict[str, Any]) -> str:
    canonical = json.dumps(arguments, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ToolExecution:
    execution_id: UUID
    run_id: UUID
    tool_call_id: str
    tool_name: str
    argument_hash: str
    mutation_class: str
    state: str
    result_ref: str | None
    started_at: datetime | None
    finished_at: datetime | None


class ToolAlreadySucceededError(RuntimeError):
    pass


class DurableToolLedger:
    def __init__(self, db: CoderDatabase) -> None:
        self._db = db

    def begin(
        self,
        *,
        run_id: UUID,
        tool_call_id: str,
        tool_name: str,
        argument_hash: str,
        mutation_class: str,
    ) -> UUID:
        existing = self.for_call(run_id, tool_call_id)
        if existing is not None:
            if existing.state == TOOL_STATE_SUCCEEDED:
                # Never auto-re-run a completed mutation after restart.
                raise ToolAlreadySucceededError(
                    f"tool {tool_call_id!r} already succeeded for run {run_id}"
                )
            if existing.state in (TOOL_STATE_RUNNING, TOOL_STATE_REQUESTED):
                # Idempotent: an in-flight execution already exists.
                return existing.execution_id
        execution_id = uuid4()
        with self._db.connect() as connection:
            with connection.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO coder_tool_executions(
                        execution_id, run_id, tool_call_id, tool_name,
                        argument_hash, mutation_class, state, started_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        execution_id,
                        run_id,
                        tool_call_id,
                        tool_name,
                        argument_hash,
                        mutation_class,
                        TOOL_STATE_RUNNING,
                        _now(),
                    ),
                )
        return execution_id

    def finish(
        self,
        execution_id: UUID,
        *,
        state: str,
        result_ref: str | None = None,
    ) -> None:
        with self._db.connect() as connection:
            with connection.cursor() as cur:
                cur.execute(
                    """
                    UPDATE coder_tool_executions
                    SET state = %s, result_ref = %s, finished_at = %s
                    WHERE execution_id = %s
                    """,
                    (state, result_ref, _now(), execution_id),
                )

    def for_call(self, run_id: UUID, tool_call_id: str) -> ToolExecution | None:
        with self._db.connect() as connection:
            with connection.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT execution_id, run_id, tool_call_id, tool_name,
                           argument_hash, mutation_class, state, result_ref,
                           started_at, finished_at
                    FROM coder_tool_executions
                    WHERE run_id = %s AND tool_call_id = %s
                    """,
                    (run_id, tool_call_id),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return ToolExecution(
            execution_id=row["execution_id"],
            run_id=row["run_id"],
            tool_call_id=row["tool_call_id"],
            tool_name=row["tool_name"],
            argument_hash=row["argument_hash"],
            mutation_class=row["mutation_class"],
            state=row["state"],
            result_ref=row["result_ref"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )
