"""DEFENDmarkets FastAPI service — real data only.

Every endpoint reads live database state; desks or data that are not
available report an explicit unavailable state rather than fabricated
values.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from defend_markets.config import MarketsSettings
from defend_markets.db import MarketsDatabase
from defend_markets.feeds import odds_api_key
from defend_markets.journal import DecisionJournal
from defend_markets.models import (
    ModelRegistry,
    ReasonerRegistry,
    build_default_models,
    build_default_reasoners,
)
from defend_markets.pipeline import DecisionPipeline, LoopOutcome
from defend_markets.quality import HealthGate
from defend_markets.repositories import MarketsRepository
from defend_markets.shadow import (
    POST_COMMENCE,
    evaluation_report,
    last_valid_prematch,
)
from defend_markets.sports_adapter import SportsSelectionQuote
from defend_markets.store import MarketsStore, PostgresMarketsStore
from defend_markets.strategies import StrategyRegistry, build_default_registry

_TT_STRATEGY_KEY = "tt_two_way_arb"
_TT_MARKET_KEY = "match_winner"
_TT_FRESHNESS_MAX_AGE = timedelta(minutes=5)
_TT_ENTRY_POINT = "Setup & Integrations -> The Odds API -> THE_ODDS_API_KEY"


@dataclass(frozen=True)
class MarketsDependencies:
    settings: MarketsSettings
    database: MarketsDatabase | None = None
    sports_database: Any = None
    reader: Any = None
    registry: StrategyRegistry | None = None
    store: MarketsStore | None = None
    journal: Any = None
    forecast: Any = None
    pipeline: DecisionPipeline | None = None
    health_gate: HealthGate | None = None
    reasoners: ReasonerRegistry | None = None
    models: ModelRegistry | None = None
    clock: Callable[[], datetime] | None = None
    shadow: Any = None

    def build(self) -> "MarketsDependencies":
        store = self.store
        if store is None:
            if self.database is None:
                raise ValueError("database is required to build the default store")
            store = PostgresMarketsStore(self.database, MarketsRepository())
        registry = self.registry if self.registry is not None else build_default_registry()
        journal = self.journal
        if journal is None:
            if self.database is None:
                raise ValueError("database is required to build the default journal")
            journal = DecisionJournal(self.database, MarketsRepository())
        reasoners = self.reasoners if self.reasoners is not None else build_default_reasoners()
        models = self.models if self.models is not None else build_default_models()
        forecast = self.forecast
        if forecast is None and self.database is not None:
            from defend_markets.forecast_store import PostgresForecastStore

            forecast = PostgresForecastStore(self.database)
        health_gate = self.health_gate if self.health_gate is not None else HealthGate()
        pipeline = self.pipeline
        if pipeline is None and self.reader is not None:
            pipeline = DecisionPipeline(
                reader=self.reader,
                registry=registry,
                store=store,
                journal=journal,
                health_gate=health_gate,
                reasoners=reasoners,
                models=models,
                clock=self.clock,
            )
        return MarketsDependencies(
            settings=self.settings,
            database=self.database,
            sports_database=self.sports_database,
            reader=self.reader,
            registry=registry,
            store=store,
            journal=journal,
            forecast=forecast,
            pipeline=pipeline,
            health_gate=health_gate,
            reasoners=reasoners,
            models=models,
            clock=self.clock,
            shadow=self.shadow,
        )


def _desk_states() -> dict[str, dict[str, object]]:
    """Honest registry of desks: only Sports is implemented in DM0."""
    return {
        "overview": {"available": True, "status": "ready"},
        "opportunities": {"available": True, "status": "ready"},
        "sports": {"available": True, "status": "ready"},
        "equities": {"available": False, "status": "pending"},
        "macro": {"available": False, "status": "pending"},
        "crypto": {"available": False, "status": "pending"},
        "events": {"available": False, "status": "pending"},
        "strategies": {"available": True, "status": "ready"},
        "backtests": {"available": False, "status": "pending"},
        "journal": {"available": True, "status": "ready"},
        "data_health": {"available": True, "status": "ready"},
    }


class EvaluateSportsRequest(BaseModel):
    event_key: str
    market_key: str
    strategy_key: str = "tt_two_way_arb"
    policy_key: str = "markets_core"


def _outcome_payload(outcome: LoopOutcome) -> dict[str, object]:
    record = outcome.decision
    return {
        "decision_id": str(outcome.decision_id) if outcome.decision_id else None,
        "decision_type": record.decision_type.value,
        "reason_codes": [code.value for code in record.reason_codes],
        "strategy_key": record.strategy_key,
        "strategy_version": record.strategy_version,
        "policy_key": record.policy_key,
        "policy_version": record.policy_version,
        "thesis": record.thesis,
        "counter_thesis": record.counter_thesis,
        "confidence": str(record.confidence) if record.confidence is not None else None,
        "estimated_edge": str(record.estimated_edge) if record.estimated_edge is not None else None,
        "cost_estimate": str(record.cost_estimate) if record.cost_estimate is not None else None,
        "invalidation": record.invalidation,
        "created_at": (
            record.created_at.isoformat() if record.created_at is not None else None
        ),
        "opportunity_id": str(outcome.opportunity_id) if outcome.opportunity_id else None,
        "gate": (
            {
                "ok": outcome.gate.ok,
                "availability": outcome.gate.availability,
                "freshness_ok": outcome.gate.freshness_ok,
                "reasons": list(outcome.gate.reasons),
            }
            if outcome.gate is not None
            else None
        ),
    }


def _now(dependencies: MarketsDependencies) -> datetime:
    if dependencies.clock is not None:
        return dependencies.clock()
    return datetime.now(timezone.utc)


def _leg_quality_score(quotes: list[SportsSelectionQuote]) -> Decimal:
    """Deterministic provenance completeness score.

    Mirrors ``DecisionPipeline._leg_quality_score`` so the board shows the
    same data-quality basis the decision loop uses.
    """
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


def _freshness(observed_at: datetime | None, now: datetime) -> dict[str, object]:
    if observed_at is None:
        return {"ok": False, "status": "UNAVAILABLE", "age_seconds": None}
    age_seconds = max(0, int((now - observed_at).total_seconds()))
    ok = age_seconds <= _TT_FRESHNESS_MAX_AGE.total_seconds()
    return {
        "ok": ok,
        "status": "HEALTHY" if ok else "STALE",
        "age_seconds": age_seconds,
    }


def _normalized_legs(
    quotes: list[SportsSelectionQuote],
) -> list[dict[str, object]]:
    """Leg payloads with honest implied probabilities and provenance."""
    legs: list[dict[str, object]] = []
    for quote in quotes:
        stamp = quote.provenance
        implied = None
        if quote.decimal_odds is not None and quote.decimal_odds > Decimal("1"):
            implied = Decimal("1") / quote.decimal_odds
        legs.append(
            {
                "selection_key": quote.selection_key,
                "display_name": quote.display_name,
                "decimal_odds": (
                    str(quote.decimal_odds) if quote.decimal_odds is not None else None
                ),
                "implied_probability": str(implied) if implied is not None else None,
                "source_key": stamp.source_key if stamp is not None else None,
                "observed_at": (
                    stamp.observed_at.isoformat()
                    if stamp is not None and stamp.observed_at is not None
                    else None
                ),
                "received_at": (
                    stamp.received_at.isoformat()
                    if stamp is not None and stamp.received_at is not None
                    else None
                ),
                "raw_ref": stamp.raw_ref if stamp is not None else None,
            }
        )
    return legs


def _decision_summary(decision: dict[str, object]) -> dict[str, object]:
    return {
        "decision_id": decision.get("decision_id"),
        "decision_type": decision.get("decision_type"),
        "reason_codes": decision.get("reason_codes") or [],
        "thesis": decision.get("thesis"),
        "estimated_edge": decision.get("estimated_edge"),
        "cost_estimate": decision.get("cost_estimate"),
        "confidence": decision.get("confidence"),
        "created_at": decision.get("created_at"),
        "model_version": decision.get("model_version"),
        "model_probability": decision.get("model_probability"),
    }


def _max_drawdown(outcomes: list[dict[str, object]]) -> Decimal | None:
    pnl_values: list[Decimal] = []
    for outcome in outcomes:
        pnl = outcome.get("pnl")
        if pnl is not None:
            pnl_values.append(Decimal(str(pnl)))
    if len(pnl_values) < 2:
        return None
    peak = Decimal("0")
    cumulative = Decimal("0")
    max_dd = Decimal("0")
    for pnl in pnl_values:
        cumulative += pnl
        peak = max(peak, cumulative)
        max_dd = max(max_dd, peak - cumulative)
    return max_dd


def _tt_data_status_payload(dependencies: MarketsDependencies) -> dict[str, object]:
    """TT DATA: odds/results feed configuration, history and model readiness.

    Honest status only: every value is read from the key resolution, the
    markets feed table, the sports provider health and tt_match_results.
    """
    deps = dependencies
    env_key = os.environ.get("THE_ODDS_API_KEY", "").strip()
    key_configured = bool(odds_api_key())
    key_source = "environment" if env_key else ("secret_store" if key_configured else None)

    results_feed: dict[str, object] = {
        "provider_id": "the_odds_api_tt",
        "configured": key_configured,
        "status": "UNREGISTERED",
        "last_attempt_at": None,
        "last_success_at": None,
        "last_error": None,
        "records_ingested": None,
    }
    try:
        for feed in deps.store.list_feeds():
            if feed.get("provider_id") == "the_odds_api_tt":
                results_feed = {
                    "provider_id": "the_odds_api_tt",
                    "configured": key_configured,
                    "status": feed.get("status"),
                    "last_attempt_at": feed.get("last_attempt_at"),
                    "last_success_at": feed.get("last_success_at"),
                    "last_error": feed.get("last_error"),
                    "records_ingested": feed.get("records_ingested"),
                }
                break
    except AttributeError:
        pass

    odds_feed: dict[str, object] = {
        "provider_id": "the_odds_api",
        "configured": key_configured,
        "status": "NOT_POLLED",
        "last_success_at": None,
        "live_events": None,
    }
    if deps.reader is not None:
        odds_feed["live_events"] = len(deps.reader.tt_events())
        try:
            health = deps.reader.provider_health()
        except AttributeError:
            health = {}
        probe = health.get("the_odds_api")
        if probe is not None:
            odds_feed["status"] = probe.get("status") or "UNKNOWN"
            odds_feed["last_success_at"] = probe.get("observed_at")
    else:
        odds_feed["status"] = "SPORTS_DB_NOT_CONFIGURED"

    history = deps.store.catalog_tt_results() if deps.store is not None else []
    completed_matches = len(history)
    player_games: dict[str, int] = {}
    for row in history:
        for key in ("home_participant_key", "away_participant_key"):
            value = row.get(key)
            if value:
                player_games[str(value)] = player_games.get(str(value), 0) + 1
    min_games = 5
    players_over_threshold = sum(1 for games in player_games.values() if games >= min_games)
    top_players = [
        {"participant_key": key, "games": games}
        for key, games in sorted(player_games.items(), key=lambda item: (-item[1], item[0]))
    ][:5]

    return {
        "as_of": _now(deps).isoformat(),
        "key": {
            "configured": key_configured,
            "source": key_source,
            "entry_point": _TT_ENTRY_POINT,
        },
        "results_feed": results_feed,
        "odds_feed": odds_feed,
        "model_history": {
            "completed_matches": completed_matches,
            "players_with_history": len(player_games),
            "min_games_per_player": min_games,
            "players_over_threshold": players_over_threshold,
            "ready": players_over_threshold >= 2,
            "top_players": top_players,
        },
        "note": (
            "free tier: 500 credits/month; an h2h x 1-region odds call costs 1 credit; "
            "scores calls are also metered; keep poll intervals conservative"
        ),
    }


def _participant_keys_for_event(
    deps: MarketsDependencies,
    event: dict[str, object],
    selection_keys: list[str],
) -> list[str]:
    """Map a TT event to Elo participant keys matching tt_match_results.

    The results feed keys history by player name (participant_key(sport_key,
    name)) while live odds selections are position keys (home/away). Bridge
    the two through the provider's raw participant names when available,
    falling back to the selection keys when they are not.
    """
    from defend_markets.feeds import participant_key

    try:
        names = deps.reader.tt_event_participants(str(event["event_key"]))
    except AttributeError:
        names = []
    if len(names) >= 2:
        league = str(event.get("league_key") or "table_tennis")
        return [participant_key(league, names[0]), participant_key(league, names[1])]
    return list(selection_keys)


def _board_payload(dependencies: MarketsDependencies) -> dict[str, object]:
    deps = dependencies
    now = _now(deps)
    decisions = deps.store.catalog_decisions(limit=1000)
    by_instrument: dict[str, dict[str, object]] = {}
    for decision in decisions:
        key = decision.get("instrument_key")
        if key:
            by_instrument.setdefault(str(key), decision)

    from defend_markets.tt_rating import TTEloModel

    elo_model = TTEloModel.from_history_rows(deps.store.catalog_tt_results())

    events: list[dict[str, object]] = []
    for event in deps.reader.tt_events():
        event_key = str(event["event_key"])
        quotes = deps.reader.latest_odds(event_key, _TT_MARKET_KEY)
        strategy = deps.registry.get(_TT_STRATEGY_KEY).definition
        evaluation = deps.registry.evaluate(
            _TT_STRATEGY_KEY,
            {
                "selections": [
                    {
                        "selection_key": quote.selection_key,
                        "display_name": quote.display_name,
                        "decimal_odds": quote.decimal_odds,
                        "provenance": quote.provenance,
                        "costs": quote.costs,
                    }
                    for quote in quotes
                ],
                "params": strategy.params,
            },
        )

        legs = _normalized_legs(quotes)
        observed_times = [
            quote.provenance.observed_at
            for quote in quotes
            if quote.provenance is not None and quote.provenance.observed_at is not None
        ]
        latest_observed = max(observed_times) if observed_times else None

        live = deps.reader.latest_live_state(event_key)

        gross_edge = evaluation.gross_edge
        cost_total = evaluation.costs.total()
        net_edge = (
            gross_edge - cost_total
            if gross_edge is not None and cost_total is not None
            else None
        )
        decision = by_instrument.get(f"sports:{event_key}:{_TT_MARKET_KEY}")

        selection_keys = [quote.selection_key for quote in quotes if quote.selection_key]
        model_participants = _participant_keys_for_event(deps, event, selection_keys)
        model_eval = None
        if len(model_participants) >= 2:
            model_eval = elo_model.evaluate(model_participants[0], model_participants[1])
        model_detail: dict[str, object] = {}
        if model_eval is not None:
            model_detail = {
                "model": "tt_elo",
                "version": elo_model.version,
                "available": model_eval.available,
                "reason": model_eval.reason,
                "home_participant_key": (
                    model_participants[0] if model_participants else None
                ),
                "away_participant_key": (
                    model_participants[1] if len(model_participants) > 1 else None
                ),
                "p_home": str(model_eval.p_home) if model_eval.p_home is not None else None,
                "p_away": str(model_eval.p_away) if model_eval.p_away is not None else None,
                "home_rating": (
                    str(model_eval.home_rating) if model_eval.home_rating is not None else None
                ),
                "away_rating": (
                    str(model_eval.away_rating) if model_eval.away_rating is not None else None
                ),
                "home_games": model_eval.home_games,
                "away_games": model_eval.away_games,
                "home_form": (
                    str(model_eval.home_form) if model_eval.home_form is not None else None
                ),
                "away_form": (
                    str(model_eval.away_form) if model_eval.away_form is not None else None
                ),
                "calibration_bucket": model_eval.calibration_bucket,
            }

        events.append(
            {
                "event_key": event_key,
                "display_name": event.get("display_name"),
                "scheduled_at": event.get("scheduled_at"),
                "league_key": event.get("league_key"),
                "market_key": _TT_MARKET_KEY,
                "live": live,
                "legs": legs,
                "gross_edge": (
                    str(gross_edge) if gross_edge is not None else None
                ),
                "costs": {
                    "components": {
                        name: (
                            str(value) if value is not None else None
                        )
                        for name, value in evaluation.costs.components().items()
                    },
                    "total": str(cost_total) if cost_total is not None else None,
                },
                "net_edge": str(net_edge) if net_edge is not None else None,
                "confidence": (
                    str(evaluation.confidence)
                    if evaluation.eligible and evaluation.confidence is not None
                    else None
                ),
                "model_probability": (
                    str(model_eval.p_home) if model_eval is not None and model_eval.available else None
                ),
                "model_probability_available": (
                    bool(model_eval is not None and model_eval.available)
                ),
                "model": model_detail or None,
                "data_quality": str(_leg_quality_score(quotes)),
                "freshness": _freshness(latest_observed, now),
                "strategy": {
                    "key": strategy.strategy_key,
                    "version": strategy.version,
                    "lifecycle": strategy.lifecycle.value,
                    "eligible": evaluation.eligible,
                    "reasons": list(evaluation.reasons),
                },
                "decision": (
                    _decision_summary(decision) if decision is not None else None
                ),
            }
        )

    provider_health = [
        {"source_key": key, "status": state.get("status")}
        for key, state in deps.reader.provider_health().items()
    ]
    return {
        "events": events,
        "provider_health": provider_health,
        "strategy_key": _TT_STRATEGY_KEY,
        "market_key": _TT_MARKET_KEY,
        "now": now.isoformat(),
    }


def _performance_payload(dependencies: MarketsDependencies) -> dict[str, object]:
    deps = dependencies
    now = _now(deps)
    decisions = deps.store.catalog_decisions(limit=1000)
    outcomes = deps.store.catalog_outcomes(limit=500)

    total = len(decisions)
    opportunities = sum(
        1 for decision in decisions
        if decision.get("decision_type") == "OPPORTUNITY"
    )
    no_actions = total - opportunities

    settled = [
        outcome for outcome in outcomes
        if outcome.get("result") in ("WON", "LOST", "VOID", "PUSH")
    ]
    won = sum(1 for outcome in settled if outcome.get("result") == "WON")
    pnl_values = [
        Decimal(str(outcome["pnl"]))
        for outcome in outcomes
        if outcome.get("pnl") is not None
    ]
    clv_values = [
        Decimal(str(outcome["clv"]))
        for outcome in outcomes
        if outcome.get("clv") is not None
    ]
    buckets: dict[str, int] = {}
    for outcome in outcomes:
        bucket = outcome.get("calibration_bucket")
        if bucket:
            buckets[str(bucket)] = buckets.get(str(bucket), 0) + 1

    drawdown = _max_drawdown(outcomes)
    return {
        "sample_size": {
            "decisions": total,
            "opportunities": opportunities,
            "no_actions": no_actions,
            "settled": len(settled),
        },
        "no_action_pct": (
            round(no_actions / total, 6) if total else None
        ),
        "net_pnl": (
            round(sum(pnl_values), 8) if pnl_values else None
        ),
        "win_rate": (
            round(won / len(settled), 6) if settled else None
        ),
        "roi": {
            "value": None,
            "available": False,
            "reason": "no stake basis is recorded in market_decisions or market_outcomes",
        },
        "clv": {
            "value": round(sum(clv_values) / len(clv_values), 8)
            if clv_values
            else None,
            "available": bool(clv_values),
            "reason": None if clv_values else "no resolved outcomes carry clv",
        },
        "calibration": {
            "available": bool(buckets),
            "buckets": buckets,
            "reason": None if buckets else "no settled outcomes carry a calibration bucket",
        },
        "max_drawdown": {
            "value": round(drawdown, 8) if drawdown is not None else None,
            "available": drawdown is not None,
            "reason": None if drawdown is not None else "fewer than 2 settled outcomes with pnl",
        },
        "as_of": now.isoformat(),
    }


def build_markets_app(dependencies: MarketsDependencies) -> FastAPI:
    deps = dependencies.build()
    settings = deps.settings

    app = FastAPI(
        title="DEFENDmarkets API",
        version="0.1.0",
        description="Cross-market research, ranking, and decision engine. Real data only.",
    )

    @app.get("/health")
    def health() -> dict[str, object]:
        if deps.database is None:
            return {"ok": False, "application_id": "markets", "database": "unavailable"}
        return deps.database.health()

    @app.get("/v1/desks")
    def desks() -> dict[str, object]:
        return _desk_states()

    @app.get("/v1/overview")
    def overview() -> dict[str, object]:
        counts = deps.store.counts()
        venues = []
        health_summary: dict[str, object] = {"ok": None, "sources": []}
        if deps.reader is not None:
            venues = deps.reader.venues()
            health_summary = {
                "ok": all(
                    str(state.get("status")) == "HEALTHY"
                    for state in deps.reader.provider_health().values()
                ),
                "sources": [
                    {"source_key": key, "status": state.get("status")}
                    for key, state in deps.reader.provider_health().items()
                ],
            }
        return {
            "application_id": "markets",
            "counts": counts,
            "venues": len(venues),
            "provider_health": health_summary,
            "desks": _desk_states(),
            "pit_availability": (
                list(deps.reader.pit_availability().provided)
                if deps.reader is not None
                else []
            ),
        }

    @app.get("/v1/catalog/instruments")
    def catalog_instruments(desk: str | None = None) -> dict[str, object]:
        return {"instruments": deps.store.catalog_instruments(desk=desk)}

    @app.get("/v1/catalog/events")
    def catalog_events() -> dict[str, object]:
        return {"events": deps.store.catalog_events()}

    @app.get("/v1/catalog/venues")
    def catalog_venues() -> dict[str, object]:
        if deps.reader is None:
            raise HTTPException(status_code=503, detail="Sports data source not configured")
        return {"venues": deps.reader.venues()}

    @app.get("/v1/opportunities")
    def opportunities(limit: int = 50) -> dict[str, object]:
        return {"opportunities": deps.store.catalog_opportunities(limit=limit)}

    @app.get("/v1/decisions")
    def decisions(limit: int = 50) -> dict[str, object]:
        return {"decisions": deps.store.catalog_decisions(limit=limit)}

    @app.get("/v1/policies")
    def policies() -> dict[str, object]:
        return {"policies": deps.store.catalog_policies()}

    @app.get("/v1/strategies")
    def strategies() -> dict[str, object]:
        return {"strategies": deps.store.catalog_strategies()}

    @app.get("/v1/data-quality")
    def data_quality(limit: int = 50) -> dict[str, object]:
        quality = deps.store.catalog_quality(limit=limit)
        sports_health: list[dict[str, object]] = []
        if deps.reader is not None:
            sports_health = [
                {"source_key": key, "status": state.get("status"), "observed_at": state.get("observed_at")}
                for key, state in deps.reader.provider_health().items()
            ]
        return {"quality_observations": quality, "sports_provider_health": sports_health}

    @app.get("/v1/sports/tt/data-status")
    def sports_tt_data_status() -> dict[str, object]:
        if deps.store is None:
            raise HTTPException(status_code=503, detail="Markets store not configured")
        return _tt_data_status_payload(deps)

    @app.get("/v1/sports/tt/ops")
    def sports_tt_ops() -> dict[str, object]:
        """TT prediction pipeline operations state (read-only, honest)."""
        if deps.forecast is None:
            raise HTTPException(status_code=503, detail="Forecast store not configured")
        forecast = deps.forecast
        open_predictions = forecast.open_predictions()
        settled = forecast.catalog_settlements()
        no_actions = forecast.catalog_predictions()
        collector_state: dict[str, object] = {}
        try:
            state = forecast.collector_state()
            if state is not None:
                collector_state = {
                    "status": state.get("quota_status"),
                    "detail": state.get("last_error"),
                    "last_cycle_at": state.get("last_cycle_at"),
                    "next_odds_poll_at": state.get("next_odds_poll_at"),
                    "quota_remaining": state.get("last_quota_remaining"),
                    "quota_used": state.get("last_quota_used"),
                }
        except AttributeError:
            pass
        return {
            "pipeline": "tt_prediction_pipeline.v1",
            "collector": collector_state,
            "open_predictions": len(open_predictions),
            "settled_predictions": len(settled),
            "no_action_records": len(
                [row for row in no_actions if str(row.get("decision")) == "NO_ACTION"]
            ),
            "total_prediction_records": len(no_actions),
        }

    @app.get("/v1/sports/tt/shadow/overview")
    def sports_tt_shadow_overview() -> dict[str, object]:
        """Phase D shadow engine overview (read-only, honest)."""
        if deps.shadow is None:
            raise HTTPException(status_code=503, detail="Shadow engine not configured")
        store = deps.shadow
        now = _now(deps)
        events = store.list_forward_events()
        by_state: dict[str, int] = {}
        matched = ambiguous = unmatched = 0
        prematch_obs = postcommence_obs = 0
        bookmakers: set[str] = set()
        m5_ready = m5_insufficient = 0
        stale_events = 0
        for event in events:
            by_state[event["state"]] = by_state.get(event["state"], 0) + 1
            level = event.get("match_level")
            if level == "AMBIGUOUS":
                ambiguous += 1
            elif level is None:
                unmatched += 1
            else:
                matched += 1
            canonical_id = event.get("canonical_event_id")
            if not canonical_id:
                continue
            for obs in store.list_observations(canonical_id):
                if obs["observation_class"] == POST_COMMENCE:
                    postcommence_obs += 1
                else:
                    prematch_obs += 1
                bookmakers.add(obs.get("bookmaker", ""))
            prediction = store.m5_prediction(canonical_id)
            if prediction is not None:
                if prediction.get("availability") == "AVAILABLE":
                    m5_ready += 1
                else:
                    m5_insufficient += 1
            if (
                event.get("scheduled_commence") <= now
                and event.get("last_odds_poll_at") is not None
                and (now - event["last_odds_poll_at"]) > timedelta(minutes=5)
            ):
                stale_events += 1
        report = evaluation_report(store.evaluation_rows())
        return {
            "as_of": now.isoformat(),
            "collector": {
                "events_discovered": len(events),
                "events_matched": matched,
                "events_ambiguous": ambiguous,
                "events_unmatched": unmatched,
                "prematch_observations": prematch_obs,
                "postcommence_rejected": postcommence_obs,
                "bookmakers": sorted(b for b in bookmakers if b),
                "stale_events": stale_events,
            },
            "m5": {"available": m5_ready, "insufficient_history": m5_insufficient},
            "evaluation": report,
        }

    @app.get("/v1/sports/tt/shadow/events")
    def sports_tt_shadow_events(
        state: str | None = None, limit: int = 100
    ) -> dict[str, object]:
        """Phase D forward events with live status (read-only)."""
        if deps.shadow is None:
            raise HTTPException(status_code=503, detail="Shadow engine not configured")
        store = deps.shadow
        now = _now(deps)
        rows: list[dict[str, object]] = []
        for event in store.list_forward_events(state=state)[:limit]:
            canonical_id = event.get("canonical_event_id")
            observations = (
                store.list_observations(canonical_id) if canonical_id else []
            )
            prematch_obs = [o for o in observations if o["observation_class"] != POST_COMMENCE]
            last_prematch = last_valid_prematch(observations)
            status = "UNMATCHED"
            if event.get("match_level") == "AMBIGUOUS":
                status = "AMBIGUOUS"
            elif canonical_id:
                if event["state"] == "SETTLED":
                    status = "SETTLED"
                elif event.get("scheduled_commence") <= now:
                    status = "LIVE"
                elif not prematch_obs:
                    status = "UNMATCHED"
                elif (
                    event.get("last_odds_poll_at") is not None
                    and (now - event["last_odds_poll_at"]) > timedelta(minutes=5)
                ):
                    status = "STALE"
                else:
                    status = "PREMATCH"
            prediction = store.m5_prediction(canonical_id) if canonical_id else None
            rows.append(
                {
                    "forward_event_id": event["forward_event_id"],
                    "provider": event.get("provider"),
                    "provider_event_id": event.get("provider_event_id"),
                    "canonical_event_id": canonical_id,
                    "match_level": event.get("match_level"),
                    "competition": event.get("competition"),
                    "player_a": event.get("player_a_name"),
                    "player_b": event.get("player_b_name"),
                    "scheduled_commence": (
                        event.get("scheduled_commence").isoformat()
                        if event.get("scheduled_commence")
                        else None
                    ),
                    "status": status,
                    "last_odds_poll_at": (
                        event.get("last_odds_poll_at").isoformat()
                        if event.get("last_odds_poll_at")
                        else None
                    ),
                    "observation_count": len(prematch_obs),
                    "last_valid_prematch_at": (
                        last_prematch["observed_at"].isoformat()
                        if last_prematch
                        else None
                    ),
                    "m5_p_a": prediction["p_a"] if prediction else None,
                    "m5_availability": (
                        prediction["availability"] if prediction else None
                    ),
                    "model_market_disagreement": (
                        store.list_ruler_rows(canonical_id)[-1].get("model_market_disagreement")
                        if canonical_id and store.list_ruler_rows(canonical_id)
                        else None
                    ),
                }
            )
        return {"as_of": now.isoformat(), "events": rows}

    @app.get("/v1/sports/tt/shadow/evaluation")
    def sports_tt_shadow_evaluation(
        limit: int = 200,
    ) -> dict[str, object]:
        """Phase D shadow evaluation rows (read-only, real settled data)."""
        if deps.shadow is None:
            raise HTTPException(status_code=503, detail="Shadow engine not configured")
        store = deps.shadow
        rows = store.evaluation_rows()[-limit:]
        return {
            "as_of": _now(deps).isoformat(),
            "evaluation": evaluation_report(rows),
            "recent": [
                {
                    "canonical_event_id": row["canonical_event_id"],
                    "result_id": row["result_id"],
                    "reference_class": row["reference_class"],
                    "settled_at": row["settled_at"].isoformat(),
                    "m5_p_a": row["m5_p_a"],
                    "market_no_vig_p_a": row["market_no_vig_p_a"],
                    "actual": row["actual"],
                }
                for row in rows
            ],
        }

    @app.get("/v1/sports/table-tennis")
    def sports_table_tennis() -> dict[str, object]:
        if deps.reader is None:
            raise HTTPException(status_code=503, detail="Sports data source not configured")
        return _board_payload(deps)

    @app.get("/v1/providers")
    def providers() -> dict[str, object]:
        if deps.store is None:
            raise HTTPException(status_code=503, detail="Markets store not configured")
        try:
            feeds = deps.store.list_feeds()
        except AttributeError:
            feeds = []
        return {"providers": feeds}

    @app.get("/v1/providers/{provider_id}/records")
    def provider_records(provider_id: str, limit: int = 50) -> dict[str, object]:
        if deps.store is None:
            raise HTTPException(status_code=503, detail="Markets store not configured")
        try:
            records = deps.store.list_records(provider_id, limit=limit)
        except AttributeError:
            raise HTTPException(status_code=404, detail=f"provider not found: {provider_id}") from None
        return {"provider_id": provider_id, "records": records}

    @app.get("/v1/performance")
    def performance() -> dict[str, object]:
        return _performance_payload(deps)

    @app.post("/v1/evaluate/sports")
    def evaluate_sports(request: EvaluateSportsRequest) -> dict[str, object]:
        if deps.pipeline is None:
            raise HTTPException(status_code=503, detail="Sports data source not configured")
        outcome = deps.pipeline.evaluate_sports(
            event_key=request.event_key,
            market_key=request.market_key,
            strategy_key=request.strategy_key,
            policy_key=request.policy_key,
        )
        return _outcome_payload(outcome)

    if deps.database is not None:
        quant_state = {
            "state": "NOT_CONFIGURED",
            "reason": "quant director not initialized",
            "runtime_model": "",
            "initialized": False,
        }
        try:
            from defend_markets.quant.config import QuantDirectorSettings
            from defend_markets.quant.orchestrator import MarketsIntelligenceOrchestrator
            from defend_markets.quant.routes import build_quant_router
            from defend_markets.quant.store import PostgresQuantStore
            from defend_markets.quant.tools import PostgresMarketTools

            quant_settings = QuantDirectorSettings.from_env()
            quant_store = PostgresQuantStore(deps.database)
            quant_tools = PostgresMarketTools(deps.database, quant_store)
            quant_orchestrator = MarketsIntelligenceOrchestrator(
                store=quant_store,
                tools=quant_tools,
                settings=quant_settings,
            )
            app.include_router(build_quant_router(quant_orchestrator))
            quant_state = quant_orchestrator.health_state()
        except Exception as exc:  # noqa: BLE001 - surfaced as FAILED state, never silent
            quant_state = {
                "state": "FAILED",
                "reason": f"quant director initialization failed: {type(exc).__name__}",
                "runtime_model": "",
                "initialized": False,
            }

        @app.get("/v1/quant/state")
        def quant_state_endpoint() -> dict[str, object]:
            return quant_state

    return app