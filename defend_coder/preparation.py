"""Atomic run preparation: one transaction persists the run + all pins +
envelope + route-history revision 1 + checkpoint revision 1.

A run only becomes eligible to execute AFTER the transaction commits. Any
failure rolls back everything (no half-prepared queued run).
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any
from uuid import UUID, uuid4

from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row

from .db import CoderDatabase


def prompt_sha256(prompt: str) -> str:
    """Server-derived canonical immutable task identity (browser cannot
    control the trusted hash)."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RunExecutionEnvelope:
    """Persisted, immutable run-authority snapshot (real workspace UUID)."""

    run_id: UUID
    workspace_id: UUID
    owner_account_id: UUID
    requested_mode: str
    selected_tier: str
    provider: str
    model: str
    prompt_sha256: str | None
    identity_profile_id: str
    identity_version: str
    identity_hash: str
    prompt_core_id: str
    prompt_core_version: str
    prompt_core_hash: str
    technical_profile_id: str
    technical_profile_version: str
    technical_profile_hash: str
    initial_checkpoint_revision: int


@dataclass(frozen=True)
class PreparedRun:
    run_id: UUID
    checkpoint_id: UUID


class RunPreparationError(RuntimeError):
    pass


class RunPreparationService:
    def __init__(self, db: CoderDatabase) -> None:
        self._db = db

    def prepare_run(
        self,
        *,
        workspace_id: UUID,
        owner_account_id: UUID,
        prompt: str,
        requested_mode: str,
        selected_tier: str,
        provider: str,
        model: str,
        identity: tuple[str, str, str],
        prompt_core: tuple[str, str, str],
        technical: tuple[str, str, str],
        objective: str | None = None,
        reason: str = "initial",
    ) -> PreparedRun:
        if not isinstance(prompt, str) or not prompt.strip():
            raise RunPreparationError("prompt is required")
        run_id = uuid4()
        checkpoint_id = uuid4()
        ip_id, ip_version, ip_hash = identity
        pc_id, pc_version, pc_hash = prompt_core
        tp_id, tp_version, tp_hash = technical
        objective_text = objective or prompt.strip()
        task_hash = prompt_sha256(prompt)

        with self._db.connect() as connection:
            try:
                with connection.transaction():
                    with connection.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO coder_runs(
                                run_id, workspace_id, owner_account_id, prompt,
                                status, phase, reason, requested_mode,
                                selected_tier, selected_model, selected_provider,
                                route_reason, identity_profile_id,
                                identity_version, identity_hash,
                                prompt_bundle_id, prompt_bundle_version,
                                prompt_bundle_hash
                            )
                            VALUES (%s, %s, %s, %s, 'queued', 'queued', 'unknown',
                                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                run_id,
                                workspace_id,
                                owner_account_id,
                                prompt,
                                requested_mode,
                                selected_tier,
                                model,
                                provider,
                                reason,
                                ip_id,
                                ip_version,
                                ip_hash,
                                pc_id,
                                pc_version,
                                pc_hash,
                            ),
                        )
                        cur.execute(
                            """
                            INSERT INTO coder_run_route_history(
                                run_id, revision, provider, model,
                                technical_profile_id,
                                technical_profile_version,
                                technical_profile_hash, requested_mode, reason
                            )
                            VALUES (%s, 1, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                run_id,
                                provider,
                                model,
                                tp_id,
                                tp_version,
                                tp_hash,
                                requested_mode,
                                reason,
                            ),
                        )
                        cur.execute(
                            """
                            INSERT INTO coder_run_execution_envelopes(
                                run_id, workspace_id, owner_account_id,
                                requested_mode, selected_tier, provider, model,
                                prompt_sha256, identity_profile_id,
                                identity_version, identity_hash, prompt_core_id,
                                prompt_core_version, prompt_core_hash,
                                technical_profile_id,
                                technical_profile_version,
                                technical_profile_hash,
                                initial_checkpoint_revision
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                                    %s, %s, %s, %s, %s, %s, 1)
                            """,
                            (
                                run_id,
                                workspace_id,
                                owner_account_id,
                                requested_mode,
                                selected_tier,
                                provider,
                                model,
                                task_hash,
                                ip_id,
                                ip_version,
                                ip_hash,
                                pc_id,
                                pc_version,
                                pc_hash,
                                tp_id,
                                tp_version,
                                tp_hash,
                            ),
                        )
                        cur.execute(
                            """
                            INSERT INTO coder_run_checkpoints(
                                checkpoint_id, run_id, revision, objective,
                                completed_work, relevant_files, latest_tests,
                                constraints, dirty_files, pending_approvals,
                                identity_profile_id, identity_version,
                                identity_hash, prompt_core_id,
                                prompt_core_version, prompt_core_hash,
                                provider, model, technical_profile_id,
                                technical_profile_version,
                                technical_profile_hash
                            )
                            VALUES (%s, %s, 1, %s, '[]'::jsonb, '[]'::jsonb,
                                    '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                                    '[]'::jsonb, %s, %s, %s, %s, %s, %s, %s, %s,
                                    %s, %s, %s)
                            """,
                            (
                                checkpoint_id,
                                run_id,
                                objective_text,
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
                            ),
                        )
            except UniqueViolation:
                raise RunPreparationError(
                    "another run is already active for this workspace"
                ) from None
        return PreparedRun(run_id=run_id, checkpoint_id=checkpoint_id)

    def load_envelope(self, run_id: UUID) -> RunExecutionEnvelope | None:
        with self._db.connect() as connection:
            with connection.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT run_id, workspace_id, owner_account_id,
                           requested_mode, selected_tier, provider, model,
                           prompt_sha256, identity_profile_id,
                           identity_version, identity_hash, prompt_core_id,
                           prompt_core_version, prompt_core_hash,
                           technical_profile_id, technical_profile_version,
                           technical_profile_hash, initial_checkpoint_revision
                    FROM coder_run_execution_envelopes
                    WHERE run_id = %s
                    """,
                    (run_id,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return RunExecutionEnvelope(
            run_id=row["run_id"],
            workspace_id=row["workspace_id"],
            owner_account_id=row["owner_account_id"],
            requested_mode=row["requested_mode"],
            selected_tier=row["selected_tier"],
            provider=row["provider"],
            model=row["model"],
            prompt_sha256=row["prompt_sha256"],
            identity_profile_id=row["identity_profile_id"],
            identity_version=row["identity_version"],
            identity_hash=row["identity_hash"],
            prompt_core_id=row["prompt_core_id"],
            prompt_core_version=row["prompt_core_version"],
            prompt_core_hash=row["prompt_core_hash"],
            technical_profile_id=row["technical_profile_id"],
            technical_profile_version=row["technical_profile_version"],
            technical_profile_hash=row["technical_profile_hash"],
            initial_checkpoint_revision=row["initial_checkpoint_revision"],
        )
