"""RunAuthority fail-closed resolution + provider-neutral core tests
(no live provider calls)."""

from __future__ import annotations

import pytest

from defend_coder.identity import default_identity_profile
from defend_coder.registry import (
    IdentityHashMismatchError,
    IdentityRegistry,
    MissingIdentityPinError,
    MissingPromptPinError,
    MissingRouteError,
    PromptAuthorityComposer,
    PromptBundleHashMismatchError,
    PromptBundleRegistry,
    PromptBundleUnavailableError,
    PromptIdentityIntegrityError,
    ProviderTechnicalRegistry,
    RunAuthorityResolver,
    build_prompt_core_bundle,
)


def _profile(v: str = "1"):
    if v == "1":
        return default_identity_profile()
    return default_identity_profile().with_content(
        version=v, communication_style="Terse."
    )


def _resolver():
    identity = IdentityRegistry()
    identity.activate(_profile("1"))
    prompt = PromptBundleRegistry()
    prompt.activate(build_prompt_core_bundle(identity.active()))
    technical = ProviderTechnicalRegistry()
    return RunAuthorityResolver(
        identity_registry=identity,
        prompt_registry=prompt,
        technical_registry=technical,
    )


def _pins(profile, bundle):
    return (
        (profile.profile_id, profile.version, profile.hash),
        (bundle.bundle_id, bundle.version, bundle.hash),
    )


class TestFailClosedResolution:
    def test_missing_identity_pin_fails_closed(self):
        resolver = _resolver()
        profile = default_identity_profile()
        bundle = build_prompt_core_bundle(profile)
        with pytest.raises(MissingIdentityPinError):
            resolver.resolve(
                run_id="r1",
                identity_pin=None,
                prompt_pin=(bundle.bundle_id, bundle.version, bundle.hash),
                route=("AUTO", "deepseek-v4-flash"),
                provider="deepseek",
            )

    def test_missing_prompt_pin_fails_closed(self):
        resolver = _resolver()
        profile = default_identity_profile()
        with pytest.raises(MissingPromptPinError):
            resolver.resolve(
                run_id="r1",
                identity_pin=(profile.profile_id, profile.version, profile.hash),
                prompt_pin=None,
                route=("AUTO", "deepseek-v4-flash"),
                provider="deepseek",
            )

    def test_missing_route_fails_closed(self):
        resolver = _resolver()
        profile = default_identity_profile()
        bundle = build_prompt_core_bundle(profile)
        with pytest.raises(MissingRouteError):
            resolver.resolve(
                run_id="r1",
                identity_pin=(profile.profile_id, profile.version, profile.hash),
                prompt_pin=(bundle.bundle_id, bundle.version, bundle.hash),
                route=None,
                provider="deepseek",
            )

    def test_identity_hash_mismatch_fails_closed(self):
        resolver = _resolver()
        profile = default_identity_profile()
        bundle = build_prompt_core_bundle(profile)
        with pytest.raises(IdentityHashMismatchError):
            resolver.resolve(
                run_id="r1",
                identity_pin=(profile.profile_id, profile.version, "0" * 64),
                prompt_pin=(bundle.bundle_id, bundle.version, bundle.hash),
                route=("AUTO", "deepseek-v4-flash"),
                provider="deepseek",
            )

    def test_prompt_hash_mismatch_fails_closed(self):
        resolver = _resolver()
        profile = default_identity_profile()
        bundle = build_prompt_core_bundle(profile)
        with pytest.raises(PromptBundleHashMismatchError):
            resolver.resolve(
                run_id="r1",
                identity_pin=(profile.profile_id, profile.version, profile.hash),
                prompt_pin=(bundle.bundle_id, bundle.version, "f" * 64),
                route=("AUTO", "deepseek-v4-flash"),
                provider="deepseek",
            )

    def test_historical_prompt_missing_fails_closed(self):
        resolver = _resolver()
        profile = default_identity_profile()
        with pytest.raises(PromptBundleUnavailableError):
            resolver.resolve(
                run_id="r1",
                identity_pin=(profile.profile_id, profile.version, profile.hash),
                prompt_pin=("missing-bundle", "9", None),
                route=("AUTO", "deepseek-v4-flash"),
                provider="deepseek",
            )

    def test_bundle_identity_mismatch_fails_closed(self):
        identity = IdentityRegistry()
        identity.activate(default_identity_profile())
        prompt = PromptBundleRegistry()
        composer = PromptAuthorityComposer()
        profile_v2 = _profile("2")
        bundle_v2 = build_prompt_core_bundle(
            profile_v2, composer, bundle_id="defendcoder-prompt-core-v2"
        )
        prompt.register(bundle_v2)
        resolver = RunAuthorityResolver(
            identity_registry=identity,
            prompt_registry=prompt,
            technical_registry=ProviderTechnicalRegistry(),
        )
        profile_v1 = default_identity_profile()
        # Pin identity v1 but prompt bundle built from v2 -> cross mismatch.
        with pytest.raises(PromptIdentityIntegrityError):
            resolver.resolve(
                run_id="r1",
                identity_pin=(
                    profile_v1.profile_id,
                    profile_v1.version,
                    profile_v1.hash,
                ),
                prompt_pin=(
                    bundle_v2.bundle_id,
                    bundle_v2.version,
                    bundle_v2.hash,
                ),
                route=("AUTO", "deepseek-v4-flash"),
                provider="deepseek",
            )

    def test_valid_resolution_builds_envelope_and_authority(self):
        resolver = _resolver()
        profile = default_identity_profile()
        bundle = build_prompt_core_bundle(profile)
        envelope = resolver.resolve(
            run_id="r1",
            identity_pin=(profile.profile_id, profile.version, profile.hash),
            prompt_pin=(bundle.bundle_id, bundle.version, bundle.hash),
            route=("AUTO", "deepseek-v4-flash"),
            provider="deepseek",
        )
        assert envelope.identity_hash == profile.hash
        assert envelope.prompt_bundle_hash == bundle.hash
        assert envelope.provider_technical_profile_id == "deepseek-v4-chat-v1"
        authority = resolver.compose_authority(envelope)
        assert "[DEFEND OWNER DIRECTIVE]" in authority
        assert "[PROVIDER TECHNICAL INSTRUCTIONS]" in authority
        # No secret/reasoning in the envelope.
        assert "reasoning" not in repr(envelope.as_public_dict()).lower()


