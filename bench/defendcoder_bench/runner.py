"""Benchmark run execution.

Runs one task end-to-end through the real CodingAgent + CoderToolkit in
a temporary workspace, using an in-memory repository that satisfies the
toolkit's workspace ownership lookups (WorkspaceService only needs
list_workspaces_for_owner).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from uuid import UUID, uuid4

from defend_coder.agent import AgentOutcome, CodingAgent
from defend_coder.repositories import WorkspaceRecord
from defend_coder.telemetry import (
    ModelCallRecord,
    aggregate_model_calls,
    wall_clock_accounting,
)
from defend_coder.tools import CoderToolkit

from .client import ScriptedBenchClient
from .tasks import Task, materialize_workspace


class BenchRepository:
    """In-memory repository satisfying the toolkit's needs (no DB)."""

    def __init__(self, workspace: WorkspaceRecord) -> None:
        self._workspace = workspace

    def list_workspaces_for_owner(
        self,
        account_id: UUID,
    ) -> tuple[WorkspaceRecord, ...]:
        if account_id == self._workspace.owner_account_id:
            return (self._workspace,)
        return ()


@dataclass
class BenchRunResult:
    task: Task
    outcome: AgentOutcome | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    phases: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    workspace: Path | None = None
    error: str | None = None
    generation_tokens: int = 0
    original_hashes: dict[str, str] = field(default_factory=dict)
    original_files: dict[str, str] = field(default_factory=dict)
    expected_error_calls: int = 0
    telemetry: list[ModelCallRecord] = field(default_factory=list)


def run_task(
    task: Task,
    *,
    workspace_root: Path,
    account_id: UUID | None = None,
    owner_account_id: UUID | None = None,
    log: Callable[[str], None] | None = None,
) -> BenchRunResult:
    """Materialize the fixture, run the real agent loop, return results."""
    account_id = account_id or uuid4()
    owner_account_id = owner_account_id or account_id

    workspace = workspace_root / task.id
    workspace.mkdir(parents=True, exist_ok=True)
    original_hashes = materialize_workspace(workspace, task.files)
    original_files: dict[str, str] = dict(task.files)

    record = WorkspaceRecord(
        workspace_id=uuid4(),
        owner_account_id=owner_account_id,
        name=task.id,
        workspace_root=str(workspace.resolve()),
        repository_url=None,
        default_branch=None,
        created_at=None,
        updated_at=None,
    )
    repository = BenchRepository(record)
    toolkit = CoderToolkit(
        repository=repository,
        configured_root=workspace_root.resolve(),
    )
    client = ScriptedBenchClient(task.script)

    events: list[dict[str, Any]] = []
    phases: list[str] = []
    telemetry: list[ModelCallRecord] = []

    agent = CodingAgent(
        client=client,
        toolkit=toolkit,
        log=log or (lambda _line: None),
        max_steps=task.max_steps,
        phase_sink=phases.append,
        telemetry_sink=telemetry.append,
    )

    started = time.monotonic()
    outcome: AgentOutcome | None = None
    error: str | None = None
    try:
        outcome = agent.run(
            prompt=task.prompt,
            account_id=record.owner_account_id,
            workspace_id=record.workspace_id,
            sink=lambda **kw: events.append(kw),
        )
    except Exception as exc:  # noqa: BLE001 - report, do not crash the bench
        error = f"{type(exc).__name__}: {exc}"
    elapsed = time.monotonic() - started

    return BenchRunResult(
        task=task,
        outcome=outcome,
        events=events,
        phases=phases,
        elapsed_seconds=elapsed,
        workspace=workspace,
        error=error,
        generation_tokens=client.generation_tokens,
        original_hashes=original_hashes,
        original_files=original_files,
        expected_error_calls=sum(
            1
            for entry in task.script
            if entry.get("expect_error") and entry.get("tool")
        ),
        telemetry=telemetry,
    )