"""Run-layer glue: resolve starting model targets and map outcomes to
escalation proposals, plus the small replaceable runtime-manager adapter.

The real ProductRuntimeManager (when merged) supplies the adapter; this
module only defines the boundary and a conservative default that never
starts paid compute on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .agent import AgentOutcome
from .providers import ModelTarget
from .router import (
    EscalationManager,
    EscalationPolicy,
    EscalationProposal,
    EscalationReason,
    ModelSelector,
    ModelTier,
    is_infrastructure_failure,
    tier_for_model,
)

#: Agent terminal reasons that are infrastructure failures (never
#: escalation evidence). Tool/test failures are ambiguous: callers pass an
#: explicit infrastructure marker to suppress escalation.
_INFRA_REASON_TO_MARKER = {
    "model_timeout": "timeout",
    "model_unavailable": "model_unavailable",
}


def failure_marker_for_reason(reason: str | None) -> str | None:
    """Map a terminal agent reason to an infrastructure-failure marker.

    Returns None when the reason is not clearly infrastructure (quality
    failures stay eligible for escalation).
    """
    if reason is None:
        return None
    return _INFRA_REASON_TO_MARKER.get(reason)


def is_quality_failure(outcome: AgentOutcome) -> bool:
    """True when the run outcome is a model-quality failure (not infra)."""
    if outcome.state == "failed":
        marker = failure_marker_for_reason(outcome.reason)
        return not is_infrastructure_failure(marker)
    return False


@dataclass(frozen=True)
class ResolvedRoute:
    target: ModelTarget
    tier: ModelTier
    routed_by: str
    previous_model: str | None = None


def resolve_starting_route(
    *,
    requested_mode: str,
    explicit_tier: ModelTier | None,
    targets: dict[str, ModelTarget],
    selector: ModelSelector,
) -> ResolvedRoute:
    """Resolve the starting backend for a run.

    AUTO -> TIER_1 (DeepSeek). Explicit tiers are sticky for the run.
    NEXT/SOL resolution does NOT start compute: it only selects the target.
    """
    mode = (requested_mode or "AUTO").strip().upper()
    if mode not in ("AUTO", "DEEPSEEK", "NEXT", "SOL"):
        raise ValueError(
            f"requested_mode must be AUTO, DEEPSEEK, NEXT, or SOL (got {mode!r})"
        )

    if mode != "AUTO":
        tier = ModelTier(mode)
        decision = selector.select(tier)
    else:
        decision = selector.select_auto()

    target = targets.get(decision.model)
    if target is None:
        raise ValueError(f"no configured target for {decision.model!r}")
    return ResolvedRoute(
        target=target,
        tier=decision.tier,
        routed_by=decision.routed_by,
        previous_model=decision.previous_model,
    )


def propose_for_outcome(
    *,
    manager: EscalationManager,
    current_model: str,
    outcome: AgentOutcome,
    summary: str,
    evidence: tuple[str, ...] = (),
    attempt_count: int = 0,
    tests_failed: int = 0,
    reason_code: EscalationReason = EscalationReason.REPEATED_TEST_FAILURE,
) -> EscalationProposal | None:
    """Create a persisted-ready proposal from a quality failure.

    Infrastructure failures (timeout / unavailable / explicit markers)
    never produce proposals. The returned proposal changes nothing until
    the owner approves it.
    """
    marker = failure_marker_for_reason(outcome.reason)
    return manager.propose(
        current_model,
        reason_code=reason_code,
        human_summary=summary,
        evidence=evidence,
        attempt_count=attempt_count,
        tests_failed=tests_failed,
        failure_marker=marker,
    )


class RuntimeResumeDenied(RuntimeError):
    """Resuming a retained paid runtime requires explicit owner approval."""


class ProductRuntimeAdapterBoundary:
    """Default runtime-manager boundary (replaceable by ProductRuntimeManager).

    Status-only observation never starts compute. ``start_runtime`` raises
    unless the caller explicitly authorizes a resume of a retained instance.
    """

    def __init__(self, *, status: dict[str, Any] | None = None) -> None:
        self._status = status or {
            "state": "stopped",
            "provider_instance_state": "retained",
            "model": "Qwen/Qwen3-Coder-Next",
            "instance_id": None,
            "gpu": None,
            "hourly_cost": None,
            "detail": "STOPPED_RETAINED",
        }

    def runtime_status(self, product_id: str = "defendcoder") -> dict[str, Any]:
        del product_id
        return dict(self._status)

    def get_runtime_endpoint(self, product_id: str = "defendcoder") -> str | None:
        del product_id
        state = str(self._status.get("state") or "stopped")
        if state == "ready":
            return "http://127.0.0.1:8003/v1"
        return None

    def start_runtime(
        self,
        product_id: str = "defendcoder",
        *,
        authorize_resume: bool = False,
    ) -> dict[str, Any]:
        del product_id
        if not authorize_resume:
            raise RuntimeResumeDenied(
                "resuming a retained paid runtime requires owner approval"
            )
        if self.runtime_status().get("state") == "ready":
            return {"state": "ready", "reused": True}
        self._status = {**self._status, "state": "ready"}
        return {"state": "ready", "reused": True}

    def stop_runtime(self, product_id: str = "defendcoder") -> dict[str, Any]:
        del product_id
        self._status = {**self._status, "state": "stopped"}
        return {"state": "stopped", "retained": True}
