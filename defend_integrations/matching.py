"""Deterministic event matching (P5): join provider events to the canonical
match corpus without fuzzy identity establishment.

Hierarchy (first match wins):
  1. EXACT_ID      - provider event id shared with the canonical corpus
  2. IDENTITY_MAP  - existing provider identity mapping
  3. PARTICIPANT_ID- canonical participant ids present in provider event
  4. NORMALIZED    - normalized participants + competition + bounded commence

Fuzzy name matching NEVER establishes identity. If step 4 yields more than
one canonical candidate (same participants, same competition, commence within
the window), the match is AMBIGUOUS and fails closed.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any


class MatchLevel(str, Enum):
    EXACT_ID = "EXACT_ID"
    IDENTITY_MAP = "IDENTITY_MAP"
    PARTICIPANT_ID = "PARTICIPANT_ID"
    NORMALIZED = "NORMALIZED"
    AMBIGUOUS = "AMBIGUOUS"
    UNMATCHED = "UNMATCHED"


@dataclass(frozen=True)
class MatchResult:
    level: MatchLevel
    matched_event_key: str | None = None
    candidate_keys: tuple[str, ...] = ()
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level.value,
            "matched_event_key": self.matched_event_key,
            "candidate_keys": list(self.candidate_keys),
            "note": self.note,
        }


_WINDOW = timedelta(hours=2)


def normalize_name(name: str) -> str:
    """Deterministic participant normalization: casefold, drop diacritics,
    strip punctuation and collapse whitespace. Never fuzzy."""
    text = unicodedata.normalize("NFKD", str(name))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def compact_name(name: str) -> str:
    """Token-level normalization (no separators) for opaque participant keys
    such as ``table_tennis:levickymatej`` (surname+given concatenated) which
    must be comparable to spaced display names like ``Levicky, Jakub``."""
    return normalize_name(name).replace(" ", "")


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def match_event(
    *,
    provider_event_id: str,
    provider_prefix: str,
    participants: list[str],
    competition: str | None,
    commence_at: str | None,
    canonical_events: list[dict[str, Any]],
    identity_map: dict[str, str] | None = None,
    window_hours: float = 2.0,
) -> MatchResult:
    """Match one provider event against canonical candidates.

    ``canonical_events`` entries carry: event_key, provider_event_id (the
    provider's id embedded in the canonical key, if any), participant_keys
    (normalized canonical participant names), competition, commence_at.
    """
    # 1. exact provider id
    for candidate in canonical_events:
        if candidate.get("provider_event_id") == provider_event_id:
            return MatchResult(MatchLevel.EXACT_ID, candidate["event_key"], (candidate["event_key"],))
    if provider_prefix and any(
        c.get("event_key") == f"{provider_prefix}:{provider_event_id}"
        for c in canonical_events
    ):
        for candidate in canonical_events:
            if candidate.get("event_key") == f"{provider_prefix}:{provider_event_id}":
                return MatchResult(MatchLevel.EXACT_ID, candidate["event_key"], (candidate["event_key"],))

    # 2. existing identity mapping
    if identity_map:
        mapped = identity_map.get(provider_event_id)
        if mapped:
            for candidate in canonical_events:
                if candidate.get("event_key") == mapped:
                    return MatchResult(MatchLevel.IDENTITY_MAP, mapped, (mapped,))

    provider_norm = {compact_name(p) for p in participants}

    # 3. canonical participant ids present on the provider event
    for candidate in canonical_events:
        candidate_ids = candidate.get("participant_ids") or ()
        if candidate_ids and all(
            compact_name(cid) in provider_norm for cid in candidate_ids
        ):
            return MatchResult(MatchLevel.PARTICIPANT_ID, candidate["event_key"], (candidate["event_key"],))

    # 4. normalized participants + competition + bounded commence time
    commence = _parse_ts(commence_at)
    window = timedelta(hours=window_hours)
    matched: list[str] = []
    for candidate in canonical_events:
        candidate_participants = candidate.get("participant_keys") or ()
        if len(provider_norm) != len(candidate_participants):
            continue
        if provider_norm != {compact_name(p) for p in candidate_participants}:
            continue
        if competition and candidate.get("competition"):
            if normalize_name(competition) != normalize_name(candidate["competition"]):
                continue
        if commence is not None:
            candidate_commence = _parse_ts(candidate.get("commence_at"))
            if candidate_commence is not None and abs(candidate_commence - commence) > window:
                continue
        matched.append(candidate["event_key"])
    if len(matched) == 1:
        return MatchResult(MatchLevel.NORMALIZED, matched[0], tuple(matched))
    if len(matched) > 1:
        return MatchResult(
            MatchLevel.AMBIGUOUS,
            None,
            tuple(matched),
            "multiple canonical candidates; fails closed",
        )
    return MatchResult(MatchLevel.UNMATCHED, None, (), "no deterministic candidate")


def matching_rates(results: list[MatchResult]) -> dict[str, Any]:
    """Counts and rates across a list of match results."""
    total = len(results)
    counts = {level.value: 0 for level in MatchLevel}
    for result in results:
        counts[result.level.value] += 1
    rates = {
        "TOTAL": total,
        "EXACT_ID_MATCH_RATE": counts["EXACT_ID"] / total if total else None,
        "IDENTITY_MAP_MATCH_RATE": counts["IDENTITY_MAP"] / total if total else None,
        "PARTICIPANT_ID_MATCH_RATE": counts["PARTICIPANT_ID"] / total if total else None,
        "NORMALIZED_MATCH_RATE": counts["NORMALIZED"] / total if total else None,
        "AMBIGUOUS_RATE": counts["AMBIGUOUS"] / total if total else None,
        "UNMATCHED_RATE": counts["UNMATCHED"] / total if total else None,
        "MATCHED_RATE": (
            (counts["EXACT_ID"] + counts["IDENTITY_MAP"] + counts["PARTICIPANT_ID"] + counts["NORMALIZED"]) / total
            if total
            else None
        ),
        "counts": counts,
    }
    return rates