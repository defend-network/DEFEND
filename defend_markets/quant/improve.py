"""Active improvement orchestrator: closed loop from operational truth to
weakness registry to improvement action to data-derived hypothesis.

Deterministic first, one bounded improvement action per review, evidence-based
verification, and a daily learning review. Never modifies the production
champion or real-money authority.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from defend_markets.quant.weakness import WeaknessDetector, WeaknessRegistry, utc_now_iso


def collect_operational_snapshot(database: Any) -> dict[str, Any]:
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
    return {
        "prices": {"observations": observations, "unique_events_priced": priced_events},
        "events": {"discovered": discovered, "matched": matched},
        "predictions": {"total": predictions_total, "m5_available": m5_available, "shadow_available": shadow_available},
        "pass_reasons": pass_reasons,
        "provider": {"hard_rock_selected": True, "hard_rock_tt_events": 0},
    }


class ImprovementOrchestrator:
    def __init__(self, store: Any, database: Any) -> None:
        self._store = store
        self._database = database

    def run_once(self) -> dict[str, Any]:
        snapshot = collect_operational_snapshot(self._database)
        registry = WeaknessRegistry(self._store)
        recorded = registry.record(snapshot, WeaknessDetector())
        weaknesses = self._store.list_weaknesses(limit=100)
        actionable = [
            weakness for weakness in weaknesses
            if weakness.get("status") in ("DETECTED", "VALIDATING", "ACTIONABLE", "REOPENED")
            and weakness.get("auto_action_allowed")
        ]
        if actionable:
            top = max(actionable, key=lambda item: item.get("priority_score") or 0)
            action_id = self._store.create_improvement_action(
                {
                    "weakness_id": top["weakness_id"],
                    "action_type": "MONITOR_ONLY",
                    "description": f"Track {top['title']} and verify via operational metric",
                    "expected_effect": "Reduce blocking data-coverage weakness",
                    "status": "STARTED",
                    "verification_metric": "price_coverage_rate",
                    "baseline_value": None,
                }
            )
            self._store.update_weakness_status(top["weakness_id"], status="MONITORING")
            selected = {"weakness_id": top["weakness_id"], "title": top["title"], "action_id": action_id}
        else:
            selected = None
        return {"recorded": recorded, "selected": selected, "weaknesses": self._store.weakness_counts()}

    def daily_learning_review(self) -> dict[str, Any]:
        snapshot = collect_operational_snapshot(self._database)
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
            "provider_state": {"hard_rock_tt_events": snapshot["provider"]["hard_rock_tt_events"]},
            "data_coverage": snapshot["prices"],
            "as_of": utc_now_iso(),
        }
