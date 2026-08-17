"""Model/reasoner abstraction for DEFENDmarkets.

Domain logic must never embed a concrete model ID. Reasoning capability is
injected through the ``Reasoner`` protocol; ``NullReasoner`` ships as a
deterministic stub so every domain object stays usable without an LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol, runtime_checkable


@runtime_checkable
class Reasoner(Protocol):
    """Injected reasoning capability. Capabilities describe what a model may do."""

    @property
    def label(self) -> str: ...

    @property
    def version(self) -> str: ...

    @property
    def capabilities(self) -> frozenset[str]: ...

    def reason(self, question: str, context: Mapping[str, object]) -> str: ...


@dataclass(frozen=True)
class NullReasoner:
    """Deterministic stub: never invents analysis, always declines."""

    label: str = "null"
    version: str = "0.1.0"
    capabilities: frozenset[str] = frozenset({"decline"})

    def reason(self, question: str, context: Mapping[str, object]) -> str:
        return (
            "No model attached. Domain evaluation is deterministic; "
            "synthesis requires an injected reasoner."
        )


@dataclass(frozen=True)
class ReasonerRegistry:
    """Label-keyed reasoner lookup with an explicit null default."""

    providers: Mapping[str, Reasoner] = field(default_factory=dict)

    def get(self, label: str | None = None) -> Reasoner:
        if not label:
            return NullReasoner()
        provider = self.providers.get(label)
        return provider if provider is not None else NullReasoner()

    def labels(self) -> tuple[str, ...]:
        return tuple(sorted(self.providers))


def build_default_reasoners() -> ReasonerRegistry:
    return ReasonerRegistry({"null": NullReasoner()})