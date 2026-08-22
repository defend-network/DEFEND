"""Machine promotion gates for challenger experiments (policy v2).

Policy v2 adds FEATURE_USEFULNESS and PARSIMONY gates: a challenger that adds
model complexity must demonstrate measurable positive lift, never mere
equality. Paired out-of-sample deltas (with bootstrap CI) drive the decision.
Every result records the promotion policy version.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from defend_markets.quant.research.paired import classify_lift


PROMOTION_POLICY_VERSION = 2


@dataclass(frozen=True)
class PromotionPolicy:
    version: int = PROMOTION_POLICY_VERSION
    min_sample: int = 100
    brier_tolerance: float = 0.01
    logloss_tolerance: float = 0.02
    calibration_tolerance: float = 0.05
    stability_tolerance: float = 0.03
    min_absolute_lift: float = 1e-4
    min_calibration_improvement: float = 5e-3


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
    def __init__(self, policy: PromotionPolicy | None = None) -> None:
        self._policy = policy or PromotionPolicy()

    def evaluate(
        self,
        *,
        leakage_detected: bool,
        sample_n: int,
        challenger_brier: float | None,
        challenger_log_loss: float | None,
        challenger_ece: float | None,
        challenger_brier_std: float | None,
        added_complexity: bool,
        metric_deltas: dict[str, Any] | None = None,
        calibration_improvement: bool = False,
        data_quality_ok: bool = True,
        champion_brier: float | None = None,
        champion_log_loss: float | None = None,
        market_metrics_available: bool = False,
    ) -> dict[str, Any]:
        policy = self._policy
        deltas = metric_deltas or {}
        delta_brier = deltas.get("delta_brier")
        delta_ci_low = deltas.get("delta_brier_ci_low")
        delta_logloss = deltas.get("delta_logloss")

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
                status="PASS" if sample_n >= policy.min_sample else "FAIL",
                metric="validation_rows",
                threshold=float(policy.min_sample),
                observed=float(sample_n),
                reason=f"{sample_n} >= {policy.min_sample}" if sample_n >= policy.min_sample else f"{sample_n} < {policy.min_sample}",
            )
        )
        brier_ok = challenger_brier is not None and champion_brier is not None and challenger_brier <= champion_brier + policy.brier_tolerance
        gates.append(
            GateResult(
                gate="BRIER",
                status="NOT_AVAILABLE" if challenger_brier is None else ("PASS" if brier_ok else "FAIL"),
                metric="weighted_brier",
                threshold=float(champion_brier + policy.brier_tolerance) if champion_brier is not None else None,
                observed=challenger_brier,
                reason="challenger brier within tolerance" if brier_ok else ("metrics missing" if challenger_brier is None else "challenger materially worse on Brier"),
            )
        )
        logloss_ok = challenger_log_loss is not None and champion_log_loss is not None and challenger_log_loss <= champion_log_loss + policy.logloss_tolerance
        gates.append(
            GateResult(
                gate="LOGLOSS",
                status="NOT_AVAILABLE" if challenger_log_loss is None else ("PASS" if logloss_ok else "FAIL"),
                metric="weighted_log_loss",
                threshold=float(champion_log_loss + policy.logloss_tolerance) if champion_log_loss is not None else None,
                observed=challenger_log_loss,
                reason="challenger log loss within tolerance" if logloss_ok else ("metrics missing" if challenger_log_loss is None else "challenger materially worse on log loss"),
            )
        )
        gates.append(
            GateResult(
                gate="CALIBRATION",
                status="PASS" if (challenger_ece is not None and challenger_ece <= policy.calibration_tolerance) else ("FAIL" if challenger_ece is not None else "NOT_AVAILABLE"),
                metric="ece",
                threshold=policy.calibration_tolerance,
                observed=challenger_ece,
                reason="calibration within tolerance" if (challenger_ece is not None and challenger_ece <= policy.calibration_tolerance) else ("metrics missing" if challenger_ece is None else "calibration regression"),
            )
        )
        gates.append(
            GateResult(
                gate="STABILITY",
                status="PASS" if (challenger_brier_std is not None and challenger_brier_std <= policy.stability_tolerance) else ("FAIL" if challenger_brier_std is not None else "NOT_AVAILABLE"),
                metric="brier_std_across_windows",
                threshold=policy.stability_tolerance,
                observed=challenger_brier_std,
                reason="stable across windows" if (challenger_brier_std is not None and challenger_brier_std <= policy.stability_tolerance) else ("metrics missing" if challenger_brier_std is None else "unstable across windows"),
            )
        )

        usefulness_status = "NOT_AVAILABLE"
        usefulness_reason = "no added complexity; usefulness gate not required"
        if added_complexity:
            classification = classify_lift(delta_brier, delta_ci_low, min_lift=policy.min_absolute_lift)
            if classification == "MEASURABLE_POSITIVE_LIFT":
                usefulness_status = "PASS"
                usefulness_reason = "paired out-of-sample positive lift measured"
            elif classification == "MEASURABLE_REGRESSION":
                usefulness_status = "FAIL"
                usefulness_reason = "measurable regression vs baseline"
            elif calibration_improvement:
                usefulness_status = "PASS"
                usefulness_reason = "meaningful calibration improvement without global regression"
            else:
                usefulness_status = "FAIL"
                usefulness_reason = "no measurable lift (equality is not utility)"
        gates.append(
            GateResult(
                gate="FEATURE_USEFULNESS",
                status=usefulness_status,
                metric="delta_brier",
                threshold=policy.min_absolute_lift,
                observed=delta_brier,
                reason=usefulness_reason,
            )
        )

        parsimony_status = "NOT_AVAILABLE"
        parsimony_reason = "no added complexity; parsimony not binding"
        if added_complexity:
            if delta_brier is not None and delta_brier >= policy.min_absolute_lift:
                parsimony_status = "PASS"
                parsimony_reason = "added feature demonstrates benefit over baseline"
            else:
                parsimony_status = "FAIL"
                parsimony_reason = "no demonstrated benefit; simpler model is preferred"
        gates.append(
            GateResult(
                gate="PARSIMONY",
                status=parsimony_status,
                metric="delta_brier",
                threshold=policy.min_absolute_lift,
                observed=delta_brier,
                reason=parsimony_reason,
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

        required = {"LEAKAGE", "SAMPLE", "BRIER", "LOGLOSS", "CALIBRATION", "STABILITY", "DATA_QUALITY"}
        if added_complexity:
            required.update({"FEATURE_USEFULNESS", "PARSIMONY"})
        blocked_reasons = [
            gate.reason for gate in gates
            if gate.gate in required and gate.status == "FAIL"
        ]
        passed = all(gate.status == "PASS" for gate in gates if gate.gate in required)
        return {
            "promotion": "PROMOTION_ALLOWED" if passed else "PROMOTION_BLOCKED",
            "promotion_policy_version": policy.version,
            "gates": [gate.to_dict() for gate in gates],
            "blockers": blocked_reasons,
            "market_metrics": "NOT_AVAILABLE" if not market_metrics_available else "AVAILABLE",
            "metric_deltas": {
                "delta_brier": delta_brier,
                "delta_brier_ci_low": deltas.get("delta_brier_ci_low"),
                "delta_brier_ci_high": deltas.get("delta_brier_ci_high"),
                "delta_logloss": delta_logloss,
                "delta_logloss_ci_low": deltas.get("delta_logloss_ci_low"),
                "delta_logloss_ci_high": deltas.get("delta_logloss_ci_high"),
            },
        }
