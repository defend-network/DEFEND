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

    Stable order: product identity -> owner directive -> engineering contract
    -> communication -> tool/security -> provider technical section. Dynamic
    workspace/task context is appended by the caller AFTER this block.
    """

    owner_directive_text: str = field(default_factory=owner_directive)

    def compose(
        self,
        profile: DefendCoderIdentityProfile,
        *,
        provider: str = "deepseek",
    ) -> str:
        technical = PROVIDER_TECHNICAL.get(provider, lambda: "")()
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
        owner_directive_hash=OWNER_DIRECTIVE_SHA256,
        engineering_contract_hash=_sha256(profile.engineering_contract),
        communication_contract_hash=_sha256(profile.communication_style),
        tool_policy_hash=_sha256(profile.tool_behavior_rules),
        system_authority=composer.compose(profile, provider=provider),
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
