"""Model/reasoner abstraction for DEFENDmarkets.

Domain logic must never embed a concrete model ID. Reasoning capability is
injected through the ``Reasoner`` protocol; ``NullReasoner`` ships as a
deterministic stub so every domain object stays usable without an LLM.
``TTReasoner`` is the deterministic L3 explanation layer for Table Tennis:
it consumes only L1/L2 outputs and never invents probabilities or edges.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
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
class TTReasoner:
    """Deterministic L3 explanation layer for the Table Tennis decision loop.

    Consumes the L1 strategy evaluation (arb edge, costs, provenance) and
    the L2 model evaluation (Elo ratings, games, form, model probability).
    Every figure in the output is a real L1/L2 value; nothing is invented.
    """

    label: str = "tt_elo_reasoner"
    version: str = "1.0.0"
    capabilities: frozenset[str] = frozenset(
        {"explain_l1", "explain_l2", "decline_on_insufficient_input"}
    )

    def reason(self, question: str, context: Mapping[str, object]) -> str:
        strategy = context.get("strategy") or {}
        model = context.get("model") or {}
        p_home = model.get("p_home")
        if p_home is None:
            reason = model.get("reason") or "insufficient model history"
            return (
                f"No model probability available for this matchup: {reason}. "
                "The decision loop therefore abstains regardless of the "
                "deterministic L1 signal."
            )
        parts: list[str] = []
        if isinstance(strategy, Mapping):
            gross = strategy.get("gross_edge")
            if isinstance(gross, Decimal):
                parts.append(
                    f"L1 arb gross edge {gross:.4f} from real quoted odds"
                )
            cost_total = strategy.get("cost_total")
            if isinstance(cost_total, Decimal):
                parts.append(f"costs {cost_total:.4f}")
            net = strategy.get("net_edge")
            if isinstance(net, Decimal):
                parts.append(f"net edge {net:.4f}")
        parts.append(
            f"L2 Elo model (v{model.get('version') or 'unknown'}) rates home "
            f"{model.get('home_rating')} vs away {model.get('away_rating')} "
            f"over {model.get('home_games')} and {model.get('away_games')} "
            f"recorded matches"
        )
        form_home = model.get("home_form")
        if isinstance(form_home, Decimal):
            parts.append(f"home recent form {form_home:.2f}")
        pct = p_home if isinstance(p_home, Decimal) else None
        if pct is not None:
            parts.append(f"model P(home) {pct:.4f}")
        return ". ".join(parts) + "."


@dataclass(frozen=True)
class Model:
    """A predictive model attached to a desk strategy."""

    label: str
    version: str

    def evaluate(self, context: Mapping[str, object]) -> Mapping[str, object]:
        return {}


@dataclass(frozen=True)
class ModelRegistry:
    """Label-keyed predictive model lookup."""

    providers: Mapping[str, Model] = field(default_factory=dict)

    def get(self, label: str | None = None) -> Model | None:
        if not label:
            return None
        return self.providers.get(label)

    def labels(self) -> tuple[str, ...]:
        return tuple(sorted(self.providers))


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
    return ReasonerRegistry(
        {
            "null": NullReasoner(),
            TTReasoner().label: TTReasoner(),
        }
    )


def build_default_models() -> ModelRegistry:
    """Register the predictive models this deployment actually ships.

    The registry gates capability; the decision pipeline evaluates the
    model over real persisted match history at decision time.
    """
    from defend_markets.tt_rating import TTEloModel

    return ModelRegistry(
        {
            TTEloModel.label: Model(label=TTEloModel.label, version=TTEloModel.version),
        }
    )