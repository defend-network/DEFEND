"""Source-labeled hypothesis registry and deterministic prioritization.

Hypotheses are classified by source (SEED / DATA_DERIVED / OWNER_PROPOSED /
AI_PROPOSED) and scored deterministically. Market-dependent hypotheses are
blocked while TT prices are absent; previously rejected hypotheses stay
rejected without new evidence. The next experiment is selected from the
highest-scoring actionable hypothesis or DEFERRED.
"""

from __future__ import annotations

from typing import Any

SEED_HYPOTHESES = [
    {
        "source": "SEED",
        "title": "Recent 20-match weighted form may outperform lifetime rating",
        "supporting_observation": "recency ELO window is fixed at 100; near-term form may dominate",
        "data_requirements": "tt_match_results chronological rows",
        "dependencies": [],
        "expected_value": 0.7,
        "sample_support": 0.9,
        "leakage_risk": 0.1,
        "implementation_cost": 0.4,
        "compute_cost": 0.3,
        "feature_availability": 0.6,
        "market_dependency": False,
        "prior_rejection": False,
    },
    {
        "source": "SEED",
        "title": "Form volatility may identify unpredictable players",
        "supporting_observation": "std of recent outcomes is untracked; form5 holds five outcomes",
        "data_requirements": "tt_match_results chronological rows",
        "dependencies": [],
        "expected_value": 0.6,
        "sample_support": 0.8,
        "leakage_risk": 0.1,
        "implementation_cost": 0.3,
        "compute_cost": 0.3,
        "feature_availability": 0.8,
        "market_dependency": False,
        "prior_rejection": False,
    },
    {
        "source": "SEED",
        "title": "Fatigue/schedule density feature may matter on same-day back-to-backs",
        "supporting_observation": "same_day_diff counts games but not elapsed rest",
        "data_requirements": "tt_match_results chronological rows",
        "dependencies": [],
        "expected_value": 0.5,
        "sample_support": 0.7,
        "leakage_risk": 0.1,
        "implementation_cost": 0.3,
        "compute_cost": 0.2,
        "feature_availability": 0.7,
        "market_dependency": False,
        "prior_rejection": False,
    },
    {
        "source": "SEED",
        "title": "H2H recency weighting may beat lifetime head-to-head",
        "supporting_observation": "h2h_winrate_diff uses all meetings equally",
        "data_requirements": "tt_match_results chronological rows",
        "dependencies": [],
        "expected_value": 0.5,
        "sample_support": 0.6,
        "leakage_risk": 0.1,
        "implementation_cost": 0.4,
        "compute_cost": 0.2,
        "feature_availability": 0.5,
        "market_dependency": False,
        "prior_rejection": False,
    },
    {
        "source": "SEED",
        "title": "Opponent-strength adjustment may help identity weak opponents",
        "supporting_observation": "degree/log_depth ignore beaten-opponent strength",
        "data_requirements": "tt_match_results chronological rows",
        "dependencies": [],
        "expected_value": 0.6,
        "sample_support": 0.7,
        "leakage_risk": 0.2,
        "implementation_cost": 0.5,
        "compute_cost": 0.3,
        "feature_availability": 0.5,
        "market_dependency": False,
        "prior_rejection": False,
    },
    {
        "source": "SEED",
        "title": "Non-linear rest-days treatment may matter",
        "supporting_observation": "rest_diff_days is linear",
        "data_requirements": "tt_match_results chronological rows",
        "dependencies": [],
        "expected_value": 0.4,
        "sample_support": 0.6,
        "leakage_risk": 0.1,
        "implementation_cost": 0.2,
        "compute_cost": 0.2,
        "feature_availability": 0.7,
        "market_dependency": False,
        "prior_rejection": False,
    },
    {
        "source": "SEED",
        "title": "Player-history depth gate could flag low-evidence matches",
        "supporting_observation": "overconfidence expected on limited-history matchups",
        "data_requirements": "tt_match_results chronological rows",
        "dependencies": [],
        "expected_value": 0.5,
        "sample_support": 0.6,
        "leakage_risk": 0.2,
        "implementation_cost": 0.3,
        "compute_cost": 0.2,
        "feature_availability": 0.6,
        "market_dependency": False,
        "prior_rejection": False,
    },
    {
        "source": "SEED",
        "title": "Competition/surface interaction may explain league-specific calibration",
        "supporting_observation": "league_key is stored but not consumed by M5",
        "data_requirements": "tt_match_results rows with league_key",
        "dependencies": [],
        "expected_value": 0.4,
        "sample_support": 0.5,
        "leakage_risk": 0.2,
        "implementation_cost": 0.4,
        "compute_cost": 0.2,
        "feature_availability": 0.6,
        "market_dependency": False,
        "prior_rejection": False,
    },
    {
        "source": "SEED",
        "title": "Rating curvature (elo_diff squared) does not help",
        "supporting_observation": "walk-forward experiment rejected the added quadratic term",
        "data_requirements": "none",
        "dependencies": [],
        "expected_value": 0.0,
        "sample_support": 0.9,
        "leakage_risk": 0.0,
        "implementation_cost": 0.0,
        "compute_cost": 0.0,
        "feature_availability": 0.0,
        "market_dependency": False,
        "prior_rejection": True,
    },
    {
        "source": "SEED",
        "title": "Market-aware features require live TT prices",
        "supporting_observation": "model-market delta is meaningful only with valid pre-match prices",
        "data_requirements": "TT pre-match prices",
        "dependencies": ["TT prices"],
        "expected_value": 0.8,
        "sample_support": 0.0,
        "leakage_risk": 0.0,
        "implementation_cost": 0.4,
        "compute_cost": 0.1,
        "feature_availability": 0.0,
        "market_dependency": True,
        "prior_rejection": False,
    },
]


