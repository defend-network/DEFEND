"""Durable attempt + checkpoint + route-history stores (restart-safe).

AttemptRecord: one per agent repair loop, referencing a checkpoint revision.
Checkpoints: revisioned, immutable snapshots (structured facts only).
Route history: one revision per provider/model change (escalation).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any
from uuid import UUID, uuid4

from psycopg.rows import dict_row

from .db import CoderDatabase

ATTEMPT_STATE_RUNNING = "running"
ATTEMPT_STATE_SUCCEEDED = "succeeded"
ATTEMPT_STATE_FAILED = "failed"
ATTEMPT_STATE_UNKNOWN = "unknown_after_interruption"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class AttemptRecord:
    attempt_id: UUID
    run_id: UUID
    checkpoint_revision: int | None
    summary: str
    failure_class: str | None
    relevant_files: tuple[str, ...]
    test_summary: str | None
    tool_refs: tuple[str, ...]
    state: str


@dataclass(frozen=True)
class CheckpointRecord:
    checkpoint_id: UUID
    run_id: UUID
    revision: int
    objective: str
    current_task: str | None
    completed_work: tuple[str, ...]
    current_failure: str | None
    relevant_files: tuple[str, ...]
    latest_tests: tuple[str, ...]
    constraints: tuple[str, ...]
    next_action: str | None
    branch: str | None
    head: str | None
    dirty_files: tuple[str, ...]
    identity_profile_id: str
    identity_version: str
    identity_hash: str
    prompt_core_id: str
    prompt_core_version: str
    prompt_core_hash: str
    provider: str
    model: str
    technical_profile_id: str
    technical_profile_version: str
    technical_profile_hash: str
    pending_approvals: tuple[str, ...]


class RunAttemptStore:
    def __init__(self, db: CoderDatabase) -> None:
        self._db = db

    def begin(
        self,
        *,
        run_id: UUID,
        checkpoint_revision: int | None,
        summary: str,
        relevant_files: tuple[str, ...] = (),
    ) -> UUID:
        attempt_id = uuid4()
        with self._db.connect() as connection:
            with connection.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO coder_run_attempts(
                        attempt_id, run_id, checkpoint_revision, summary,
                        relevant_files, state
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        attempt_id,
                        run_id,
                        checkpoint_revision,
                        summary,
                        json.dumps(list(relevant_files)),
                        ATTEMPT_STATE_RUNNING,
                    ),
                )
        return attempt_id

    def finish(
        self,
        attempt_id: UUID,
        *,
        state: str,
        failure_class: str | None = None,
        test_summary: str | None = None,
        tool_refs: tuple[str, ...] = (),
    ) -> None:
        with self._db.connect() as connection:
            with connection.cursor() as cur:
                cur.execute(
                    """
                    UPDATE coder_run_attempts
                    SET state = %s, failure_class = %s,
                        test_summary = %s, tool_refs = %s
                    WHERE attempt_id = %s
                    """,
                    (
                        state,
                        failure_class,
                        test_summary,
                        json.dumps(list(tool_refs)),
                        attempt_id,
                    ),
                )

    def list(self, run_id: UUID) -> tuple[AttemptRecord, ...]:
        with self._db.connect() as connection:
            with connection.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT attempt_id, run_id, checkpoint_revision, summary,
                           failure_class, relevant_files, test_summary,
                           tool_refs, state
                    FROM coder_run_attempts
                    WHERE run_id = %s
                    ORDER BY created_at ASC
                    """,
                    (run_id,),
                )
                rows = cur.fetchall()
        return tuple(
            AttemptRecord(
                attempt_id=row["attempt_id"],
                run_id=row["run_id"],
                checkpoint_revision=row["checkpoint_revision"],
                summary=row["summary"],
                failure_class=row["failure_class"],
                relevant_files=tuple(row["relevant_files"] or []),
                test_summary=row["test_summary"],
                tool_refs=tuple(row["tool_refs"] or []),
                state=row["state"],
            )
            for row in rows
        )


