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


def prospective_shadow_pairing(database: Any) -> dict[str, Any]:
    """Prospective M5/shadow pairing for events first mutually eligible after
    the shadow pipeline's parallel start."""
    with database.connect() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT min(generated_at) FROM quant_shadow_predictions")
        start = cursor.fetchone()[0]
        if start is None:
            return {"parallel_start_at": None, "eligible": 0, "complete": 0, "rate": None, "failure_reasons": {}}
        cursor.execute(
            "SELECT count(*) FROM tt_m5_live_predictions "
            "WHERE availability = 'AVAILABLE' AND generated_at >= %s",
            (start,),
        )
        m5_eligible = int(cursor.fetchone()[0])
        cursor.execute(
            "SELECT count(*) FROM quant_shadow_predictions "
            "WHERE availability = 'AVAILABLE' AND generated_at >= %s",
            (start,),
        )
        shadow_eligible = int(cursor.fetchone()[0])
        cursor.execute(
            "SELECT count(*) FROM tt_m5_live_predictions m "
            "JOIN quant_shadow_predictions s ON s.canonical_event_id = m.canonical_event_id "
            "WHERE m.availability = 'AVAILABLE' AND s.availability = 'AVAILABLE' "
            "AND m.generated_at >= %s AND s.generated_at >= %s",
            (start, start),
        )
        complete = int(cursor.fetchone()[0])
    eligible = int(m5_eligible)
    return {
        "parallel_start_at": start.isoformat() if start else None,
        "eligible": eligible,
        "complete": complete,
        "rate": round(complete / eligible, 4) if eligible else None,
        "failure_reasons": {
            "m5_without_shadow": max(0, m5_eligible - complete),
            "shadow_without_m5": max(0, shadow_eligible - complete),
        },
    }
