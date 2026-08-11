"""Additive admin + owner-only TableTennis routes.

This router intentionally does not depend on api_server internals. It can be
included with `app.include_router(admin_tt_router)` and removed cleanly later.
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from admin_auth import (
    AdminPrincipal,
    authenticate,
    canonical_admin_login_identifier,
    require_admin,
    require_owner,
    revoke,
    token_from_header,
)
from api_identity_routes import _admin_login_rate_keys, _limiter

_TT_ROOT = Path(__file__).resolve().parent / "TableTennis"
if str(_TT_ROOT) not in sys.path:
    sys.path.insert(0, str(_TT_ROOT))

from tt_engine import LiveState, eval_to_dict, evaluate_live, find_two_way_arb, hedge_lock  # noqa: E402
from tt_store import (  # noqa: E402
    add_event,
    add_manual_match,
    init_db,
    list_live_matches,
    log_bet,
    metrics,
    recent_events,
    record_arb,
    settle_bet,
    upsert_snapshot,
)

router = APIRouter()


class _LoginWorkGate:
    """Bound admitted login work before it reaches the shared worker pool."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._active = 0
        self._lock = threading.Lock()

    def try_acquire(self) -> bool:
        with self._lock:
            if self._active >= self.limit:
                return False
            self._active += 1
            return True

    def release(self) -> None:
        with self._lock:
            if self._active <= 0:
                raise RuntimeError("admin login work gate released without acquisition")
            self._active -= 1


def _login_work_concurrency() -> int:
    try:
        configured = int(os.getenv("DEFEND_ADMIN_LOGIN_HASH_CONCURRENCY", "2"))
    except ValueError:
        configured = 2
    return max(1, min(configured, 8))


def _login_work_gate(request: Request) -> _LoginWorkGate:
    gate = getattr(request.app.state, "admin_login_work_gate", None)
    if gate is None:
        gate = _LoginWorkGate(_login_work_concurrency())
        setattr(request.app.state, "admin_login_work_gate", gate)
    return gate


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str


class ManualMatchIn(BaseModel):
    event_name: str = Field(min_length=1, max_length=200)
    player_a: str = Field(min_length=1, max_length=160)
    player_b: str = Field(min_length=1, max_length=160)
    best_of: int = Field(default=5, ge=3, le=7)
    sets_a: int = Field(default=0, ge=0, le=4)
    sets_b: int = Field(default=0, ge=0, le=4)
    points_a: int = Field(default=0, ge=0, le=99)
    points_b: int = Field(default=0, ge=0, le=99)


class TTEvalIn(BaseModel):
    match_id: str = Field(min_length=1, max_length=128)
    best_of: int = Field(default=5, ge=3, le=7)
    sets_leader: int = Field(ge=0, le=4)
    sets_trailer: int = Field(ge=0, le=4)
    points_leader: int = Field(default=0, ge=0, le=99)
    points_trailer: int = Field(default=0, ge=0, le=99)
    leader_is_a: bool = True
    second_set_margin: int | None = Field(default=None, ge=-50, le=50)
    # trailer_rank - leader_rank. Positive means leader has the better/lower rank.
    rank_delta: float | None = Field(default=None, ge=-5000, le=5000)
    h2h_leader_wins: int | None = Field(default=None, ge=0, le=10000)
    h2h_trailer_wins: int | None = Field(default=None, ge=0, le=10000)
    prob_reach_2_0_within_4_points: float = Field(ge=0.0, le=1.0)
    offered_odds: float | None = Field(default=None, gt=1.0, le=1000)
    model_adjust: float = Field(default=0.0, ge=-1.0, le=1.0)
    book_a_odds: float | None = Field(default=None, gt=1.0, le=1000)
    book_b_odds: float | None = Field(default=None, gt=1.0, le=1000)
    original_stake: float | None = Field(default=None, gt=0, le=1_000_000)
    original_odds: float | None = Field(default=None, gt=1.0, le=1000)
    hedge_odds: float | None = Field(default=None, gt=1.0, le=1000)
    # Optional actual scoreboard so the manual/live board can be updated at evaluation time.
    sets_a: int | None = Field(default=None, ge=0, le=4)
    sets_b: int | None = Field(default=None, ge=0, le=4)
    points_a: int | None = Field(default=None, ge=0, le=99)
    points_b: int | None = Field(default=None, ge=0, le=99)


class BetIn(BaseModel):
    match_id: str
    book: str = Field(default="manual", max_length=100)
    market: str = Field(default="manual", max_length=160)
    selection: str = Field(min_length=1, max_length=160)
    odds: float = Field(gt=1.0, le=1000)
    stake: float = Field(gt=0, le=1_000_000)
    evaluation: dict[str, Any] | None = None


class SettleIn(BaseModel):
    result: str
    pnl: float = Field(ge=-1_000_000, le=1_000_000)
    closing_odds: float | None = Field(default=None, gt=1.0, le=1000)


