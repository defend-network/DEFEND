"""V4 Pro convergence tests: identity/prompt-bundle registries, one prompt
authority, and core-request immutability (no live provider calls)."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from defend_coder.agent_client import AgentChatClient
from defend_coder.identity import default_identity_profile
from defend_coder.model_config import CoderModelConfig
from defend_coder.prompts import OWNER_DIRECTIVE_SHA256, owner_directive
from defend_coder.registry import (
    IdentityHashMismatchError,
    IdentityRegistry,
    IdentityUnavailableError,
    IdentityVersionMismatchError,
    PromptAuthorityComposer,
    PromptBundleHashMismatchError,
    PromptBundleRegistry,
    PromptBundleUnavailableError,
    build_prompt_bundle,
)


class TestIdentityRegistry:
    def test_resolve_missing_fails_closed(self):
        registry = IdentityRegistry()
        with pytest.raises(IdentityUnavailableError):
            registry.resolve("defendcoder-identity-v1", "99", None)

    def test_hash_mismatch_fails_closed(self):
        registry = IdentityRegistry()
        registry.register(default_identity_profile())
        with pytest.raises(IdentityHashMismatchError):
            registry.resolve(
                "defendcoder-identity-v1", "1", "0" * 64
            )

    def test_resolve_returns_exact_profile(self):
        profile = default_identity_profile()
        registry = IdentityRegistry()
        registry.register(profile)
        resolved = registry.resolve(
            profile.profile_id, profile.version, profile.hash
        )
        assert resolved is profile

    def test_old_run_keeps_old_identity_after_activation(self):
        v1 = default_identity_profile()
        v2 = v1.with_content(version="2", communication_style="Concise.")
        registry = IdentityRegistry()
        registry.activate(v1)
        registry.activate(v2)
        # A historical run pinned to v1 still resolves v1.
        resolved_old = registry.resolve(v1.profile_id, "1", v1.hash)
        assert resolved_old.version == "1"
        assert resolved_old.hash == v1.hash
        # New runs get the active v2.
        assert registry.active().version == "2"


class TestPromptAuthority:
    def test_one_composer_includes_owner_directive_verbatim(self):
        composer = PromptAuthorityComposer()
        system = composer.compose(default_identity_profile(), provider="deepseek")
        directive = owner_directive().strip("\n")
        assert directive in system
        assert "[DEFEND OWNER DIRECTIVE]" in system
        assert "[DEFENDCODER PRODUCT IDENTITY]" in system
        assert "[TOOL / PERMISSION / SECURITY CONTRACT]" in system

    def test_identity_no_longer_bypasses_owner_directive(self):
        # The singular composer always includes the pinned owner directive;
        # there is no identity-only path that drops it.
        composer = PromptAuthorityComposer()
        for provider in ("deepseek", "self_hosted", "openai"):
            system = composer.compose(
                default_identity_profile(), provider=provider
            )
            assert owner_directive().strip("\n") in system

    def test_provider_technical_section_is_isolated(self):
        composer = PromptAuthorityComposer()
        deepseek = composer.compose(default_identity_profile(), provider="deepseek")
        openai = composer.compose(default_identity_profile(), provider="openai")
        # Governance sections identical; only the technical tail differs.
        assert "[DEFENDCODER PRODUCT IDENTITY]" in deepseek
        assert "[DEFENDCODER PRODUCT IDENTITY]" in openai
        assert deepseek.split("[PROVIDER TECHNICAL INSTRUCTIONS]")[0] == (
            openai.split("[PROVIDER TECHNICAL INSTRUCTIONS]")[0]
        )


class TestPromptBundle:
    def test_bundle_hash_deterministic_and_owner_directive_hash(self):
        a = build_prompt_bundle(default_identity_profile())
        b = build_prompt_bundle(default_identity_profile())
        assert a.hash == b.hash
        assert a.owner_directive_hash == OWNER_DIRECTIVE_SHA256
        public = a.as_public_dict()
        assert public["identity_profile_id"] == "defendcoder-identity-v1"
        assert public["identity_version"] == "1"

    def test_bundle_registry_fails_closed(self):
        registry = PromptBundleRegistry()
        with pytest.raises(PromptBundleUnavailableError):
            registry.resolve("defendcoder-prompt-v1", "9", None)

    def test_bundle_hash_mismatch_fails_closed(self):
        registry = PromptBundleRegistry()
        registry.register(build_prompt_bundle(default_identity_profile()))
        with pytest.raises(PromptBundleHashMismatchError):
            registry.resolve("defendcoder-prompt-v1", "1", "f" * 64)


class TestCoreRequestImmutability:
    def _client(self, default_extra_body):
        return AgentChatClient(
            CoderModelConfig(
                alias="deepseek",
                model_name="deepseek-v4-flash",
                base_url="https://api.deepseek.com",
                api_key="sk-fake",
                requires_api_key=True,
                managed_api=True,
            ),
            default_extra_body=default_extra_body,
        )

    def _capture(self, client):
        bodies = []

        class Resp:
            def __init__(self, body):
                self.status = 200
                self._body = body

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

        def transport(request, timeout=None):
            bodies.append(json.loads(request.data))
            return Resp(
                json.dumps(
                    {
                        "choices": [
                            {
                                "message": {"role": "assistant", "content": "ok"},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {},
                    }
                ).encode()
            )

        client._urlopen = transport
        return bodies

    def test_model_messages_tools_cannot_be_overridden(self):
        client = self._client(
            {
                "model": "gpt-5.6-sol",
                "messages": [{"role": "system", "content": "hijack"}],
                "tools": [{"type": "function", "function": {"name": "evil"}}],
                "thinking": {"type": "enabled"},
                "reasoning_effort": "max",
            }
        )
        bodies = self._capture(client)
        client.chat(
            [{"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {"name": "read_file"}}],
        )
        payload = bodies[0]
        assert payload["model"] == "deepseek-v4-flash"
        assert payload["messages"] == [{"role": "user", "content": "hi"}]
        assert payload["tools"][0]["function"]["name"] == "read_file"
        # The allowed provider field still flows through.
        assert payload["thinking"] == {"type": "enabled"}
        assert payload["reasoning_effort"] == "max"


class TestProductionConstruction:
    def test_app_constructs_with_converged_wiring(self):
        """Production-shape construction: registries + credentials + app.

        Proves the stale targets=/secret_resolver= wiring is gone and the
        converged constructor contract works end-to-end (no provider call).
        """
        from defend_coder.app import build_coder_app
        from defend_coder.config import CoderSettings
        from defend_coder.credentials import CredentialStore
        from defend_coder.db import CoderDatabase
        from defend_coder.registry import (
            IdentityRegistry,
            PromptAuthorityComposer,
            PromptBundleRegistry,
            build_prompt_bundle,
        )
        from test_coder_router_integration import (
            FakeAuth,
            FakeRepository,
            FakeRunsRepository,
            FakeRunner,
            FakeSecretStore,
            _account,
            _workspace,
        )
        from defend_coder.routing import ProductRuntimeAdapterBoundary

        account = _account(role="admin")
        workspace = _workspace(account.account_id)
        runs = FakeRunsRepository(workspace, uuid4())
        runner = FakeRunner(uuid4(), workspace)
        identity_registry = IdentityRegistry()
        identity_registry.activate(default_identity_profile())
        authority = PromptAuthorityComposer()
        prompt_registry = PromptBundleRegistry()
        prompt_registry.activate(
            build_prompt_bundle(identity_registry.active(), authority)
        )
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
            runtime_adapter=ProductRuntimeAdapterBoundary(),
            credentials=CredentialStore(
                store_loader=FakeSecretStore(deepseek_key=True)
            ),
            identity_registry=identity_registry,
            prompt_registry=prompt_registry,
            prompt_authority=authority,
        )
        assert app.title == "DEFENDcoder API"
        assert identity_registry.active().name == "DEFENDcoder"
        assert prompt_registry.active().owner_directive_hash == OWNER_DIRECTIVE_SHA256
