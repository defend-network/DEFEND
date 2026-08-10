"""
Admin-only tool wrapper — register only under owner policy.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# Adjust imports to your package layout when copying into DEFEND32B
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tt_engine import LiveState, evaluate_live, eval_to_dict, find_two_way_arb, hedge_lock


class TTEvaluateInput(BaseModel):
    match_id: str
    best_of: int = 5
    sets_leader: int
    sets_trailer: int
    points_leader: int = 0
    points_trailer: int = 0
    leader_is_a: bool = True
    second_set_margin: int | None = None
    rank_delta: float | None = None
    h2h_leader_wins: int | None = None
    h2h_trailer_wins: int | None = None
    prob_reach_2_0_within_4_points: float = Field(ge=0.0, le=1.0)
    offered_odds: float | None = None
    model_adjust: float = 0.0
    # Optional arb legs from two books
    book_a_odds: float | None = None
    book_b_odds: float | None = None
    # Optional hedge
    original_stake: float | None = None
    original_odds: float | None = None
    hedge_odds: float | None = None


class TTEvaluateOutput(BaseModel):
    evaluation: dict[str, Any]
    arb: dict[str, Any] | None = None
    hedge: dict[str, Any] | None = None
    human_action: str = "Place bets yourself if decision=bet; AI does not wager."


def run_tt_evaluate(args: TTEvaluateInput) -> TTEvaluateOutput:
    st = LiveState(
        match_id=args.match_id,
        best_of=args.best_of,
        sets_leader=args.sets_leader,
        sets_trailer=args.sets_trailer,
        points_leader=args.points_leader,
        points_trailer=args.points_trailer,
        leader_is_a=args.leader_is_a,
        second_set_margin=args.second_set_margin,
        rank_delta=args.rank_delta,
        h2h_leader_wins=args.h2h_leader_wins,
        h2h_trailer_wins=args.h2h_trailer_wins,
        prob_reach_2_0_within_4_points=args.prob_reach_2_0_within_4_points,
        offered_odds=args.offered_odds,
    )
    ev = evaluate_live(st, model_adjust=args.model_adjust)
    arb = None
    if args.book_a_odds and args.book_b_odds:
        arb = find_two_way_arb(args.book_a_odds, args.book_b_odds)
    hedge = None
    if args.original_stake and args.original_odds and args.hedge_odds:
        hedge = hedge_lock(args.original_stake, args.original_odds, args.hedge_odds)
    return TTEvaluateOutput(
        evaluation=eval_to_dict(ev),
        arb=arb,
        hedge=hedge,
    )
