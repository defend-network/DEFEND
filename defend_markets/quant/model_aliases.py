"""Runtime model alias resolution for the Quant Director.

Alias-based routing mirrors DEFENDcoder and keeps concrete model/provider
identifiers and credential env-var names in the external ``runtime_models.json``
config, never in domain code. Default supervisory reasoning uses the V4 Flash
tier, escalation uses the V4 Pro tier, and the highest-value Sol profile
requires owner approval. When no runtime credential is configured, callers
receive ``configured=False`` and tests use a deterministic/mock backend.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


RUNTIME_ALIAS = "defendmarkets-quant-director"
DEEP_RESEARCH_ALIAS = "defendmarkets-quant-director-deep"
SOL_ALIAS = "defendmarkets-quant-director-sol"


@dataclass(frozen=True)
class DirectorProfile:
    provider: str
    model: str
    reasoning: str
    requires_approval: bool = False
    credential_env: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, str]:
        return {
            "provider": self.provider,
            "model": self.model,
            "reasoning": self.reasoning,
            "requires_approval": str(self.requires_approval).lower(),
        }


def _load_aliases() -> dict[str, DirectorProfile]:
    path = Path(__file__).with_name("runtime_models.json")
    raw = json.loads(path.read_text(encoding="utf-8"))
    aliases: dict[str, DirectorProfile] = {}
    for alias, entry in raw.items():
        aliases[alias] = DirectorProfile(
            provider=str(entry["provider"]),
            model=str(entry["model"]),
            reasoning=str(entry.get("reasoning", "")),
            requires_approval=bool(entry.get("requires_approval", False)),
            credential_env=tuple(str(name) for name in entry.get("credential_env", [])),
        )
    return aliases


_ALIASES = _load_aliases()


def resolve_runtime_profile(alias: str = RUNTIME_ALIAS) -> DirectorProfile:
    return _ALIASES[alias]


def _credential(profile: DirectorProfile) -> str | None:
    for name in profile.credential_env:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return None


def is_configured(provider: str | None = None) -> bool:
    profiles = (
        [profile for profile in _ALIASES.values() if profile.provider == provider]
        if provider is not None
        else list(_ALIASES.values())
    )
    return any(bool(_credential(profile)) for profile in profiles)


def runtime_credentials_present() -> bool:
    return is_configured()
