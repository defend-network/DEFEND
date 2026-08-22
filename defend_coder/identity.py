"""DEFENDcoder server-owned product identity profile + prompt composer.

The identity is SERVER OWNED and never replaced by user text or by the
underlying provider/model. Escalation (DeepSeek -> Next -> Sol) must NOT
change identity. The profile is versioned + hashed so every run can be
proven to have used one exact identity.

No secrets/credentials ever live in a profile.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Mapping

PRODUCT_NAME = "DEFENDcoder"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _stable_hash(fields: Mapping[str, object]) -> str:
    payload = "\x1f".join(f"{k}={v}" for k, v in sorted(fields.items()))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DefendCoderIdentityProfile:
    """Server-owned, versioned product identity (no secrets)."""

    name: str = PRODUCT_NAME
    version: str = "1"
    profile_id: str = "defendcoder-identity-v1"
    system_policy: str = (
        "You are DEFENDcoder, the software-engineering AI in the DEFEND "
        "platform. Help users understand, design, debug, build, test, and "
        "improve software. Be technically rigorous, practical, and clear. "
        "Never claim that you inspected, executed, modified, or verified "
        "something unless you actually did through the authorized tools. "
        "OpenCode, DeepSeek, Qwen, GPT, and vLLM are implementation details, "
        "not your identity."
    )
    engineering_contract: str = (
        "Work is verified before completion. Changes are targeted and "
        "reviewable. Use tools only when the answer requires repository or "
        "workspace state; answer directly otherwise. When a request requires "
        "filesystem, terminal, Git, or test authority and no authorized "
        "workspace is attached, explain that a workspace is required."
    )
    communication_style: str = (
        "Direct, practical, and evidence-based. Report what was done, what "
        "was observed, and what remains. When asked which underlying model "
        "is running, answer truthfully."
    )
    tool_behavior_rules: str = (
        "Tool authority is granted server-side and NEVER changes because the "
        "model changed. Keep all file and command activity within the "
        "authorized workspace. Never expose credentials or hidden reasoning."
    )
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    active: bool = True
    hash: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("profile name must not be empty")
        if not self.hash:
            object.__setattr__(
                self,
                "hash",
                _stable_hash(
                    {
                        "name": self.name,
                        "version": self.version,
                        "profile_id": self.profile_id,
                        "system_policy": self.system_policy,
                        "engineering_contract": self.engineering_contract,
                        "communication_style": self.communication_style,
                        "tool_behavior_rules": self.tool_behavior_rules,
                    }
                ),
            )

    def with_content(
        self,
        *,
        name: str | None = None,
        version: str | None = None,
        profile_id: str | None = None,
        system_policy: str | None = None,
        engineering_contract: str | None = None,
        communication_style: str | None = None,
        tool_behavior_rules: str | None = None,
    ) -> "DefendCoderIdentityProfile":
        """Create a NEW versioned profile (immutable; never mutate in place)."""
        return DefendCoderIdentityProfile(
            name=name if name is not None else self.name,
            version=version if version is not None else self.version,
            profile_id=profile_id if profile_id is not None else self.profile_id,
            system_policy=(
                system_policy
                if system_policy is not None
                else self.system_policy
            ),
            engineering_contract=(
                engineering_contract
                if engineering_contract is not None
                else self.engineering_contract
            ),
            communication_style=(
                communication_style
                if communication_style is not None
                else self.communication_style
            ),
            tool_behavior_rules=(
                tool_behavior_rules
                if tool_behavior_rules is not None
                else self.tool_behavior_rules
            ),
        )

    def as_public_dict(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "version": self.version,
            "name": self.name,
            "hash": self.hash,
            "active": self.active,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            # Policy fields are part of the versioned identity; they are
            # not secrets, but full text is not required in run metadata.
        }


def default_identity_profile() -> DefendCoderIdentityProfile:
    """Canonical DEFENDcoder identity (server owned)."""
    return DefendCoderIdentityProfile()


def identity_continuity(
    profiles: Mapping[str, DefendCoderIdentityProfile],
) -> bool:
    """True when every tier resolves the SAME identity profile (same hash)."""
    hashes = {profile.hash for profile in profiles.values()}
    return len(hashes) == 1


def compose_system_instructions(
    profile: DefendCoderIdentityProfile,
) -> str:
    """Stable system block: identity -> engineering contract -> tool rules.

    Order is fixed so the provider prompt-cache prefix stays stable; dynamic
    workspace/task context is composed separately and later.
    """
    return "\n\n".join(
        (
            f"[DEFENDCODER IDENTITY PROFILE {profile.version} "
            f"({profile.profile_id})]",
            profile.system_policy,
            "[ENGINEERING OPERATING CONTRACT]",
            profile.engineering_contract,
            "[COMMUNICATION STYLE]",
            profile.communication_style,
            "[TOOL AUTHORITY / SECURITY RULES]",
            profile.tool_behavior_rules,
        )
    )


def compose_run_context(
    *,
    workspace_facts: str | None = None,
    checkpoint: str | None = None,
    task: str | None = None,
) -> str:
    """Dynamic (non-cacheable) run context appended AFTER the stable block."""
    sections: list[str] = []
    if workspace_facts:
        sections.append("[WORKSPACE / REPOSITORY FACTS]\n" + workspace_facts)
    if checkpoint:
        sections.append("[CURRENT RUN CHECKPOINT]\n" + checkpoint)
    if task:
        sections.append("[CURRENT TASK]\n" + task)
    return "\n\n".join(sections)
