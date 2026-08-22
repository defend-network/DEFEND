"""Settlement -> evaluation -> error journal -> metrics pipeline.

Outcomes are joined to predictions idempotently, corrections are audited, and
deterministic Brier / log loss / calibration / drift are computed. No fabricated
outcomes and no future-feature leakage.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol, Sequence

from defend_markets.quant.research.metrics import brier_score, calibration_buckets, ece_score, log_loss_score


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class PredictionOutcome:
    prediction_id: str
    event_id: str
    model_id: str
    model_version: str
    prediction_ts: str
    predicted_probability: float
    actual: float
    outcome_version: str
    league: str | None = None
    history_depth: dict[str, Any] | None = None
    market_data_available: bool | None = None


class OutcomeSource(Protocol):
    def settled_predictions(self) -> Sequence[PredictionOutcome]: ...


class PostgresOutcomeSource:
    def __init__(self, database: Any) -> None:
        self._database = database

    def settled_predictions(self):
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT p.prediction_id, p.canonical_event_id, p.model_id, p.model_version, "
                "p.generated_at, p.p_a, r.completed_at, "
                "(CASE WHEN r.home_score > r.away_score THEN 1.0 ELSE 0.0 END) AS actual "
                "FROM tt_m5_live_predictions p "
                "JOIN tt_match_results r ON r.event_key = p.canonical_event_id "
                "WHERE p.availability = 'AVAILABLE' AND r.home_score IS NOT NULL "
                "AND r.away_score IS NOT NULL ORDER BY p.prediction_id"
            )
            rows = [
                PredictionOutcome(
                    prediction_id=str(row[0]),
                    event_id=str(row[1]),
                    model_id=str(row[2]),
                    model_version=str(row[3]),
                    prediction_ts=str(row[4]),
                    predicted_probability=float(row[5]),
                    actual=float(row[7]),
                    outcome_version=str(row[6]),
                )
                for row in cursor.fetchall()
            ]
        return rows


class EvaluationService:
    def __init__(
        self,
        store: Any,
        *,
        outcome_source: OutcomeSource,
        metric_calculation_version: str = "v1",
    ) -> None:
        self._store = store
        self._outcome_source = outcome_source
        self._metric_calculation_version = metric_calculation_version

    @staticmethod
    def _contributions(p: float, actual: float) -> tuple[float, float, float]:
        clipped = min(max(p, 1e-9), 1.0 - 1e-9)
        abs_error = abs(p - actual)
        brier = (p - actual) ** 2
        logloss = -(actual * math.log(clipped) + (1.0 - actual) * math.log(1.0 - clipped))
        return abs_error, brier, logloss

    @staticmethod
    def _confidence_band(p: float) -> str:
        if p < 0.55:
            return "low_under_0.55"
        if p < 0.75:
            return "mid_0.55_0.75"
        return "high_over_0.75"

    def settle(self) -> dict[str, Any]:
        inserted = 0
        skipped = 0
        corrected = 0
        for outcome in self._outcome_source.settled_predictions():
            existing = [
                evaluation for evaluation in self._store.list_evaluations(limit=100000)
                if evaluation["prediction_id"] == outcome.prediction_id
                and evaluation["event_id"] == outcome.event_id
                and evaluation["status"] == "ACTIVE"
            ]
            if existing and float(existing[0]["actual"]) != outcome.actual:
                self._store.supersede_evaluation(existing[0]["evaluation_id"])
                self._store.record_correction(
                    {
                        "event_id": outcome.event_id,
                        "evaluation_id": existing[0]["evaluation_id"],
                        "previous_actual": existing[0]["actual"],
                        "new_actual": outcome.actual,
                        "source": "result_correction",
                    }
                )
                corrected += 1
            abs_error, brier, logloss = self._contributions(outcome.predicted_probability, outcome.actual)
            created = self._store.insert_evaluation(
                {
                    "prediction_id": outcome.prediction_id,
                    "event_id": outcome.event_id,
                    "model_id": outcome.model_id,
                    "model_version": outcome.model_version,
                    "prediction_ts": outcome.prediction_ts,
                    "predicted_probability": outcome.predicted_probability,
                    "actual": outcome.actual,
                    "outcome_version": outcome.outcome_version,
                    "brier_contribution": round(brier, 8),
                    "logloss_contribution": round(logloss, 8),
                    "abs_probability_error": round(abs_error, 6),
                }
            )
            if created:
                inserted += 1
                evaluation = next(
                    evaluation for evaluation in self._store.list_evaluations(limit=100000)
                    if evaluation["prediction_id"] == outcome.prediction_id
                    and evaluation["event_id"] == outcome.event_id
                )
                self._store.insert_prediction_error(
                    {
                        "evaluation_id": evaluation["evaluation_id"],
                        "event_id": outcome.event_id,
                        "prediction_id": outcome.prediction_id,
                        "prediction_ts": outcome.prediction_ts,
                        "model_id": outcome.model_id,
                        "model_version": outcome.model_version,
                        "predicted_probability": outcome.predicted_probability,
                        "predicted_side": "home" if outcome.predicted_probability >= 0.5 else "away",
                        "actual": outcome.actual,
                        "abs_probability_error": round(abs_error, 6),
                        "brier_contribution": round(brier, 8),
                        "logloss_contribution": round(logloss, 8),
                        "confidence_band": self._confidence_band(outcome.predicted_probability),
                        "league": outcome.league,
                        "market_data_available": outcome.market_data_available,
                    }
                )
            else:
                skipped += 1
        return {"inserted": inserted, "skipped": skipped, "corrected": corrected}

    def active_evaluations(self) -> list[dict[str, Any]]:
        return [
            evaluation for evaluation in self._store.list_evaluations(limit=100000)
            if evaluation["status"] == "ACTIVE"
        ]

    def compute_metrics(self) -> dict[str, Any]:
        evaluations = self.active_evaluations()
        preds = [float(evaluation["predicted_probability"]) for evaluation in evaluations]
        actuals = [float(evaluation["actual"]) for evaluation in evaluations]
        report: dict[str, Any] = {
            "evaluation_rows": len(evaluations),
            "computed_at": utc_now_iso(),
            "metric_calculation_version": self._metric_calculation_version,
        }
        if evaluations:
            report["brier"] = round(brier_score(actuals, preds), 6)
            report["log_loss"] = round(log_loss_score(actuals, preds), 6)
            report["ece"] = ece_score(actuals, preds)
            report["calibration"] = calibration_buckets(actuals, preds)
        else:
            report["brier"] = None
            report["log_loss"] = None
            report["ece"] = None
            report["calibration"] = []
        report["drift_state"] = self._drift(report)
        report["state_hash"] = self._state_hash(report)
        self._store.insert_metric_snapshot(
            {
                "metric_calculation_version": self._metric_calculation_version,
                "computed_at": report["computed_at"],
                "state_hash": report["state_hash"],
                "brier": report["brier"],
                "log_loss": report["log_loss"],
                "ece": report["ece"],
                "evaluation_rows": report["evaluation_rows"],
                "drift_state": report["drift_state"],
                "detail": {"calibration": report["calibration"]},
            }
        )
        return report

    def _drift(self, metrics: dict[str, Any]) -> str:
        if metrics["evaluation_rows"] < 30:
            return "INSUFFICIENT_EVIDENCE"
        if metrics["ece"] is not None and metrics["ece"] > 0.05:
            return "DEGRADED"
        if metrics["ece"] is not None and metrics["ece"] > 0.03:
            return "WATCH"
        return "NONE"

    def evaluation_state(self) -> dict[str, Any]:
        counts = self._store.evaluation_counts()
        predictions = {"total": 0, "unsettled": 0, "settled": 0}
        linked = counts["active"] + counts["superseded"]
        if counts["active"] == 0 and counts["superseded"] == 0:
            state = "PREDICTIONS_UNSETTLED"
        else:
            state = "EVALUATION_READY"
        return {
            "state": state,
            "predictions_total": predictions["total"],
            "predictions_unsettled": predictions["unsettled"],
            "predictions_settled": linked,
            "settled_linked": linked,
            "settled_unlinked": 0,
            "evaluation_rows": counts["active"],
        }

    @staticmethod
    def _state_hash(metrics: dict[str, Any]) -> str:
        payload = {
            "brier": metrics.get("brier"),
            "log_loss": metrics.get("log_loss"),
            "ece": metrics.get("ece"),
            "evaluation_rows": metrics.get("evaluation_rows"),
            "drift_state": metrics.get("drift_state"),
        }
        return hashlib.sha256(repr(sorted(payload.items())).encode("utf-8")).hexdigest()
