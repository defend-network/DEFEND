"""M4.7.2 result reconciliation + revision-safe settlement (P16-P21).

Recently-FINAL events remain eligible for a bounded correction window
(:class:`ReconciliationService`). When a provider revises the SAME source_result_id
with changed scores/status, the settlement authority detects it via the
normalized-result fingerprint and appends an immutable settlement revision —
historical settlement content is never mutated (P18/P19). Forward scores follow
the revision chain (P20); PAPER_ARB follows canonical revisions (P21).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from defend_markets.quant.normalize import canonical_result_fingerprint

RECONCILIATION_POLICY_VERSION = "RESULT_RECONCILIATION_V1"
RECONCILIATION_WINDOW_HOURS = 48  # finite correction window


def reconciliation_eligible(row: dict[str, Any], *, now: datetime | None = None) -> bool:
    """P16: a recently-FINAL event remains eligible for a bounded recheck."""
    now = now or datetime.now(timezone.utc)
    if str(row.get("result_status") or "") not in ("settled", "FINAL"):
        return False
    last_settled = _parse(row.get("last_reconciled_at")) or _parse(row.get("updated_at"))
    if last_settled is None:
        return True
    return (now - last_settled) <= timedelta(hours=RECONCILIATION_WINDOW_HOURS)


def detect_revision(*, prior_fingerprint: str | None, new_fingerprint: str) -> str:
    """P17/P18: compare normalized fingerprints.

    Returns NO_CHANGE or RESULT_REVISION_DETECTED. Same source_result_id with
    changed scores/status yields a different fingerprint -> revision.
    """
    if prior_fingerprint is None:
        return "NEW_RESULT"
    if prior_fingerprint == new_fingerprint:
        return "NO_CHANGE"
    return "RESULT_REVISION_DETECTED"


class ReconciliationService:
    """P16: bounded reconciliation of recently-FINAL results."""

    def __init__(self, store: Any, *, window_hours: int = RECONCILIATION_WINDOW_HOURS) -> None:
        self._store = store
        self._window_hours = window_hours

    def due_events(self, *, now: datetime | None = None) -> list[dict[str, Any]]:
        now = now or datetime.now(timezone.utc)
        due: list[dict[str, Any]] = []
        for row in self._store.list_result_acquisition(limit=100000):
            if str(row.get("acquisition_state") or "") not in ("LOCAL_RESULT_PRESENT", "PROVIDER_RESULT_AVAILABLE"):
                continue
            if str(row.get("result_status") or "") not in ("settled", "FINAL"):
                continue
            next_reconcile = _parse(row.get("next_reconcile_at"))
            if next_reconcile is not None and next_reconcile > now:
                continue
            if reconciliation_eligible(row, now=now):
                due.append(row)
        return due


def revision_fingerprint_for_row(row: dict[str, Any]) -> str:
    return canonical_result_fingerprint(
        provider=str(row.get("provider") or "odds_api_io"),
        provider_event_id=str(row.get("provider_event_id") or ""),
        canonical_event_id=str(row.get("canonical_event_id") or ""),
        status=str(row.get("result_status") or "FINAL"),
        actual_a=row.get("actual_a"),
        actual_b=row.get("actual_b"),
        orientation=str(row.get("orientation") or ""),
        source_result_id=str(row.get("provider_result_id") or ""),
    )


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
