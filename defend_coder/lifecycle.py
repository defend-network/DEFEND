"""Single authoritative run lifecycle / reconstruction authority.

Owns the full start/resume flow in exactly this order:

    RECONCILE -> EVALUATE RECOVERY -> VALIDATE AUTHORITY ->
    CLAIM WORKSPACE EXECUTION -> TRANSITION STATE -> DISPATCH WORKER

If any step fails, NO worker starts and NO provider/model/tool call occurs.
Reconciliation happens BEFORE authorization, so a mutation that reconciliation
transitions to UNKNOWN_AFTER_INTERRUPTION always blocks the run (never a
worker that continues past a just-created UNKNOWN).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from .preparation import prompt_sha256
from .tool_ledger import (
    MUTATION_CLASS_MUTATING,
    TOOL_STATE_UNKNOWN,
)


class RunLifecycleError(RuntimeError):
    pass


class RunConflictError(RunLifecycleError):
    pass


class RecoveryRequiredError(RunLifecycleError):
    pass


class NotResumableError(RunLifecycleError):
    pass


class EnvelopeValidationError(RunLifecycleError):
    pass


@dataclass(frozen=True)
class LifecycleResult:
    run_id: UUID
    recovered: int
    resumed: bool


class RunLifecycleService:
    """Central resume/reconstruction coordinator."""

    def __init__(
        self,
        *,
        runs: object,
        preparation: object,
        tool_ledger: object | None = None,
        runner: object | None = None,
    ) -> None:
        self._runs = runs
        self._preparation = preparation
        self._tool_ledger = tool_ledger
        self._runner = runner

    def unresolved_mutations(self, run_id: UUID) -> tuple[object, ...]:
        if self._tool_ledger is None:
            return ()
        return tuple(
            e
            for e in self._tool_ledger.list_for_run(run_id)
            if e.state == TOOL_STATE_UNKNOWN
            and e.mutation_class == MUTATION_CLASS_MUTATING
        )

    def start(
        self,
        *,
        run_id: UUID,
        workspace: object,
        account_id: UUID,
        prompt_override: str | None = None,
        allow_resume: bool = True,
    ) -> LifecycleResult:
        run = self._runs.get_run(run_id)
        if run is None:
            raise RunLifecycleError("run not found")

        # 1. Authorization: workspace + owner binding.
        if str(run.workspace_id) != str(workspace.workspace_id):
            raise EnvelopeValidationError("workspace mismatch")
        if str(run.owner_account_id) != str(account_id):
            raise EnvelopeValidationError("owner mismatch")

        # 2. RECONCILE FIRST (before any authorization).
        recovered = 0
        if self._tool_ledger is not None:
            recovered = self._tool_ledger.recover_interrupted(run_id)

        # 3. EVALUATE RECOVERY STATE. A just-created or pre-existing UNKNOWN
        #    mutation blocks all execution paths.
        unresolved = self.unresolved_mutations(run_id)
        if unresolved:
            raise RecoveryRequiredError(
                f"{len(unresolved)} unresolved mutation(s) require recovery"
            )

        # 4. VALIDATE RESUMPTION STATE MACHINE.
        live = (
            self._runner is not None and self._runner.is_active(run_id)
        )
        resumed = self._validate_resumable(run, live, allow_resume)

        # 5. VALIDATE IMMUTABLE ENVELOPE.
        envelope = self._preparation.load_envelope(run_id)
        if envelope is None:
            raise EnvelopeValidationError("missing execution envelope")
        self._validate_envelope(
            envelope, run, workspace, account_id, prompt_override
        )

        # 6. CLAIM exclusive workspace execution authority (atomic). The
        #    database partial-unique index rejects a second active run.
        try:
            self._runs.claim_active(run_id)
        except RunConflictError:
            raise
        except Exception as error:  # noqa: BLE001
            raise RunConflictError(
                f"another run is already active for this workspace: {error!r}"
            ) from None

        # 7. DISPATCH worker.
        if self._runner is not None:
            self._runner.start_existing(
                run_id=run_id,
                workspace=workspace,
                prompt=prompt_override or run.prompt,
            )
        return LifecycleResult(run_id=run_id, recovered=recovered, resumed=resumed)

    def _validate_resumable(self, run: object, live: bool, allow_resume: bool) -> bool:
        status = run.status
        if live:
            # A genuinely live worker already holds the run.
            raise RunConflictError("run already has a live worker")
        if status in ("queued", "running"):
            # Persisted active state with no live worker: explicit
            # reconstruction is the only valid path (this IS that path).
            return True
        if status in ("succeeded", "cancelled"):
            raise NotResumableError(f"run is {status}; not resumable")
        if status in ("failed", "partial_success"):
            if not allow_resume:
                raise NotResumableError(f"run is {status}; resume not allowed")
            return True
        raise NotResumableError(f"run status {status!r} is not resumable")

    def _validate_envelope(
        self,
        envelope: object,
        run: object,
        workspace: object,
        account_id: UUID,
        prompt_override: str | None,
    ) -> None:
        if str(envelope.workspace_id) != str(workspace.workspace_id):
            raise EnvelopeValidationError("envelope workspace mismatch")
        if str(envelope.owner_account_id) != str(account_id):
            raise EnvelopeValidationError("envelope owner mismatch")
        # Immutable task identity: persisted prompt must match envelope hash.
        expected_prompt = prompt_override or run.prompt
        if envelope.prompt_sha256 is not None:
            if prompt_sha256(expected_prompt) != envelope.prompt_sha256:
                raise EnvelopeValidationError("prompt hash mismatch")
        elif prompt_override is not None and prompt_override != run.prompt:
            raise EnvelopeValidationError(
                "caller-supplied prompt does not match historical run prompt"
            )
