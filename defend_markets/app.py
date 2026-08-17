"""DEFENDmarkets FastAPI service — real data only.

Every endpoint reads live database state; desks or data that are not
available report an explicit unavailable state rather than fabricated
values.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from defend_markets.config import MarketsSettings
from defend_markets.db import MarketsDatabase
from defend_markets.journal import DecisionJournal
from defend_markets.models import ReasonerRegistry, build_default_reasoners
from defend_markets.pipeline import DecisionPipeline, LoopOutcome
from defend_markets.quality import HealthGate
from defend_markets.repositories import MarketsRepository
from defend_markets.store import MarketsStore, PostgresMarketsStore
from defend_markets.strategies import StrategyRegistry, build_default_registry


@dataclass(frozen=True)
class MarketsDependencies:
    settings: MarketsSettings
    database: MarketsDatabase | None = None
    sports_database: Any = None
    reader: Any = None
    registry: StrategyRegistry | None = None
    store: MarketsStore | None = None
    journal: Any = None
    pipeline: DecisionPipeline | None = None
    health_gate: HealthGate | None = None
    reasoners: ReasonerRegistry | None = None
    clock: Callable[[], datetime] | None = None

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
            pipeline=pipeline,
            health_gate=health_gate,
            reasoners=reasoners,
            clock=self.clock,
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

    return app