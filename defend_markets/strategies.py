"""Versioned strategy registry.

Strategies exist as versioned definitions with a lifecycle; the LLM may
reason about a registered strategy but must never invent one ad hoc.
CLV is registered as PLANNED until real closing-line logic exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Callable, Mapping, Sequence

from defend_markets.domain import (
    CostModel,
    NoActionReason,
    StrategyDefinition,
    StrategyEvaluation,
    StrategyLifecycle,
    ProvenanceStamp,
)


EvaluationFn = Callable[[Mapping[str, object]], StrategyEvaluation]


@dataclass(frozen=True)
class RegisteredStrategy:
    definition: StrategyDefinition
    evaluator: EvaluationFn | None = None


def implied_probability(decimal_odds: Decimal) -> Decimal:
    if not isinstance(decimal_odds, Decimal) or decimal_odds <= Decimal("1"):
        raise ValueError("decimal odds must be > 1")
    return Decimal("1") / decimal_odds


def tt_two_way_arb_evaluate(inputs: Mapping[str, object]) -> StrategyEvaluation:
    """Deterministic two-way arb evaluation for a sports market.

    Mirrors the legacy TableTennis arb math (edge = 1 - sum of implied
    probabilities, minus commission). Costs are represented explicitly:
    no cost components are estimated here, so net edge stays None.
    """
    selections = inputs.get("selections")
    if not isinstance(selections, Sequence) or len(selections) != 2:
        return StrategyEvaluation(
            eligible=False,
            reasons=("requires_exactly_two_selections",),
        )

    params = inputs.get("params") or {}
    min_edge = Decimal(str(params.get("min_edge_pct", "0.5"))) / Decimal("100")
    commission = Decimal(str(params.get("commission", "0")))

    legs: list[tuple[str, Decimal, ProvenanceStamp | None, CostModel | None]] = []
    for selection in selections:
        if not isinstance(selection, Mapping):
            return StrategyEvaluation(eligible=False, reasons=("malformed_selection",))
        key = str(selection.get("selection_key") or "")
        raw_odds = selection.get("decimal_odds")
        if not key:
            return StrategyEvaluation(eligible=False, reasons=("selection_key_blank",))
        if not isinstance(raw_odds, Decimal) or raw_odds <= Decimal("1"):
            return StrategyEvaluation(
                eligible=False,
                reasons=(f"invalid_odds:{key}",),
            )
        provenance_raw = selection.get("provenance")
        provenance = (
            provenance_raw if isinstance(provenance_raw, ProvenanceStamp) else None
        )
        costs_raw = selection.get("costs")
        costs = costs_raw if isinstance(costs_raw, CostModel) else None
        legs.append((key, raw_odds, provenance, costs))

    require_provenance = bool(params.get("require_provenance", True))
    if require_provenance and any(provenance is None for _, _, provenance, _ in legs):
        return StrategyEvaluation(
            eligible=False,
            reasons=("missing_provenance",),
        )

    total = sum(implied_probability(odds) / (Decimal("1") - commission) for _, odds, _, _ in legs)
    if total >= Decimal("1"):
        return StrategyEvaluation(
            eligible=False,
            reasons=("no_arbitrage",),
        )

    gross_edge = Decimal("1") - total
    if gross_edge < min_edge:
        return StrategyEvaluation(
            eligible=False,
            reasons=(f"below_min_edge:{gross_edge}",),
            gross_edge=gross_edge,
        )

    evidence = tuple(
        {
            "selection_key": key,
            "decimal_odds": str(odds),
            "implied_probability": str(implied_probability(odds)),
            "source_key": provenance.source_key if provenance is not None else None,
            "observed_at": provenance.observed_at.isoformat() if provenance is not None and provenance.observed_at else None,
            "received_at": provenance.received_at.isoformat() if provenance is not None and provenance.received_at else None,
        }
        for key, odds, provenance, _ in legs
    )
    complete_provenance = all(
        provenance is not None
        and provenance.observed_at is not None
        and provenance.received_at is not None
        for _, _, provenance, _ in legs
    )
    confidence = Decimal("0.9") if complete_provenance else Decimal("0.4")

    costs = _combine_leg_costs(legs)

    return StrategyEvaluation(
        eligible=True,
        reasons=("two_way_arb",),
        gross_edge=gross_edge,
        costs=costs,
        evidence=evidence,
        confidence=confidence,
    )


def _combine_leg_costs(
    legs: Sequence[tuple[str, Decimal, ProvenanceStamp | None, CostModel | None]],
) -> CostModel:
    """Sum venue-supplied execution costs; unknown components stay None.

    The overround itself is the strategy signal and is never counted as
    an external execution cost here.
    """
    components = ("spread", "slippage", "fees", "other_costs")
    totals: dict[str, Decimal | None] = {}
    for name in components:
        values = [
            getattr(leg_costs, name)
            for _, _, _, leg_costs in legs
            if leg_costs is not None and getattr(leg_costs, name) is not None
        ]
        if len(values) == len(legs) and values:
            totals[name] = sum(values, Decimal("0"))
        else:
            totals[name] = None
    return CostModel(
        vig=None,
        spread=totals["spread"],
        slippage=totals["slippage"],
        fees=totals["fees"],
        other_costs=totals["other_costs"],
    )


_CLV_HYPOTHESIS = (
    "Closing line value: compare decision-time odds against closing odds to "
    "measure long-run edge. Not implemented; registered as PLANNED until a "
    "real closing-line capture and comparison pipeline exists."
)


class StrategyRegistry:
    def __init__(self) -> None:
        self._strategies: dict[tuple[str, int], RegisteredStrategy] = {}

    def register(self, strategy: StrategyDefinition, evaluator: EvaluationFn | None = None) -> None:
        key = (strategy.strategy_key, strategy.version)
        if key in self._strategies:
            raise ValueError(f"duplicate strategy registration: {strategy.strategy_key}@{strategy.version}")
        self._strategies[key] = RegisteredStrategy(definition=strategy, evaluator=evaluator)

    def get(self, strategy_key: str, version: int | None = None) -> RegisteredStrategy:
        if version is not None:
            candidate = self._strategies.get((strategy_key, version))
            if candidate is not None:
                return candidate
            raise KeyError(f"strategy not registered: {strategy_key}@{version}")
        versions = [
            item for (key, _), item in self._strategies.items() if key == strategy_key
        ]
        if not versions:
            raise KeyError(f"strategy not registered: {strategy_key}")
        return max(versions, key=lambda item: item.definition.version)

    def list(self) -> tuple[StrategyDefinition, ...]:
        return tuple(
            item.definition
            for item in sorted(
                self._strategies.values(),
                key=lambda item: (item.definition.strategy_key, item.definition.version),
            )
        )

    def evaluate(
        self,
        strategy_key: str,
        inputs: Mapping[str, object],
        version: int | None = None,
    ) -> StrategyEvaluation:
        registered = self.get(strategy_key, version)
        if registered.definition.lifecycle in (
            StrategyLifecycle.PLANNED,
            StrategyLifecycle.RETIRED,
        ):
            return StrategyEvaluation(
                eligible=False,
                reasons=(NoActionReason.STRATEGY_NOT_ELIGIBLE.value,),
            )
        if registered.evaluator is None:
            return StrategyEvaluation(
                eligible=False,
                reasons=(NoActionReason.STRATEGY_NOT_ELIGIBLE.value,),
            )
        return registered.evaluator(inputs)


def build_default_registry() -> StrategyRegistry:
    registry = StrategyRegistry()
    registry.register(
        StrategyDefinition(
            strategy_key="tt_two_way_arb",
            version=1,
            display_name="Table Tennis Two-Way Arbitrage",
            hypothesis=(
                "Two books quote opposing sides of a two-way market with summed "
                "implied probabilities below 1, leaving a bookmaker-free edge."
            ),
            lifecycle=StrategyLifecycle.EXPERIMENTAL,
            params={
                "min_edge_pct": "0.5",
                "commission": "0",
                "require_provenance": True,
            },
            source_ref="defend_markets.strategies:tt_two_way_arb_evaluate",
        ),
        tt_two_way_arb_evaluate,
    )
    registry.register(
        StrategyDefinition(
            strategy_key="tt_clv",
            version=1,
            display_name="Table Tennis Closing Line Value",
            hypothesis=_CLV_HYPOTHESIS,
            lifecycle=StrategyLifecycle.PLANNED,
            params={},
            source_ref="defend_markets.strategies:tt_clv_evaluate (planned)",
        ),
        None,
    )
    return registry