@router.post("/api/admin/login")
async def admin_login(body: LoginIn, request: Request) -> dict[str, Any]:
    gate = _login_work_gate(request)
    if not gate.try_acquire():
        raise HTTPException(status_code=429, detail="Too many authentication attempts")
    try:
        rate_identifier = await run_in_threadpool(
            canonical_admin_login_identifier, body.username
        )
        limiter = _limiter(request, "admin_login")
        if not limiter.allow_many(_admin_login_rate_keys(request, rate_identifier)):
            raise HTTPException(
                status_code=429, detail="Too many authentication attempts"
            )
        if len(body.password) > 512:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        username, role, token, expires_in = await run_in_threadpool(
            authenticate, body.username, body.password
        )
    finally:
        gate.release()
    return {
        "username": username,
        "role": role,
        "token": token,
        "expires_in": expires_in,
    }


@router.post("/api/admin/logout")
async def admin_logout(
    authorization: str | None = Header(default=None),
    _principal: AdminPrincipal = Depends(require_admin),
) -> dict[str, bool]:
    revoke(token_from_header(authorization))
    return {"ok": True}


@router.get("/api/admin/tt/health")
async def tt_health(_owner: AdminPrincipal = Depends(require_owner)) -> dict[str, Any]:
    init_db()
    return {"ok": True, "owner_only": True, "persistence": "sqlite"}


@router.get("/api/admin/tt/metrics")
async def tt_metrics(_owner: AdminPrincipal = Depends(require_owner)) -> dict[str, Any]:
    return metrics()


@router.get("/api/admin/tt/live")
async def tt_live(_owner: AdminPrincipal = Depends(require_owner)) -> dict[str, Any]:
    return {"matches": list_live_matches()}


@router.post("/api/admin/tt/matches/manual")
async def tt_add_manual_match(
    body: ManualMatchIn,
    _owner: AdminPrincipal = Depends(require_owner),
) -> dict[str, Any]:
    return add_manual_match(**body.model_dump())


@router.post("/api/admin/tt/evaluate")
async def tt_evaluate(
    body: TTEvalIn,
    _owner: AdminPrincipal = Depends(require_owner),
) -> dict[str, Any]:
    st = LiveState(
        match_id=body.match_id,
        best_of=body.best_of,
        sets_leader=body.sets_leader,
        sets_trailer=body.sets_trailer,
        points_leader=body.points_leader,
        points_trailer=body.points_trailer,
        leader_is_a=body.leader_is_a,
        second_set_margin=body.second_set_margin,
        rank_delta=body.rank_delta,
        h2h_leader_wins=body.h2h_leader_wins,
        h2h_trailer_wins=body.h2h_trailer_wins,
        prob_reach_2_0_within_4_points=body.prob_reach_2_0_within_4_points,
        offered_odds=body.offered_odds,
    )
    ev = evaluate_live(st, model_adjust=body.model_adjust)
    ev_dict = eval_to_dict(ev)

    if None not in (body.sets_a, body.sets_b, body.points_a, body.points_b):
        upsert_snapshot(
            body.match_id,
            sets_a=int(body.sets_a),
            sets_b=int(body.sets_b),
            points_a=int(body.points_a),
            points_b=int(body.points_b),
            raw_json={"source": "panel_evaluate"},
        )

    arb = None
    if body.book_a_odds is not None and body.book_b_odds is not None:
        arb = find_two_way_arb(body.book_a_odds, body.book_b_odds)
        if arb:
            record_arb(body.match_id, arb)

    hedge = None
    if body.original_stake and body.original_odds and body.hedge_odds:
        hedge = hedge_lock(body.original_stake, body.original_odds, body.hedge_odds)

    add_event(
        "evaluation",
        f"Evaluation {ev.decision.upper()} hard_pass={ev.hard_pass} final={ev.final_score}",
        body.match_id,
        {"evaluation": ev_dict, "arb": arb, "hedge": hedge},
    )
    return {
        "evaluation": ev_dict,
        "arb": arb,
        "hedge": hedge,
        "human_action": "Decision support only. No wager is placed by the system.",
    }


@router.post("/api/admin/tt/bets")
async def tt_log_bet(
    body: BetIn,
    _owner: AdminPrincipal = Depends(require_owner),
) -> dict[str, Any]:
    return log_bet(**body.model_dump())


@router.post("/api/admin/tt/bets/{bet_id}/settle")
async def tt_settle_bet(
    bet_id: str,
    body: SettleIn,
    _owner: AdminPrincipal = Depends(require_owner),
) -> dict[str, Any]:
    try:
        out = settle_bet(
            bet_id,
            result=body.result,
            pnl=body.pnl,
            closing_odds=body.closing_odds,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if out is None:
        raise HTTPException(status_code=404, detail="Bet not found")
    return out


@router.get("/api/admin/tt/events")
async def tt_events(
    limit: int = 100,
    _owner: AdminPrincipal = Depends(require_owner),
) -> dict[str, Any]:
    return {"events": recent_events(limit=limit)}
