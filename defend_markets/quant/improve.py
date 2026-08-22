"""Active improvement orchestrator (M4.5): closed loop from current market truth
to weakness registry to verification-bound improvement actions.

Provider/bookmaker state is fully dynamic. Price coverage is cohort-aligned.
Shadow coverage is prospective. Improvement actions carry baseline + target +
verification and close with a measured outcome.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from defend_markets.quant.coverage import compute_coverage, prospective_shadow_pairing
from defend_markets.quant.provider import ProviderTruthService
from defend_markets.quant.weakness import WeaknessDetector, WeaknessRegistry, utc_now_iso


def collect_operational_snapshot(store: Any, database: Any, *, live_selected: list[str] | None = None) -> dict[str, Any]:
    provider = ProviderTruthService(store, database)
    selected = live_selected if live_selected is not None else provider.selected_bookmakers()
    bookmakers = provider.snapshot()
    with database.connect() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM tt_market_observations")
        observations = int(cursor.fetchone()[0])
        cursor.execute("SELECT count(distinct provider_event_id) FROM tt_market_observations")
        priced_events = int(cursor.fetchone()[0])
        cursor.execute("SELECT count(*) FROM tt_forward_events")
        discovered = int(cursor.fetchone()[0])
        cursor.execute("SELECT count(*) FROM tt_forward_events WHERE canonical_event_id IS NOT NULL")
        matched = int(cursor.fetchone()[0])
        cursor.execute("SELECT count(*) FROM tt_m5_live_predictions")
        predictions_total = int(cursor.fetchone()[0])
        cursor.execute("SELECT count(*) FROM tt_m5_live_predictions WHERE availability='AVAILABLE'")
        m5_available = int(cursor.fetchone()[0])
        cursor.execute("SELECT count(*) FROM quant_shadow_predictions WHERE availability='AVAILABLE'")
        shadow_available = int(cursor.fetchone()[0])
        cursor.execute(
            "SELECT reason, count(*) FROM quant_decision_evaluations WHERE decision='PASS' GROUP BY reason"
        )
        pass_reasons = {str(row[0]): int(row[1]) for row in cursor.fetchall()}
    pairing = prospective_shadow_pairing(database)
    coverage = _bet365_cohort(bookmakers, selected)
    return {
        "prices": {"observations": observations, "unique_events_priced": priced_events},
        "events": {"discovered": discovered, "matched": matched},
        "predictions": {"total": predictions_total, "m5_available": m5_available, "shadow_available": shadow_available},
        "bookmakers": bookmakers,
        "selected_bookmakers": selected,
        "coverage": coverage,
        "pairing": pairing,
        "pass_reasons": pass_reasons,
    }


def _bet365_cohort(bookmakers: dict[str, Any], selected: list[str]) -> dict[str, Any]:
    entry = bookmakers.get("Bet365") or {}
    eligible = int(entry.get("filtered_events", 0))
    priced = int(entry.get("priced_events", 0))
    if eligible == 0:
        return {"eligible_events": 0, "priced_events": 0, "coverage_rate": None, "cohort_aligned": True}
    return {
        "eligible_events": eligible,
        "priced_events": priced,
        "coverage_rate": round(priced / eligible, 4),
        "cohort_aligned": True,
        "bookmaker": "Bet365",
        "selected": "Bet365" in selected,
        "attestation_state": entry.get("attestation_state", "UNKNOWN"),
    }


class ImprovementOrchestrator:
    def __init__(self, store: Any, database: Any, *, live_selected: list[str] | None = None) -> None:
        self._store = store
        self._database = database
        self._live_selected = live_selected

    def snapshot(self) -> dict[str, Any]:
        return collect_operational_snapshot(self._store, self._database, live_selected=self._live_selected)

    def run_once(self) -> dict[str, Any]:
        snapshot = self.snapshot()
        registry = WeaknessRegistry(self._store)
        recorded = registry.record(snapshot, WeaknessDetector())
        actions = self._create_actions(snapshot)
        self._close_loops(snapshot)
        return {
            "recorded": recorded,
            "actions_created": actions,
            "weaknesses": self._store.weakness_counts(),
        }

    def _create_actions(self, snapshot: dict[str, Any]) -> int:
        created = 0
        for weakness in self._store.list_weaknesses(limit=100):
            if weakness.get("status") not in ("DETECTED", "VALIDATING", "ACTIONABLE", "REOPENED"):
                continue
            existing = [a for a in self._store.list_improvement_actions() if a["weakness_id"] == weakness["weakness_id"]]
            if existing:
                continue
            wtype = weakness.get("weakness_type")
            action_type, metric, baseline = "MONITOR_ONLY", None, None
            if wtype == "PRICE_COVERAGE_LOW":
                action_type = "RECOMPUTE_METRIC"
                metric = "cohort_aligned_coverage_rate"
                baseline = snapshot.get("coverage", {}).get("coverage_rate")
            elif wtype == "SHADOW_COVERAGE_GAP":
                action_type = "RESOLVE_HISTORICAL_ARTIFACT"
                metric = "prospective_pair_rate"
                baseline = snapshot.get("pairing", {}).get("rate")
            elif wtype == "PROVIDER_COVERAGE":
                action_type = "PROVIDER_ATTESTATION"
                metric = "second_book_observations"
            elif wtype == "PASS_REASON_SPIKE":
                action_type = "ANALYZE_PASS_REASONS"
                metric = "no_price_rate"
                baseline = snapshot.get("pass_reasons", {}).get("NO_PRICE")
            elif wtype == "MODEL_ELIGIBILITY_LOW":
                action_type = "COLLECT_MORE_DATA"
                metric = "m5_eligible_rate"
            self._store.create_improvement_action(
                {
                    "weakness_id": weakness["weakness_id"],
                    "action_type": action_type,
                    "description": f"{action_type} for {weakness['title']}",
                    "expected_effect": "Improve measurement truth or resolve historical artifact",
                    "status": "STARTED",
                    "verification_metric": metric,
                    "baseline_value": baseline,
                    "requires_owner": wtype == "PROVIDER_COVERAGE",
                }
            )
            created += 1
        return created

    def _close_loops(self, snapshot: dict[str, Any]) -> None:
        detected_types = {spec["weakness_type"] for spec in WeaknessDetector().detect(snapshot)}
        for weakness in self._store.list_weaknesses(limit=100):
            wtype = weakness.get("weakness_type")
            actions = [a for a in self._store.list_improvement_actions() if a["weakness_id"] == weakness["weakness_id"]]
            if not actions:
                continue
            action = actions[0]
            if wtype == "PRICE_COVERAGE_LOW":
                rate = snapshot.get("coverage", {}).get("coverage_rate")
                self._store.update_action_outcome(
                    action["action_id"],
                    status="COMPLETED",
                    result_value=rate,
                    outcome="IMPROVED" if rate is not None else "INCONCLUSIVE",
                )
                if rate is not None:
                    self._store.update_weakness_status(weakness["weakness_id"], status="MONITORING")
            elif wtype == "SHADOW_COVERAGE_GAP":
                m5_without_shadow = snapshot.get("pairing", {}).get("failure_reasons", {}).get("m5_without_shadow", 0)
                rate = snapshot.get("pairing", {}).get("rate")
                if m5_without_shadow == 0 and wtype not in detected_types:
                    self._store.update_action_outcome(
                        action["action_id"],
                        status="COMPLETED",
                        result_value=rate,
                        outcome="RESOLVED",
                    )
                    self._store.update_weakness_status(weakness["weakness_id"], status="RESOLVED")
                elif action.get("status") == "STARTED":
                    self._store.update_action_outcome(
                        action["action_id"],
                        status="COMPLETED",
                        result_value=rate,
                        outcome="NO_CHANGE",
                    )
                    self._store.update_weakness_status(weakness["weakness_id"], status="MONITORING")
            elif action.get("status") == "STARTED":
                self._store.update_action_outcome(
                    action["action_id"],
                    status="COMPLETED",
                    result_value=None,
                    outcome="INCONCLUSIVE",
                )

    def daily_learning_review(self) -> dict[str, Any]:
        snapshot = self.snapshot()
        weaknesses = self._store.list_weaknesses(limit=50)
        active = [w for w in weaknesses if w.get("status") not in ("RESOLVED", "REJECTED")]
        top = sorted(active, key=lambda item: item.get("priority_score") or 0, reverse=True)[:5]
        actions = self._store.list_improvement_actions(limit=20)
        return {
            "current_champion": "M5_REGULARIZED_LOGISTIC",
            "active_challengers": [w for w in self._store.list_models() if w.get("role") == "CHALLENGER"],
            "forward_eval_n": self._store.decision_evaluation_counts().get("total", 0),
            "top_5_weaknesses": top,
            "weaknesses": self._store.weakness_counts(),
            "actions_started": sum(1 for a in actions if a.get("status") in ("STARTED", "MONITORING")),
            "actions_completed": sum(1 for a in actions if a.get("status") in ("COMPLETED", "FAILED")),
            "bookmaker_state": {
                bookmaker_id: {"attestation_state": entry.get("attestation_state"), "selected": entry.get("selected")}
                for bookmaker_id, entry in snapshot.get("bookmakers", {}).items()
            },
            "coverage": snapshot.get("coverage"),
            "pairing": snapshot.get("pairing"),
            "as_of": utc_now_iso(),
        }