class ResearchPrioritizer:
    def __init__(self, *, market_prices_available: bool = False) -> None:
        self._market_prices_available = market_prices_available

    def score(self, hypothesis: dict[str, Any]) -> tuple[float, dict[str, Any], str | None]:
        components: dict[str, float] = {}
        if hypothesis.get("market_dependency") and not self._market_prices_available:
            return 0.0, {
                "DATA_AVAILABLE": 0.0,
                "MARKET_DEPENDENCY": 1.0,
                "score": 0.0,
            }, "requires TT market prices; blocked while prices absent"
        if hypothesis.get("prior_rejection"):
            return 0.0, {
                "PRIOR_REJECTION": 1.0,
                "score": 0.0,
            }, "previously rejected without new evidence; do not auto-rerun"
        components["DATA_AVAILABLE"] = 0.5
        components["EXPECTED_VALUE"] = hypothesis.get("expected_value", 0.0)
        components["SAMPLE_SUPPORT"] = hypothesis.get("sample_support", 0.0)
        components["FEATURE_AVAILABILITY"] = hypothesis.get("feature_availability", 0.0)
        components["IMPLEMENTATION_COST_PENALTY"] = hypothesis.get("implementation_cost", 0.0)
        components["COMPUTE_COST_PENALTY"] = hypothesis.get("compute_cost", 0.0)
        components["LEAKAGE_RISK_PENALTY"] = hypothesis.get("leakage_risk", 0.0)
        score = (
            components["DATA_AVAILABLE"]
            + 0.25 * components["EXPECTED_VALUE"]
            + 0.1 * components["SAMPLE_SUPPORT"]
            + 0.1 * components["FEATURE_AVAILABILITY"]
            - 0.1 * components["IMPLEMENTATION_COST_PENALTY"]
            - 0.05 * components["COMPUTE_COST_PENALTY"]
            - 0.2 * components["LEAKAGE_RISK_PENALTY"]
        )
        components["score"] = round(score, 4)
        return round(score, 4), components, None

    def prioritize(
        self,
        store: Any,
        *,
        data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        for hypothesis in SEED_HYPOTHESES:
            priority, breakdown, blocked = self.score(hypothesis)
            hypothesis_id = store.upsert_hypothesis(
                {
                    "source": hypothesis["source"],
                    "title": hypothesis["title"],
                    "supporting_observation": hypothesis.get("supporting_observation"),
                    "status": "REJECTED" if hypothesis.get("prior_rejection") else ("BLOCKED" if blocked else "PROPOSED"),
                    "rejection_reason": hypothesis.get("prior_rejection", False) and "previously rejected without new evidence" or None,
                    "dependencies": hypothesis.get("dependencies", []),
                    "data_requirements": hypothesis.get("data_requirements"),
                    "priority_score": priority,
                    "priority_breakdown": breakdown,
                    "blocked_reason": blocked,
                }
            )
            store.update_hypothesis_priority(hypothesis_id, priority_score=priority, breakdown=breakdown, blocked_reason=blocked)
        return store.list_hypotheses()

    def select_next(self, hypotheses: list[dict[str, Any]]) -> dict[str, Any]:
        actionable = [
            hypothesis for hypothesis in hypotheses
            if hypothesis.get("status") not in ("REJECTED", "BLOCKED")
            and hypothesis.get("blocked_reason") is None
            and hypothesis.get("priority_score") is not None
        ]
        if not actionable:
            return {"selected": False, "reason": "no actionable hypothesis with sufficient evidence"}
        top = max(actionable, key=lambda item: item["priority_score"])
        return {
            "selected": True,
            "hypothesis_id": top["hypothesis_id"],
            "title": top["title"],
            "source": top["source"],
            "priority_score": top["priority_score"],
        }


def seed_hypotheses(store: Any, *, market_prices_available: bool = False) -> list[dict[str, Any]]:
    return ResearchPrioritizer(market_prices_available=market_prices_available).prioritize(store, data={})
