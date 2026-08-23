"""DEFEND AI paid-canary run plan + behavioral attempt readiness.

``PaidCanaryRunPlan`` is the immutable run authority (run_id is the source of
truth, never parsed back out of a mutable path). ``PaidCanaryAttemptReadiness``
is the single behavioral authority consulted by the CLI before any provider
mutation. Structural/introspection checks never authorize mutation here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

CANDIDATE_LABEL_PREFIX = "defend-ai-qwen3-canary"


def new_run_id() -> str:
    return uuid.uuid4().hex[:16]


def run_candidate_label(run_id: str) -> str:
    """Server-generated run-scoped candidate identity (never caller-supplied)."""
    return f"{CANDIDATE_LABEL_PREFIX}-{run_id}"


@dataclass(frozen=True)
class PaidCanaryRunPlan:
    """Immutable run authority bound before any provider mutation."""

    run_id: str
    authorized_git_head: str
    trusted_repository_remote: str
    base_repo: str
    base_revision: str
    tokenizer_repo: str
    tokenizer_revision: str
    raw_training_sha256: str
    converted_training_sha256: str
    training_environment_profile: str
    training_environment_hash: str
    image: str
    hourly_cap_usd: Decimal
    total_cap_usd: Decimal
    teardown_reserve_seconds: float
    protocol_version: str
    required_stages: tuple[str, ...] = field(default_factory=tuple)

    @property
    def candidate_label(self) -> str:
        return run_candidate_label(self.run_id)

    @property
    def remote_workspace(self) -> str:
        return f"/workspace/defend-ai-canary/{self.run_id}"

    @property
    def artifact_path(self) -> str:
        return f"{self.remote_workspace}/artifacts/adapter"


@dataclass(frozen=True)
class PaidCanaryAttemptReadiness:
    """The single behavioral authority that gates provider mutation."""

    owner_authorization_valid: bool
    whole_product_isolation: bool
    deployment_profile_authority: bool
    run_plan_valid: bool
    inventory_ready: bool
    zero_cost_behavioral_contract: bool

    @property
    def authorized_to_attempt(self) -> bool:
        return all(
            (
                self.owner_authorization_valid,
                self.whole_product_isolation,
                self.deployment_profile_authority,
                self.run_plan_valid,
                self.inventory_ready,
                self.zero_cost_behavioral_contract,
            )
        )


def build_readiness(
    *,
    owner_authorization: str,
    run_plan: PaidCanaryRunPlan | None,
    inventory_status: str,
    zero_cost_behavioral_contract: bool,
    deployment_profile_authority: bool = True,
    whole_product_isolation: bool = True,
) -> PaidCanaryAttemptReadiness:
    return PaidCanaryAttemptReadiness(
        owner_authorization_valid=(owner_authorization == "M1.9.2D"),
        whole_product_isolation=whole_product_isolation,
        deployment_profile_authority=deployment_profile_authority,
        run_plan_valid=(run_plan is not None and bool(run_plan.authorized_git_head) and bool(run_plan.run_id)),
        inventory_ready=(inventory_status == "NONE_FOUND" or inventory_status == "COMPLETE"),
        zero_cost_behavioral_contract=zero_cost_behavioral_contract,
    )
