"""First real decision loop.

Real Sports data -> normalize -> strategy evaluation -> costs -> health
gate -> risk policy -> typed OPPORTUNITY | NO_ACTION -> append-only journal.

The loop never manufactures an opportunity: it returns NO_ACTION with
machine-readable reason codes whenever data, provenance, costs, health or
policy do not support a defensible positive net edge.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Mapping, Sequence
from uuid import UUID

from defend_markets import risk as risk_module
from defend_markets.domain import (
    DataQualityAssessment,
    DecisionRecord,
    DecisionType,
    NoActionReason,
    Opportunity,
    RiskEvaluation,
    StrategyEvaluation,
)
from defend_markets.journal import DecisionSink, JournalEntry
from defend_markets.models import (
    ModelRegistry,
    ReasonerRegistry,
    build_default_reasoners,
)
from defend_markets.quality import HealthGate, HealthGateResult, ProviderHealthState
from defend_markets.sports_adapter import SportsDataReader, SportsSelectionQuote
from defend_markets.store import MarketsStore
from defend_markets.strategies import StrategyRegistry
from defend_markets.tt_rating import TTEloModel


def market_instrument_key(event_key: str, market_key: str) -> str:
    return f"sports:{event_key}:{market_key}"


@dataclass(frozen=True)
class LoopOutcome:
    decision: DecisionRecord
    decision_id: UUID | None = None
    opportunity: Opportunity | None = None
    opportunity_id: UUID | None = None
    gate: HealthGateResult | None = None
    risk: RiskEvaluation | None = None
    strategy: StrategyEvaluation | None = None

    @property
    def is_opportunity(self) -> bool:
        return self.decision.decision_type is DecisionType.OPPORTUNITY


def _leg_quality_score(quotes: Sequence[SportsSelectionQuote]) -> Decimal:
    """Deterministic provenance completeness score for the quoted legs."""
    if not quotes:
        return Decimal("0")
    scores: list[Decimal] = []
    for quote in quotes:
        stamp = quote.provenance
        if stamp is None:
            scores.append(Decimal("0.5"))
            continue
        score = Decimal("1.0")
        if stamp.observed_at is None:
            score -= Decimal("0.3")
        if stamp.received_at is None:
            score -= Decimal("0.3")
        if stamp.raw_ref is None:
            score -= Decimal("0.2")
        scores.append(max(Decimal("0"), score))
    return sum(scores, Decimal("0")) / len(scores)


class DecisionPipeline:
    """Evaluates one strategy against one real sports market and journals it."""

    def __init__(
        self,
        *,
        reader: SportsDataReader,
        registry: StrategyRegistry,
        store: MarketsStore,
        journal: DecisionSink,
        health_gate: HealthGate | None = None,
        reasoners: ReasonerRegistry | None = None,
        models: ModelRegistry | None = None,
        clock: object | None = None,
    ) -> None:
        self._reader = reader
        self._registry = registry
        self._store = store
        self._journal = journal
        self._health_gate = health_gate if health_gate is not None else HealthGate()
        self._reasoners = reasoners if reasoners is not None else build_default_reasoners()
        self._models = models if models is not None else ModelRegistry()
        self._clock = clock if clock is not None else (lambda: datetime.now(timezone.utc))

    def evaluate_sports(
        self,
        *,
        event_key: str,
        market_key: str,
        strategy_key: str = "tt_two_way_arb",
        policy_key: str = "markets_core",
        reasoner_label: str | None = None,
    ) -> LoopOutcome:
        now = self._clock()
        definition = self._registry.get(strategy_key).definition

        quotes = self._reader.latest_odds(event_key, market_key)
        if not quotes:
            return self._journal_no_action(
                strategy_key=strategy_key,
                policy_key=policy_key,
                thesis=f"No odds data for {event_key} {market_key}",
                reason_codes=(NoActionReason.NO_ELIGIBLE_DATA,),
                now=now,
            )

        normalized = [
            {
                "selection_key": quote.selection_key,
                "display_name": quote.display_name,
                "decimal_odds": quote.decimal_odds,
                "provenance": quote.provenance,
                "costs": quote.costs,
            }
            for quote in quotes
        ]
        inputs: dict[str, object] = {
            "selections": normalized,
            "params": definition.params,
        }
        model_context: dict[str, object] = {}
        if definition.model_label:
            inputs["model"] = self._evaluate_model(
                definition.model_label, normalized, now
            )
            model_context = {"model": inputs["model"], "version": inputs["model"].get("version")}
        strategy_eval = self._registry.evaluate(strategy_key, inputs)

        if not strategy_eval.eligible:
            reason = self._strategy_failure_reason(strategy_eval)
            return self._journal_no_action(
                strategy_key=strategy_key,
                policy_key=policy_key,
                thesis=self._thesis(
                    event_key,
                    market_key,
                    strategy_key,
                    model_context=model_context,
                    strategy={"gross_edge": strategy_eval.gross_edge},
                ),
                reason_codes=(reason,),
                now=now,
            )

        gate = self._evaluate_health(quotes)
        if not gate.ok:
            reason = (
                NoActionReason.PROVIDER_UNHEALTHY
                if any(r.startswith("provider_unhealthy") for r in gate.reasons)
                else NoActionReason.STALE_DATA
            )
            return self._journal_no_action(
                strategy_key=strategy_key,
                policy_key=policy_key,
                thesis=self._thesis(event_key, market_key, strategy_key),
                reason_codes=(reason,),
                now=now,
            )

        data_quality = min(gate.score, _leg_quality_score(quotes))
        policy = self._store.load_policy(policy_key)

        gross_edge = strategy_eval.gross_edge
        cost_estimate = strategy_eval.costs.total()
        net_edge = (
            gross_edge - cost_estimate
            if gross_edge is not None and cost_estimate is not None
            else None
        )

        opportunity = Opportunity(
            instrument_key=market_instrument_key(event_key, market_key),
            strategy_key=strategy_key,
            strategy_version=definition.version,
            policy_key=policy_key,
            policy_version=policy.version,
            direction="arb",
            horizon="event",
            thesis=self._thesis(
                event_key,
                market_key,
                strategy_key,
                model_context=model_context,
                strategy={
                    "gross_edge": gross_edge,
                    "cost_total": cost_estimate,
                    "net_edge": net_edge,
                },
            ),
            counter_thesis="Overround reversion after quoting delays or stale prices.",
            evidence=strategy_eval.evidence,
            historical_analogs=(),
            gross_edge=gross_edge,
            net_edge=net_edge,
            costs=strategy_eval.costs,
            confidence=strategy_eval.confidence,
            expected_value=net_edge,
            max_loss=Decimal("0.02"),
            data_quality=data_quality,
            data_quality_note=None if gate.ok else "; ".join(gate.reasons),
            risk_tier=policy.tier,
            model_version=(
                str(model_context.get("version")) if model_context.get("version") else None
            ),
            model_probability=strategy_eval.model_probability,
            model_detail=dict(model_context.get("model") or {}),
            invalidation="Arb vanishes once either leg reprices below the edge threshold.",
            provenance=tuple(
                quote.provenance for quote in quotes if quote.provenance is not None
            ),
            generated_at=now,
            reasoner_label=reasoner_label,
        )

        if net_edge is None:
            return self._journal_no_action(
                strategy_key=strategy_key,
                policy_key=policy_key,
                thesis=opportunity.thesis,
                counter_thesis=opportunity.counter_thesis,
                reason_codes=(NoActionReason.COSTS_UNACCOUNTED,),
                now=now,
                opportunity=opportunity,
            )
        if net_edge <= Decimal("0"):
            return self._journal_no_action(
                strategy_key=strategy_key,
                policy_key=policy_key,
                thesis=opportunity.thesis,
                counter_thesis=opportunity.counter_thesis,
                reason_codes=(NoActionReason.COSTS_EXCEED_EDGE,),
                now=now,
                opportunity=opportunity,
            )

        risk_eval = risk_module.evaluate(opportunity, policy, desk="sports")
        if not risk_eval.accepted:
            return self._journal_no_action(
                strategy_key=strategy_key,
                policy_key=policy_key,
                thesis=opportunity.thesis,
                counter_thesis=opportunity.counter_thesis,
                reason_codes=(NoActionReason.BELOW_RISK_POLICY,),
                now=now,
                opportunity=opportunity,
                note="; ".join(risk_eval.reasons),
            )

        return self._journal_opportunity(
            opportunity=opportunity,
            strategy_key=strategy_key,
            policy_key=policy_key,
            now=now,
        )

    def _journal_opportunity(
        self,
        *,
        opportunity: Opportunity,
        strategy_key: str,
        policy_key: str,
        now: datetime,
    ) -> LoopOutcome:
        self._store.ensure_instrument(opportunity)
        opportunity_id = self._store.insert_opportunity(opportunity)
        decision = DecisionRecord(
            opportunity_id=str(opportunity_id),
            strategy_key=strategy_key,
            strategy_version=opportunity.strategy_version,
            policy_key=policy_key,
            policy_version=opportunity.policy_version,
            decision_type=DecisionType.OPPORTUNITY,
            thesis=opportunity.thesis,
            counter_thesis=opportunity.counter_thesis,
            confidence=opportunity.confidence,
            estimated_edge=opportunity.net_edge,
            cost_estimate=opportunity.cost_estimate,
            data_cutoff_timestamp=now,
            invalidation=opportunity.invalidation,
            model_version=opportunity.model_version,
            model_probability=opportunity.model_probability,
            created_at=now,
        )
        entry = self._journal.append(
            decision,
            opportunity_id=opportunity_id,
            strategy_id=self._store.strategy_id(strategy_key),
            policy_id=self._store.policy_id(policy_key),
        )
        return LoopOutcome(
            decision=entry.record,
            decision_id=entry.decision_id,
            opportunity=opportunity,
            opportunity_id=opportunity_id,
        )

    def _journal_no_action(
        self,
        *,
        strategy_key: str,
        policy_key: str,
        thesis: str,
        reason_codes: tuple[NoActionReason, ...],
        now: datetime,
        counter_thesis: str | None = None,
        opportunity: Opportunity | None = None,
        note: str | None = None,
    ) -> LoopOutcome:
        policy_version = self._store.load_policy(policy_key).version
        opportunity_id = (
            self._store.insert_opportunity(opportunity) if opportunity is not None else None
        )
        decision = DecisionRecord(
            opportunity_id=str(opportunity_id) if opportunity_id else None,
            strategy_key=strategy_key,
            strategy_version=(
                opportunity.strategy_version if opportunity is not None else
                self._registry.get(strategy_key).definition.version
            ),
            policy_key=policy_key,
            policy_version=policy_version,
            decision_type=DecisionType.NO_ACTION,
            reason_codes=reason_codes,
            thesis=thesis,
            counter_thesis=counter_thesis,
            confidence=opportunity.confidence if opportunity is not None else None,
            estimated_edge=opportunity.net_edge if opportunity is not None else None,
            cost_estimate=opportunity.cost_estimate if opportunity is not None else None,
            data_cutoff_timestamp=now,
            invalidation=opportunity.invalidation if opportunity is not None else None,
            model_version=opportunity.model_version if opportunity is not None else None,
            model_probability=(
                opportunity.model_probability if opportunity is not None else None
            ),
            created_at=now,
            note=note,
        )
        entry = self._journal.append(
            decision,
            opportunity_id=opportunity_id,
            strategy_id=self._store.strategy_id(strategy_key),
            policy_id=self._store.policy_id(policy_key),
        )
        return LoopOutcome(
            decision=entry.record,
            decision_id=entry.decision_id,
            opportunity=opportunity,
            opportunity_id=opportunity_id,
        )

    def _evaluate_model(
        self,
        model_label: str,
        normalized: Sequence[Mapping[str, object]],
        now: datetime,
    ) -> dict[str, object]:
        """Run the strategy's L2 model over real match history.

        Returns a mapping with ``available`` plus model outputs. The model
        source is the markets store's ``tt_match_results`` history; with
        no model registered or no history the result is unavailable and
        the strategy gate abstains.
        """
        model = self._models.get(model_label)
        if model is None:
            return {"available": False, "reason": f"model not registered: {model_label}"}
        keys = [
            str(item.get("selection_key") or "")
            for item in normalized
            if item.get("selection_key")
        ]
        if len(keys) < 2:
            return {"available": False, "reason": "model requires two selections"}
        history = self._store.catalog_tt_results()
        evaluator = TTEloModel.from_history_rows(history)
        evaluation = evaluator.evaluate(keys[0], keys[1])
        payload: dict[str, object] = {
            "available": evaluation.available,
            "reason": evaluation.reason,
            "version": f"{model.label}@{evaluator.version}",
            "p_home": evaluation.p_home,
            "p_away": evaluation.p_away,
            "home_rating": evaluation.home_rating,
            "away_rating": evaluation.away_rating,
            "home_games": evaluation.home_games,
            "away_games": evaluation.away_games,
            "home_form": evaluation.home_form,
            "away_form": evaluation.away_form,
            "calibration_bucket": evaluation.calibration_bucket,
            "player_a": keys[0],
            "player_b": keys[1],
        }
        return payload

    def _evaluate_health(self, quotes: Sequence[SportsSelectionQuote]) -> HealthGateResult:
        provider_states: dict[str, ProviderHealthState] = {}
        for source_key, state in self._reader.provider_health().items():
            provider_states[source_key] = ProviderHealthState(
                source_key=source_key,
                status=str(state.get("status") or "UNAVAILABLE"),
                observed_at=state.get("observed_at"),
            )
        quality: dict[str, DataQualityAssessment] = {}
        return self._health_gate.evaluate(provider_states, quality, now=self._clock())

    def _strategy_failure_reason(self, evaluation: StrategyEvaluation) -> NoActionReason:
        reasons = {str(reason) for reason in evaluation.reasons}
        if "missing_provenance" in reasons:
            return NoActionReason.MISSING_PROVENANCE
        if "insufficient_model_history" in reasons:
            return NoActionReason.INSUFFICIENT_MODEL_HISTORY
        if "no_arbitrage" in reasons or any(r.startswith("below_min_edge") for r in reasons):
            return NoActionReason.INSUFFICIENT_EDGE
        if NoActionReason.STRATEGY_NOT_ELIGIBLE.value in reasons:
            return NoActionReason.STRATEGY_NOT_ELIGIBLE
        return NoActionReason.INSUFFICIENT_EDGE

    def _thesis(
        self,
        event_key: str,
        market_key: str,
        strategy_key: str,
        model_context: Mapping[str, object] | None = None,
        strategy: Mapping[str, object] | None = None,
    ) -> str:
        base = f"{strategy_key} evaluation on {event_key} {market_key} using real observed odds."
        context = dict(model_context or {})
        if context.get("model"):
            context["strategy"] = dict(strategy or {})
            reasoner = self._reasoners.get("tt_elo_reasoner")
            return reasoner.reason("explain decision", context)
        return base