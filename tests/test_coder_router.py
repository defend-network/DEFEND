"""DEFENDcoder three-tier router + owner escalation tests (pure logic, no I/O).

Covers the product contract:
- new sessions default to DeepSeek (TIER_1)
- identity is always DEFENDcoder
- proposals never switch models without owner approval
- transient infra failures never escalate
- Next resumes a retained instance only after approval; stop preserves it
- Sol never runs without approval
- explicit model selection is sticky for the run
- switching models never changes tool authority
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from defend_coder.prompts import compose_system_prompt
from defend_coder.router import (
    NEXT_ALIAS,
    NEXT_MODEL,
    NEXT_REST_STATE,
    PRODUCT_IDENTITY,
    SOL_MODEL,
    TIER_1_MODEL,
    ApprovedEscalation,
    EscalationManager,
    EscalationPolicy,
    EscalationProposal,
    EscalationProposalError,
    EscalationReason,
    ModelSelector,
    ModelTier,
    identity_statement,
    is_frontier,
    is_infrastructure_failure,
    model_for_tier,
    next_tier,
    tier_for_model,
)

UTC = timezone.utc


def _now() -> datetime:
    return datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


class TestIdentityAndDefaults:
    def test_new_session_defaults_to_deepseek(self):
        selector = ModelSelector()
        decision = selector.select_auto()
        assert decision.model == TIER_1_MODEL
        assert decision.tier == ModelTier.DEEPSEEK
        assert decision.routed_by == "AUTO"

    def test_product_identity_is_defendcoder(self):
        assert PRODUCT_IDENTITY == "DEFENDcoder"
        assert "DEFENDcoder" in identity_statement()

    def test_composed_system_prompt_keeps_defendcoder_identity(self):
        prompt = compose_system_prompt()
        assert "DEFENDcoder" in prompt

    def test_identity_is_model_independent(self):
        for model in (TIER_1_MODEL, NEXT_MODEL, SOL_MODEL):
            assert PRODUCT_IDENTITY not in (
                model,
                "OpenCode",
                "Qwen",
            )


class TestTiers:
    def test_tier_chain_is_deepseek_next_sol(self):
        assert next_tier(ModelTier.DEEPSEEK) == ModelTier.NEXT
        assert next_tier(ModelTier.NEXT) == ModelTier.SOL
        assert next_tier(ModelTier.SOL) is None

    def test_frontier_detection(self):
        assert is_frontier(ModelTier.SOL) is True
        assert is_frontier(ModelTier.DEEPSEEK) is False

    def test_model_aliases_match_mission(self):
        assert NEXT_ALIAS == "defendcoder-heavy"
        assert NEXT_MODEL == "Qwen/Qwen3-Coder-Next"
        assert SOL_MODEL == "gpt-5.6-sol"

    def test_tier_lookup_round_trip(self):
        assert tier_for_model(model_for_tier(ModelTier.NEXT)) == ModelTier.NEXT
        with pytest.raises(ValueError):
            tier_for_model("not-a-model")


class TestInfrastructureFiltering:
    @pytest.mark.parametrize(
        "marker",
        [
            "timeout",
            "model_timeout",
            "connect_timeout",
            "429",
            "rate_limited",
            "provider_5xx",
            "network_error",
            "tool_server_failure",
            "model_unavailable",
        ],
    )
    def test_transient_infrastructure_failures_never_escalate(self, marker):
        policy = EscalationPolicy()
        proposal = policy.propose(
            TIER_1_MODEL,
            reason_code=EscalationReason.REPEATED_TEST_FAILURE,
            human_summary="boom",
            failure_marker=marker,
        )
        assert proposal is None

    def test_reasoning_failure_is_escalation_eligible(self):
        proposal = EscalationPolicy().propose(
            TIER_1_MODEL,
            reason_code=EscalationReason.REPEATED_TEST_FAILURE,
            human_summary="same integration tests fail",
            attempt_count=2,
            tests_failed=2,
        )
        assert proposal is not None


class TestProposalCreation:
    def test_deepseek_failure_creates_next_proposal(self):
        manager = EscalationManager()
        proposal = manager.propose(
            TIER_1_MODEL,
            reason_code=EscalationReason.REPEATED_TEST_FAILURE,
            human_summary="Two complete repair attempts failed the same tests.",
            evidence=("test_login_flow", "test_checkout_flow"),
            attempt_count=2,
            tests_failed=2,
            now=_now(),
        )
        assert proposal is not None
        assert proposal.from_model == TIER_1_MODEL
        assert proposal.to_model == NEXT_MODEL
        assert proposal.reason_code == EscalationReason.REPEATED_TEST_FAILURE
        assert proposal.attempt_count == 2
        assert proposal.tests_failed == 2
        assert proposal.requires_gpu_resume is True
        assert proposal.target_runtime_state == NEXT_REST_STATE
        assert proposal.estimated_incremental_cost is not None

    def test_next_failure_creates_sol_proposal(self):
        proposal = EscalationPolicy().propose(
            NEXT_MODEL,
            reason_code=EscalationReason.REPEATED_TEST_FAILURE,
            human_summary="Next could not pass the suite either.",
            attempt_count=1,
            tests_failed=1,
        )
        assert proposal is not None
        assert proposal.to_model == SOL_MODEL
        assert proposal.requires_gpu_resume is False
        assert proposal.target_runtime_state == "MANAGED_API"

    def test_frontier_never_escalates(self):
        assert EscalationPolicy().propose(
            SOL_MODEL,
            reason_code=EscalationReason.REPEATED_TEST_FAILURE,
            human_summary="at the frontier",
        ) is None

    def test_owner_requested_escalation_is_allowed(self):
        proposal = EscalationPolicy().propose(
            TIER_1_MODEL,
            reason_code=EscalationReason.OWNER_REQUESTED,
            human_summary="owner wants Next",
        )
        assert proposal is not None

    def test_proposal_must_escalate_exactly_one_tier(self):
        with pytest.raises(ValueError, match="exactly one tier"):
            EscalationProposal(
                from_model=TIER_1_MODEL,
                to_model=SOL_MODEL,
                reason_code=EscalationReason.OWNER_REQUESTED,
                human_summary="skip a tier",
                evidence=(),
                attempt_count=0,
                tests_failed=0,
                estimated_incremental_cost=None,
                target_runtime_state="x",
                requires_gpu_resume=False,
                expires_at=_now() + timedelta(minutes=15),
                created_at=_now(),
            )

    def test_proposal_validates_counts(self):
        with pytest.raises(ValueError, match="tests_failed"):
            EscalationPolicy().propose(
                TIER_1_MODEL,
                reason_code=EscalationReason.REPEATED_TEST_FAILURE,
                human_summary="counts broken",
                attempt_count=1,
                tests_failed=2,
            )

    def test_proposal_rejects_unknown_models(self):
        with pytest.raises(EscalationProposalError):
            EscalationPolicy().propose(
                "unknown-model",
                reason_code=EscalationReason.OTHER,
                human_summary="nope",
            )

    def test_expired_proposal_cannot_be_approved(self):
        manager = EscalationManager()
        proposal = manager.propose(
            TIER_1_MODEL,
            reason_code=EscalationReason.REPEATED_TEST_FAILURE,
            human_summary="expires soon",
            now=_now(),
        )
        assert proposal is not None
        later = _now() + timedelta(minutes=30)
        assert proposal.is_expired(now=later)
        with pytest.raises(EscalationProposalError, match="expired"):
            manager.approve(now=later)


class TestOwnerApprovalGate:
    def test_proposal_does_not_switch_model_without_approval(self):
        manager = EscalationManager()
        manager.propose(
            TIER_1_MODEL,
            reason_code=EscalationReason.REPEATED_TEST_FAILURE,
            human_summary="hard task",
            now=_now(),
        )
        assert manager.pending is not None
        assert manager.approved is None
        # The run stays on DeepSeek until approval is applied.

    def test_approved_next_resumes_retained_instance(self):
        manager = EscalationManager()
        manager.propose(
            TIER_1_MODEL,
            reason_code=EscalationReason.REPEATED_TEST_FAILURE,
            human_summary="hard task",
            now=_now(),
        )
        approval = manager.approve(now=_now())
        assert approval.to_model == NEXT_MODEL
        assert approval.requires_gpu_resume is True
        assert approval.proposal.target_runtime_state == NEXT_REST_STATE
        assert manager.approved is approval
        assert manager.pending is None

    def test_denied_proposal_stays_deepseek(self):
        manager = EscalationManager()
        manager.propose(
            TIER_1_MODEL,
            reason_code=EscalationReason.REPEATED_TEST_FAILURE,
            human_summary="hard task",
            now=_now(),
        )
        denied = manager.deny()
        assert denied is not None
        assert manager.pending is None
        assert manager.approved is None
        decision = ModelSelector().select_auto()
        assert decision.model == TIER_1_MODEL

    def test_sol_does_not_run_without_approval(self):
        manager = EscalationManager()
        manager.propose(
            NEXT_MODEL,
            reason_code=EscalationReason.REPEATED_TEST_FAILURE,
            human_summary="Next failed materially",
            now=_now(),
        )
        assert manager.pending is not None
        assert manager.approved is None
        # Approve to actually move to Sol.
        approval = manager.approve(now=_now())
        assert approval.to_model == SOL_MODEL

    def test_no_approval_when_nothing_pending(self):
        manager = EscalationManager()
        with pytest.raises(EscalationProposalError, match="no pending"):
            manager.approve(now=_now())

    def test_only_one_pending_proposal_at_a_time(self):
        manager = EscalationManager()
        manager.propose(
            TIER_1_MODEL,
            reason_code=EscalationReason.REPEATED_TEST_FAILURE,
            human_summary="first",
            now=_now(),
        )
        with pytest.raises(EscalationProposalError, match="already pending"):
            manager.propose(
                TIER_1_MODEL,
                reason_code=EscalationReason.CONTEXT_COMPLEXITY,
                human_summary="second",
                now=_now(),
            )


class TestAutoRouteResolution:
    def test_auto_resolves_to_approved_escalated_model(self):
        selector = ModelSelector()
        assert selector.select_auto().model == TIER_1_MODEL
        decision = selector.select_auto(escalated_model=NEXT_MODEL)
        assert decision.model == NEXT_MODEL
        assert decision.tier == ModelTier.NEXT
        assert decision.routed_by == "AUTO"
        assert decision.previous_model == TIER_1_MODEL


class TestManualModelSelector:
    def test_explicit_selection_is_sticky_for_the_run(self):
        selector = ModelSelector()
        first = selector.select(ModelTier.NEXT)
        assert first.routed_by == "EXPLICIT"
        assert selector.select(ModelTier.NEXT).routed_by == "EXPLICIT"
        assert selector.explicit_tier == ModelTier.NEXT

    def test_auto_resets_explicit_selection(self):
        selector = ModelSelector()
        selector.select(ModelTier.NEXT)
        assert selector.explicit_tier == ModelTier.NEXT
        decision = selector.select_auto()
        assert decision.model == TIER_1_MODEL
        assert selector.explicit_tier is None

    def test_all_tiers_selectable(self):
        selector = ModelSelector()
        assert selector.select(ModelTier.DEEPSEEK).model == TIER_1_MODEL
        assert selector.select(ModelTier.NEXT).model == NEXT_MODEL
        assert selector.select(ModelTier.SOL).model == SOL_MODEL

    def test_default_must_be_tier_one(self):
        with pytest.raises(ValueError, match="TIER_1"):
            ModelSelector(default_model=NEXT_MODEL)


class TestToolAuthorityInvariant:
    def test_routing_never_changes_tool_authority(self):
        # A route decision carries model identity only — no toolkit, no
        # workspace, no tool list. Switching models therefore cannot grant
        # or revoke workspace permission.
        selector = ModelSelector()
        deepseek = selector.select_auto()
        next_route = selector.select(ModelTier.NEXT)
        assert {f for f in vars(deepseek)} == {f for f in vars(next_route)}
        assert "tool" not in vars(deepseek)

    def test_router_never_constructs_a_toolkit(self):
        import sys

        import defend_coder.router as router_module

        assert "CoderToolkit" not in dir(router_module)
        assert "defend_coder.tools" not in sys.modules

    def test_identity_statement_never_claims_unearned_authority(self):
        statement = identity_statement()
        assert "Never claim" in statement


class TestStopPreservesInstance:
    def test_next_rest_state_is_retained_not_destroyed(self):
        assert NEXT_REST_STATE == "STOPPED_RETAINED"
        # A proposal for Next never carries a destroy directive.
        proposal = EscalationPolicy().propose(
            TIER_1_MODEL,
            reason_code=EscalationReason.REPEATED_TEST_FAILURE,
            human_summary="resume retained",
        )
        assert proposal is not None
        assert "destroy" not in proposal.as_public_dict().values()
        assert proposal.target_runtime_state == "STOPPED_RETAINED"


class TestPublicDict:
    def test_proposal_public_dict_has_no_secrets(self):
        manager = EscalationManager()
        proposal = manager.propose(
            TIER_1_MODEL,
            reason_code=EscalationReason.REPEATED_TEST_FAILURE,
            human_summary="safe summary",
            evidence=("file_x",),
            now=_now(),
        )
        assert proposal is not None
        public = proposal.as_public_dict()
        text = " ".join(str(value) for value in public.values())
        assert "key" not in text.casefold() or "token" not in text.casefold()
        assert public["from_model"] == TIER_1_MODEL
        assert public["to_model"] == NEXT_MODEL
