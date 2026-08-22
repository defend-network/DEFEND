"""DEFENDcoder three-tier intelligence router and owner escalation.

Product identity is ALWAYS ``DEFENDcoder``; the underlying model is an
implementation detail that changes without touching identity.

Tiers
-----
TIER_1 / DEEPSEEK   - configured external coding backend; default for new runs.
TIER_2 / NEXT       - self-hosted ``defendcoder-heavy``
                      (``Qwen/Qwen3-Coder-Next``). Normally STOPPED_RETAINED
                      until the owner approves a resume; never auto-rented.
TIER_3 / SOL        - frontier ``gpt-5.6-sol``. Used only after Next has
                      materially failed, an objective verifier requests it, or
                      the owner explicitly escalates.

Rules enforced here (pure logic, no I/O)
----------------------------------------
* New sessions default to DEEPSEEK (AUTO route).
* An ``EscalationProposal`` is created from objective evidence; it NEVER
  switches the model by itself.
* No compute starts (GPU resume or token spend) without owner approval.
* Transient infrastructure failures (timeout / 429 / provider 5xx / bad
  network / tool-server failure) are NEVER escalation evidence.
* Explicit model selection is sticky for the run.
* Switching models never changes tool permissions: this module never
  constructs or exposes a CoderToolkit and never grants repository
  authority; that boundary stays server-authoritative in the run layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Literal

# Canonical model/tier identity (product-visible, not provider-specific).
PRODUCT_IDENTITY = "DEFENDcoder"

TIER_1_MODEL = "deepseek"
NEXT_ALIAS = "defendcoder-heavy"
NEXT_MODEL = "Qwen/Qwen3-Coder-Next"
SOL_MODEL = "gpt-5.6-sol"

#: Next's normal resting state: the provider instance is preserved and only
#: resumed on owner approval. It is never auto-destroyed.
NEXT_REST_STATE = "STOPPED_RETAINED"

DEFAULT_ESCAPE_MINUTES = 15


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EscalationReason(str, Enum):
    REPEATED_TEST_FAILURE = "REPEATED_TEST_FAILURE"
    REPEATED_INVALID_PATCH = "REPEATED_INVALID_PATCH"
    ARCHITECTURE_COMPLEXITY = "ARCHITECTURE_COMPLEXITY"
    MODEL_REQUESTED_ESCALATION = "MODEL_REQUESTED_ESCALATION"
    VERIFIER_REQUESTED_ESCALATION = "VERIFIER_REQUESTED_ESCALATION"
    OWNER_REQUESTED = "OWNER_REQUESTED"
    CONTEXT_COMPLEXITY = "CONTEXT_COMPLEXITY"
    OTHER = "OTHER"


class ModelTier(str, Enum):
    AUTO = "AUTO"
    DEEPSEEK = "DEEPSEEK"
    NEXT = "NEXT"
    SOL = "SOL"


_TIER_MODEL: dict[ModelTier, str] = {
    ModelTier.DEEPSEEK: TIER_1_MODEL,
    ModelTier.NEXT: NEXT_MODEL,
    ModelTier.SOL: SOL_MODEL,
}

_TIER_ORDER: tuple[ModelTier, ModelTier, ModelTier] = (
    ModelTier.DEEPSEEK,
    ModelTier.NEXT,
    ModelTier.SOL,
)

_MODEL_TO_TIER: dict[str, ModelTier] = {
    TIER_1_MODEL: ModelTier.DEEPSEEK,
    NEXT_MODEL: ModelTier.NEXT,
    SOL_MODEL: ModelTier.SOL,
}


def model_for_tier(tier: ModelTier) -> str:
    return _TIER_MODEL[tier]


def tier_for_model(model: str) -> ModelTier:
    try:
        return _MODEL_TO_TIER[model]
    except KeyError:
        raise ValueError(f"unknown model tier for {model!r}") from None


def next_tier(tier: ModelTier) -> ModelTier | None:
    """The next higher tier, or None at the frontier."""
    try:
        index = _TIER_ORDER.index(tier)
    except ValueError:
        raise ValueError(f"unknown model tier {tier!r}") from None
    if index + 1 >= len(_TIER_ORDER):
        return None
    return _TIER_ORDER[index + 1]


def is_frontier(tier: ModelTier) -> bool:
    return tier == _TIER_ORDER[-1]


#: Transient infrastructure failures are never escalation evidence. The
#: run layer maps error classes / status codes onto these markers.
_INFRA_MARKERS = frozenset(
    {
        "timeout",
        "model_timeout",
        "connect_timeout",
        "rate_limited",
        "429",
        "provider_5xx",
        "network_error",
        "tool_server_failure",
        "model_unavailable",
    }
)


def is_infrastructure_failure(marker: str | None) -> bool:
    """True for timeout/429/5xx/network/tool-server failures.

    These are infrastructure failures, not reasoning failures, and must
    never trigger an escalation proposal.
    """
    if marker is None:
        return False
    return marker.casefold() in _INFRA_MARKERS


def identity_statement() -> str:
    """Canonical product identity line for system-prompt composition.

    The model must present as DEFENDcoder; the runtime model is an
    implementation detail the product may report when asked directly.
    """
    return (
        "You are DEFENDcoder, the software-engineering AI in the DEFEND "
        "platform. Help users understand, design, debug, build, test, and "
        "improve software. Be technically rigorous, practical, and clear. "
        "Never claim that you inspected, executed, modified, or verified "
        "something unless you actually did. OpenCode may be part of the "
        "harness; it is not your identity."
    )


@dataclass(frozen=True)
class EscalationProposal:
    """A first-class owner-facing escalation decision.

    Merely creating a proposal NEVER changes the active model; the run
    continues on ``from_model`` until the owner approves (or denies).
    """

    from_model: str
    to_model: str
    reason_code: EscalationReason
    human_summary: str
    evidence: tuple[str, ...]
    attempt_count: int
    tests_failed: int
    estimated_incremental_cost: str | None
    target_runtime_state: str
    requires_gpu_resume: bool
    expires_at: datetime
    created_at: datetime = utc_now()

    def __post_init__(self) -> None:
        if not isinstance(self.from_model, str) or not self.from_model:
            raise ValueError("from_model must be non-empty")
        if not isinstance(self.to_model, str) or not self.to_model:
            raise ValueError("to_model must be non-empty")
        if self.from_model == self.to_model:
            raise ValueError("escalation must change the model")
        if self.attempt_count < 0 or self.tests_failed < 0:
            raise ValueError("attempt/test counts must be non-negative")
        if self.tests_failed > self.attempt_count:
            raise ValueError("tests_failed cannot exceed attempt_count")
        try:
            tier_for_model(self.from_model)
        except ValueError as error:
            raise ValueError(f"from_model is not a known tier: {error}") from None
        try:
            tier_for_model(self.to_model)
        except ValueError as error:
            raise ValueError(f"to_model is not a known tier: {error}") from None
        if next_tier(tier_for_model(self.from_model)) != tier_for_model(self.to_model):
            raise ValueError("proposal must escalate exactly one tier")
        if self.expires_at.tzinfo is None:
            raise ValueError("expires_at must carry a timezone")
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must carry a timezone")

    def is_expired(self, *, now: datetime | None = None) -> bool:
        return (now or utc_now()) > self.expires_at

    def as_public_dict(self) -> dict[str, object]:
        return {
            "from_model": self.from_model,
            "to_model": self.to_model,
            "reason_code": str(self.reason_code.value),
            "human_summary": self.human_summary,
            "evidence": list(self.evidence),
            "attempt_count": self.attempt_count,
            "tests_failed": self.tests_failed,
            "estimated_incremental_cost": self.estimated_incremental_cost,
            "target_runtime_state": self.target_runtime_state,
            "requires_gpu_resume": self.requires_gpu_resume,
            "expires_at": self.expires_at.isoformat(),
            "created_at": self.created_at.isoformat(),
        }


class EscalationProposalError(RuntimeError):
    pass


def _propose_next(
    from_tier: ModelTier,
    *,
    reason_code: EscalationReason,
    human_summary: str,
    evidence: tuple[str, ...],
    attempt_count: int,
    tests_failed: int,
    now: datetime | None = None,
) -> EscalationProposal | None:
    """Internal builder: propose a single-tier escalation from ``from_tier``.

    Returns None when there is no higher tier (already at the frontier).
    """
    target = next_tier(from_tier)
    if target is None:
        return None
    created = now or utc_now()
    if from_tier == ModelTier.DEEPSEEK:
        target_runtime_state = NEXT_REST_STATE
        requires_gpu_resume = True
        cost = "resume retained Vast instance (hourly compute)"
    elif from_tier == ModelTier.NEXT:
        target_runtime_state = "MANAGED_API"
        requires_gpu_resume = False
        cost = "frontier token-cost class"
    else:  # pragma: no cover - unreachable for known tiers
        return None
    return EscalationProposal(
        from_model=model_for_tier(from_tier),
        to_model=model_for_tier(target),
        reason_code=reason_code,
        human_summary=human_summary,
        evidence=evidence,
        attempt_count=attempt_count,
        tests_failed=tests_failed,
        estimated_incremental_cost=cost,
        target_runtime_state=target_runtime_state,
        requires_gpu_resume=requires_gpu_resume,
        expires_at=created + timedelta(minutes=DEFAULT_ESCAPE_MINUTES),
        created_at=created,
    )


class EscalationPolicy:
    """Objective escalation policy.

    AUTO mode consults this policy. Proposals are advisory: they change
    nothing until the owner approves them.
    """

    #: Failures with these markers are transient infrastructure failures.
    ignore_infrastructure = True

    def propose(
        self,
        current_model: str,
        *,
        reason_code: EscalationReason,
        human_summary: str,
        evidence: tuple[str, ...] = (),
        attempt_count: int = 0,
        tests_failed: int = 0,
        failure_marker: str | None = None,
        now: datetime | None = None,
    ) -> EscalationProposal | None:
        """Propose escalation from ``current_model`` when justified.

        Returns None when:
        * the failure is a transient infrastructure failure, or
        * ``current_model`` is already at the frontier, or
        * the reason is ``OWNER_REQUESTED`` handled elsewhere (still
          allowed here as an explicit owner path).
        """
        if self.ignore_infrastructure and is_infrastructure_failure(
            failure_marker
        ):
            return None
        try:
            current_tier = tier_for_model(current_model)
        except ValueError as error:
            raise EscalationProposalError(str(error)) from None
        return _propose_next(
            current_tier,
            reason_code=reason_code,
            human_summary=human_summary,
            evidence=evidence,
            attempt_count=attempt_count,
            tests_failed=tests_failed,
            now=now,
        )


@dataclass(frozen=True)
class RouteDecision:
    """Resolved model routing for one run.

    ``tier`` is the effective model tier; ``routed_by`` records whether the
    model was picked automatically (AUTO) or explicitly (sticky selection).
    Tool authority is intentionally NOT part of a route: switching models
    never grants or removes workspace permissions.
    """

    model: str
    tier: ModelTier
    routed_by: Literal["AUTO", "EXPLICIT"]
    previous_model: str | None = None


class ModelSelector:
    """Per-run model selection with AUTO default and sticky explicit picks.

    Explicit selection persists for the run; a subsequent AUTO selection
    clears the explicit override. The selector never authorizes compute:
    resuming a retained runtime or spending tokens still requires owner
    approval through the approval flow.
    """

    def __init__(self, *, default_model: str = TIER_1_MODEL) -> None:
        if tier_for_model(default_model) != ModelTier.DEEPSEEK:
            raise ValueError("default model must be the TIER_1 backend")
        self._default_model = default_model
        self._explicit: ModelTier | None = None

    @property
    def default_model(self) -> str:
        return self._default_model

    def select(self, tier: ModelTier) -> RouteDecision:
        """Explicit selection: sticky for the run."""
        model = model_for_tier(tier)
        self._explicit = tier
        return RouteDecision(model=model, tier=tier, routed_by="EXPLICIT")

    def select_auto(self, *, escalated_model: str | None = None) -> RouteDecision:
        """AUTO resolution: default tier unless an approved escalation moved
        the run to a higher tier."""
        self._explicit = None
        if escalated_model is not None:
            tier = tier_for_model(escalated_model)
            return RouteDecision(
                model=model_for_tier(tier),
                tier=tier,
                routed_by="AUTO",
                previous_model=self._default_model,
            )
        return RouteDecision(
            model=self._default_model,
            tier=ModelTier.DEEPSEEK,
            routed_by="AUTO",
        )

    @property
    def explicit_tier(self) -> ModelTier | None:
        return self._explicit


class ApprovedEscalation:
    """Owner approval binding to ONE exact proposal."""

    def __init__(
        self,
        proposal: EscalationProposal,
        *,
        approved_at: datetime | None = None,
    ) -> None:
        if not isinstance(proposal, EscalationProposal):
            raise TypeError("approval requires an EscalationProposal")
        if proposal.is_expired(now=approved_at):
            raise EscalationProposalError("proposal has expired")
        self.proposal = proposal
        self.approved_at = approved_at or utc_now()

    @property
    def to_model(self) -> str:
        return self.proposal.to_model

    @property
    def requires_gpu_resume(self) -> bool:
        return self.proposal.requires_gpu_resume


class EscalationManager:
    """Holds at most one pending proposal and applies only approved changes.

    Denial clears the proposal and keeps the run on the current model.
    Approval is explicit: the caller (run layer) is responsible for
    resuming retained compute / switching the model client AFTER approval,
    and only then.
    """

    def __init__(self, *, policy: EscalationPolicy | None = None) -> None:
        self._policy = policy or EscalationPolicy()
        self._pending: EscalationProposal | None = None
        self._approved: ApprovedEscalation | None = None
        self._denied: EscalationProposal | None = None

    @property
    def policy(self) -> EscalationPolicy:
        return self._policy

    @property
    def pending(self) -> EscalationProposal | None:
        return self._pending

    @property
    def approved(self) -> ApprovedEscalation | None:
        return self._approved

    def propose(
        self,
        current_model: str,
        *,
        reason_code: EscalationReason,
        human_summary: str,
        evidence: tuple[str, ...] = (),
        attempt_count: int = 0,
        tests_failed: int = 0,
        failure_marker: str | None = None,
        now: datetime | None = None,
    ) -> EscalationProposal | None:
        if self._pending is not None and not self._pending.is_expired(now=now):
            raise EscalationProposalError(
                "an escalation is already pending approval"
            )
        proposal = self._policy.propose(
            current_model,
            reason_code=reason_code,
            human_summary=human_summary,
            evidence=evidence,
            attempt_count=attempt_count,
            tests_failed=tests_failed,
            failure_marker=failure_marker,
            now=now,
        )
        if proposal is None:
            return None
        self._pending = proposal
        self._approved = None
        return proposal

    def approve(self, *, now: datetime | None = None) -> ApprovedEscalation:
        if self._pending is None:
            raise EscalationProposalError("no pending escalation to approve")
        approval = ApprovedEscalation(self._pending, approved_at=now)
        self._approved = approval
        self._pending = None
        return approval

    def deny(self) -> EscalationProposal | None:
        """Deny the pending proposal; the run stays on the current model."""
        denied = self._pending
        self._denied = denied
        self._pending = None
        return denied
