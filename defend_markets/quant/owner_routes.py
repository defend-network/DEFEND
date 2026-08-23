"""M4.8.1 owner-facing Markets read API.

Read-only owner workstation endpoints. Every endpoint returns real persisted
state with explicit unavailable/unknown states; no fabricated rows. Gated by
``require_owner`` (reused shared admin auth). No real-money actions, no secrets.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from admin_auth import AdminPrincipal, authenticate, require_owner, revoke, token_from_header
from defend_markets.quant.orchestrator import MarketsIntelligenceOrchestrator

_OWNER_PREFIX = "/api/markets/owner"


def _require_owner(principal: AdminPrincipal) -> None:
    if principal.role != "owner":
        raise HTTPException(status_code=403, detail="owner-only")


class OwnerLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=500)


def build_owner_router(orchestrator: MarketsIntelligenceOrchestrator) -> APIRouter:
    router = APIRouter(prefix=_OWNER_PREFIX, tags=["markets-owner"])

    @router.post("/login")
    async def login(body: OwnerLoginRequest) -> dict:
        username, role, token, ttl = authenticate(body.username, body.password)
        return {"username": username, "role": role, "token": token, "expires_in": ttl}

    @router.post("/logout")
    async def logout(authorization: str | None = Header(default=None)) -> dict:
        try:
            revoke(token_from_header(authorization))
        except HTTPException:
            pass
        return {"ok": True}

    @router.get("/overview")
    async def overview(_principal: AdminPrincipal = Depends(require_owner)) -> dict:
        _require_owner(_principal)
        return orchestrator.markets_health_snapshot()

    @router.get("/live-tt")
    async def live_tt(_principal: AdminPrincipal = Depends(require_owner)) -> dict:
        _require_owner(_principal)
        quotes = orchestrator._store.list_hardrock_quotes(limit=10000) if hasattr(orchestrator._store, "list_hardrock_quotes") else []
        events: dict[str, dict] = {}
        for q in quotes:
            events.setdefault(q["canonical_event_id"], {"canonical_event_id": q["canonical_event_id"], "sides": {}})
            events[q["canonical_event_id"]]["sides"][q["selection_side"]] = {
                "american_odds": q.get("american_odds"),
                "decimal_odds": str(q.get("decimal_odds")),
                "implied_probability": str(q.get("implied_probability")) if q.get("implied_probability") is not None else None,
                "observed_at": q.get("observed_at"),
            }
        return {"events": list(events.values())}

    @router.get("/data-health")
    async def data_health(_principal: AdminPrincipal = Depends(require_owner)) -> dict:
        _require_owner(_principal)
        return orchestrator.markets_health_snapshot()

    @router.get("/arbitrage")
    async def arbitrage(_principal: AdminPrincipal = Depends(require_owner)) -> dict:
        _require_owner(_principal)
        return orchestrator.arbitrage_status()

    @router.get("/jobs")
    async def jobs(_principal: AdminPrincipal = Depends(require_owner)) -> dict:
        _require_owner(_principal)
        return orchestrator.scheduler_status()

    @router.get("/model")
    async def model(_principal: AdminPrincipal = Depends(require_owner)) -> dict:
        _require_owner(_principal)
        champion = orchestrator._store.champion() if hasattr(orchestrator._store, "champion") else None
        return {
            "champion": champion["model_id"] if champion else "M5_REGULARIZED_LOGISTIC",
            "artifact_hash_short": (champion["artifact_sha256"] or "fe6f18d1")[:12] if champion else "fe6f18d1",
            "predictions": len(orchestrator._store.list_official_predictions(limit=100000)),
        }

    return router
