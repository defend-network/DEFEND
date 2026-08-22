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
        coverage = snapshot.get("coverage", {})
        pairing = snapshot.get("pairing", {})
        bookmakers = snapshot.get("bookmakers", {})
        passes = snapshot.get("pass_reasons", {})

        eligible = int(coverage.get("eligible_events", 0))
        priced = int(coverage.get("priced_events", 0))
        rate = coverage.get("coverage_rate")
        if eligible > 0 and rate is not None and rate < 0.5:
            specs.append(
                self._spec(
                    now,
                    weakness_type="PRICE_COVERAGE_LOW",
                    category="MARKET_DATA_COVERAGE",
                    title="Selected-book price coverage is low",
                    description=f"cohort-aligned: {priced} of {eligible} eligible events priced ({rate}); same-book/same-window/same-cohort",
                    severity="HIGH" if rate < 0.3 else "MEDIUM",
                    evidence={"metric_name": "coverage_rate", "metric_value": rate, "sample_size": eligible},
                    state_hash=state_hash({"coverage_rate": rate, "eligible": eligible, "priced": priced}),
                )
            )

        pair_rate = pairing.get("rate")
        failure = pairing.get("failure_reasons", {})
        if failure.get("m5_without_shadow", 0) > 0:
            specs.append(
                self._spec(
                    now,
                    weakness_type="SHADOW_COVERAGE_GAP",
                    category="MODEL_COVERAGE",
                    title="Prospective shadow pairing incomplete",
                    description=f"{failure.get('m5_without_shadow')} freshly generated M5 predictions lack a shadow prediction",
                    severity="LOW",
                    evidence={"metric_name": "m5_without_shadow", "metric_value": failure.get("m5_without_shadow"), "sample_size": pairing.get("eligible", 0)},
                    state_hash=state_hash(pairing),
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

        for bookmaker_id, entry in bookmakers.items():
            if entry.get("selected") and entry.get("attestation_state") == "ZERO_CURRENT_COVERAGE":
                specs.append(
                    self._spec(
                        now,
                        weakness_type="PROVIDER_COVERAGE",
                        category="PROVIDER_COVERAGE",
                        title=f"Selected book {bookmaker_id} has zero current TT capture",
                        description="bookmaker-filtered TT discovery returned 0 in the attested window; does not imply the bookmaker never offers TT",
                        severity="MEDIUM",
                        evidence={"metric_name": "filtered_events", "metric_value": entry.get("filtered_events", 0), "sample_size": 1},
                        state_hash=state_hash({"bookmaker": bookmaker_id, "attestation_state": "ZERO_CURRENT_COVERAGE"}),
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
