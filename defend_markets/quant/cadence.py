"""M4.8.2 adaptive Hard Rock capture cadence (P13/P13A/P13B).

Provider-governed cadence derived from the current slate state and provider
quota/capacity. Live capacity has priority over historical backfill; the
effective cadence mode (IN_PLAY / UPCOMING / IDLE / BACKOFF) is exposed to the
owner UI. Exact values are conservative and bounded by configured provider
capacity, never exceeding provider limits.
"""

from __future__ import annotations

from typing import Any

ADAPTIVE_CADENCE_POLICY_VERSION = "ADAPTIVE_CAPTURE_V1"

MODE_IN_PLAY = "IN_PLAY"
MODE_UPCOMING = "UPCOMING"
MODE_IDLE = "IDLE"
MODE_BACKOFF = "BACKOFF"

# conservative default intervals (seconds); bounded by provider capacity
_INTERVAL = {
    MODE_IN_PLAY: 60,
    MODE_UPCOMING: 300,
    MODE_IDLE: 900,
    MODE_BACKOFF: 1800,
}


def adaptive_cadence(
    *,
    in_play_count: int,
    upcoming_count: int,
    has_slate: bool,
    error_state: str | None = None,
    rate_limited: bool = False,
) -> dict[str, Any]:
    """Derive the effective capture mode + interval from the slate.

    Backoff always wins; then in-play (fastest), then upcoming, then idle.
    """
    if rate_limited or error_state in ("rate_limited", "auth_failed", "plan_required", "unavailable"):
        mode = MODE_BACKOFF
        reason = f"backoff: {error_state or 'rate limited'}"
    elif in_play_count > 0:
        mode = MODE_IN_PLAY
        reason = f"{in_play_count} in-play events"
    elif has_slate and upcoming_count > 0:
        mode = MODE_UPCOMING
        reason = f"{upcoming_count} upcoming events"
    elif has_slate:
        mode = MODE_UPCOMING
        reason = "slate present"
    else:
        mode = MODE_IDLE
        reason = "no slate"
    return {
        "mode": mode,
        "interval_seconds": _INTERVAL[mode],
        "reason": reason,
        "policy_version": ADAPTIVE_CADENCE_POLICY_VERSION,
    }


class AdaptiveCaptureState:
    """Tracks current effective capture cadence for UI visibility (P13B)."""

    def __init__(self, store: Any) -> None:
        self._store = store

    def current(self, *, in_play_count: int, upcoming_count: int, has_slate: bool,
                error_state: str | None = None) -> dict[str, Any]:
        cadence = adaptive_cadence(
            in_play_count=in_play_count,
            upcoming_count=upcoming_count,
            has_slate=has_slate,
            error_state=error_state,
        )
        # next eligible poll = now + interval (surface only; scheduler owns actual timing)
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        next_poll = (now + timedelta(seconds=cadence["interval_seconds"])).isoformat().replace("+00:00", "Z")
        return {**cadence, "next_eligible_poll": next_poll}
