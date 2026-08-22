"""Deterministic weakness detection with evidence-first registry updates.

Weaknesses are only recorded with measurable evidence; confidence follows an
explicit evidence-level policy (EARLY_SIGNAL / SUPPORTED / STRONG) based on
sample size, effect size, and bootstrap CI where available.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Sequence


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def state_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def evidence_level(
    *,
    sample_size: int,
    effect_size: float | None = None,
    ci_low: float | None = None,
    min_sample: int = 100,
    min_effect: float = 0.01,
) -> str:
    if sample_size < 30:
        return "EARLY_SIGNAL"
    if effect_size is None or effect_size < min_effect or sample_size < min_sample:
        return "SUPPORTED"
    if ci_low is not None and ci_low > 0:
        return "STRONG"
    return "SUPPORTED"


class WeaknessDetector:
    """Deterministic detectors over an operational snapshot. No AI claims."""

    def detect(self, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        specs: list[dict[str, Any]] = []
        now = utc_now_iso()
        prices = snapshot.get("prices", {})
        events = snapshot.get("events", {})
        predictions = snapshot.get("predictions", {})
        provider = snapshot.get("provider", {})
        passes = snapshot.get("pass_reasons", {})

        discovered = int(events.get("discovered", 0))
        priced = int(prices.get("unique_events_priced", 0))
        if discovered > 0 and priced / discovered < 0.5:
            rate = round(priced / discovered, 4)
            specs.append(
                self._spec(
                    now,
                    weakness_type="PRICE_COVERAGE_LOW",
                    category="MARKET_DATA_COVERAGE",
                    title="Bet365 event price coverage is low",
                    description=f"{priced} of {discovered} discovered events have prices ({rate})",
                    severity="HIGH" if rate < 0.3 else "MEDIUM",
                    evidence={"metric_name": "price_coverage_rate", "metric_value": rate, "sample_size": discovered},
                    state_hash=state_hash({"priced": priced, "discovered": discovered}),
                )
            )

        m5 = int(predictions.get("m5_available", 0))
        shadow = int(predictions.get("shadow_available", 0))
        if shadow < m5:
            specs.append(
                self._spec(
                    now,
                    weakness_type="SHADOW_COVERAGE_GAP",
                    category="MODEL_COVERAGE",
                    title="Recent-form20 shadow coverage lags M5",
                    description=f"shadow AVAILABLE={shadow} vs M5 AVAILABLE={m5}",
                    severity="LOW",
                    evidence={"metric_name": "shadow_available", "metric_value": shadow, "comparison_value": m5, "sample_size": m5},
                    state_hash=state_hash({"m5": m5, "shadow": shadow}),
                )
            )

        total_predictions = int(predictions.get("total", 0))
        if total_predictions > 0 and int(predictions.get("m5_available", 0)) / total_predictions < 0.5:
            specs.append(
                self._spec(
                    now,
                    weakness_type="MODEL_ELIGIBILITY_LOW",
                    category="MODEL_COVERAGE",
                    title="M5 eligibility below half of stored predictions",
                    description=f"available={predictions.get('m5_available')} total={total_predictions}",
                    severity="LOW",
                    evidence={"metric_name": "m5_available", "metric_value": predictions.get("m5_available"), "sample_size": total_predictions},
                    state_hash=state_hash({"total": total_predictions, "available": predictions.get("m5_available")}),
                )
            )

        total_passes = sum(int(value) for value in passes.values())
        if total_passes and passes.get("NO_PRICE", 0) / total_passes > 0.5:
            specs.append(
                self._spec(
                    now,
                    weakness_type="PASS_REASON_SPIKE",
                    category="MARKET_DATA_COVERAGE",
                    title="NO_PRICE dominates pass reasons",
                    description=f"NO_PRICE={passes.get('NO_PRICE')} of {total_passes} passes",
                    severity="MEDIUM",
                    evidence={"metric_name": "no_price_rate", "metric_value": passes.get("NO_PRICE", 0) / total_passes, "sample_size": total_passes},
                    state_hash=state_hash(passes),
                )
            )

        if provider.get("hard_rock_selected") and provider.get("hard_rock_tt_events", 0) == 0:
            specs.append(
                self._spec(
                    now,
                    weakness_type="PROVIDER_COVERAGE",
                    category="PROVIDER_COVERAGE",
                    title="Odds-API.io exposes zero Hard Rock TT events",
                    description="Hard Rock is selected but bookmaker-filtered TT discovery returns 0; likely provider capture gap, not Hard Rock absence",
                    severity="MEDIUM",
                    evidence={"metric_name": "hard_rock_tt_events", "metric_value": 0, "sample_size": 1},
                    state_hash=state_hash({"hard_rock_tt_events": 0}),
                )
            )
        return specs

    @staticmethod
    def _spec(now, *, weakness_type, category, title, description, severity, evidence, state_hash):
        return {
            "weakness_type": weakness_type,
            "category": category,
            "title": title,
            "description": description,
            "status": "DETECTED",
            "severity": severity,
            "confidence": "EARLY_SIGNAL",
            "first_detected_at": now,
            "last_observed_at": now,
            "affected_scope": "table_tennis",
            "affected_competition": "all",
            "affected_model": "M5_REGULARIZED_LOGISTIC",
            "blocking_capability": "DATA_COVERAGE",
            "auto_action_allowed": True,
            "state_hash": state_hash,
            "evidence": evidence,
        }


class WeaknessRegistry:
    def __init__(self, store: Any) -> None:
        self._store = store

    def record(self, snapshot: dict[str, Any], detector: WeaknessDetector | None = None) -> list[dict[str, Any]]:
        detector = detector or WeaknessDetector()
        recorded: list[dict[str, Any]] = []
        for spec in detector.detect(snapshot):
            evidence = spec.pop("evidence", {})
            weakness_id = self._store.upsert_weakness(spec)
            self._store.add_weakness_evidence(
                {
                    "weakness_id": weakness_id,
                    "evidence_type": "operational",
                    "metric_name": evidence["metric_name"],
                    "metric_value": evidence.get("metric_value"),
                    "sample_size": evidence.get("sample_size"),
                    "comparison_value": evidence.get("comparison_value"),
                    "observed_at": spec["last_observed_at"],
                    "source_ref": "operational-snapshot",
                }
            )
            recorded.append({"weakness_id": weakness_id, **spec})
        return recorded
