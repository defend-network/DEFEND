"""M4.7.2 single settlement authority and single forward-scoring authority.

Exactly ONE production service creates official settlement records
(:class:`SettlementService`) and exactly ONE creates official forward-score
records (:class:`ForwardScoringService`). Result acquisition NEVER writes
settlements or scores (P0-P4).

Scoring consumes the current valid canonical settlement revision plus the exact
frozen pre-result prediction, and classifies champion vs shadow by persisted
model role/registry identity — never by a "M5" substring in model_id (P33).
"""

from __future__ import annotations

from typing import Any

from defend_markets.quant.forward_evidence import (
    LOGLOSS_EPSILON_POLICY,
    SCORING_POLICY_VERSION,
    score_prediction,
)
from defend_markets.quant.result_acquisition import (
    LOCAL_RESULT_PRESENT,
    PROVIDER_RESULT_AVAILABLE,
    RESULT_STATE_FINAL,
)

SETTLEMENT_POLICY_VERSION = "SETTLEMENT_AUTHORITY_V1"
SCORING_POLICY_VERSION_LABEL = "FORWARD_SCORING_AUTHORITY_V1"


def model_role(store: Any, model_id: str) -> str:
    """P33: classify a model by persisted role, never by id substring.

    Returns CHAMPION / SHADOW / CHALLENGER / UNKNOWN. A model named
    M5_SHADOW_V2 that is registered as SHADOW stays SHADOW.
    """
    for model in store.list_models():
        if str(model.get("model_id")) == model_id:
            return str(model.get("role") or "UNKNOWN")
    return "UNKNOWN"


class SettlementService:
    """ONE settlement authority (P1). Creates/revises official settlements only.

    Consumes acquired-result evidence (from the acquisition ledger) and persists
    canonical settlement revisions. When the normalized fingerprint differs from
    the current settlement, an immutable NEW revision is appended (P18/P19) and
    the prior row is never mutated destructively. Never writes forward scores.
    """

    def __init__(self, store: Any) -> None:
        self._store = store

    def settle(self) -> dict[str, Any]:
        from defend_markets.quant.reconciliation import detect_revision, revision_fingerprint_for_row

        acquisitions = self._store.list_result_acquisition(limit=100000)
        settled = 0
        revised = 0
        for acq in acquisitions:
            state = str(acq.get("acquisition_state") or "")
            if state not in (LOCAL_RESULT_PRESENT, PROVIDER_RESULT_AVAILABLE):
                continue
            if str(acq.get("result_status") or "") not in ("settled", "FINAL"):
                continue
            winner_side = acq.get("winner_side")
            if winner_side is None:
                continue
            orientation = str(acq.get("orientation") or "")
            if orientation not in ("CANONICAL", "REVERSED"):
                continue
            canonical_event_id = str(acq["canonical_event_id"])
            provider_event_id = acq.get("provider_event_id")
            provider_result_id = acq.get("provider_result_id") or provider_event_id
            source_result_id = provider_result_id or (f"oaio:{provider_event_id}" if provider_event_id else canonical_event_id)
            new_fingerprint = acq.get("normalized_result_fingerprint") or revision_fingerprint_for_row(acq)
            existing = self._store.latest_final_settlement(canonical_event_id)
            if existing is None:
                created = self._store.insert_settlement(
                    {
                        "canonical_event_id": canonical_event_id,
                        "provider_event_id": provider_event_id,
                        "status": RESULT_STATE_FINAL,
                        "actual_a": acq.get("actual_a"),
                        "actual_b": acq.get("actual_b"),
                        "winner_side": winner_side,
                        "source_result_id": source_result_id,
                        "source_provider": acq.get("provider") or "odds_api_io",
                        "observed_at": None,
                        "raw_payload_hash": acq.get("raw_provenance_hash"),
                        "orientation_verified": True,
                        "provider_result_id": provider_result_id,
                        "normalized_result_fingerprint": new_fingerprint,
                    }
                )
                if created:
                    settled += 1
                continue
            # P18: same source_result_id with changed scores/status -> revision.
            prior_fingerprint = existing.get("normalized_result_fingerprint")
            decision = detect_revision(prior_fingerprint=prior_fingerprint, new_fingerprint=new_fingerprint)
            if decision == "RESULT_REVISION_DETECTED":
                self._store.insert_settlement_revision(
                    {
                        "canonical_event_id": canonical_event_id,
                        "provider_event_id": provider_event_id,
                        "status": RESULT_STATE_FINAL,
                        "actual_a": acq.get("actual_a"),
                        "actual_b": acq.get("actual_b"),
                        "winner_side": winner_side,
                        "source_result_id": source_result_id,
                        "source_provider": acq.get("provider") or "odds_api_io",
                        "observed_at": None,
                        "raw_payload_hash": acq.get("raw_provenance_hash"),
                        "orientation_verified": True,
                        "provider_result_id": provider_result_id,
                        "normalized_result_fingerprint": new_fingerprint,
                    }
                )
                revised += 1
        return {"settled": settled, "revised": revised, "summary": f"settlement: {settled} settled, {revised} revised"}


class ForwardScoringService:
    """ONE forward-scoring authority (P2). Creates official scores only.

    Consumes the current valid canonical settlement revision + the exact frozen
    pre-result prediction. Never writes settlements.
    """

    def __init__(self, store: Any) -> None:
        self._store = store

    def score(self) -> dict[str, Any]:
        scores = 0
        settlements = self._store.list_settlements(limit=100000)
        finals = [s for s in settlements if s.get("status") == "FINAL"]
        by_event: dict[str, dict[str, Any]] = {}
        for s in finals:
            event = str(s["canonical_event_id"])
            current = by_event.get(event)
            if current is None or int(s.get("revision", 0)) >= int(current.get("revision", 0)):
                by_event[event] = s
        for canonical_event_id, settlement in by_event.items():
            winner_side = settlement.get("winner_side")
            if winner_side is None:
                continue
            actual = 1.0 if winner_side == "A" else 0.0
            for p in self._store.list_official_predictions(limit=100000):
                if str(p["canonical_event_id"]) != canonical_event_id:
                    continue
                brier, logloss, clipped = score_prediction(probability_a=float(p["probability_a"]), actual_outcome=actual)
                created = self._store.insert_forward_score(
                    {
                        "canonical_event_id": canonical_event_id,
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
                if created:
                    scores += 1
        return {"scores": scores, "summary": f"forward scoring: {scores} scored"}
