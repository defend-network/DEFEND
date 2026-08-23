"""M4.8 canonical cross-provider event matching (P8).

Match TT events across providers (Owls Hard Rock, Odds-API.io, OddsPapi) by
priority:
  1. exact known cross-provider/native IDs (e.g. Betradar ID)
  2. exact canonical participant identity mapping
  3. normalized participant names + competition + bounded start-time window
  4. reviewed high-confidence fallback.

States: KEY_EXACT, NAME_TIME_EXACT, AMBIGUOUS, CONFLICT, UNMATCHED. AMBIGUOUS /
CONFLICT never merge automatically.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

STATE_KEY_EXACT = "KEY_EXACT"
STATE_NAME_TIME_EXACT = "NAME_TIME_EXACT"
STATE_AMBIGUOUS = "AMBIGUOUS"
STATE_CONFLICT = "CONFLICT"
STATE_UNMATCHED = "UNMATCHED"

_TIME_WINDOW_SECONDS = 600  # bounded start-time window for name+time matching


def _compact(name: str) -> str:
    import re
    import unicodedata

    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def resolve_provider_orientation(
    *,
    provider_participant_a: str,
    provider_participant_b: str,
    canonical_participant_1: str,
    canonical_participant_2: str,
) -> tuple[str, str, str]:
    """P4B/P5: map provider selection sides onto canonical participants.

    Returns (selection_a_maps_to, selection_b_maps_to, state) where state is
    one of CANONICAL / REVERSED / CONFLICT. Fails closed on CONFLICT (cannot
    prove orientation -> no cross-book comparison).
    """
    a1 = _compact(provider_participant_a) == _compact(canonical_participant_1)
    a2 = _compact(provider_participant_a) == _compact(canonical_participant_2)
    b1 = _compact(provider_participant_b) == _compact(canonical_participant_1)
    b2 = _compact(provider_participant_b) == _compact(canonical_participant_2)
    if a1 and b2:
        return "1", "2", "CANONICAL"
    if a2 and b1:
        return "2", "1", "REVERSED"
    return "", "", "CONFLICT"


def match_event(
    *,
    provider: str,
    native_event_id: str,
    cross_provider_id: str | None,
    participants: list[str],
    scheduled_time: Any,
    candidate: dict[str, Any],
) -> tuple[str, str]:
    """Match one provider event against a candidate canonical event.

    Returns (identity_mode, confidence). Never returns a match on a conflict.
    """
    # 1. exact cross-provider/native ID
    if cross_provider_id:
        candidate_native = str(candidate.get("native_event_id") or "")
        candidate_betradar = str(candidate.get("betradar_id") or "")
        if cross_provider_id and cross_provider_id in (candidate_native, candidate_betradar):
            return STATE_KEY_EXACT, "HIGH"

    # 2/3. normalized participant names + competition + bounded time window
    cand_parts = {_compact(p) for p in candidate.get("participants", [])}
    src_parts = {_compact(p) for p in participants if p}
    if len(cand_parts) != 2 or len(src_parts) != 2:
        return STATE_UNMATCHED, "UNKNOWN"
    if cand_parts == src_parts:
        src_time = _parse_time(scheduled_time)
        cand_time = _parse_time(candidate.get("scheduled_time"))
        if src_time is not None and cand_time is not None:
            if abs((src_time - cand_time).total_seconds()) <= _TIME_WINDOW_SECONDS:
                return STATE_NAME_TIME_EXACT, "HIGH"
        # same participants, but no/loose time -> ambiguous, not a merge
        return STATE_AMBIGUOUS, "MEDIUM"
    if cand_parts & src_parts:
        # partial overlap -> conflict (do not merge)
        return STATE_CONFLICT, "LOW"
    return STATE_UNMATCHED, "UNKNOWN"


class CanonicalEventMatcher:
    """Matches provider events to canonical events and persists evidence (P8)."""

    def __init__(self, store: Any) -> None:
        self._store = store

    def match_and_record(
        self,
        *,
        provider: str,
        native_event_id: str,
        cross_provider_id: str | None,
        participants: list[str],
        scheduled_time: Any,
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        best_mode = STATE_UNMATCHED
        best_confidence = "UNKNOWN"
        best_canonical: str | None = None
        for candidate in candidates:
            mode, confidence = match_event(
                provider=provider,
                native_event_id=native_event_id,
                cross_provider_id=cross_provider_id,
                participants=participants,
                scheduled_time=scheduled_time,
                candidate=candidate,
            )
            if mode == STATE_KEY_EXACT:
                best_mode, best_confidence = mode, confidence
                best_canonical = str(candidate.get("canonical_event_id") or "")
                break
            if mode == STATE_NAME_TIME_EXACT and best_mode in (STATE_UNMATCHED, STATE_AMBIGUOUS):
                best_mode, best_confidence = mode, confidence
                best_canonical = str(candidate.get("canonical_event_id") or "")
            elif mode == STATE_CONFLICT and best_mode == STATE_UNMATCHED:
                best_mode, best_confidence = mode, confidence
        self._store.upsert_provider_event_mapping(
            {
                "provider": provider,
                "native_event_id": native_event_id,
                "canonical_event_id": best_canonical if best_mode in (STATE_KEY_EXACT, STATE_NAME_TIME_EXACT) else None,
                "identity_mode": best_mode,
                "confidence": best_confidence,
                "normalized_participants": "|".join(sorted(_compact(p) for p in participants if p)),
                "scheduled_time": _parse_time(scheduled_time),
            }
        )
        return {
            "provider": provider,
            "native_event_id": native_event_id,
            "canonical_event_id": best_canonical,
            "identity_mode": best_mode,
            "confidence": best_confidence,
        }