class RunCheckpointStore:
    def __init__(self, db: CoderDatabase) -> None:
        self._db = db

    def latest(self, run_id: UUID) -> CheckpointRecord | None:
        with self._db.connect() as connection:
            with connection.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT * FROM coder_run_checkpoints
                    WHERE run_id = %s
                    ORDER BY revision DESC
                    LIMIT 1
                    """,
                    (run_id,),
                )
                row = cur.fetchone()
        return self._row_to_record(row) if row else None

    def revision(self, run_id: UUID, revision: int) -> CheckpointRecord | None:
        with self._db.connect() as connection:
            with connection.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT * FROM coder_run_checkpoints
                    WHERE run_id = %s AND revision = %s
                    """,
                    (run_id, revision),
                )
                row = cur.fetchone()
        return self._row_to_record(row) if row else None

    def write(
        self,
        *,
        run_id: UUID,
        revision: int,
        objective: str,
        identity: tuple[str, str, str],
        prompt_core: tuple[str, str, str],
        provider: str,
        model: str,
        technical: tuple[str, str, str],
        current_task: str | None = None,
        completed_work: tuple[str, ...] = (),
        current_failure: str | None = None,
        relevant_files: tuple[str, ...] = (),
        latest_tests: tuple[str, ...] = (),
        constraints: tuple[str, ...] = (),
        next_action: str | None = None,
        branch: str | None = None,
        head: str | None = None,
        dirty_files: tuple[str, ...] = (),
        pending_approvals: tuple[str, ...] = (),
    ) -> UUID:
        checkpoint_id = uuid4()
        ip_id, ip_version, ip_hash = identity
        pc_id, pc_version, pc_hash = prompt_core
        tp_id, tp_version, tp_hash = technical
        with self._db.connect() as connection:
            with connection.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO coder_run_checkpoints(
                        checkpoint_id, run_id, revision, objective,
                        current_task, completed_work, current_failure,
                        relevant_files, latest_tests, constraints, next_action,
                        branch, head, dirty_files, identity_profile_id,
                        identity_version, identity_hash, prompt_core_id,
                        prompt_core_version, prompt_core_hash, provider, model,
                        technical_profile_id, technical_profile_version,
                        technical_profile_hash, pending_approvals
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s)
                    """,
                    (
                        checkpoint_id,
                        run_id,
                        revision,
                        objective,
                        current_task,
                        json.dumps(list(completed_work)),
                        current_failure,
                        json.dumps(list(relevant_files)),
                        json.dumps(list(latest_tests)),
                        json.dumps(list(constraints)),
                        next_action,
                        branch,
                        head,
                        json.dumps(list(dirty_files)),
                        ip_id,
                        ip_version,
                        ip_hash,
                        pc_id,
                        pc_version,
                        pc_hash,
                        provider,
                        model,
                        tp_id,
                        tp_version,
                        tp_hash,
                        json.dumps(list(pending_approvals)),
                    ),
                )
        return checkpoint_id

    @staticmethod
    def _row_to_record(row: dict[str, Any]) -> CheckpointRecord:
        return CheckpointRecord(
            checkpoint_id=row["checkpoint_id"],
            run_id=row["run_id"],
            revision=row["revision"],
            objective=row["objective"],
            current_task=row["current_task"],
            completed_work=tuple(row["completed_work"] or []),
            current_failure=row["current_failure"],
            relevant_files=tuple(row["relevant_files"] or []),
            latest_tests=tuple(row["latest_tests"] or []),
            constraints=tuple(row["constraints"] or []),
            next_action=row["next_action"],
            branch=row["branch"],
            head=row["head"],
            dirty_files=tuple(row["dirty_files"] or []),
            identity_profile_id=row["identity_profile_id"],
            identity_version=row["identity_version"],
            identity_hash=row["identity_hash"],
            prompt_core_id=row["prompt_core_id"],
            prompt_core_version=row["prompt_core_version"],
            prompt_core_hash=row["prompt_core_hash"],
            provider=row["provider"],
            model=row["model"],
            technical_profile_id=row["technical_profile_id"],
            technical_profile_version=row["technical_profile_version"],
            technical_profile_hash=row["technical_profile_hash"],
            pending_approvals=tuple(row["pending_approvals"] or []),
        )
