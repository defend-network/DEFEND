"""Quant Director intelligence layer.

Deterministic monitoring, weakness identification, hypothesis generation, and
research reports. The AI layer interprets these structured results; it never
invents data, bypasses gates, promotes models, or alters risk policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

from defend_markets.quant.explanation import explain_m5_prediction
from defend_markets.quant.research.metrics import (
    calibration_buckets,
    ece_score,
    log_loss_score,
    brier_score,
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def collect_monitor_data(tools: Any) -> dict[str, Any]:
    evaluation = tools.prediction_outcomes(limit=5000)
    outcomes = [row for row in evaluation if row.get("p") is not None and row.get("actual") is not None]
    return {
        "evaluation": evaluation,
        "outcomes": outcomes,
        "missing": tools.missing_data_stats(),
        "disagreement": tools.market_disagreement_summary(),
        "freshness": tools.data_freshness(),
        "confidence": tools.confidence_distribution(),
    }


@dataclass(frozen=True)
class WeaknessFinding:
    id: str
    category: str
    severity: str
    description: str
    supporting_data: dict[str, Any]
    recommendation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "severity": self.severity,
            "description": self.description,
            "supporting_data": self.supporting_data,
            "recommendation": self.recommendation,
        }


_HYPOTHESIS_POOL = [
    {
        "title": "Recent 20-match weighted form may outperform lifetime rating",
        "reason": "recency ELO window is fixed at 100; near-term form may dominate outcome more than long-run rating",
        "supporting_data": "recency_elo_diff and form5_diff are the two largest live inputs after elo_diff",
        "expected_effect": "improved Brier on high-activity player populations",
        "risk": "overfits to streaks; unstable on sparse schedules",
        "required_features": ["recent_form20_weighted"],
        "evaluation_plan": "challenger = M5 + recent_form20_weighted; walk-forward only",
    },
    {
        "title": "Opponent-strength adjustment may help identity weak opponents",
        "reason": "degree_diff and log_depth_diff ignore the strength of beaten opponents",
        "supporting_data": "opponents set is tracked but not strength-weighted",
        "expected_effect": "better probability when a high-rated player faces a low-activity opponent",
        "risk": "collinear with elo_diff; limited lift",
        "required_features": ["sos_opponent_strength"],
        "evaluation_plan": "challenger = M5 + sos_opponent_strength; walk-forward only",
    },
    {
        "title": "Competition/surface interaction may explain league-specific calibration",
        "reason": "league is stored on results but not consumed by M5 features",
        "supporting_data": "league_key available on tt_match_results rows",
        "expected_effect": "reduced ECE in unbalanced leagues",
        "risk": "low counts per league; regularization needed",
        "required_features": ["competition_indicator"],
        "evaluation_plan": "challenger = M5 + competition_indicator; walk-forward only",
    },
    {
        "title": "Fatigue/schedule density feature may matter on same-day back-to-backs",
        "reason": "same_day_diff counts games but not elapsed rest in hours",
        "supporting_data": "day_games tracked per player",
        "expected_effect": "better probability on congested schedules",
        "risk": "rest_diff_days collinear",
        "required_features": ["same_day_games"],
        "evaluation_plan": "challenger = M5 + same_day_games; walk-forward only",
    },
    {
        "title": "H2H recency weighting may beat lifetime head-to-head",
        "reason": "h2h_winrate_diff uses all meetings equally",
        "supporting_data": "h2h meetings tracked with recency",
        "expected_effect": "better when player form has diverged since early meetings",
        "risk": "small h2h samples",
        "required_features": ["h2h_recency_weighted"],
        "evaluation_plan": "challenger = M5 + h2h_recency_weighted; walk-forward only",
    },
    {
        "title": "Rating curvature (elo_diff squared) does not help",
        "reason": "walk-forward experiment rejected the added quadratic term",
        "supporting_data": "challenger weighted Brier 0.242473 vs baseline 0.242471",
        "expected_effect": "none; rejected",
        "risk": "none",
        "required_features": [],
        "evaluation_plan": "rejected; do not retry without new data",
    },
    {
        "title": "Form volatility may identify unpredictable players",
        "reason": "std of recent outcomes is untracked",
        "supporting_data": "form5 stores only the last five outcomes",
        "expected_effect": "reduced confidence on volatile players",
        "risk": "needs >= 10 history rows",
        "required_features": ["form_volatility"],
        "evaluation_plan": "challenger = M5 + form_volatility; walk-forward only",
    },
    {
        "title": "Player-history depth gate could flag low-evidence matches",
        "reason": "overconfidence is expected on limited-history matchups",
        "supporting_data": "missing_data_stats reports unmatched/low-history events",
        "expected_effect": "flatter probabilities when history is thin",
        "risk": "reduces discrimination where history is genuinely informative",
        "required_features": ["history_depth_gate"],
        "evaluation_plan": "challenger = M5 + history_depth_gate; walk-forward only",
    },
    {
        "title": "Market-aware features require live TT prices",
        "reason": "model-market delta is meaningful only with valid pre-match prices",
        "supporting_data": "market disagreement summary currently reports no ruler rows",
        "expected_effect": "calibrated edge after prices exist",
        "risk": "none while prices absent",
        "required_features": ["market_implied_p"],
        "evaluation_plan": "blocked until TT prices are delivered",
    },
    {
        "title": "Non-linear rest-days treatment may matter",
        "reason": "rest_diff_days is linear; very long rests behave differently",
        "supporting_data": "rest tracked in days",
        "expected_effect": "marginal Brier improvement",
        "risk": "weak signal",
        "required_features": ["rest_diff_log"],
        "evaluation_plan": "challenger = M5 + rest_diff_log; walk-forward only",
    },
]


class QuantIntelligence:
    def __init__(self, weights_doc: dict[str, Any] | None = None) -> None:
        self._weights_doc = weights_doc

    def monitor(self, data: dict[str, Any]) -> dict[str, Any]:
        outcomes = data.get("outcomes", [])
        preds = [float(row["p"]) for row in outcomes]
        actuals = [float(row["actual"]) for row in outcomes]
        report: dict[str, Any] = {
            "evaluation_rows": len(outcomes),
            "as_of": utc_now_iso(),
        }
        if outcomes:
            report["brier"] = round(brier_score(actuals, preds), 6)
            report["log_loss"] = round(log_loss_score(actuals, preds), 6)
            report["ece"] = ece_score(actuals, preds)
            report["calibration"] = calibration_buckets(actuals, preds)
        else:
            report["brier"] = None
            report["log_loss"] = None
            report["ece"] = None
            report["calibration"] = []
        report["confidence"] = data.get("confidence", {})
        report["missing"] = data.get("missing", {})
        report["disagreement"] = data.get("disagreement", {})
        report["freshness"] = data.get("freshness", {})
        return report

    def find_weaknesses(self, data: dict[str, Any]) -> list[WeaknessFinding]:
        monitor = self.monitor(data)
        findings: list[WeaknessFinding] = []
        if monitor["evaluation_rows"] == 0:
            findings.append(
                WeaknessFinding(
                    id="W-001",
                    category="evaluation",
                    severity="high",
                    description="No settled evaluation rows yet; M5 calibration cannot be measured.",
                    supporting_data={"evaluation_rows": 0},
                    recommendation="Reach settled events with observed outcomes to enable calibration monitoring.",
                )
            )
        else:
            bad_buckets = [
                bucket for bucket in monitor["calibration"]
                if abs(bucket["predicted_mean"] - bucket["observed_rate"]) > 0.05
            ]
            if bad_buckets:
                findings.append(
                    WeaknessFinding(
                        id="W-002",
                        category="calibration",
                        severity="medium",
                        description="Calibration error exceeds 5% in some probability buckets.",
                        supporting_data={"bucket_errors": bad_buckets},
                        recommendation="Investigate bucket-level recalibration or feature gaps.",
                    )
                )
        missing = data.get("missing", {})
        if missing.get("unmatched_events", 0) > 0:
            findings.append(
                WeaknessFinding(
                    id="W-003",
                    category="identity",
                    severity="medium",
                    description="Some forward events remain unmatched, so they cannot receive predictions.",
                    supporting_data=missing,
                    recommendation="Expand canonical identity coverage for unmatched events.",
                )
            )
        disagreement = data.get("disagreement", {})
        if disagreement.get("ruler_rows_with_disagreement", 0) == 0:
            findings.append(
                WeaknessFinding(
                    id="W-004",
                    category="market",
                    severity="low",
                    description="No model-market disagreement computed; market comparison unavailable without TT prices.",
                    supporting_data=disagreement,
                    recommendation="Recompute disagreement once TT prices are delivered.",
                )
            )
        if monitor["evaluation_rows"] == 0 or not bad_buckets:
            findings.append(
                WeaknessFinding(
                    id="W-005",
                    category="evidence",
                    severity="low",
                    description="Evidence base for calibration is still small or clean.",
                    supporting_data={"evaluation_rows": monitor["evaluation_rows"]},
                    recommendation="Continue collecting settled outcomes before acting on calibration findings.",
                )
            )
        return findings

    def generate_hypotheses(self, data: dict[str, Any], *, limit: int = 10) -> list[dict[str, Any]]:
        hypotheses = []
        for item in _HYPOTHESIS_POOL[:limit]:
            hypotheses.append(
                {
                    "title": item["title"],
                    "reason": item["reason"],
                    "supporting_data": item["supporting_data"],
                    "expected_effect": item["expected_effect"],
                    "risk": item["risk"],
                    "required_features": item["required_features"],
                    "evaluation_plan": item["evaluation_plan"],
                }
            )
        return hypotheses

    def research_report(self, data: dict[str, Any]) -> dict[str, Any]:
        monitor = self.monitor(data)
        weaknesses = self.find_weaknesses(data)
        hypotheses = self.generate_hypotheses(data)
        return {
            "model_health": monitor,
            "recent_mistakes": weaknesses,
            "possible_improvements": [
                finding.recommendation for finding in weaknesses
            ],
            "new_experiments_proposed": [
                hypothesis["title"] for hypothesis in hypotheses if "blocked" not in hypothesis["evaluation_plan"]
            ],
            "features_worth_testing": list(
                {
                    feature
                    for hypothesis in hypotheses
                    for feature in hypothesis["required_features"]
                    if feature
                }
            ),
            "rejected_ideas": [
                hypothesis["title"] for hypothesis in hypotheses if "rejected" in hypothesis["evaluation_plan"]
            ],
            "generated_at": utc_now_iso(),
        }

    def explain_prediction(self, features: dict[str, float], *, model_version: str | None = None) -> dict[str, Any]:
        if self._weights_doc is None:
            return {"available": False, "reason": "M5 weights not loaded"}
        return explain_m5_prediction(features, self._weights_doc, model_version=model_version)
