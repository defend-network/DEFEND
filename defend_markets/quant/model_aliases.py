"""Runtime model alias resolution for the Quant Director.

Production policy is alias-based. The default supervisory alias
``defendmarkets-quant-director`` maps to GPT-5.6 Terra (openai); the
high-value escalation profile maps to GPT-5.6 Sol. Concrete model IDs never
leak into domain code. When no OpenAI runtime credential is configured, callers
receive ``configured=False`` and tests use a deterministic/mock backend.
"""

from __future__ import annotations

from dataclasses import dataclass
import os


RUNTIME_ALIAS = "defendmarkets-quant-director"
DEEP_RESEARCH_ALIAS = "defendmarkets-quant-director-deep"


@dataclass(frozen=True)
class DirectorProfile:
    provider: str
    model: str
    reasoning: str

    def to_dict(self) -> dict[str, str]:
        return {
            "provider": self.provider,
            "model": self.model,
            "reasoning": self.reasoning,
        }


_ALIASES: dict[str, DirectorProfile] = {
    RUNTIME_ALIAS: DirectorProfile("openai", "gpt-5.6-terra", "high"),
    DEEP_RESEARCH_ALIAS: DirectorProfile("openai", "gpt-5.6-sol", "xhigh"),
}


def resolve_runtime_profile(alias: str = RUNTIME_ALIAS) -> DirectorProfile:
    return _ALIASES[alias]


def is_configured(provider: str = "openai") -> bool:
    if provider == "openai":
        return bool(
            (os.environ.get("OPENAI_API_KEY") or "").strip()
            or (os.environ.get("MARKETS_AI_API_KEY") or "").strip()
        )
    return bool((os.environ.get("MARKETS_AI_API_KEY") or "").strip())


def runtime_credentials_present() -> bool:
    return is_configured()
