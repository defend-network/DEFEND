"""Admin-only Markets AI chat routes.

Enforcement: unauthenticated -> 401, consumer/non-admin -> 403, admin ->
allowed. Responses come from the orchestrator's governed tools and persisted
chat history.
"""

from __future__ import annotations

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
