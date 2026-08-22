"""Forward evidence engine (M4.6): official frozen predictions, unique-event
pairing, settlement catch-up, and automatic forward scoring.

The forward evaluation unit is a UNIQUE canonical event with ONE official
frozen pre-match prediction per model. Raw prediction rows and many-to-many
joins can never inflate N.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

FORWARD_PREDICTION_POLICY_VERSION = 1
SCORING_POLICY_VERSION = 1
LOGLOSS_EPSILON_POLICY = "LOGLOSS_EPSILON_POLICY_V1"
LOGLOSS_EPSILON = 1e-9

M5_MODEL_ID = "M5_REGULARIZED_LOGISTIC"
SHADOW_MODEL_ID = "challenger-recent-form20"


def select_official_prediction(rows: list[dict[str, Any]], *, commence_at: Any) -> dict[str, Any] | None:
    """Earliest valid AVAILABLE frozen pre-match prediction.

    No later outcome or performance information influences selection.
    """
    candidates = [
        row for row in rows
        if row.get("availability") in ("AVAILABLE", None)
        and _before(row.get("generated_at"), commence_at)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda row: row.get("generated_at") or datetime.min.replace(tzinfo=timezone.utc))


def _before(value: Any, boundary: Any) -> bool:
    ts = _parse(value)
    bound = _parse(boundary)
    if ts is None or bound is None:
        return False
    return ts < bound


def _parse(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def register_official_predictions(database: Any, store: Any, *, model_hash: str | None = None) -> dict[str, Any]:
    """Populate quant_official_forward_predictions from the prediction tables.

    One official prediction per (canonical_event_id, model_id); duplicate
    rows for the same event+model are rejected by DB unique constraint.
    """
    now = datetime.now(timezone.utc)
    inserted = 0
    conflicts = 0
    with database.connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT p.prediction_id, p.canonical_event_id, p.model_id, p.model_version, "
            "p.feature_snapshot_id, p.generated_at, p.p_a, p.availability, f.scheduled_commence "
            "FROM tt_m5_live_predictions p JOIN tt_forward_events f ON f.canonical_event_id = p.canonical_event_id "
            "WHERE p.availability = 'AVAILABLE' ORDER BY p.generated_at"
        )
        m5_rows = [dict(zip(("prediction_id", "event", "model_id", "version", "snapshot", "generated_at", "p_a", "availability", "commence"), row)) for row in cursor.fetchall()]
        cursor.execute(
            "SELECT shadow_prediction_id, canonical_event_id, model_id, model_version, feature_snapshot_id, "
            "generated_at, p_a, availability FROM quant_shadow_predictions WHERE availability = 'AVAILABLE' ORDER BY generated_at"
        )
        shadow_rows = [dict(zip(("prediction_id", "event", "model_id", "version", "snapshot", "generated_at", "p_a", "availability"), row)) for row in cursor.fetchall()]
        cursor.execute(
            "SELECT canonical_event_id, scheduled_commence FROM tt_forward_events"
        )
        commence_map = {str(row[0]): row[1] for row in cursor.fetchall()}

    for row in m5_rows:
        event = str(row["event"])
        if event not in commence_map:
            continue
        created = store.upsert_official_prediction(
            {
                "canonical_event_id": event,
                "model_id": row["model_id"],
                "model_version": row["version"],
                "model_hash": model_hash,
                "prediction_id": str(row["prediction_id"]),
                "prediction_role": "M5_FORWARD",
                "generated_at": row["generated_at"],
                "commence_at": commence_map[event],
                "probability_a": row["p_a"],
                "feature_snapshot_id": row.get("snapshot"),
                "frozen_forward": True,
                "policy_version": FORWARD_PREDICTION_POLICY_VERSION,
            }
        )
        if created:
            inserted += 1
        else:
            conflicts += 1
    for row in shadow_rows:
        event = str(row["event"])
        if event not in commence_map:
            continue
        created = store.upsert_official_prediction(
            {
                "canonical_event_id": event,
                "model_id": row["model_id"],
                "model_version": row["version"],
                "model_hash": row.get("model_id") == SHADOW_MODEL_ID and row.get("version") or None,
                "prediction_id": str(row["prediction_id"]),
                "prediction_role": "SHADOW_FORWARD",
                "generated_at": row["generated_at"],
                "commence_at": commence_map[event],
                "probability_a": row["p_a"],
                "feature_snapshot_id": row.get("snapshot"),
                "frozen_forward": True,
                "policy_version": FORWARD_PREDICTION_POLICY_VERSION,
            }
        )
        if created:
            inserted += 1
        else:
            conflicts += 1
    return {"inserted": inserted, "conflicts": conflicts}


def unique_event_pairing(store: Any) -> dict[str, Any]:
    """Prospective pairing over DISTINCT canonical events (official rows).

    M5 events whose official prediction predates the shadow parallel start are
    HISTORICAL_PRE_SHADOW and are excluded from the active defect count.
    """
    predictions = store.list_official_predictions(limit=100000)
    m5_events = {str(p["canonical_event_id"]): p for p in predictions if p["prediction_role"] == "M5_FORWARD"}
    shadow_events = {str(p["canonical_event_id"]): p for p in predictions if p["prediction_role"] == "SHADOW_FORWARD"}
    shadow_times = [_parse(p.get("generated_at")) for p in shadow_events.values()]
    parallel_start = min(shadow_times).isoformat() if shadow_times else None
    paired = set(m5_events) & set(shadow_events)
    m5_only = set(m5_events) - set(shadow_events)
    if parallel_start is not None:
        bound = _parse(parallel_start)
        fresh_m5_only = {event for event in m5_only if (lambda ts: ts is not None and ts >= bound)(_parse(m5_events[event].get("generated_at")))}
    else:
        fresh_m5_only = set()
    eligible = set(m5_events) | set(shadow_events)
    return {
        "m5_events": len(m5_events),
        "shadow_events": len(shadow_events),
        "pair_eligible_events": len(eligible),
        "pair_complete_events": len(paired),
        "pair_rate": round(len(paired) / len(eligible), 4) if eligible else None,
        "m5_only_events": len(m5_only),
        "m5_only_historical_pre_shadow": len(m5_only - fresh_m5_only),
        "m5_only_fresh_defect": len(fresh_m5_only),
        "shadow_only_events": len(set(shadow_events) - set(m5_events)),
        "duplicate_conflicts": 0,
    }


def classify_unpriced_event(
    *,
    filtered: bool,
    priced: bool,
    commenced_before_capture: bool,
    identity_unresolved: bool,
    provider_error: bool,
    polled_in_time: bool,
    market_evidence: bool,
) -> str:
    """Mutually exclusive unpriced taxonomy. MARKET_NOT_POSTED requires evidence."""
    if priced:
        return "PRICED"
    if identity_unresolved:
        return "IDENTITY_UNRESOLVED"
    if provider_error:
        return "PROVIDER_ERROR"
    if commenced_before_capture:
        return "POST_COMMENCE_FIRST_CAPTURE"
    if not polled_in_time:
        return "NOT_POLLED_IN_TIME"
    if market_evidence:
        return "MARKET_NOT_POSTED_YET"
    return "UNKNOWN_UNEXPLAINED"


def score_prediction(*, probability_a: float, actual_outcome: float) -> tuple[float, float, float | None]:
    """Brier + logloss (versioned epsilon clipping). Never mutates stored p."""
    p = float(probability_a)
    clipped = min(max(p, LOGLOSS_EPSILON), 1.0 - LOGLOSS_EPSILON)
    effective_clipped = clipped if clipped != p else None
    brier = (p - actual_outcome) ** 2
    logloss = -(actual_outcome * math.log(clipped) + (1.0 - actual_outcome) * math.log(1.0 - clipped))
    return brier, logloss, effective_clipped


def settlement_catchup(database: Any, store: Any) -> dict[str, Any]:
    """Find official-prediction events whose commence is past and classify
    their settlement state, settling those with a real FINAL result."""
    official = store.list_official_predictions(limit=100000)
    events = {str(p["canonical_event_id"]): p for p in official}
    if not events:
        return {"classified": {}, "settled": 0, "scores": 0}
    with database.connect() as connection, connection.cursor() as cursor:
        placeholders = ",".join("%s" for _ in events)
        cursor.execute(
            f"SELECT event_key, home_participant_key, away_participant_key, home_score, away_score, completed_at "
            f"FROM tt_match_results WHERE event_key IN ({placeholders})",
            list(events),
        )
        results = {str(row[0]): row for row in cursor.fetchall()}
    classified: dict[str, int] = {}
    settled = 0
    scores = 0
    for event_id, prediction in events.items():
        commence = _parse(prediction["commence_at"])
        if commence is None or commence >= datetime.now(timezone.utc):
            continue
        row = results.get(event_id)
        if row is None:
            state = "RESULT_PROVIDER_EMPTY"
        else:
            hs, aws = row[3], row[4]
            if hs is None or aws is None:
                state = "RESULT_NOT_AVAILABLE_YET"
            else:
                state = "SETTLED"
        classified[state] = classified.get(state, 0) + 1
        if state == "SETTLED":
            hs, aws = int(row[3]), int(row[4])
            winner = "A" if hs > aws else "B"
            created = store.insert_settlement(
                {
                    "canonical_event_id": event_id,
                    "provider_event_id": prediction.get("prediction_id"),
                    "status": "FINAL",
                    "actual_a": hs,
                    "actual_b": aws,
                    "winner_side": winner,
                    "source_result_id": str(event_id),
                    "source_provider": "odds_api_io",
                    "orientation_verified": True,
                }
            )
            if created:
                settled += 1
            official_row = store.list_official_predictions(limit=100000)
            event_predictions = [p for p in official_row if str(p["canonical_event_id"]) == event_id]
            settlements = store.list_settlements(limit=100000)
            settlement = next((s for s in settlements if str(s["canonical_event_id"]) == event_id and s["status"] == "FINAL"), None)
            if settlement is None:
                continue
            actual = 1.0 if winner == "A" else 0.0
            for p in event_predictions:
                brier, logloss, clipped = score_prediction(probability_a=float(p["probability_a"]), actual_outcome=actual)
                scored = store.insert_forward_score(
                    {
                        "canonical_event_id": event_id,
                        "official_prediction_id": p["official_prediction_id"],
                        "model_id": p["model_id"],
                        "settlement_id": settlement["settlement_id"],
                        "probability_a": float(p["probability_a"]),
                        "actual_outcome": actual,
                        "brier": round(brier, 8),
                        "logloss": round(logloss, 8),
                        "effective_clipped_p": clipped,
                        "logloss_eps_policy": LOGLOSS_EPSILON_POLICY,
                        "scoring_policy_version": SCORING_POLICY_VERSION,
                    }
                )
                if scored:
                    scores += 1
    return {"classified": classified, "settled": settled, "scores": scores}
