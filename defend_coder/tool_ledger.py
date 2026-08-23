"""Durable tool-execution ledger (run-scoped, restart-safe).

Each execution has a server-generated ``execution_id`` UUID; the
provider-generated ``tool_call_id`` is unique only within a run. States:
REQUESTED / RUNNING / SUCCEEDED / FAILED / UNKNOWN_AFTER_INTERRUPTION.

Mutation safety contract:
- SUCCEEDED: never re-execute; deterministic idempotent skip (result_ref).
- FAILED: terminal for that provider call id; retry needs a NEW call id.
- UNKNOWN_AFTER_INTERRUPTION: never auto-execute; owner recovery required.
- REQUESTED/RUNNING from a previous interrupted worker are reconciled to
  UNKNOWN_AFTER_INTERRUPTION at the resume boundary (never blindly re-run).
- The same call id with different tool name/arguments/class FAILS CLOSED.
- ``begin`` is atomic (single transaction, conflict-safe) so two concurrent
  workers for the same (run_id, tool_call_id) never both get authority.
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


class ToolLedgerError(RuntimeError):
    """Base class for ledger policy errors (fail-closed)."""


class ToolAlreadySucceededError(ToolLedgerError):
    """The same (run_id, tool_call_id) already SUCCEEDED; never re-execute."""

    def __init__(self, tool_call_id: str, result_ref: str | None) -> None:
        super().__init__(
            f"tool {tool_call_id!r} already succeeded (durable ledger)"
        )
        self.result_ref = result_ref


class ToolAlreadyFailedError(ToolLedgerError):
    """The same (run_id, tool_call_id) already FAILED; terminal for that call id."""


class ToolRecoveryRequiredError(ToolLedgerError):
    """The mutation is UNKNOWN_AFTER_INTERRUPTION (or stale in-flight) and
    must never be automatically re-executed; owner recovery is required."""


class ToolIdentityMismatchError(ToolLedgerError):
    """The same call id reappeared with different tool name/arguments/class.

    This is a protocol-integrity failure: never reuse, skip, or execute."""


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
        """Atomically claim execution authority for a tool call.

        Returns a freshly created ``execution_id`` ONLY when this call owns a
        NEW execution. Otherwise raises the terminal-state policy error
        (fail-closed). Two concurrent workers for the same call id can never
        both receive execution authority.
        """
        execution_id = uuid4()
        with self._db.connect() as connection:
            with connection.transaction():
                with connection.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        """
                        INSERT INTO coder_tool_executions(
                            execution_id, run_id, tool_call_id, tool_name,
                            argument_hash, mutation_class, state, started_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (run_id, tool_call_id) DO NOTHING
                        RETURNING execution_id
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
                    inserted = cur.fetchone()
                    if inserted is not None:
                        return execution_id
                    # Conflict: load and lock the existing row, then apply
                    # the terminal-state policy (fail-closed) inside the txn.
                    cur.execute(
                        """
                        SELECT tool_name, argument_hash, mutation_class,
                               state, result_ref
                        FROM coder_tool_executions
                        WHERE run_id = %s AND tool_call_id = %s
                        FOR UPDATE
                        """,
                        (run_id, tool_call_id),
                    )
                    existing = cur.fetchone()
        # Outside the transaction (after commit/rollback) apply policy.
        return self._resolve_existing(
            tool_call_id, existing, tool_name, argument_hash, mutation_class
        )

    @staticmethod
    def _resolve_existing(
        tool_call_id: str,
        existing: dict[str, Any] | None,
        tool_name: str,
        argument_hash: str,
        mutation_class: str,
    ) -> UUID:
        if existing is None:
            # Extremely unlikely: the conflicting row vanished. Fail closed.
            raise ToolRecoveryRequiredError(
                f"tool {tool_call_id!r} disappeared during begin"
            )
        # P3: identity integrity — same call id must agree on identity.
        if (
            existing["tool_name"] != tool_name
            or existing["argument_hash"] != argument_hash
            or existing["mutation_class"] != mutation_class
        ):
            raise ToolIdentityMismatchError(
                f"tool {tool_call_id!r} identity mismatch: existing "
                f"{existing['tool_name']}/{existing['argument_hash'][:8]} "
                f"vs incoming {tool_name}/{argument_hash[:8]}"
            )
        state = existing["state"]
        if state == TOOL_STATE_SUCCEEDED:
            raise ToolAlreadySucceededError(
                tool_call_id, existing.get("result_ref")
            )
        if state == TOOL_STATE_FAILED:
            raise ToolAlreadyFailedError(
                f"tool {tool_call_id!r} already failed (terminal); "
                "use a new call id to retry"
            )
        # UNKNOWN / REQUESTED / RUNNING -> ambiguous, never auto-run.
        raise ToolRecoveryRequiredError(
            f"tool {tool_call_id!r} is {state}; recovery required, "
            "not re-executed"
        )

    def recover_interrupted(self, run_id: UUID) -> int:
        """Atomically reconcile stale in-flight mutating executions.

        Any mutating execution left in REQUESTED/RUNNING by a previous
        (interrupted) worker becomes UNKNOWN_AFTER_INTERRUPTION. Called at
        the resume/reconstruction boundary BEFORE the run may execute tools.
        """
        with self._db.connect() as connection:
            with connection.cursor() as cur:
                cur.execute(
                    """
                    UPDATE coder_tool_executions
                    SET state = %s, finished_at = %s
                    WHERE run_id = %s
                      AND mutation_class = %s
                      AND state IN (%s, %s)
                    """,
                    (
                        TOOL_STATE_UNKNOWN,
                        _now(),
                        run_id,
                        MUTATION_CLASS_MUTATING,
                        TOOL_STATE_REQUESTED,
                        TOOL_STATE_RUNNING,
                    ),
                )
                return cur.rowcount

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
