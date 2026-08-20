"""Pre-outcome prediction service: identity -> features -> market -> model
-> policy decision -> immutable prediction record -> shadow baselines.

LEAKAGE FIREWALL: no prediction is generated once the event outcome is
known to the system (a completed ``tt_match_results`` row for the event
blocks prediction entirely). Model probability is only recorded when the
Elo model is actually available; otherwise the record keeps model P NULL
and the reason codes say why (MODEL_NOT_READY / INSUFFICIENT_MODEL_HISTORY).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping
from uuid import UUID, uuid4

from defend_markets.domain import DecisionRecord, DecisionType, NoActionReason
from defend_markets.features import (
    FEATURE_CODE_VERSION,
    FEATURE_SCHEMA_VERSION,
    build_feature_snapshot,
)
from defend_markets.feeds import participant_key
from defend_markets.forecast import PredictionRecord, ShadowRecord
from defend_markets.identity import (
    IDENTITY_AMBIGUOUS,
    IDENTITY_UNRESOLVED,
    IdentityService,
)
from defend_markets.market_state import MARKET_METHOD_VERSION, build_market_state
from defend_markets.pipeline import DecisionPipeline, LoopOutcome
from defend_markets.sports_adapter import SportsDataReader
from defend_markets.store import MarketsStore
from defend_markets.tt_rating import TTEloModel

STRATEGY_KEY = "tt_elo_arb"
POLICY_KEY = "markets_core"
MARKET_KEY = "match_winner"
SPORT_KEY = "table_tennis"


@dataclass(frozen=True)
class TtPredictionOutcome:
    prediction_id: UUID
    decision: str
    reason_codes: tuple[str, ...]
    model_available: bool
    model_p_a: Decimal | None
    model_p_b: Decimal | None
    blocked: bool
    blocked_reason: str | None
    journal_ref: UUID | None
    event_key: str
    created_ts: datetime


class TtPredictionService:
    def __init__(
        self,
        *,
        reader: SportsDataReader,
        store: MarketsStore,
        forecast: Any,
        pipeline: DecisionPipeline,
        identity: IdentityService,
        clock: Any | None = None,
        strategy_key: str = STRATEGY_KEY,
        policy_key: str = POLICY_KEY,
    ) -> None:
        self._reader = reader
        self._store = store
        self._forecast = forecast
        self._pipeline = pipeline
        self._identity = identity
        self._clock = clock if clock is not None else (lambda: datetime.now(timezone.utc))
        self._strategy_key = strategy_key
        self._policy_key = policy_key

    def predict(self, event_key: str, *, cutoff: datetime | None = None) -> TtPredictionOutcome:
        now = cutoff if cutoff is not None else self._clock()

        if self._event_result_known(event_key):
            return self._blocked(event_key, now, "result_known")

        event = self._event(event_key)
        if event is None:
            return self._blocked(event_key, now, "event_not_found")

        league = str(event.get("league_key") or "table_tennis")
        names = self._event_names(event_key)
        if len(names) < 2:
            names = self._names_from_quotes(event_key)
        if len(names) < 2:
            return self._blocked(event_key, now, "participants_unresolved")

        a_name, b_name = names[0], names[1]
        identity_a = self._identity.resolve(
            a_name, provider="the_odds_api", raw_ref=str(event.get("event_key"))
        )
        identity_b = self._identity.resolve(
            b_name, provider="the_odds_api", raw_ref=str(event.get("event_key"))
        )
        identity_state = self._identity_state(identity_a, identity_b)
        if not self._identity.identity_allows_prediction(identity_state):
            decision = DecisionRecord(
                strategy_key=self._strategy_key,
                policy_key=self._policy_key,
                decision_type=DecisionType.NO_ACTION,
                reason_codes=(NoActionReason.LOW_IDENTITY_CONFIDENCE,),
                thesis="identity resolution blocked prediction",
                data_cutoff_timestamp=now,
                created_at=now,
            )
            prediction_id = self._record(
                event_key=event_key,
                now=now,
                names=(a_name, b_name),
                identity_a=identity_a,
                identity_b=identity_b,
                identity_state=identity_state,
                quotes=[],
                history=self._history_before(now),
                model=None,
                model_engine=None,
                decision=decision,
                decision_id=None,
                gate=None,
                league=league,
            )
            return TtPredictionOutcome(
                prediction_id=prediction_id,
                decision=decision.decision_type.value,
                reason_codes=(NoActionReason.LOW_IDENTITY_CONFIDENCE.value,),
                model_available=False,
                model_p_a=None,
                model_p_b=None,
                blocked=False,
                blocked_reason=None,
                journal_ref=None,
                event_key=event_key,
                created_ts=now,
            )

        history = self._history_before(now)
        quotes = self._reader.latest_odds(event_key, MARKET_KEY)
        prior = self._reader.odds_history(event_key, MARKET_KEY, before=now)[:4]
        market = build_market_state(quotes, cutoff=now, previous_quotes=prior)
        keys = (
            participant_key(league, a_name),
            participant_key(league, b_name),
        )
        model_engine = TTEloModel.from_history_rows(history)
        model = model_engine.evaluate(keys[0], keys[1])

        outcome = self._run(event_key, now)
        prediction_id = self._record(
            event_key=event_key,
            now=now,
            names=(a_name, b_name),
            identity_a=identity_a,
            identity_b=identity_b,
            identity_state=identity_state,
            quotes=quotes,
            history=history,
            model=model,
            model_engine=model_engine,
            decision=outcome.decision,
            decision_id=outcome.decision_id,
            gate=outcome.gate,
            league=league,
            market=market,
        )
        return TtPredictionOutcome(
            prediction_id=prediction_id,
            decision=outcome.decision.decision_type.value,
            reason_codes=tuple(code.value for code in outcome.decision.reason_codes),
            model_available=bool(model is not None and model.available),
            model_p_a=model.p_home if model is not None and model.available else None,
            model_p_b=model.p_away if model is not None and model.available else None,
            blocked=False,
            blocked_reason=None,
            journal_ref=outcome.decision_id,
            event_key=event_key,
            created_ts=now,
        )

    # ------------------------------------------------------------------
    def _run(self, event_key: str, now: datetime) -> LoopOutcome:
        return self._pipeline.evaluate_sports(
            event_key=event_key,
            market_key=MARKET_KEY,
            strategy_key=self._strategy_key,
            policy_key=self._policy_key,
        )

    def _record(
        self,
        *,
        event_key: str,
        now: datetime,
        names: tuple[str, str],
        identity_a: Mapping[str, object],
        identity_b: Mapping[str, object],
        identity_state: str,
        quotes: list[Any],
        history: list[Mapping[str, object]],
        model: Any,
        model_engine: Any,
        decision: DecisionRecord,
        decision_id: str | None,
        gate: Any,
        league: str,
        market: Any | None = None,
    ) -> UUID:
        market_payload = market.as_dict() if market is not None else {}
        snapshot = build_feature_snapshot(
            event_key=event_key,
            prediction_ts=now,
            player_a_key=participant_key(league, names[0]),
            player_a_name=names[0],
            player_a_identity_state=str(identity_a.get("identity_state")),
            player_b_key=participant_key(league, names[1]),
            player_b_name=names[1],
            player_b_identity_state=str(identity_b.get("identity_state")),
            history_rows=history,
            quotes=quotes,
            market_state_payload=market_payload,
            source_observation_ids=(
                str(quote.provenance.raw_ref)
                for quote in quotes
                if quote.provenance is not None and quote.provenance.raw_ref
            ),
        )
        snapshot_id = self._forecast.insert_feature_snapshot(
            event_key=event_key,
            prediction_ts=now,
            feature_schema_version=FEATURE_SCHEMA_VERSION,
            feature_code_version=FEATURE_CODE_VERSION,
            source_observation_ids=snapshot.source_observation_ids,
            payload=snapshot.payload(),
        )

        model_p_a = model.p_home if model is not None and model.available else None
        model_p_b = model.p_away if model is not None and model.available else None
        strategy = self._pipeline._registry.get(self._strategy_key).definition

        record = PredictionRecord(
            prediction_id=uuid4(),
            created_ts=now,
            event_key=event_key,
            sport_key=SPORT_KEY,
            player_a_name_at_prediction=names[0],
            player_b_name_at_prediction=names[1],
            player_a_id=_pid(identity_a),
            player_b_id=_pid(identity_b),
            feature_snapshot_id=snapshot_id,
            market_method_version=MARKET_METHOD_VERSION,
            market_p_a=_dec(market_payload.get("consensus_p_a")),
            market_p_b=_dec(market_payload.get("consensus_p_b")),
            best_price_a=_dec(market_payload.get("best_price_a")),
            best_price_b=_dec(market_payload.get("best_price_b")),
            consensus_p_a=_dec(market_payload.get("consensus_p_a")),
            consensus_p_b=_dec(market_payload.get("consensus_p_b")),
            overround=_dec(market_payload.get("overround")),
            book_count=int(market_payload["book_count"]) if "book_count" in market_payload else None,
            model_id=model_engine.label if model_engine is not None else "tt_elo",
            model_version=model_engine.version if model_engine is not None else "0.0.0",
            model_p_a=model_p_a,
            model_p_b=model_p_b,
            model_uncertainty=None,
            edge_gross=_edge_from_quotes(quotes),
            edge_net=None,
            data_age_seconds=_dec(market_payload.get("data_age_seconds")),
            provider_health=(
                str(gate.availability) if gate is not None else None
            ),
            identity_state=identity_state,
            strategy_id=strategy.strategy_key,
            strategy_version=strategy.version,
            strategy_lifecycle=strategy.lifecycle.value,
            decision=decision.decision_type.value,
            reason_codes=tuple(code.value for code in decision.reason_codes),
            risk_policy_version=decision.policy_version,
            journal_ref=decision_id,
        )
        prediction_id = self._forecast.insert_prediction(record)

        shadow = ShadowRecord(
            event_key=event_key,
            created_ts=now,
            prediction_id=prediction_id,
            market_p_a=_dec(market_payload.get("consensus_p_a")),
            market_p_b=_dec(market_payload.get("consensus_p_b")),
            elo_p_a=model_p_a,
            elo_p_b=model_p_b,
            model_id="tt_elo",
            model_version=model_engine.version if model_engine is not None else "0.0.0",
            strategy_id=strategy.strategy_key,
            strategy_version=strategy.version,
        )
        self._forecast.insert_shadow(shadow)
        return prediction_id

    def _event_result_known(self, event_key: str) -> bool:
        for row in self._store.catalog_tt_results():
            if str(row.get("event_key") or "") == event_key:
                return True
        return False

    def _event(self, event_key: str) -> dict[str, object] | None:
        for event in self._reader.tt_events():
            if str(event.get("event_key") or "") == event_key:
                return event
        return None

    def _event_names(self, event_key: str) -> list[str]:
        try:
            return self._reader.tt_event_participants(event_key)
        except AttributeError:
            return []

    def _names_from_quotes(self, event_key: str) -> list[str]:
        names: list[str] = []
        for quote in self._reader.latest_odds(event_key, MARKET_KEY):
            if quote.display_name and quote.display_name not in names:
                names.append(quote.display_name)
        return names

    def _history_before(self, now: datetime) -> list[dict[str, object]]:
        return [
            dict(row)
            for row in self._store.catalog_tt_results()
            if row.get("completed_at") is not None and row["completed_at"] < now
        ]

    def _identity_state(self, identity_a: Mapping[str, object], identity_b: Mapping[str, object]) -> str:
        states = {str(identity_a.get("identity_state")), str(identity_b.get("identity_state"))}
        if IDENTITY_UNRESOLVED in states:
            return IDENTITY_UNRESOLVED
        if IDENTITY_AMBIGUOUS in states:
            return IDENTITY_AMBIGUOUS
        if len(states) == 1:
            return states.pop()
        return "MIXED"

    def _blocked(self, event_key: str, now: datetime, reason: str) -> TtPredictionOutcome:
        return TtPredictionOutcome(
            prediction_id=uuid4(),
            decision="NO_ACTION",
            reason_codes=(reason,),
            model_available=False,
            model_p_a=None,
            model_p_b=None,
            blocked=True,
            blocked_reason=reason,
            journal_ref=None,
            event_key=event_key,
            created_ts=now,
        )


def _pid(identity: Mapping[str, object]) -> int | None:
    value = identity.get("participant_id")
    return int(value) if value is not None else None


def _dec(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (ValueError, ArithmeticError):
        return None


def _edge_from_quotes(quotes: list[Any]) -> Decimal | None:
    """Gross two-way edge from the latest quotes, mirroring the strategy."""
    if len(quotes) < 2:
        return None
    total = Decimal("0")
    for quote in quotes:
        if quote.decimal_odds is None:
            return None
        try:
            total += Decimal("1") / quote.decimal_odds
        except (ValueError, ArithmeticError, ZeroDivisionError):
            return None
    return Decimal("1") - total