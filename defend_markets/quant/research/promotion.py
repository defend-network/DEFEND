"""Machine promotion gates for challenger experiments.

Every gate returns PASS / FAIL / NOT_AVAILABLE with the metric, threshold,
observed value, and a reason. Promotion requires all required gates to pass;
a NOT_AVAILABLE optional market metric never permits unsupported claims.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GateResult:
    gate: str
    status: str
    metric: str | None = None
    threshold: float | None = None
    observed: float | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate,
            "status": self.status,
            "metric": self.metric,
            "threshold": self.threshold,
            "observed": self.observed,
            "reason": self.reason,
        }


class PromotionGateSet:
    def __init__(
        self,
        *,
        min_sample: int = 100,
        brier_tolerance: float = 0.01,
        logloss_tolerance: float = 0.02,
        calibration_tolerance: float = 0.05,
        stability_tolerance: float = 0.03,
    ) -> None:
        self._min_sample = min_sample
        self._brier_tolerance = brier_tolerance
        self._logloss_tolerance = logloss_tolerance
        self._calibration_tolerance = calibration_tolerance
        self._stability_tolerance = stability_tolerance

    def evaluate(
        self,
        *,
        leakage_detected: bool,
        sample_n: int,
        challenger_brier: float | None,
        challenger_log_loss: float | None,
        challenger_ece: float | None,
        challenger_brier_std: float | None,
        ablation_kept: bool | None,
        data_quality_ok: bool = True,
        champion_brier: float | None = None,
        champion_log_loss: float | None = None,
        market_metrics_available: bool = False,
    ) -> dict[str, Any]:
        gates: list[GateResult] = []

        gates.append(
            GateResult(
                gate="LEAKAGE",
                status="FAIL" if leakage_detected else "PASS",
                metric="future_leakage",
                observed=1.0 if leakage_detected else 0.0,
                reason="no future rows or state used" if not leakage_detected else "future leakage detected",
            )
        )
        gates.append(
            GateResult(
                gate="SAMPLE",
                status="PASS" if sample_n >= self._min_sample else "FAIL",
                metric="validation_rows",
                threshold=float(self._min_sample),
                observed=float(sample_n),
                reason=f"{sample_n} >= {self._min_sample}" if sample_n >= self._min_sample else f"{sample_n} < {self._min_sample}",
            )
        )
        brier_within = (
            challenger_brier is not None
            and champion_brier is not None
            and challenger_brier <= champion_brier + self._brier_tolerance
        )
        brier_available = challenger_brier is not None
        gates.append(
            GateResult(
                gate="BRIER",
                status=(
                    "NOT_AVAILABLE"
                    if not brier_available
                    else ("PASS" if brier_within else "FAIL")
                ),
                metric="weighted_brier",
                threshold=float(champion_brier + self._brier_tolerance) if champion_brier is not None else None,
                observed=challenger_brier,
                reason=(
                    "metrics missing"
                    if not brier_available
                    else ("challenger brier within tolerance" if brier_within else "challenger materially worse on Brier")
                ),
            )
        )
        logloss_within = (
            challenger_log_loss is not None
            and champion_log_loss is not None
            and challenger_log_loss <= champion_log_loss + self._logloss_tolerance
        )
        logloss_available = challenger_log_loss is not None
        gates.append(
            GateResult(
                gate="LOGLOSS",
                status=(
                    "NOT_AVAILABLE"
                    if not logloss_available
                    else ("PASS" if logloss_within else "FAIL")
                ),
                metric="weighted_log_loss",
                threshold=float(champion_log_loss + self._logloss_tolerance) if champion_log_loss is not None else None,
                observed=challenger_log_loss,
                reason=(
                    "metrics missing"
                    if not logloss_available
                    else ("challenger log loss within tolerance" if logloss_within else "challenger materially worse on log loss")
                ),
            )
        )
        gates.append(
            GateResult(
                gate="CALIBRATION",
                status="PASS" if (challenger_ece is not None and challenger_ece <= self._calibration_tolerance) else ("FAIL" if challenger_ece is not None else "NOT_AVAILABLE"),
                metric="ece",
                threshold=self._calibration_tolerance,
                observed=challenger_ece,
                reason="calibration within tolerance" if (challenger_ece is not None and challenger_ece <= self._calibration_tolerance) else ("metrics missing" if challenger_ece is None else "calibration regression"),
            )
        )
        gates.append(
            GateResult(
                gate="STABILITY",
                status="PASS" if (challenger_brier_std is not None and challenger_brier_std <= self._stability_tolerance) else ("FAIL" if challenger_brier_std is not None else "NOT_AVAILABLE"),
                metric="brier_std_across_windows",
                threshold=self._stability_tolerance,
                observed=challenger_brier_std,
                reason="stable across windows" if (challenger_brier_std is not None and challenger_brier_std <= self._stability_tolerance) else ("metrics missing" if challenger_brier_std is None else "unstable across windows"),
            )
        )
        gates.append(
            GateResult(
                gate="ABLATION",
                status="PASS" if ablation_kept else ("FAIL" if ablation_kept is False else "NOT_AVAILABLE"),
                metric="feature_lift_survives_ablation",
                observed=1.0 if ablation_kept else 0.0,
                reason="claimed feature lift survives ablation" if ablation_kept else ("claimed feature lift fails ablation" if ablation_kept is False else "ablation not run"),
            )
        )
        gates.append(
            GateResult(
                gate="DATA_QUALITY",
                status="PASS" if data_quality_ok else "FAIL",
                metric="data_quality",
                reason="data quality ok" if data_quality_ok else "data quality regression",
            )
        )
        gates.append(
            GateResult(
                gate="MARKET_METRIC",
                status="NOT_AVAILABLE",
                metric="model_market_metrics",
                reason="no valid market observations; market-beating claims not supported" if not market_metrics_available else "market metrics available",
            )
        )

        required = {"LEAKAGE", "SAMPLE", "BRIER", "LOGLOSS", "CALIBRATION", "STABILITY", "ABLATION", "DATA_QUALITY"}
        passed = all(gate.status == "PASS" for gate in gates if gate.gate in required)
        blocked_reasons = [
            gate.reason for gate in gates
            if gate.gate in required and gate.status == "FAIL"
        ]
        return {
            "promotion": "PROMOTION_ALLOWED" if passed else "PROMOTION_BLOCKED",
            "gates": [gate.to_dict() for gate in gates],
            "blockers": blocked_reasons,
            "market_metrics": "NOT_AVAILABLE" if not market_metrics_available else "AVAILABLE",
        }
