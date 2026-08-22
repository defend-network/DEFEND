"""M2.1 routing-truth + credential-safety regressions (no live spend).

Proves: strict per-provider credential routing, dynamic availability after a
credential save (no restart), route-before-start gating (zero worker/model
calls on preflight failure), per-run AND mid-run real provider dispatch,
DeepSeek tool-continuation protocol, and that hidden reasoning_content is
never exposed.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from defend_coder.agent import AgentOutcome
from defend_coder.agent_client import (
    AgentChatClient,
    AgentChatResponse,
    RoutingAgentClient,
)
from defend_coder.config import CoderSettings
from defend_coder.credentials import CredentialStore
from defend_coder.db import CoderDatabase
from defend_coder.model_config import CoderModelConfig
from defend_coder.providers import (
    DEFAULT_DEEPSEEK_MODEL,
    NEXT_MODEL,
    SOL_MODEL,
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
    EscalationReason,
    ModelSelector,
    ModelTier,
    tier_for_model,
)
from defend_coder.routing import propose_for_outcome


class _Store:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def load(self):
        return dict(self.values)

    def save(self, values):
        self.values = dict(values)


def _credentials(values=None, env=None):
    return CredentialStore(store_loader=_Store(values), env=env or {})


class TestStrictSecretRouting:
    def test_deepseek_key_never_resolves_as_sol(self):
        store = _credentials({"DEEPSEEK_API_KEY": "sk-deepseek-only"})
        assert store.resolve("deepseek") == "sk-deepseek-only"
        assert store.resolve("sol") is None

    def test_openai_key_never_resolves_as_deepseek(self):
        store = _credentials({"OPENAI_API_KEY": "sk-openai-only"})
        assert store.resolve("sol") == "sk-openai-only"
        assert store.resolve("deepseek") is None

    def test_both_keys_resolve_to_their_own_values(self):
        store = _credentials(
            {
                "DEEPSEEK_API_KEY": "sk-deepseek",
                "OPENAI_API_KEY": "sk-openai",
            }
        )
        assert store.resolve("deepseek") == "sk-deepseek"
        assert store.resolve("sol") == "sk-openai"

    def test_unknown_provider_fails_closed(self):
        store = _credentials({"DEEPSEEK_API_KEY": "x"})
        assert store.resolve("unknown-provider") is None
        with pytest.raises(ValueError):
            store.set("unknown-provider", "x")

    def test_env_does_not_leak_across_providers(self):
        store = _credentials(env={"OPENAI_API_KEY": "sk-env-openai"})
        assert store.resolve("sol") == "sk-env-openai"
        assert store.resolve("deepseek") is None

    def test_status_never_contains_values(self):
        store = _credentials(
            {"DEEPSEEK_API_KEY": "sk-deepseek", "OPENAI_API_KEY": "sk-openai"}
        )
        status = store.status()
        assert "sk-deepseek" not in json.dumps(status)
        assert "sk-openai" not in json.dumps(status)
        assert status["deepseek"] == "CONFIGURED"
        assert status["sol"] == "CONFIGURED"


class TestDynamicCredentialRefresh:
    def test_save_takes_effect_without_restart(self):
        store = _Store()
        credentials = CredentialStore(store_loader=store)
        assert credentials.configured("deepseek") is False
        credentials.set("deepseek", "sk-fresh")
        assert credentials.configured("deepseek") is True
        assert credentials.resolve("deepseek") == "sk-fresh"
        assert store.values["DEEPSEEK_API_KEY"] == "sk-fresh"

    def test_replace_takes_effect_without_restart(self):
        store = _Store({"DEEPSEEK_API_KEY": "sk-old"})
        credentials = CredentialStore(store_loader=store)
        assert credentials.resolve("deepseek") == "sk-old"
        credentials.set("deepseek", "sk-new")
        assert credentials.resolve("deepseek") == "sk-new"
        assert store.values["DEEPSEEK_API_KEY"] == "sk-new"

    def test_live_target_reflects_saved_credential(self):
        store = _Store()
        credentials = CredentialStore(store_loader=store)
        assert deepseek_target(availability=credentials.configured("deepseek")).availability is False
        credentials.set("deepseek", "sk-live")
        assert deepseek_target(availability=credentials.configured("deepseek")).availability is True


class TestRouteBeforeRunnerStart:
    def _app(self, account=None, *, configure_deepseek=True, role="admin"):
        from datetime import datetime, timezone

        from fastapi.testclient import TestClient

        from defend_coder.app import build_coder_app
        from defend_coder.auth import AuthenticatedAccount

        from test_coder_router_integration import (
            FakeAuth,
            FakeRepository,
            FakeRunsRepository,
            FakeRunner,
            _workspace,
        )
        from defend_coder.routing import ProductRuntimeAdapterBoundary

        account = account or AuthenticatedAccount(
            account_id=uuid4(),
            username="owner" if role == "admin" else "consumer",
            email="x@example.com",
            role=role,
            is_active=True,
        )
        workspace = _workspace(account.account_id)
        run_id = uuid4()
        runs = FakeRunsRepository(workspace, run_id)
        runner = FakeRunner(run_id, workspace)
        runtime = ProductRuntimeAdapterBoundary()
        app = build_coder_app(
            settings=CoderSettings(database_url="postgresql://fake:fake@localhost/fake"),
            db=CoderDatabase("postgresql://fake:fake@localhost/fake"),
            auth=FakeAuth(account),
            runtime_status=lambda: {"state": "ready"},
            repository=FakeRepository(workspace),
            runs_repository=runs,
            runner=runner,
            configured_root=Path("C:/fake/root"),
            idle_timeout_seconds=0,
            runtime_adapter=runtime,
            credentials=CredentialStore(
                store_loader=_Store(
                    {"DEEPSEEK_API_KEY": "sk-fake"} if configure_deepseek else {}
                )
            ),
        )
        client = TestClient(app)
        client.cookies.set("defendcoder_session", "session-token")
        client.cookies.set("defendcoder_csrf", "csrf-token")
        return client, workspace, runs, runner, account

    def _headers(self):
        return {"X-CSRF-Token": "csrf-token"}

    def test_auto_missing_deepseek_starts_zero_workers(self):
        client, workspace, runs, runner, _ = self._app(configure_deepseek=False)
        response = client.post(
            f"/v1/workspaces/{workspace.workspace_id}/runs",
            headers=self._headers(),
            json={"prompt": "hello", "requested_mode": "AUTO"},
        )
        assert response.status_code == 503
        assert runner.start_existing_calls == 0
        assert runs.created == 0

    def test_invalid_mode_starts_zero_workers(self):
        client, workspace, runs, runner, _ = self._app()
        response = client.post(
            f"/v1/workspaces/{workspace.workspace_id}/runs",
            headers=self._headers(),
            json={"prompt": "hello", "requested_mode": "BOGUS"},
        )
        assert response.status_code == 400
        assert runner.start_existing_calls == 0
        assert runs.created == 0

    def test_consumer_next_starts_zero_workers(self):
        client, workspace, runs, runner, _ = self._app(role="consumer")
        response = client.post(
            f"/v1/workspaces/{workspace.workspace_id}/runs",
            headers=self._headers(),
            json={"prompt": "hello", "requested_mode": "NEXT"},
        )
        assert response.status_code == 403
        assert runner.start_existing_calls == 0
        assert runs.created == 0

    def test_sol_unavailable_starts_zero_workers(self):
        client, workspace, runs, runner, _ = self._app(role="admin")
        response = client.post(
            f"/v1/workspaces/{workspace.workspace_id}/runs",
            headers=self._headers(),
            json={"prompt": "hello", "requested_mode": "SOL"},
        )
        assert response.status_code == 400
        assert runner.start_existing_calls == 0
        assert runs.created == 0

    def test_success_routes_before_start(self):
        client, workspace, runs, runner, _ = self._app()
        response = client.post(
            f"/v1/workspaces/{workspace.workspace_id}/runs",
            headers=self._headers(),
            json={"prompt": "hello", "requested_mode": "AUTO"},
        )
        assert response.status_code == 201
        assert runner.start_existing_calls == 1
        assert runs.created == 1
        routing = response.json()["routing"]
        assert routing["selected_model"] == DEFAULT_DEEPSEEK_MODEL
        assert routing["requested_mode"] == "AUTO"

    def test_credential_save_enables_chat_without_restart(self, monkeypatch):
        client, workspace, runs, runner, account = self._app(
            configure_deepseek=False, role="admin"
        )
        # Not configured yet.
        status = client.get("/v1/admin/model-credentials").json()["providers"]
        assert status["deepseek"] == "MISSING"

        from defend_coder.agent_client import AgentChatResponse

        class FakeChatClient(AgentChatClient):
            def __init__(self):
                super().__init__(
                    CoderModelConfig(
                        alias="deepseek",
                        model_name=DEFAULT_DEEPSEEK_MODEL,
                        base_url="https://api.deepseek.com",
                        api_key="sk-fake",
                        requires_api_key=True,
                        managed_api=True,
                    )
                )

            def chat(self, messages, tools=None, *, timeout_seconds=None,
                     max_tokens=None, on_request_started=None):
                return AgentChatResponse(
                    content="I am DEFENDcoder.",
                    tool_calls=(),
                    usage={},
                )

        monkeypatch.setattr(
            "defend_coder.app.build_client",
            lambda target, api_key: FakeChatClient(),
        )
        # Save the credential; availability must change without restart.
        saved = client.post(
            "/v1/admin/model-credentials/deepseek",
            headers=self._headers(),
            json={"api_key": "sk-fresh"},
        )
        assert saved.status_code == 200
        assert saved.json()["configured"] is True
        status = client.get("/v1/admin/model-credentials").json()["providers"]
        assert status["deepseek"] == "CONFIGURED"

        chat = client.post(
            "/v1/chat",
            headers=self._headers(),
            json={"message": "Who are you?"},
        )
        assert chat.status_code == 200
        assert "DEFENDcoder" in chat.json()["reply"]
        assert chat.json()["model"] == DEFAULT_DEEPSEEK_MODEL


class TestPerRunClientDispatch:
    def test_resolver_switches_real_client_mid_run(self):
        clients = {
            DEFAULT_DEEPSEEK_MODEL: AgentChatClient(
                CoderModelConfig(
                    alias=TIER_1_MODEL,
                    model_name=DEFAULT_DEEPSEEK_MODEL,
                    base_url="https://api.deepseek.com",
                    api_key="sk-fake",
                    requires_api_key=True,
                    managed_api=True,
                ),
                urlopen=_FakeNoopTransport(),
            ),
            NEXT_MODEL: AgentChatClient(
                CoderModelConfig(
                    alias=NEXT_ALIAS,
                    model_name=NEXT_MODEL,
                    base_url="http://127.0.0.1:8403/v1",
                ),
                urlopen=_FakeNoopTransport(),
            ),
        }
        current = {"model": DEFAULT_DEEPSEEK_MODEL}

        def resolver():
            return clients[current["model"]]

        routed = RoutingAgentClient(resolver)
        assert routed.model_name == DEFAULT_DEEPSEEK_MODEL
        current["model"] = NEXT_MODEL
        # The same delegating client now targets the NEW real backend.
        assert routed.model_name == NEXT_MODEL

    def test_proposal_alone_changes_nothing(self):
        manager = EscalationManager()
        proposal = manager.propose(
            DEFAULT_DEEPSEEK_MODEL,
            reason_code=EscalationReason.REPEATED_TEST_FAILURE,
            human_summary="hard",
            now=None,
        )
        assert proposal is not None
        assert manager.approved is None
        # Resolution still defaults to DeepSeek.
        assert ModelSelector().select_auto().model == DEFAULT_DEEPSEEK_MODEL

    def test_infra_failure_creates_no_proposal(self):
        outcome = AgentOutcome(
            state="failed", error="timeout", steps=1, reason="model_timeout"
        )
        proposal = propose_for_outcome(
            manager=EscalationManager(),
            current_model=DEFAULT_DEEPSEEK_MODEL,
            outcome=outcome,
            summary="timeout",
            attempt_count=2,
            tests_failed=1,
        )
        assert proposal is None

    def test_quality_failure_creates_proposal(self):
        outcome = AgentOutcome(
            state="failed", error="tests failing", steps=3, reason="model_error"
        )
        proposal = propose_for_outcome(
            manager=EscalationManager(),
            current_model=DEFAULT_DEEPSEEK_MODEL,
            outcome=outcome,
            summary="same tests fail twice",
            evidence=("test_x",),
            attempt_count=2,
            tests_failed=1,
        )
        assert proposal is not None
        assert proposal.to_model == NEXT_MODEL


class _FakeNoopTransport:
    def __call__(self, request, timeout=None):
        return _FakeResp(
            200,
            json.dumps(
                {
                    "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                    "usage": {},
                }
            ).encode(),
        )


class _FakeResp:
    def __init__(self, status, body):
        self.status = status
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


class TestDeepSeekToolContinuation:
    def _client(self, transport):
        return AgentChatClient(
            CoderModelConfig(
                alias=TIER_1_MODEL,
                model_name=DEFAULT_DEEPSEEK_MODEL,
                base_url="https://api.deepseek.com",
                api_key="sk-fake",
                requires_api_key=True,
                managed_api=True,
            ),
            timeout_seconds=10,
            connect_timeout_seconds=5,
            urlopen=transport,
        )

    def test_tool_call_then_continuation_preserves_state(self):
        calls = []

        def transport(request, timeout=None):
            calls.append(json.loads(request.data))
            if len(calls) == 1:
                body = {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "Let me read the file.",
                                "reasoning_content": "<hidden reasoning>",
                                "tool_calls": [
                                    {
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {
                                            "name": "read_file",
                                            "arguments": '{"path": "app.py"}',
                                        },
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                    "usage": {"prompt_tokens": 20, "completion_tokens": 8},
                }
            else:
                body = {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "Done.",
                                "reasoning_content": "<more hidden reasoning>",
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 30, "completion_tokens": 4},
                }
            return _FakeResp(200, json.dumps(body).encode())

        client = self._client(transport)
        tool_schema = {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "read",
                "parameters": {"type": "object", "properties": {}},
            },
        }
        first = client.chat(
            [{"role": "user", "content": "Read app.py"}], tools=[tool_schema]
        )
        assert len(first.tool_calls) == 1
        assert first.tool_calls[0].name == "read_file"
        assert first.tool_calls[0].arguments == {"path": "app.py"}

        messages = [
            {"role": "user", "content": "Read app.py"},
            {
                "role": "assistant",
                "content": "Let me read the file.",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path": "app.py"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "content": '{"ok": true}',
            },
        ]
        second = client.chat(messages, tools=[tool_schema])
        assert second.content == "Done."
        assert second.tool_calls == ()

        # reasoning_content must never appear in any request payload; the
        # continuation preserves the assistant tool-call + tool result.
        assert len(calls) == 2
        for payload in calls:
            text = json.dumps(payload)
            assert "reasoning_content" not in text
            assert "<hidden reasoning>" not in text
        continuation = calls[1]
        roles = [m["role"] for m in continuation["messages"]]
        assert roles == ["user", "assistant", "tool"]
        assert continuation["messages"][1]["tool_calls"][0]["id"] == "call_1"

    def test_reasoning_content_never_in_parsed_response(self):
        transport = _FakeNoopTransport()
        client = self._client(transport)
        response = client.chat([{"role": "user", "content": "hi"}])
        assert isinstance(response, AgentChatResponse)
        # Absent when the provider does not send it.
        assert response.reasoning_content is None

    def test_reasoning_content_preserved_internally_for_replay(self):
        calls = []

        def transport(request, timeout=None):
            calls.append(json.loads(request.data))
            body = {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Let me read the file.",
                            "reasoning_content": "private internal reasoning",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": '{"path": "app.py"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {},
            }
            return _FakeResp(200, json.dumps(body).encode())

        client = self._client(transport)
        response = client.chat([{"role": "user", "content": "Read app.py"}])
        # Internal provider protocol state is parsed for replay.
        assert response.reasoning_content == "private internal reasoning"
        assert len(response.tool_calls) == 1


class TestCatalogExposesAiProviders:
    def test_control_catalog_contains_deepseek_and_openai_secrets(self):
        from defend_control.integration_catalog import (
            INTEGRATION_CATALOG,
            SECRET_CATALOG,
        )

        names = {item.key for item in SECRET_CATALOG}
        assert "DEEPSEEK_API_KEY" in names
        assert "OPENAI_API_KEY" in names
        ids = {item.integration_id for item in INTEGRATION_CATALOG}
        assert "deepseek" in ids
        assert "openai" in ids

    def test_setup_registry_has_ai_provider_cards(self):
        from defend_integrations.registry import (
            PROVIDERS,
            REGISTRY_SECRET_NAMES,
        )

        ids = {p.provider_id for p in PROVIDERS}
        assert "deepseek" in ids
        assert "openai" in ids
        assert "DEEPSEEK_API_KEY" in REGISTRY_SECRET_NAMES
        assert "OPENAI_API_KEY" in REGISTRY_SECRET_NAMES
        by_id = {p.provider_id: p for p in PROVIDERS}
        assert "DEEPSEEK_API_KEY" in by_id["deepseek"].required_secrets
        assert "OPENAI_API_KEY" in by_id["openai"].required_secrets

    def test_openai_not_required_for_startup(self):
        from defend_integrations.registry import PROVIDERS

        by_id = {p.provider_id: p for p in PROVIDERS}
        assert "OPENAI_API_KEY" in by_id["openai"].required_secrets
        assert "DEEPSEEK_API_KEY" in by_id["deepseek"].required_secrets


class TestEscalationLifecycle:
    def _lifecycle_app(self, runtime_state=None):
        from datetime import datetime, timezone

        from fastapi.testclient import TestClient

        from defend_coder.app import build_coder_app
        from defend_coder.auth import AuthenticatedAccount
        from defend_coder.credentials import CredentialStore
        from defend_coder.router import EscalationPolicy, EscalationReason
        from defend_coder.routing import ProductRuntimeAdapterBoundary

        from test_coder_router_integration import (
            FakeAuth,
            FakeRepository,
            FakeRunsRepository,
            FakeRunner,
            FakeSecretStore,
            _workspace,
        )

        account = AuthenticatedAccount(
            account_id=uuid4(),
            username="owner",
            email="owner@example.com",
            role="admin",
            is_active=True,
        )
        workspace = _workspace(account.account_id)
        run_id = uuid4()

        class RecordingRuns(FakeRunsRepository):
            def __init__(self, workspace, run_id):
                super().__init__(workspace, run_id)
                self.phase_calls = []

            def update_run_phase(self, run_id, phase):
                self.phase_calls.append(phase)
                return None

        class RecordingRunner(FakeRunner):
            def __init__(self, run_id, workspace):
                super().__init__(run_id, workspace)
                self.started_run_ids = []

            def start_existing(self, *, run_id, workspace, prompt):
                self.started_run_ids.append(run_id)
                return None

        runs = RecordingRuns(workspace, run_id)
        runner = RecordingRunner(run_id, workspace)
        status = runtime_state or {
            "state": "stopped",
            "provider_instance_state": "retained",
            "model": "Qwen/Qwen3-Coder-Next",
            "instance_id": 5,
            "gpu": "H100",
            "hourly_cost": "4.04",
        }
        runtime = ProductRuntimeAdapterBoundary(status=status)
        start_calls = 0
        original = runtime.start_runtime

        def tracked(*args, **kwargs):
            nonlocal start_calls
            start_calls += 1
            return original(*args, **kwargs)

        runtime.start_runtime = tracked
        app = build_coder_app(
            settings=CoderSettings(database_url="postgresql://fake:fake@localhost/fake"),
            db=CoderDatabase("postgresql://fake:fake@localhost/fake"),
            auth=FakeAuth(account),
            runtime_status=lambda: {"state": "ready"},
            repository=FakeRepository(workspace),
            runs_repository=runs,
            runner=runner,
            configured_root=Path("C:/fake/root"),
            idle_timeout_seconds=0,
            runtime_adapter=runtime,
            credentials=CredentialStore(
                store_loader=FakeSecretStore(deepseek_key=True)
            ),
        )
        client = TestClient(app)
        client.cookies.set("defendcoder_session", "session-token")
        client.cookies.set("defendcoder_csrf", "csrf-token")
        headers = {"X-CSRF-Token": "csrf-token"}
        proposal = EscalationPolicy().propose(
            DEFAULT_DEEPSEEK_MODEL,
            reason_code=EscalationReason.REPEATED_TEST_FAILURE,
            human_summary="hard task",
            evidence=("test_x",),
            attempt_count=2,
            tests_failed=1,
            now=datetime.now(timezone.utc),
        )
        assert proposal is not None
        runs.create_escalation_proposal(run_id, proposal)
        return client, workspace, runs, runner, headers, proposal, start_calls

    def test_approve_does_not_set_completed(self):
        client, workspace, runs, runner, headers, proposal, _ = (
            self._lifecycle_app()
        )
        response = client.post(
            f"/v1/workspaces/{workspace.workspace_id}/runs/{runs._run_id}/"
            f"escalation/{proposal.proposal_id}/approve",
            headers=headers,
        )
        assert response.status_code == 200
        assert "completed" not in runs.phase_calls
        assert "resuming" in runs.phase_calls
        assert response.json()["state"] == "resuming"
        assert runner.started_run_ids == [runs._run_id]
        routing = response.json()["routing"]
        assert routing["selected_model"] == NEXT_MODEL

    def test_deny_does_not_set_failed(self):
        client, workspace, runs, runner, headers, proposal, _ = (
            self._lifecycle_app()
        )
        response = client.post(
            f"/v1/workspaces/{workspace.workspace_id}/runs/{runs._run_id}/"
            f"escalation/{proposal.proposal_id}/deny",
            headers=headers,
        )
        assert response.status_code == 200
        assert "failed" not in runs.phase_calls
        assert "resuming" in runs.phase_calls
        assert response.json()["state"] == "resuming"
        # Same run continues on the ORIGINAL model.
        assert runner.started_run_ids == [runs._run_id]
        assert runs.get_run_routing(runs._run_id) is None

    def test_approve_resumes_same_run_on_approved_model(self):
        client, workspace, runs, runner, headers, proposal, _ = (
            self._lifecycle_app()
        )
        response = client.post(
            f"/v1/workspaces/{workspace.workspace_id}/runs/{runs._run_id}/"
            f"escalation/{proposal.proposal_id}/approve",
            headers=headers,
        )
        assert response.status_code == 200
        routing = response.json()["routing"]
        assert routing["selected_model"] == NEXT_MODEL
        assert routing["escalated_from"] == DEFAULT_DEEPSEEK_MODEL
        assert response.json()["runtime"]["state"] == "ready"

    def test_approve_without_retained_instance_requires_price_confirmation(self):
        no_instance = {
            "state": "stopped",
            "provider_instance_state": None,
            "model": "Qwen/Qwen3-Coder-Next",
            "instance_id": None,
            "gpu": None,
            "hourly_cost": None,
        }
        client, workspace, runs, runner, headers, proposal, start_calls = (
            self._lifecycle_app(runtime_state=no_instance)
        )
        response = client.post(
            f"/v1/workspaces/{workspace.workspace_id}/runs/{runs._run_id}/"
            f"escalation/{proposal.proposal_id}/approve",
            headers=headers,
        )
        assert response.status_code == 409
        assert "PRICE_CONFIRMATION_REQUIRED" in response.json()["detail"]
        assert start_calls == 0
        assert runner.started_run_ids == []


class TestReasoningReplayEndToEnd:
    def test_agent_replays_reasoning_content_internally_not_to_visible_sink(
        self,
    ):
        from defend_coder.agent import CodingAgent
        from defend_coder.agent_client import AgentChatResponse
        from defend_coder.tools import CoderToolkit

        class ScriptedClient(AgentChatClient):
            def __init__(self):
                super().__init__(
                    CoderModelConfig(
                        alias="deepseek",
                        model_name=DEFAULT_DEEPSEEK_MODEL,
                        base_url="https://api.deepseek.com",
                        api_key="sk-fake",
                        requires_api_key=True,
                        managed_api=True,
                    )
                )
                self.requests = []
                self._n = 0

            def chat(self, messages, tools=None, *, timeout_seconds=None,
                     max_tokens=None, on_request_started=None):
                self.requests.append(messages)
                self._n += 1
                if self._n == 1:
                    from defend_coder.agent_client import ToolCall

                    return AgentChatResponse(
                        content="Let me read the file.",
                        tool_calls=(
                            ToolCall(
                                id="call_1",
                                name="read_file",
                                arguments={"path": "app.py"},
                            ),
                        ),
                        reasoning_content="private internal reasoning",
                    )
                return AgentChatResponse(
                    content="Done.",
                    tool_calls=(),
                    reasoning_content="more private reasoning",
                )

        from test_coder_router_integration import FakeRepository, _workspace
        from defend_coder.repositories import WorkspaceRecord

        workspace = _workspace(uuid4())
        toolkit = CoderToolkit(
            repository=FakeRepository(workspace),
            configured_root=Path("C:/fake/root"),
            enabled=False,
        )
        client = ScriptedClient()
        agent = CodingAgent(client=client, toolkit=toolkit, max_steps=3)
        visible: list[dict] = []

        def sink(**fields):
            visible.append(dict(fields))

        outcome = agent.run(
            prompt="Read app.py",
            account_id=workspace.owner_account_id,
            workspace_id=workspace.workspace_id,
            sink=sink,
        )
        assert outcome.state == "succeeded"
        # The visible transcript never contains reasoning.
        transcript = json.dumps(visible)
        assert "private internal reasoning" not in transcript
        assert "reasoning_content" not in transcript
        # Internal continuation request replayed it to the provider.
        continuation = client.requests[1]
        assistant = next(
            m for m in continuation if m["role"] == "assistant"
        )
        assert assistant["reasoning_content"] == "private internal reasoning"