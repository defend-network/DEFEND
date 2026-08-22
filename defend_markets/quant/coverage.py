"""Cohort-aligned price coverage and prospective shadow pairing.

Price coverage must use a same-book, same-window, same-eligibility cohort, not
a mixed population. Shadow coverage is measured prospectively (events first
mutually eligible after the shadow pipeline started), never by comparing
historical pre-shadow M5 rows.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def compute_coverage(
    *,
    eligible_event_ids: set[str],
    priced_event_ids: set[str],
    exclusions: dict[str, int] | None = None,
) -> dict[str, Any]:
    eligible = set(eligible_event_ids)
    priced = set(priced_event_ids) & eligible
    numerator = len(priced)
    denominator = len(eligible)
    rate = round(numerator / denominator, 4) if denominator else None
    return {
        "eligible_events": denominator,
        "priced_events": numerator,
        "coverage_rate": rate,
        "exclusions": exclusions or {},
        "true_unexplained_unpriced": max(0, denominator - numerator - sum((exclusions or {}).values())),
        "cohort_aligned": True,
    }


def classify_unpriced(
    *,
    event_ids_unpriced: set[str],
    filtered_event_ids: set[str],
    priced_event_ids: set[str],
    commenced_event_ids: set[str],
    unresolved_identity_event_ids: set[str],
    not_polled_event_ids: set[str],
) -> dict[str, int]:
    """Separate market-not-posted, polling misses, identity exclusions, and
    true unexplained missing from an unpriced cohort."""
    unpriced = set(event_ids_unpriced)
    filtered = set(filtered_event_ids)
    priced = set(priced_event_ids)
    commenced = set(commenced_event_ids)
    identity = set(unresolved_identity_event_ids)
    not_polled = set(not_polled_event_ids)
    post_commence = unpriced & commenced
    identity_excluded = unpriced & identity
    not_polled_excluded = unpriced & not_polled
    market_not_posted = unpriced - priced - post_commence - identity_excluded - not_polled_excluded
    return {
        "priced": len(priced),
        "market_not_posted_yet": len(market_not_posted),
        "post_commence_first_capture": len(post_commence),
        "identity_unresolved": len(identity_excluded),
        "not_polled_before_commence": len(not_polled_excluded),
        "true_unexplained_unpriced": max(0, len(market_not_posted)),
    }


def prospective_shadow_pairing(store: Any) -> dict[str, Any]:
    """Prospective M5/shadow pairing over DISTINCT canonical events using the
    official frozen forward prediction registry. No raw-row or many-to-many
    inflation. Historical pre-shadow M5 events are excluded from the active
    defect count."""
    from defend_markets.quant.forward_evidence import unique_event_pairing

    result = unique_event_pairing(store)
    shadow_predictions = [
        p for p in store.list_official_predictions(limit=100000)
        if p.get("prediction_role") == "SHADOW_FORWARD"
    ]
    return {
        "parallel_start_at": _earliest(shadow_predictions) or None,
        "eligible": result["pair_eligible_events"],
        "complete": result["pair_complete_events"],
        "rate": result["pair_rate"],
        "failure_reasons": {
            "m5_without_shadow": result["m5_only_fresh_defect"],
            "shadow_without_m5": result["shadow_only_events"],
            "historical_pre_shadow": result["m5_only_historical_pre_shadow"],
        },
    }


def _earliest(predictions: list[dict[str, Any]]) -> str | None:
    values = [p.get("generated_at") for p in predictions]
    if not values:
        return None
    return str(min(values))
