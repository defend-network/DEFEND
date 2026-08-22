"""Admin-only Markets AI chat routes.

Enforcement: unauthenticated -> 401, consumer/non-admin -> 403, admin ->
allowed. Responses come from the orchestrator's governed tools and persisted
chat history.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from admin_auth import AdminPrincipal, require_admin
from defend_markets.quant.orchestrator import MarketsIntelligenceOrchestrator

_ALLOWED_ROLES = {"admin", "owner"}


def _require_markets_admin(principal: AdminPrincipal) -> None:
    if principal.role not in _ALLOWED_ROLES:
        raise HTTPException(status_code=403, detail="Markets AI access requires admin")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    thread_id: int | None = None


class ResearchEntryRequest(BaseModel):
    hypothesis: str = Field(min_length=1, max_length=2000)
    rationale: str | None = None
    data_needed: str | None = None


class ProposalRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=2000)
    supporting_data: str | None = None
    expected_effect: str | None = None
    risk: str | None = None
    required_features: list[str] = Field(default_factory=list)
    evaluation_plan: str | None = None


def build_quant_router(orchestrator: MarketsIntelligenceOrchestrator) -> APIRouter:
    router = APIRouter(prefix="/api/markets/ai", tags=["markets-ai"])

    @router.get("/state")
    async def ai_state(_principal: AdminPrincipal = Depends(require_admin)) -> dict:
        _require_markets_admin(_principal)
        return {
            "markets_state": orchestrator.markets_state(),
            "quant_director_state": orchestrator.health_state(),
            "runtime_profile": orchestrator.runtime_profile(),
            "live_ai_configured": orchestrator.live_ai_configured(),
            "budget": orchestrator.budget_policy(),
            "budget_usage": orchestrator._budget_state(),
            "blocking_layers": orchestrator._tools.current_blocking_layers(),
        }

    @router.get("/overview")
    async def ai_overview(_principal: AdminPrincipal = Depends(require_admin)) -> dict:
        _require_markets_admin(_principal)
        champion = orchestrator._tools.m5_champion()
        registry = orchestrator._tools.model_registry()
        experiments = orchestrator.list_experiments()
        return {
            "quant_director_state": orchestrator.health_state(),
            "runtime_model": orchestrator.runtime_profile(),
            "champion": champion,
            "challengers": [
                entry for entry in registry if entry.get("role") == "CHALLENGER"
            ],
            "latest_experiment": experiments[0] if experiments else None,
            "research_hypotheses": orchestrator.list_research(),
            "current_blockers": orchestrator._tools.current_blocking_layers(),
            "provider_tt_coverage": orchestrator._tools.price_observations(),
            "budget": orchestrator.budget_policy(),
            "budget_usage": orchestrator._budget_state(),
            "promotion_funnel": {
                stage: sum(1 for entry in registry if entry.get("stage") == stage)
                for stage in ("RESEARCH", "BACKTEST", "WALK_FORWARD", "SHADOW", "PAPER", "REJECTED")
            },
        }

    @router.get("/experiments")
    async def list_experiments(_principal: AdminPrincipal = Depends(require_admin)) -> dict:
        _require_markets_admin(_principal)
        return {"experiments": orchestrator.list_experiments()}

    @router.get("/monitor")
    async def monitor_m5(_principal: AdminPrincipal = Depends(require_admin)) -> dict:
        _require_markets_admin(_principal)
        return {"monitor": orchestrator.monitor_m5()}

    @router.get("/weaknesses")
    async def weaknesses(_principal: AdminPrincipal = Depends(require_admin)) -> dict:
        _require_markets_admin(_principal)
        return {"weaknesses": orchestrator.analyze_weaknesses()}

    @router.get("/hypotheses")
    async def hypotheses(
        limit: int = 10,
        _principal: AdminPrincipal = Depends(require_admin),
    ) -> dict:
        _require_markets_admin(_principal)
        return {"hypotheses": orchestrator.generate_hypotheses(limit=limit)}

    @router.post("/proposals")
    async def create_proposal(
        body: ProposalRequest,
        _principal: AdminPrincipal = Depends(require_admin),
    ) -> dict:
        _require_markets_admin(_principal)
        entry_id = orchestrator.create_proposal(
            title=body.title,
            reason=body.reason,
            supporting_data=body.supporting_data,
            expected_effect=body.expected_effect,
            risk=body.risk,
            required_features=body.required_features,
            evaluation_plan=body.evaluation_plan,
        )
        return {"entry_id": entry_id, "status": "PROPOSED"}

    @router.get("/proposals")
    async def list_proposals(_principal: AdminPrincipal = Depends(require_admin)) -> dict:
        _require_markets_admin(_principal)
        return {"proposals": orchestrator.list_proposals()}

    @router.post("/review/daily")
    async def run_daily_review(_principal: AdminPrincipal = Depends(require_admin)) -> dict:
        _require_markets_admin(_principal)
        return orchestrator.run_daily_review()

    @router.post("/review/weekly")
    async def run_weekly_review(_principal: AdminPrincipal = Depends(require_admin)) -> dict:
        _require_markets_admin(_principal)
        return orchestrator.run_weekly_review()

    @router.get("/reviews")
    async def list_reviews(_principal: AdminPrincipal = Depends(require_admin)) -> dict:
        _require_markets_admin(_principal)
        return {"reviews": orchestrator.list_reviews()}

    @router.post("/approve-expensive")
    async def approve_expensive(_principal: AdminPrincipal = Depends(require_admin)) -> dict:
        _require_markets_admin(_principal)
        return {"approved": orchestrator.approve_expensive()}

    @router.get("/operational-status")
    async def operational_status(_principal: AdminPrincipal = Depends(require_admin)) -> dict:
        _require_markets_admin(_principal)
        return orchestrator.operational_status()

    @router.post("/scheduler/register")
    async def register_scheduler(_principal: AdminPrincipal = Depends(require_admin)) -> dict:
        _require_markets_admin(_principal)
        orchestrator.register_scheduler_jobs()
        return orchestrator.scheduler_status()

    @router.post("/scheduler/run/{weekly}")
    async def run_scheduled(
        weekly: bool,
        _principal: AdminPrincipal = Depends(require_admin),
    ) -> dict:
        _require_markets_admin(_principal)
        return orchestrator.run_scheduled_review(weekly=weekly)

    @router.get("/scheduler")
    async def scheduler_status(_principal: AdminPrincipal = Depends(require_admin)) -> dict:
        _require_markets_admin(_principal)
        return orchestrator.scheduler_status()

    @router.get("/triggers")
    async def list_triggers(_principal: AdminPrincipal = Depends(require_admin)) -> dict:
        _require_markets_admin(_principal)
        return {"triggers": orchestrator.list_event_triggers()}

    @router.get("/evaluation")
    async def evaluation_state(_principal: AdminPrincipal = Depends(require_admin)) -> dict:
        _require_markets_admin(_principal)
        return {
            "state": orchestrator.evaluation_state(),
            "metrics": orchestrator._store.latest_metric_snapshot(),
        }

    @router.post("/evaluation/settle")
    async def settle_evaluation(_principal: AdminPrincipal = Depends(require_admin)) -> dict:
        _require_markets_admin(_principal)
        return orchestrator.settle_and_evaluate()

    @router.get("/research/prioritized")
    async def prioritized_research(_principal: AdminPrincipal = Depends(require_admin)) -> dict:
        _require_markets_admin(_principal)
        return orchestrator.prioritize_research()

    @router.post("/champion/seed")
    async def seed_champion(_principal: AdminPrincipal = Depends(require_admin)) -> dict:
        _require_markets_admin(_principal)
        try:
            return orchestrator.ensure_champion(
                artifact_path=str(
                    Path(__file__).resolve().parents[2] / "docs" / "operations" / "TT_M5_LIVE_WEIGHTS_V1.json"
                ),
                artifact_sha256="fe6f18d1fb5eea640fc42d904d9010470ee75f73e594b2c00a86982d3381e229",
            )
        except Exception as exc:  # noqa: BLE001 - surfaced as FAIL_CLOSED, not silent
            raise HTTPException(status_code=409, detail=f"champion conflict: {type(exc).__name__}") from exc

    @router.post("/chat")
    async def chat(
        body: ChatRequest,
        _principal: AdminPrincipal = Depends(require_admin),
    ) -> dict:
        _require_markets_admin(_principal)
        try:
            return orchestrator.chat(thread_id=body.thread_id, message=body.message)
        except RuntimeError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @router.post("/research")
    async def create_research(
        body: ResearchEntryRequest,
        _principal: AdminPrincipal = Depends(require_admin),
    ) -> dict:
        _require_markets_admin(_principal)
        entry_id = orchestrator.create_research_entry(
            hypothesis=body.hypothesis,
            rationale=body.rationale,
            data_needed=body.data_needed,
        )
        return {"entry_id": entry_id}

    @router.get("/research")
    async def list_research(
        _principal: AdminPrincipal = Depends(require_admin),
    ) -> dict:
        _require_markets_admin(_principal)
        return {"entries": orchestrator.list_research()}

    return router
