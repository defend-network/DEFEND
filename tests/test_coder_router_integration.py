"""DEFENDcoder router-integration V1 tests (mocked providers, no spend).

End-to-end API routing/approval flow through a FastAPI TestClient with
fakes, plus pure routing/provider unit tests. No DeepSeek/Sol/GPU spend:
all backends are mocked or unconfigured.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from defend_coder.agent import AgentOutcome
from defend_coder.app import build_coder_app
from defend_coder.auth import AuthenticatedAccount
from defend_coder.config import CoderSettings
from defend_coder.db import CoderDatabase
from defend_coder.providers import (
    DEFAULT_DEEPSEEK_MODEL,
    NEXT_MODEL,
    SOL_MODEL,
    ModelTarget,
    build_client,
    deepseek_target,
    next_target,
    sol_target,
)
from defend_coder.router import (
    NEXT_ALIAS,
    PRODUCT_IDENTITY,
    TIER_1_MODEL,
    EscalationManager,
    EscalationPolicy,
    EscalationProposal,
    EscalationReason,
    ModelSelector,
    ModelTier,
    next_tier,
)
from defend_coder.routing import (
    ProductRuntimeAdapterBoundary,
    RuntimeResumeDenied,
    propose_for_outcome,
    resolve_starting_route,
)

UTC = timezone.utc


def _now() -> datetime:
    return datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


def _workspace(owner_account_id: Any) -> Any:
    from defend_coder.repositories import WorkspaceRecord

    return WorkspaceRecord(
        workspace_id=uuid4(),
        owner_account_id=owner_account_id,
        name="test-ws",
        workspace_root=str(Path("C:/fake/root")),
        repository_url=None,
        default_branch=None,
        created_at=_now(),
        updated_at=_now(),
    )


class FakeRunsRepository:
    def __init__(self, workspace: Any, run_id: Any) -> None:
        self._workspace = workspace
        self._run_id = run_id
        self._routing: dict[str, Any] | None = None
        self._proposals: dict[str, dict[str, Any]] = {}
        self._approved_by: list[str] = []
        self.routing_writes: list[tuple[str, str]] = []

    def get_run(self, run_id):
        if str(run_id) == str(self._run_id):
            return self._run(self._workspace)
        return None

    def messages_for_run(self, run_id):
        return ()

    @staticmethod
    def _run(workspace):
        from defend_coder.runs import RunRecord

        return RunRecord(
            run_id=uuid4(),
            workspace_id=workspace.workspace_id,
            owner_account_id=workspace.owner_account_id,
            prompt="prompt",
            status="queued",
            phase="queued",
            reason="unknown",
            error=None,
            created_at=_now(),
            finished_at=None,
        )

    def set_run_routing(
        self,
        run_id,
        *,
        requested_mode,
        selected_tier,
        selected_model,
        selected_provider,
        route_reason=None,
        escalated_from=None,
        escalation_approved_at=None,
        escalation_approved_by=None,
    ):
        self._routing = {
            "requested_mode": requested_mode,
            "selected_tier": selected_tier,
            "selected_model": selected_model,
            "selected_provider": selected_provider,
            "route_reason": route_reason,
            "escalated_from": escalated_from,
            "escalation_approved_at": escalation_approved_at,
            "escalation_approved_by": escalation_approved_by,
        }
        self.routing_writes.append(
            (selected_tier, selected_model)
        )

    def get_run_routing(self, run_id):
        from defend_coder.runs import RunRouting

        if self._routing is None:
            return None
        return RunRouting(
            run_id=run_id,
            requested_mode=self._routing["requested_mode"],
            selected_tier=self._routing["selected_tier"],
            selected_model=self._routing["selected_model"],
            selected_provider=self._routing["selected_provider"],
            route_reason=self._routing["route_reason"],
            escalated_from=self._routing["escalated_from"],
            escalation_approved_at=self._routing["escalation_approved_at"],
            escalation_approved_by=self._routing["escalation_approved_by"],
        )

    def create_escalation_proposal(self, run_id, proposal):
        public = proposal.as_public_dict()
        self._proposals[public["proposal_id"]] = {
            **public,
            "status": "pending",
            "approved_at": None,
            "approved_by": None,
        }

    def list_escalation_proposals(self, run_id):
        return tuple(self._proposals.values())

    def update_escalation_proposal_status(
        self, run_id, proposal_id, *, status, approved_by=None, approved_at=None
    ):
        if proposal_id not in self._proposals:
            return False
        self._proposals[proposal_id]["status"] = status
        self._proposals[proposal_id]["approved_by"] = approved_by
        self._proposals[proposal_id]["approved_at"] = approved_at
        return True


class FakeRepository:
    def __init__(self, workspace: Any) -> None:
        self._workspace = workspace

    def list_workspaces_for_owner(self, account_id):
        if str(account_id) == str(self._workspace.owner_account_id):
            return [self._workspace]
        return []


class FakeAuth:
    def __init__(self, account: AuthenticatedAccount) -> None:
        self._account = account

    def authenticate_session(self, token: str) -> AuthenticatedAccount:
        if token != "session-token":
            from defend_coder.auth import AuthError

            raise AuthError("invalid session")
        return self._account

    def touch_session(self, token: str) -> None:
        return None


class FakeRunner:
    def __init__(self, run_id: Any, workspace: Any) -> None:
        self._run_id = run_id
        self._workspace = workspace

    def start(self, *, workspace, prompt):
        from defend_coder.runs import RunRecord

        return RunRecord(
            run_id=uuid4(),
            workspace_id=workspace.workspace_id,
            owner_account_id=workspace.owner_account_id,
            prompt=prompt,
            status="running",
            phase="queued",
            reason="unknown",
            error=None,
            created_at=_now(),
            finished_at=None,
        )

    def cancel(self, run_id):
        return None

    @property
    def policy(self):
        return {"model": TIER_1_MODEL}


def _account(role: str = "consumer") -> AuthenticatedAccount:
    return AuthenticatedAccount(
        account_id=uuid4(),
        username="alice" if role == "consumer" else "owner",
        email="alice@example.com" if role == "consumer" else "owner@defend-network.org",
        role=role,
        is_active=True,
    )


class _App:
    def __init__(self, account: AuthenticatedAccount) -> None:
        workspace = _workspace(account.account_id)
        self.workspace = workspace
        self.run_id = uuid4()
        self.runs = FakeRunsRepository(workspace, self.run_id)
        self.auth = FakeAuth(account)
        self.runtime = ProductRuntimeAdapterBoundary()
        self.runner = FakeRunner(self.run_id, workspace)
        self.start_calls = 0
        original_start = self.runtime.start_runtime

        def tracked_start(*args, **kwargs):
            self.start_calls += 1
            return original_start(*args, **kwargs)

        self.runtime.start_runtime = tracked_start
        app = build_coder_app(
            settings=CoderSettings(database_url="postgresql://fake:fake@localhost/fake"),
            db=CoderDatabase("postgresql://fake:fake@localhost/fake"),
            auth=self.auth,
            runtime_status=lambda: {"state": "ready"},
            repository=FakeRepository(workspace),
            runs_repository=self.runs,
            runner=self.runner,
            configured_root=Path("C:/fake/root"),
            idle_timeout_seconds=0,
            runtime_adapter=self.runtime,
        )
        from fastapi.testclient import TestClient

        self.client = TestClient(app)
        self.client.cookies.set("defendcoder_session", "session-token")
        self.client.cookies.set("defendcoder_csrf", "csrf-token")

    def _headers(self):
        return {"X-CSRF-Token": "csrf-token"}

    def seed_pending_proposal(
        self, *, from_model=TIER_1_MODEL, to_model=NEXT_MODEL
    ) -> str:
        policy = EscalationPolicy()
        proposal = policy.propose(
            from_model,
            reason_code=EscalationReason.REPEATED_TEST_FAILURE,
            human_summary="Two repair attempts failed the same tests.",
            evidence=("test_x::test_y",),
            attempt_count=2,
            tests_failed=2,
            now=datetime.now(timezone.utc),
        )
        assert proposal is not None
        self.runs.create_escalation_proposal(self.run_id, proposal)
        return proposal.proposal_id


class TestNewSessionDefaults:
    def test_auto_run_routes_to_deepseek(self):
        harness = _App(_account())
        response = harness.client.post(
            f"/v1/workspaces/{harness.workspace.workspace_id}/runs",
            headers=harness._headers(),
            json={"prompt": "hello", "requested_mode": "AUTO"},
        )
        assert response.status_code == 201
        routing = response.json()["routing"]
        assert routing["requested_mode"] == "AUTO"
        assert routing["selected_tier"] == "DEEPSEEK"
        assert routing["selected_model"] == DEFAULT_DEEPSEEK_MODEL
        assert routing["selected_provider"] == "deepseek"

    def test_identity_is_defendcoder_in_routing(self):
        harness = _App(_account())
        response = harness.client.get(
            f"/v1/runs/{harness.run_id}/routing?workspace_id={harness.workspace.workspace_id}"
        )
        assert response.status_code == 200
        assert response.json()["identity"] == PRODUCT_IDENTITY


class TestModelSelector:
    def test_explicit_deepseek_sticky(self):
        harness = _App(_account())
        response = harness.client.post(
            f"/v1/runs/{harness.run_id}/model?workspace_id={harness.workspace.workspace_id}",
            headers=harness._headers(),
            json={"requested_mode": "DEEPSEEK"},
        )
        assert response.status_code == 200
        routing = response.json()["routing"]
        assert routing["selected_model"] == DEFAULT_DEEPSEEK_MODEL
        assert routing["route_reason"] == "OWNER_REQUESTED"

    def test_explicit_next_requires_owner(self):
        harness = _App(_account(role="consumer"))
        response = harness.client.post(
            f"/v1/runs/{harness.run_id}/model?workspace_id={harness.workspace.workspace_id}",
            headers=harness._headers(),
            json={"requested_mode": "NEXT"},
        )
        assert response.status_code == 403

    def test_explicit_next_admin_gives_resume_approval_step(self):
        harness = _App(_account(role="admin"))
        response = harness.client.post(
            f"/v1/runs/{harness.run_id}/model?workspace_id={harness.workspace.workspace_id}",
            headers=harness._headers(),
            json={"requested_mode": "NEXT"},
        )
        assert response.status_code == 200
        assert response.json()["next_step"] == "resume_approval_required"
        assert response.json()["routing"]["selected_model"] == NEXT_MODEL

    def test_explicit_sol_requires_owner_and_configuration(self):
        harness = _App(_account(role="consumer"))
        response = harness.client.post(
            f"/v1/runs/{harness.run_id}/model?workspace_id={harness.workspace.workspace_id}",
            headers=harness._headers(),
            json={"requested_mode": "SOL"},
        )
        assert response.status_code == 403

        harness = _App(_account(role="admin"))
        response = harness.client.post(
            f"/v1/runs/{harness.run_id}/model?workspace_id={harness.workspace.workspace_id}",
            headers=harness._headers(),
            json={"requested_mode": "SOL"},
        )
        # Sol is not configured in this environment.
        assert response.status_code == 400
        assert "not currently configured" in response.json()["detail"]


class TestEscalationProposalAPI:
    def test_proposal_listing_has_no_secrets(self):
        harness = _App(_account())
        harness.seed_pending_proposal()
        response = harness.client.get(
            f"/v1/runs/{harness.run_id}/escalation?workspace_id={harness.workspace.workspace_id}"
        )
        assert response.status_code == 200
        proposals = response.json()["proposals"]
        assert len(proposals) == 1
        proposal = proposals[0]
        text = " ".join(str(v) for v in proposal.values())
        assert "api_key" not in text.casefold()
        assert "Bearer" not in text
        assert proposal["from_model"] == TIER_1_MODEL
        assert proposal["to_model"] == NEXT_MODEL
        assert proposal["reason_code"] == "REPEATED_TEST_FAILURE"
        assert proposal["requires_gpu_resume"] is True
        assert proposal["target_runtime_state"] == "STOPPED_RETAINED"

    def test_consumer_cannot_approve(self):
        harness = _App(_account(role="consumer"))
        proposal_id = harness.seed_pending_proposal()
        response = harness.client.post(
            f"/v1/runs/{harness.run_id}/escalation/{proposal_id}/approve"
            f"?workspace_id={harness.workspace.workspace_id}",
            headers=harness._headers(),
        )
        assert response.status_code == 403

    def test_unauthenticated_cannot_approve(self):
        harness = _App(_account(role="admin"))
        proposal_id = harness.seed_pending_proposal()
        harness.client.cookies.delete("defendcoder_session")
        response = harness.client.post(
            f"/v1/runs/{harness.run_id}/escalation/{proposal_id}/approve"
            f"?workspace_id={harness.workspace.workspace_id}",
            headers=harness._headers(),
        )
        assert response.status_code == 401

    def test_approve_moves_deepseek_to_next_monotonically(self):
        harness = _App(_account(role="admin"))
        proposal_id = harness.seed_pending_proposal()
        response = harness.client.post(
            f"/v1/runs/{harness.run_id}/escalation/{proposal_id}/approve"
            f"?workspace_id={harness.workspace.workspace_id}",
            headers=harness._headers(),
        )
        assert response.status_code == 200
        routing = response.json()["routing"]
        assert routing["selected_model"] == NEXT_MODEL
        assert routing["selected_tier"] == "NEXT"
        assert routing["escalated_from"] == TIER_1_MODEL
        assert routing["route_reason"] == "REPEATED_TEST_FAILURE"
        assert harness.start_calls == 1
        assert harness.runtime.runtime_status()["state"] == "ready"

    def test_deny_leaves_current_model(self):
        harness = _App(_account(role="admin"))
        proposal_id = harness.seed_pending_proposal()
        response = harness.client.post(
            f"/v1/runs/{harness.run_id}/escalation/{proposal_id}/deny"
            f"?workspace_id={harness.workspace.workspace_id}",
            headers=harness._headers(),
        )
        assert response.status_code == 200
        assert response.json()["status"] == "denied"
        assert harness.start_calls == 0
        assert harness.runs.get_run_routing(harness.run_id) is None

    def test_approve_non_pending_proposal_rejected(self):
        harness = _App(_account(role="admin"))
        proposal_id = harness.seed_pending_proposal()
        first = harness.client.post(
            f"/v1/runs/{harness.run_id}/escalation/{proposal_id}/approve"
            f"?workspace_id={harness.workspace.workspace_id}",
            headers=harness._headers(),
        )
        assert first.status_code == 200
        second = harness.client.post(
            f"/v1/runs/{harness.run_id}/escalation/{proposal_id}/approve"
            f"?workspace_id={harness.workspace.workspace_id}",
            headers=harness._headers(),
        )
        assert second.status_code == 409

    def test_expired_proposal_cannot_be_approved(self):
        harness = _App(_account(role="admin"))
        # Seed an already-expired proposal directly.
        policy = EscalationPolicy()
        proposal = policy.propose(
            TIER_1_MODEL,
            reason_code=EscalationReason.REPEATED_TEST_FAILURE,
            human_summary="expired",
            now=_now(),
        )
        assert proposal is not None
        expired = EscalationProposal(
            **{
                **proposal.__dict__,
                "created_at": _now() - timedelta(days=1),
                "expires_at": _now() - timedelta(minutes=1),
            }
        )
        harness.runs.create_escalation_proposal(harness.run_id, expired)
        response = harness.client.post(
            f"/v1/runs/{harness.run_id}/escalation/{expired.proposal_id}/approve"
            f"?workspace_id={harness.workspace.workspace_id}",
            headers=harness._headers(),
        )
        assert response.status_code == 409
        assert harness.start_calls == 0

    def test_model_switch_preserves_run_and_workspace(self):
        harness = _App(_account(role="admin"))
        proposal_id = harness.seed_pending_proposal()
        response = harness.client.post(
            f"/v1/runs/{harness.run_id}/escalation/{proposal_id}/approve"
            f"?workspace_id={harness.workspace.workspace_id}",
            headers=harness._headers(),
        )
        assert response.status_code == 200
        # Routing is keyed to the same run/workspace; no tool field exists.
        routing_keys = set(response.json()["routing"])
        assert "tool" not in " ".join(routing_keys).casefold()


class TestNextToSol:
    def test_next_failure_proposes_sol(self):
        manager = EscalationManager()
        proposal = manager.propose(
            NEXT_MODEL,
            reason_code=EscalationReason.REPEATED_TEST_FAILURE,
            human_summary="Next failed materially.",
            evidence=("suite_x",),
            attempt_count=1,
            tests_failed=1,
            now=_now(),
        )
        assert proposal is not None
        assert proposal.to_model == SOL_MODEL
        assert proposal.requires_gpu_resume is False
        assert manager.approved is None

    def test_frontier_never_escalates_further(self):
        manager = EscalationManager()
        assert manager.propose(
            SOL_MODEL,
            reason_code=EscalationReason.REPEATED_TEST_FAILURE,
            human_summary="frontier",
            now=_now(),
        ) is None


class TestInfrastructureNeverEscalates:
    @pytest.mark.parametrize(
        "reason",
        ["model_timeout", "model_unavailable"],
    )
    def test_infra_reason_produces_no_proposal(self, reason):
        manager = EscalationManager()
        outcome = AgentOutcome(
            state="failed",
            error=reason,
            steps=3,
            reason=reason,
        )
        proposal = propose_for_outcome(
            manager=manager,
            current_model=TIER_1_MODEL,
            outcome=outcome,
            summary="boom",
            attempt_count=2,
            tests_failed=2,
        )
        assert proposal is None

    def test_repeated_quality_failure_proposes(self):
        manager = EscalationManager()
        outcome = AgentOutcome(
            state="failed",
            error="tests still failing",
            steps=5,
            reason="model_error",
        )
        proposal = propose_for_outcome(
            manager=manager,
            current_model=TIER_1_MODEL,
            outcome=outcome,
            summary="same integration tests fail twice.",
            evidence=("test_login",),
            attempt_count=2,
            tests_failed=2,
        )
        assert proposal is not None
        assert proposal.to_model == NEXT_MODEL


class TestRuntimeAdapter:
    def test_status_polling_never_starts_gpu(self):
        adapter = ProductRuntimeAdapterBoundary()
        state = adapter.runtime_status()["state"]
        assert state == "stopped"
        assert adapter.get_runtime_endpoint() is None
        # No start call happened.
        assert state == "stopped"

    def test_resume_requires_explicit_authorization(self):
        adapter = ProductRuntimeAdapterBoundary()
        with pytest.raises(RuntimeResumeDenied):
            adapter.start_runtime()
        # Still stopped-retained after a denied attempt.
        assert adapter.runtime_status()["state"] == "stopped"

    def test_authorized_resume_reuses_runtime(self):
        adapter = ProductRuntimeAdapterBoundary()
        result = adapter.start_runtime(authorize_resume=True)
        assert result["state"] == "ready"
        assert result["reused"] is True
        assert adapter.get_runtime_endpoint() == "http://127.0.0.1:8003/v1"
        # Stopping preserves the instance (retained).
        stopped = adapter.stop_runtime()
        assert stopped["state"] == "stopped"
        assert stopped["retained"] is True

    def test_ready_runtime_is_reused_not_replaced(self):
        adapter = ProductRuntimeAdapterBoundary(
            status={
                "state": "ready",
                "provider_instance_state": "running",
                "model": NEXT_MODEL,
                "instance_id": 123,
                "gpu": "H100",
                "hourly_cost": "4.04",
            }
        )
        result = adapter.start_runtime(authorize_resume=True)
        assert result["reused"] is True
        assert adapter.runtime_status()["instance_id"] == 123


class TestProviders:
    def test_deepseek_target_defaults(self):
        target = deepseek_target(env={})
        assert target.tier == "DEEPSEEK"
        assert target.model_id == DEFAULT_DEEPSEEK_MODEL
        assert target.provider == "deepseek"
        assert target.runtime_kind == "managed_api"
        assert target.availability is False
        assert target.managed_api is True

    def test_deepseek_target_availability_from_key_env(self):
        target = deepseek_target(
            env={"DEEPSEEK_API_KEY": "sk-fake-deepseek-key"}
        )
        assert target.availability is True

    def test_sol_target_requires_openai_key(self):
        assert sol_target(env={}).availability is False
        assert sol_target(
            env={"OPENAI_API_KEY": "sk-fake-openai"}
        ).availability is True
        assert sol_target(env={}).model_id == SOL_MODEL

    def test_next_target_is_self_hosted(self):
        target = next_target(availability=False)
        assert target.alias == NEXT_ALIAS
        assert target.model_id == NEXT_MODEL
        assert target.requires_external_runtime is True
        assert target.runtime_kind == "vllm"
        assert target.endpoint == "http://127.0.0.1:8003/v1"

    def test_build_client_requires_key_for_managed_api(self):
        target = deepseek_target(env={})
        with pytest.raises(ValueError, match="API key"):
            build_client(target, api_key=None)

    def test_managed_api_accepts_remote_https_endpoint(self):
        from defend_coder.model_config import CoderModelConfig

        config = CoderModelConfig(
            alias=TIER_1_MODEL,
            model_name=DEFAULT_DEEPSEEK_MODEL,
            base_url="https://api.deepseek.com/v1",
            api_key="sk-fake",
            requires_api_key=True,
            managed_api=True,
        )
        assert config.base_url == "https://api.deepseek.com/v1"
        with pytest.raises(ValueError, match="managed-API providers require"):
            CoderModelConfig(
                alias=TIER_1_MODEL,
                model_name=DEFAULT_DEEPSEEK_MODEL,
                base_url="https://api.deepseek.com/v1",
                managed_api=True,
            )

    def test_self_hosted_still_loopback_only(self):
        from defend_coder.model_config import CoderModelConfig

        with pytest.raises(ValueError, match="loopback"):
            CoderModelConfig(
                alias=NEXT_ALIAS,
                model_name=NEXT_MODEL,
                base_url="https://example.com/v1",
            )


class TestModelMetadata:
    def test_targets_report_exact_model_ids(self):
        targets = {
            "deepseek": deepseek_target(env={}),
            "Qwen/Qwen3-Coder-Next": next_target(),
            "gpt-5.6-sol": sol_target(env={}),
        }
        assert targets["deepseek"].model_id == DEFAULT_DEEPSEEK_MODEL
        assert targets["Qwen/Qwen3-Coder-Next"].model_id == NEXT_MODEL
        assert targets["gpt-5.6-sol"].model_id == SOL_MODEL
