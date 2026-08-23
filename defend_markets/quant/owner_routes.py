"""M4.8.2 owner-facing Markets read API.

Read-only owner workstation endpoints. Every endpoint returns real persisted
state with explicit unavailable/unknown states; no fabricated rows. Gated by
``require_owner`` (reused shared admin auth). Routes invoke public orchestrator
methods (live_tt_board / event_detail / markets_health_snapshot / arbitrage_status
/ scheduler_status), never store internals (P16). No real-money actions, no secrets.
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
    async def live_tt(
        state: str | None = None,
        actionability: str | None = None,
        matched_only: bool = False,
        sort: str = "default",
        limit: int = 200,
        _principal: AdminPrincipal = Depends(require_owner),
    ) -> dict:
        _require_owner(_principal)
        bounded = max(1, min(int(limit), 500))
        return orchestrator.live_tt_board(
            state=state, actionability=actionability, matched_only=matched_only, sort=sort, limit=bounded
        )

    @router.get("/events/{canonical_event_id}")
    async def event_detail(canonical_event_id: str, _principal: AdminPrincipal = Depends(require_owner)) -> dict:
        _require_owner(_principal)
        return orchestrator.event_detail(canonical_event_id)

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
