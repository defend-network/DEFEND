"""M4.7.2 single canonical result normalizer (P12-P15).

One authority normalizes provider and local results alike. Input: source
participant home/A + away/B, source scores, canonical participant A/B, source
provenance. Output: orientation (CANONICAL/REVERSED/CONFLICT/UNKNOWN), canonical
actual_a/actual_b, canonical winner_side, identity match mode and preserved
source provenance.

Participant identity is compared ONLY in compatible domains (P14): exact
participant key first (KEY_EXACT); normalized-name fallback only when canonical
keys are genuinely unavailable (NAME_NORMALIZED). Conflicting keys are never
silently overridden by matching names.
"""

from __future__ import annotations

from typing import Any

ORIENTATION_CANONICAL = "CANONICAL"
ORIENTATION_REVERSED = "REVERSED"
ORIENTATION_CONFLICT = "CONFLICT"
ORIENTATION_UNKNOWN = "UNKNOWN"

MATCH_KEY_EXACT = "KEY_EXACT"
MATCH_NAME_NORMALIZED = "NAME_NORMALIZED"
MATCH_CONFLICT = "CONFLICT"
MATCH_UNKNOWN = "UNKNOWN"


def _compact(name: str) -> str:
    import re
    import unicodedata

    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def normalize_participant_orientation(
    *,
    source_home: str,
    source_away: str,
    canonical_a: str,
    canonical_b: str,
    canonical_a_key: str | None = None,
    canonical_b_key: str | None = None,
) -> tuple[str, str]:
    """Resolve participant orientation in a domain-consistent way (P14).

    Priority: exact participant key -> normalized name. Returns
    (orientation, identity_match_mode).
    """
    if canonical_a_key and canonical_b_key:
        # KEY_EXACT: compare stable participant keys to source participant IDs.
        sh = str(source_home or "").strip()
        sa = str(source_away or "").strip()
        if sh == canonical_a_key and sa == canonical_b_key:
            return ORIENTATION_CANONICAL, MATCH_KEY_EXACT
        if sh == canonical_b_key and sa == canonical_a_key:
            return ORIENTATION_REVERSED, MATCH_KEY_EXACT
        # key conflict: do NOT fall through to name matching silently.
        return ORIENTATION_CONFLICT, MATCH_CONFLICT
    # NAME_NORMALIZED fallback (only when keys genuinely unavailable).
    if not canonical_a or not canonical_b:
        return ORIENTATION_UNKNOWN, MATCH_UNKNOWN
    home_n = _compact(source_home)
    away_n = _compact(source_away)
    a_n = _compact(canonical_a)
    b_n = _compact(canonical_b)
    if home_n and home_n == a_n and away_n == b_n:
        return ORIENTATION_CANONICAL, MATCH_NAME_NORMALIZED
    if home_n and home_n == b_n and away_n == a_n:
        return ORIENTATION_REVERSED, MATCH_NAME_NORMALIZED
    return ORIENTATION_CONFLICT, MATCH_CONFLICT


def normalize_result_scores(
    *,
    source_home_score: int | None,
    source_away_score: int | None,
    orientation: str,
) -> tuple[int | None, int | None, str | None]:
    """Canonicalize scores + winner. REVERSED swaps source scores into canonical
    A/B orientation BEFORE winner derivation (P12/P13)."""
    if source_home_score is None or source_away_score is None:
        return None, None, None
    hs, aws = int(source_home_score), int(source_away_score)
    if orientation == ORIENTATION_REVERSED:
        hs, aws = aws, hs
    if hs == aws:
        winner = None
    else:
        winner = "A" if hs > aws else "B"
    return hs, aws, winner


def canonical_result_fingerprint(*, provider: str, provider_event_id: str, canonical_event_id: str,
                                 status: str, actual_a: Any, actual_b: Any, orientation: str,
                                 source_result_id: str) -> str:
    """P17: deterministic normalized-result fingerprint (canonical serialization)."""
    import hashlib

    payload = "|".join(
        (
            str(provider),
            str(provider_event_id),
            str(canonical_event_id),
            str(status),
            "" if actual_a is None else str(actual_a),
            "" if actual_b is None else str(actual_b),
            str(orientation),
            str(source_result_id),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
