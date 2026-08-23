"""DEFENDcoder identity + prompt-bundle registries (fail-closed resolution).

ONE source of prompt authority. The server-owned identity profile and the
pinned owner directive are combined into an immutable, versioned, hashed
``DefendCoderPromptBundle``. Historical runs resolve their EXACT pinned
bundle by id/version/hash and fail closed (never silently substituting
today's files). Identity resolution is likewise fail-closed.

No secrets; no hidden reasoning.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Callable, Mapping

from .identity import (
    DefendCoderIdentityProfile,
    default_identity_profile,
)
from .prompts import (
    OWNER_DIRECTIVE_SHA256,
    owner_directive,
    qwen_technical_instructions,
)

PROVIDER_TECHNICAL: dict[str, Callable[[], str]] = {
    # OpenAI-compatible chat-completions lanes (DeepSeek, self-hosted vLLM)
    # share the pinned Qwen3CoderToolParser technical instructions.
    "deepseek": qwen_technical_instructions,
    "self_hosted": qwen_technical_instructions,
    # Sol (OpenAI Responses) receives a minimal provider technical section.
    "openai": lambda: (
        "Use the OpenAI Responses API contract. Functions/custom tools use "
        "the Responses tool shape. Keep all file and command activity within "
        "the authorized workspace."
    ),
}


class IdentityUnavailableError(RuntimeError):
    pass


class IdentityHashMismatchError(RuntimeError):
    pass


class IdentityVersionMismatchError(RuntimeError):
    pass


class PromptBundleUnavailableError(RuntimeError):
    pass


class PromptBundleHashMismatchError(RuntimeError):
    pass


@dataclass(frozen=True)
class PromptAuthorityComposer:
    """The SINGLE production system-authority composer.

    ``compose_core`` builds the provider-neutral governance core (identity +
    owner directive + contracts) that is pinned on runs. ``compose`` appends
    a provider technical section for the CURRENT route only — provider
    transport/protocol instructions NEVER enter the pinned core.
    """

    owner_directive_text: str = field(default_factory=owner_directive)

    def compose_core(self, profile: DefendCoderIdentityProfile) -> str:
        sections = [
            "[DEFENDCODER PRODUCT IDENTITY]",
            profile.system_policy,
            "[DEFEND OWNER DIRECTIVE]",
            self.owner_directive_text.strip("\n"),
            "[ENGINEERING OPERATING CONTRACT]",
            profile.engineering_contract,
            "[COMMUNICATION CONTRACT]",
            profile.communication_style,
            "[TOOL / PERMISSION / SECURITY CONTRACT]",
            profile.tool_behavior_rules,
        ]
        return "\n\n".join(sections)

    def compose(
        self,
        profile: DefendCoderIdentityProfile,
        *,
        provider: str = "deepseek",
    ) -> str:
        technical = PROVIDER_TECHNICAL.get(provider, lambda: "")()
        sections = [self.compose_core(profile)]
        if technical:
            sections += ["[PROVIDER TECHNICAL INSTRUCTIONS]", technical]
        return "\n\n".join(sections)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DefendCoderPromptBundle:
    """Immutable, versioned, hashed prompt bundle (no secrets)."""

    bundle_id: str
    version: str
    identity_profile_id: str
    identity_version: str
    owner_directive_hash: str
    engineering_contract_hash: str
    communication_contract_hash: str
    tool_policy_hash: str
    system_authority: str = field(repr=False)
    identity_hash: str = ""
    hash: str = field(default="")

    def __post_init__(self) -> None:
        if not self.hash:
            object.__setattr__(
                self,
                "hash",
                _sha256(
                    self.system_authority
                    + "\x1f"
                    + self.bundle_id
                    + "\x1f"
                    + self.version
                ),
            )

    def as_public_dict(self) -> dict[str, object]:
        return {
            "bundle_id": self.bundle_id,
            "version": self.version,
            "identity_profile_id": self.identity_profile_id,
            "identity_version": self.identity_version,
            "owner_directive_hash": self.owner_directive_hash,
            "engineering_contract_hash": self.engineering_contract_hash,
            "communication_contract_hash": self.communication_contract_hash,
            "tool_policy_hash": self.tool_policy_hash,
            "hash": self.hash,
        }


def build_prompt_bundle(
    profile: DefendCoderIdentityProfile,
    composer: PromptAuthorityComposer | None = None,
    *,
    provider: str = "deepseek",
    bundle_id: str = "defendcoder-prompt-v1",
    version: str = "1",
) -> DefendCoderPromptBundle:
    composer = composer or PromptAuthorityComposer()
    return DefendCoderPromptBundle(
        bundle_id=bundle_id,
        version=version,
        identity_profile_id=profile.profile_id,
        identity_version=profile.version,
        identity_hash=profile.hash,
        owner_directive_hash=OWNER_DIRECTIVE_SHA256,
        engineering_contract_hash=_sha256(profile.engineering_contract),
        communication_contract_hash=_sha256(profile.communication_style),
        tool_policy_hash=_sha256(profile.tool_behavior_rules),
        system_authority=composer.compose(profile, provider=provider),
    )


def build_prompt_core_bundle(
    profile: DefendCoderIdentityProfile,
    composer: PromptAuthorityComposer | None = None,
    *,
    bundle_id: str = "defendcoder-prompt-core-v1",
    version: str = "1",
) -> DefendCoderPromptBundle:
    """Provider-NEUTRAL governance core (no transport/technical instructions).

    Pinned on every run; provider technical profiles are appended per-route
    at generation time and NEVER enter this core.
    """
    composer = composer or PromptAuthorityComposer()
    return DefendCoderPromptBundle(
        bundle_id=bundle_id,
        version=version,
        identity_profile_id=profile.profile_id,
        identity_version=profile.version,
        identity_hash=profile.hash,
        owner_directive_hash=OWNER_DIRECTIVE_SHA256,
        engineering_contract_hash=_sha256(profile.engineering_contract),
        communication_contract_hash=_sha256(profile.communication_style),
        tool_policy_hash=_sha256(profile.tool_behavior_rules),
        system_authority=composer.compose_core(profile),
    )


class IdentityRegistry:
    """Versioned identity profiles with an explicit ACTIVE version.

    ``resolve`` recomputes the canonical hash and verifies it against the
    pinned expected hash; failures are distinct, closed, and never fall back
    to the active default.
    """

    def __init__(self) -> None:
        self._profiles: dict[tuple[str, str], DefendCoderIdentityProfile] = {}
        self._active: tuple[str, str] | None = None

    def register(self, profile: DefendCoderIdentityProfile) -> None:
        self._profiles[(profile.profile_id, profile.version)] = profile

    def activate(self, profile: DefendCoderIdentityProfile) -> None:
        self.register(profile)
        self._active = (profile.profile_id, profile.version)

    @property
    def active_key(self) -> tuple[str, str] | None:
        return self._active

    def active(self) -> DefendCoderIdentityProfile:
        if self._active is None:
            profile = default_identity_profile()
            self.activate(profile)
            return profile
        return self._profiles[self._active]

    def resolve(
        self,
        profile_id: str,
        version: str,
        expected_hash: str | None,
    ) -> DefendCoderIdentityProfile:
        profile = self._profiles.get((profile_id, version))
        if profile is None:
            raise IdentityUnavailableError(
                f"pinned identity {profile_id}@{version} is unavailable"
            )
        if profile.version != version:
            raise IdentityVersionMismatchError(
                f"identity version mismatch: requested {version}, got {profile.version}"
            )
        if expected_hash is not None and profile.hash != expected_hash:
            raise IdentityHashMismatchError(
                "pinned identity hash does not match the stored profile"
            )
        return profile


class PromptBundleRegistry:
    """Versioned prompt bundles with an explicit ACTIVE version.

    ``resolve`` verifies the pinned hash and fails closed on missing bundles
    or mismatches; it never reconstructs a bundle from today's files.
    """

    def __init__(self) -> None:
        self._bundles: dict[tuple[str, str], DefendCoderPromptBundle] = {}
        self._active: tuple[str, str] | None = None

    def register(self, bundle: DefendCoderPromptBundle) -> None:
        self._bundles[(bundle.bundle_id, bundle.version)] = bundle

    def activate(self, bundle: DefendCoderPromptBundle) -> None:
        self.register(bundle)
        self._active = (bundle.bundle_id, bundle.version)

    @property
    def active_key(self) -> tuple[str, str] | None:
        return self._active

    def active(self) -> DefendCoderPromptBundle:
        if self._active is None:
            bundle = build_prompt_bundle(default_identity_profile())
            self.activate(bundle)
            return bundle
        return self._bundles[self._active]

    def resolve(
        self,
        bundle_id: str,
        version: str,
        expected_hash: str | None,
    ) -> DefendCoderPromptBundle:
        bundle = self._bundles.get((bundle_id, version))
        if bundle is None:
            raise PromptBundleUnavailableError(
                f"pinned prompt bundle {bundle_id}@{version} is unavailable"
            )
        if expected_hash is not None and bundle.hash != expected_hash:
            raise PromptBundleHashMismatchError(
                "pinned prompt bundle hash does not match the stored bundle"
            )
        return bundle


@dataclass(frozen=True)
class ProviderTechnicalProfile:
    """Provider-specific protocol/transport instructions (NOT governance).

    The provider-neutral core remains pinned; only this profile varies by
    route. It must never contain DEFENDcoder identity/governance.
    """

    profile_id: str
    version: str
    provider: str
    protocol: str
    technical_instructions: str = field(repr=False)
    hash: str = field(default="")

    def __post_init__(self) -> None:
        if not self.hash:
            object.__setattr__(
                self,
                "hash",
                _sha256(
                    self.profile_id
                    + "\x1f"
                    + self.version
                    + "\x1f"
                    + self.provider
                    + "\x1f"
                    + self.protocol
                    + "\x1f"
                    + self.technical_instructions
                ),
            )

    def as_public_dict(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "version": self.version,
            "provider": self.provider,
            "protocol": self.protocol,
            "hash": self.hash,
        }


def build_provider_technical_profile(
    provider: str,
    *,
    version: str = "1",
) -> ProviderTechnicalProfile:
    if provider == "deepseek":
        return ProviderTechnicalProfile(
            profile_id="deepseek-v4-chat-v1",
            version=version,
            provider=provider,
            protocol="chat_completions",
            technical_instructions=qwen_technical_instructions(),
        )
    if provider in ("self_hosted", "qwen3-vllm"):
        return ProviderTechnicalProfile(
            profile_id="qwen3-coder-vllm-v1",
            version=version,
            provider=provider,
            protocol="chat_completions",
            technical_instructions=qwen_technical_instructions(),
        )
    if provider == "openai":
        return ProviderTechnicalProfile(
            profile_id="openai-responses-v1",
            version=version,
            provider=provider,
            protocol="responses",
            technical_instructions=(
                "Use the OpenAI Responses API contract. Functions/custom "
                "tools use the Responses tool shape. Keep all file and "
                "command activity within the authorized workspace."
            ),
        )
    raise ValueError(f"unknown provider {provider!r}")


class ProviderTechnicalUnavailableError(RuntimeError):
    pass


class ProviderTechnicalRegistry:
    def __init__(self) -> None:
        self._profiles: dict[tuple[str, str], ProviderTechnicalProfile] = {}

    def register(self, profile: ProviderTechnicalProfile) -> None:
        self._profiles[(profile.profile_id, profile.version)] = profile

    def for_provider(self, provider: str) -> ProviderTechnicalProfile:
        for key, profile in self._profiles.items():
            if profile.provider == provider:
                return profile
        profile = build_provider_technical_profile(provider)
        self.register(profile)
        return profile

    def resolve(
        self,
        profile_id: str,
        version: str,
        expected_hash: str | None = None,
    ) -> ProviderTechnicalProfile:
        profile = self._profiles.get((profile_id, version))
        if profile is None:
            raise ProviderTechnicalUnavailableError(
                f"provider technical profile {profile_id}@{version} is "
                "unavailable"
            )
        if expected_hash is not None and profile.hash != expected_hash:
            raise ProviderTechnicalUnavailableError(
                "provider technical profile hash mismatch"
            )
        return profile


@dataclass(frozen=True)
class RunExecutionEnvelope:
    """Complete persisted authority for ONE run. No secrets, no reasoning."""

    run_id: str
    workspace_id: str
    requested_mode: str
    provider: str
    model: str
    identity_profile_id: str
    identity_version: str
    identity_hash: str
    prompt_bundle_id: str
    prompt_bundle_version: str
    prompt_bundle_hash: str
    provider_technical_profile_id: str | None = None
    provider_technical_profile_version: str | None = None
    provider_technical_profile_hash: str | None = None
    checkpoint_ref: str | None = None

    def as_public_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "workspace_id": self.workspace_id,
            "requested_mode": self.requested_mode,
            "provider": self.provider,
            "model": self.model,
            "identity_profile_id": self.identity_profile_id,
            "identity_version": self.identity_version,
            "identity_hash": self.identity_hash,
            "prompt_bundle_id": self.prompt_bundle_id,
            "prompt_bundle_version": self.prompt_bundle_version,
            "prompt_bundle_hash": self.prompt_bundle_hash,
            "provider_technical_profile_id": self.provider_technical_profile_id,
            "provider_technical_profile_version": (
                self.provider_technical_profile_version
            ),
            "provider_technical_profile_hash": (
                self.provider_technical_profile_hash
            ),
            "checkpoint_ref": self.checkpoint_ref,
        }


class RunIntegrityError(RuntimeError):
    pass


class MissingIdentityPinError(RunIntegrityError):
    pass


class MissingPromptPinError(RunIntegrityError):
    pass


class MissingRouteError(RunIntegrityError):
    pass


class PromptIdentityIntegrityError(RunIntegrityError):
    pass


class RunAuthorityResolver:
    """Resolve the complete run authority from persisted pins, fail closed.

    ACTIVE configuration is used only while PREPARING A NEW RUN — never
    during old-run resolution. Missing pins, missing historical authority,
    hash mismatches, or identity/bundle cross-validation failures all raise
    a distinct error BEFORE any provider or tool activity.
    """

    def __init__(
        self,
        *,
        identity_registry: IdentityRegistry,
        prompt_registry: PromptBundleRegistry,
        technical_registry: ProviderTechnicalRegistry,
    ) -> None:
        self._identity = identity_registry
        self._prompt = prompt_registry
        self._technical = technical_registry

    def resolve(
        self,
        *,
        run_id: str,
        identity_pin: tuple[str, str, str] | None,
        prompt_pin: tuple[str, str, str] | None,
        route: tuple[str, str] | None,
        provider: str,
    ) -> RunExecutionEnvelope:
        if identity_pin is None:
            raise MissingIdentityPinError(
                f"run {run_id} has no identity pin; refusing execution"
            )
        if prompt_pin is None:
            raise MissingPromptPinError(
                f"run {run_id} has no prompt pin; refusing execution"
            )
        if route is None:
            raise MissingRouteError(
                f"run {run_id} has no route; refusing execution"
            )
        profile = self._identity.resolve(
            identity_pin[0], identity_pin[1], identity_pin[2]
        )
        bundle = self._prompt.resolve(
            prompt_pin[0], prompt_pin[1], prompt_pin[2]
        )
        # Cross-validate: the pinned bundle must belong to the pinned identity.
        if (
            bundle.identity_profile_id != profile.profile_id
            or bundle.identity_version != profile.version
            or bundle.identity_hash != profile.hash
        ):
            raise PromptIdentityIntegrityError(
                f"run {run_id} prompt bundle identity does not match the "
                "pinned identity"
            )
        technical = self._technical.for_provider(provider)
        requested_mode, model = route
        return RunExecutionEnvelope(
            run_id=run_id,
            workspace_id="",
            requested_mode=requested_mode,
            provider=provider,
            model=model,
            identity_profile_id=profile.profile_id,
            identity_version=profile.version,
            identity_hash=profile.hash,
            prompt_bundle_id=bundle.bundle_id,
            prompt_bundle_version=bundle.version,
            prompt_bundle_hash=bundle.hash,
            provider_technical_profile_id=technical.profile_id,
            provider_technical_profile_version=technical.version,
            provider_technical_profile_hash=technical.hash,
        )

    def compose_authority(
        self,
        envelope: RunExecutionEnvelope,
    ) -> str:
        """Compose the actual model system authority for a resolved run.

        Pinned provider-neutral core + current provider technical profile.
        """
        bundle = self._prompt.resolve(
            envelope.prompt_bundle_id,
            envelope.prompt_bundle_version,
            envelope.prompt_bundle_hash,
        )
        technical = self._technical.resolve(
            envelope.provider_technical_profile_id,
            envelope.provider_technical_profile_version,
            envelope.provider_technical_profile_hash,
        )
        return (
            bundle.system_authority
            + "\n\n[PROVIDER TECHNICAL INSTRUCTIONS]\n"
            + technical.technical_instructions
        )
