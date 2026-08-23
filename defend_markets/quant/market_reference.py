"""M4.7 MARKET_REFERENCE_POLICY_V1 (P12/P13).

A deterministic point-in-time bookmaker price reference for a canonical event,
selected from the latest complete FRESH market snapshot strictly before a
versioned pre-match cutoff. The reference is persisted with its exact
observation IDs and is never chosen after a result is known.

Market baseline (P13): settled events are scored against this reference
(no-vig implied probability) as a model-vs-market comparison.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

MARKET_REFERENCE_POLICY_VERSION = "MARKET_REFERENCE_POLICY_V1"
MARKET_REFERENCE_CUTOFF_SECONDS = 300  # require reference >= 5 min pre-commence


def _parse(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def select_reference_observation(
    rows: list[dict[str, Any]],
    *,
    commence_at: Any,
    now: datetime | None = None,
    bookmaker: str | None = None,
    cutoff_seconds: float = MARKET_REFERENCE_CUTOFF_SECONDS,
) -> dict[str, Any] | None:
    """Pick the deterministic market reference from a list of observations.

    Candidates must be OPEN/INTERMEDIATE/LAST_VALID_PREMATCH rows observed
    strictly before ``commence_at - cutoff_seconds``. The latest such
    observation for the preferred bookmaker wins; without a preferred
    bookmaker the latest observation across books wins. Persisted observation
    IDs are returned so the reference is fully auditable.
    """
    now = now or datetime.now(timezone.utc)
    commence = _parse(commence_at)
    if commence is None:
        return None
    cutoff = commence - timedelta(seconds=cutoff_seconds)
    candidates = []
    for row in rows:
        observed = _parse(row.get("observed_at"))
        if observed is None or observed >= cutoff:
            continue
        if bookmaker is not None and str(row.get("bookmaker")) != bookmaker:
            continue
        candidates.append(row)
    if not candidates:
        return None
    best = max(candidates, key=lambda row: _parse(row.get("observed_at")) or datetime.min.replace(tzinfo=timezone.utc))
    return {
        "canonical_event_id": str(best.get("canonical_event_id")),
        "policy_version": MARKET_REFERENCE_POLICY_VERSION,
        "market": str(best.get("market")),
        "side": str(best.get("side")),
        "bookmaker": str(best.get("bookmaker")),
        "price": best.get("price"),
        "observation_id": best.get("observation_id"),
        "referenced_at": now.isoformat().replace("+00:00", "Z"),
        "observed_at": _parse(best.get("observed_at")),
    }


def persist_market_reference(store: Any, rows: list[dict[str, Any]], *, commence_at: Any,
                             bookmaker: str | None = None) -> dict[str, Any]:
    """Persist the deterministic reference for an event, returning the stored row."""
    reference = select_reference_observation(rows, commence_at=commence_at, bookmaker=bookmaker)
    if reference is None:
        return {"stored": False, "reason": "no pre-cutoff observation"}
    store.upsert_market_reference(reference)
    return {"stored": True, "reference": reference}


def market_baseline_metrics(store: Any, *, model_scores: list[dict[str, Any]]) -> dict[str, Any]:
    """P13: compare model probability against the no-vig market probability.

    For each unique settled event with a persisted market reference, compute the
    no-vig implied probability from the reference and compare with the model.
    Returns unique-event aggregates; no promotion decisions are made here.
    """
    from defend_markets.quant.market import two_sided_no_vig

    references = store.list_market_reference(limit=100000)
    by_event: dict[str, dict[str, Any]] = {}
    for ref in references:
        key = str(ref["canonical_event_id"])
        family = str(ref.get("market") or "")
        side = str(ref.get("side") or "")
        if family not in ("MATCH_WINNER", "ML", "MONEYLINE"):
            continue
        by_event.setdefault(key, {})[side] = ref

    scored_by_event: dict[str, list[dict[str, Any]]] = {}
    for score in model_scores:
        event = str(score["canonical_event_id"])
        if event in by_event:
            scored_by_event.setdefault(event, []).append(score)

    model_vs_market: list[dict[str, Any]] = []
    for event, refs in by_event.items():
        if event not in scored_by_event:
            continue
        side_a = refs.get("A") or refs.get("PARTICIPANT_A")
        side_b = refs.get("B") or refs.get("PARTICIPANT_B")
        if side_a is None or side_b is None:
            continue
        try:
            market = two_sided_no_vig(float(side_a.get("price")), float(side_b.get("price")))
        except (TypeError, ValueError):
            continue
        if market.no_vig_p_a is None:
            continue
        for score in scored_by_event[event]:
            model_vs_market.append(
                {
                    "canonical_event_id": event,
                    "model_id": str(score.get("model_id")),
                    "model_p_a": float(score.get("probability_a")),
                    "market_p_a": round(market.no_vig_p_a, 8),
                    "actual_outcome": float(score.get("actual_outcome")),
                    "policy_version": MARKET_REFERENCE_POLICY_VERSION,
                }
            )

    m5 = [row for row in model_vs_market if "M5" in str(row["model_id"]).upper()]
    shadow = [row for row in model_vs_market if "M5" not in str(row["model_id"]).upper()]

    def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {"events": 0}
        n = len(rows)
        model_brier = sum((r["model_p_a"] - r["actual_outcome"]) ** 2 for r in rows) / n
        market_brier = sum((r["market_p_a"] - r["actual_outcome"]) ** 2 for r in rows) / n
        return {
            "events": n,
            "model_brier": round(model_brier, 8),
            "market_brier": round(market_brier, 8),
            "delta_model_minus_market": round(model_brier - market_brier, 8),
        }

    return {
        "policy_version": MARKET_REFERENCE_POLICY_VERSION,
        "m5_vs_market": _aggregate(m5),
        "shadow_vs_market": _aggregate(shadow),
        "reference_events": len(by_event),
    }
