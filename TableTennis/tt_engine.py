"""Deterministic table-tennis advisory rules engine.

This module does not place wagers. It evaluates supplied state, reports rule
failures/value diagnostics, and calculates informational arbitrage/hedge math.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent
RULES_PATH = ROOT / "tt_rules.yaml"


def load_rules(path: Path = RULES_PATH) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@dataclass
class LiveState:
    match_id: str
    best_of: int
    sets_leader: int
    sets_trailer: int
    points_leader: int
    points_trailer: int
    leader_is_a: bool
    second_set_margin: int | None = None
    # Convention: trailer_rank - leader_rank. Positive => leader has better (lower) rank number.
    rank_delta: float | None = None
    h2h_leader_wins: int | None = None
    h2h_trailer_wins: int | None = None
    prob_reach_2_0_within_4_points: float = 0.0
    offered_odds: float | None = None


@dataclass
class EvalResult:
    hard_pass: bool
    hard_failures: list[str]
    soft_score: float
    model_adjust: float
    final_score: float
    decision: str
    stake_pct: float
    reasons: list[str]
    features: dict[str, Any]


def _can_leader_still_make_2_0(sets_leader: int, sets_trailer: int, best_of: int) -> bool:
    del best_of  # retained for contract clarity / future format-specific rules
    return sets_trailer == 0 and sets_leader in (0, 1)


def implied_prob(decimal_odds: float) -> float:
    if decimal_odds <= 1.0:
        raise ValueError("Decimal odds must be > 1.0")
    return 1.0 / decimal_odds


def _value_edge_pct(probability: float, offered_odds: float | None) -> float | None:
    if offered_odds is None or offered_odds <= 1.0:
        return None
    return (probability - implied_prob(offered_odds)) * 100.0


def evaluate_live(
    state: LiveState,
    model_adjust: float = 0.0,
    rules: dict[str, Any] | None = None,
) -> EvalResult:
    rules = rules or load_rules()
    hard = rules.get("hard") or {}
    soft = rules.get("soft") or {}
    value_cfg = rules.get("value") or {}
    failures: list[str] = []
    reasons: list[str] = []

    if state.best_of not in (3, 5, 7):
        failures.append("unsupported_best_of")
    if min(state.sets_leader, state.sets_trailer, state.points_leader, state.points_trailer) < 0:
        failures.append("negative_score")

    already_2_0 = state.sets_leader >= 2 and state.sets_trailer == 0
    if hard.get("require_not_yet_two_zero", True) and already_2_0:
        failures.append("already_2_0")

    if hard.get("allow_only_if_leader_can_still_make_2_0", True):
        if not _can_leader_still_make_2_0(state.sets_leader, state.sets_trailer, state.best_of):
            failures.append("cannot_reach_fresh_2_0_path")

    p = max(0.0, min(1.0, float(state.prob_reach_2_0_within_4_points or 0.0)))
    min_p = float(hard.get("min_prob_reach_2_0_within_4_points", 0.80))
    if p < min_p:
        failures.append(f"prob_2_0_in_4pts={p:.3f}<{min_p:.2f}")

    edge_pct = _value_edge_pct(p, state.offered_odds)
    if bool(value_cfg.get("require_positive_edge", False)):
        min_edge = float(value_cfg.get("min_edge_pct", 0.0))
        if edge_pct is None:
            failures.append("value_edge_unavailable")
        elif edge_pct < min_edge:
            failures.append(f"value_edge={edge_pct:.3f}%<{min_edge:.3f}%")

    hard_pass = not failures

    soft_score = 0.5
    parts: list[str] = []

    w_mom = float((soft.get("second_set_margin_momentum") or {}).get("weight", 0.15))
    if state.second_set_margin is not None:
        mom = max(0.0, min(1.0, float(state.second_set_margin) / 8.0))
        soft_score += (mom - 0.5) * 2.0 * w_mom
        parts.append(f"second_set_margin={state.second_set_margin}")

    w_rank = float((soft.get("rank_delta_leader_favorite") or {}).get("weight", 0.10))
    if state.rank_delta is not None:
        rd = max(-1.0, min(1.0, float(state.rank_delta) / 50.0))
        soft_score += rd * w_rank
        parts.append(f"rank_delta={state.rank_delta}")

    w_h2h = float((soft.get("h2h_leader") or {}).get("weight", 0.10))
    if state.h2h_leader_wins is not None and state.h2h_trailer_wins is not None:
        total = state.h2h_leader_wins + state.h2h_trailer_wins
        if total > 0:
            h2h = state.h2h_leader_wins / total
            soft_score += (h2h - 0.5) * 2.0 * w_h2h
            parts.append(f"h2h={state.h2h_leader_wins}-{state.h2h_trailer_wins}")

    soft_score = 0.5 * soft_score + 0.5 * p
    soft_score = max(0.0, min(1.0, soft_score))

    max_adj = float(rules.get("max_model_adjust", 0.08))
    adj = max(-max_adj, min(max_adj, float(model_adjust)))
    final = max(0.0, min(1.0, soft_score + adj))
    floor = float(rules.get("soft_score_floor", 0.55))

    decision = "skip"
    stake_pct = 0.0
    if hard_pass and final >= floor:
        decision = "bet"
        stake_pct = float((rules.get("bankroll") or {}).get("max_stake_pct", 0.01))
        reasons.append("hard_pass_and_final_above_floor")
    elif not hard_pass:
        reasons.append("hard_fail:" + ",".join(failures))
    else:
        reasons.append(f"final_below_floor:{final:.3f}<{floor}")
    reasons.extend(parts)

    features = {
        "sets": f"{state.sets_leader}-{state.sets_trailer}",
        "points": f"{state.points_leader}-{state.points_trailer}",
        "prob_2_0_in_4pts": p,
        "second_set_margin": state.second_set_margin,
        "rank_delta": state.rank_delta,
        "rank_delta_convention": "trailer_rank_minus_leader_rank",
        "offered_odds": state.offered_odds,
        "offered_implied_prob": (
            round(implied_prob(state.offered_odds), 6)
            if state.offered_odds is not None and state.offered_odds > 1.0
            else None
        ),
        "value_edge_pct": round(edge_pct, 4) if edge_pct is not None else None,
    }

    return EvalResult(
        hard_pass=hard_pass,
        hard_failures=failures,
        soft_score=round(soft_score, 4),
        model_adjust=round(adj, 4),
        final_score=round(final, 4),
        decision=decision,
        stake_pct=stake_pct,
        reasons=reasons,
        features=features,
    )


def find_two_way_arb(
    odds_a: float,
    odds_b: float,
    commission: float = 0.0,
    min_edge_pct: float | None = None,
    rules: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if odds_a <= 1.0 or odds_b <= 1.0:
        return None
    if not 0.0 <= commission < 1.0:
        return None
    rules = rules or load_rules()
    if min_edge_pct is None:
        min_edge_pct = float((rules.get("arb") or {}).get("min_edge_pct", 0.5))

    pa = implied_prob(odds_a) / (1.0 - commission)
    pb = implied_prob(odds_b) / (1.0 - commission)
    total = pa + pb
    if total >= 1.0:
        return None
    edge_pct = (1.0 - total) * 100.0
    if edge_pct < float(min_edge_pct):
        return None

    stake_a = (1.0 / odds_a) / ((1.0 / odds_a) + (1.0 / odds_b))
    stake_b = 1.0 - stake_a
    return {
        "edge_pct": round(edge_pct, 3),
        "stake_frac_a": round(stake_a, 4),
        "stake_frac_b": round(stake_b, 4),
        "odds_a": odds_a,
        "odds_b": odds_b,
    }


def hedge_lock(
    original_stake: float,
    original_odds: float,
    hedge_odds: float,
    rules: dict[str, Any] | None = None,
) -> dict[str, float] | None:
    if original_stake <= 0 or original_odds <= 1.0 or hedge_odds <= 1.0:
        return None
    hedge_stake = (original_stake * original_odds) / hedge_odds
    profit = original_stake * original_odds - original_stake - hedge_stake
    rules = rules or load_rules()
    min_lock = float((rules.get("arb") or {}).get("min_hedge_lock_pct", 0.0))
    locked_pct = (profit / original_stake) * 100.0
    if locked_pct < min_lock:
        return None
    return {
        "hedge_stake": round(hedge_stake, 2),
        "locked_profit": round(profit, 2),
        "locked_profit_pct": round(locked_pct, 3),
        "original_stake": round(original_stake, 2),
        "original_odds": round(original_odds, 4),
        "hedge_odds": round(hedge_odds, 4),
    }


def eval_to_dict(e: EvalResult) -> dict[str, Any]:
    return asdict(e)