class TestProviderNeutralCore:
    def test_core_bundle_excludes_provider_technical(self):
        core = build_prompt_core_bundle(default_identity_profile())
        assert "[PROVIDER TECHNICAL INSTRUCTIONS]" not in core.system_authority
        assert "[DEFEND OWNER DIRECTIVE]" in core.system_authority

    def test_provider_switch_keeps_core_governance(self):
        composer = PromptAuthorityComposer()
        core = composer.compose_core(default_identity_profile())
        deepseek = composer.compose(default_identity_profile(), provider="deepseek")
        openai = composer.compose(default_identity_profile(), provider="openai")
        assert deepseek.startswith(core)
        assert openai.startswith(core)
        # Only the technical tail differs.
        assert deepseek.split("[PROVIDER TECHNICAL INSTRUCTIONS]")[0] == (
            openai.split("[PROVIDER TECHNICAL INSTRUCTIONS]")[0]
        )

    def test_technical_profiles_isolated_by_provider(self):
        registry = ProviderTechnicalRegistry()
        deepseek = registry.for_provider("deepseek")
        openai = registry.for_provider("openai")
        assert deepseek.protocol == "chat_completions"
        assert openai.protocol == "responses"
        assert deepseek.profile_id != openai.profile_id


class TestProviderTechnicalContent:
    def test_deepseek_profile_never_contains_qwen_or_vllm(self):
        from defend_coder.registry import build_provider_technical_profile

        profile = build_provider_technical_profile("deepseek")
        text = profile.technical_instructions
        assert "Qwen3" not in text
        assert "Qwen3CoderToolParser" not in text
        assert "vLLM" not in text
        assert "chat completions" in text.lower() or "Chat Completions" in text

    def test_vllm_profile_contains_qwen_semantics(self):
        from defend_coder.registry import build_provider_technical_profile

        profile = build_provider_technical_profile("qwen3-vllm")
        assert "Qwen" in profile.technical_instructions

    def test_sol_profile_uses_responses(self):
        from defend_coder.registry import build_provider_technical_profile

        profile = build_provider_technical_profile("openai")
        assert profile.protocol == "responses"
        assert "Responses" in profile.technical_instructions

    def test_composed_deepseek_authority_has_no_qwen_parser(self):
        from defend_coder.registry import PromptAuthorityComposer

        composer = PromptAuthorityComposer()
        authority = composer.compose(
            default_identity_profile(), provider="deepseek"
        )
        # The DeepSeek technical section must not carry Qwen/vLLM tool-parser
        # instructions (the governance core may legitimately name providers
        # as implementation details).
        assert "Qwen3CoderToolParser" not in authority
        assert "[DEFEND OWNER DIRECTIVE]" in authority
