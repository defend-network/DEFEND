"""Canonical Table Tennis participant identity resolution.

Deterministic normalization only: Unicode NFKC, case folding, whitespace
collapse and punctuation stripping. Distinct humans are NEVER merged on
fuzzy name similarity — a conflict (one normalized name resolving to two
participants) marks every candidate AMBIGUOUS and the prediction loop
abstains.

Identity states:

    CONFIRMED   explicitly verified (human or provider-confirmed mapping)
    NORMALIZED  resolved by deterministic normalization of one provider alias
    AMBIGUOUS   same alias maps to multiple participants (conflict)
    UNRESOLVED  name seen but not mapped to any participant

Merging policy: distinct humans are NEVER merged on fuzzy name similarity.
The only merge path is confirm_alias(), which attaches an explicit
evidence-backed alias (exact normalized-name match, e.g. a shared provider
participant ID) to an existing participant and marks it CONFIRMED. The
mapping is reversible: deleting the alias row restores pre-merge
resolution.
"""

from __future__ import annotations

import unicodedata
from datetime import datetime, timezone
from typing import Any, Protocol

IDENTITY_CONFIRMED = "CONFIRMED"
IDENTITY_NORMALIZED = "NORMALIZED"
IDENTITY_AMBIGUOUS = "AMBIGUOUS"
IDENTITY_UNRESOLVED = "UNRESOLVED"

IDENTITY_STATES = (
    IDENTITY_CONFIRMED,
    IDENTITY_NORMALIZED,
    IDENTITY_AMBIGUOUS,
    IDENTITY_UNRESOLVED,
)

# States that satisfy the prediction identity gate.
_ACCEPTED_STATES = (IDENTITY_CONFIRMED, IDENTITY_NORMALIZED)


def normalize_participant_name(name: str) -> str:
    """Deterministic, order-stable name normalization.

    NFKC normalization, lowercasing, punctuation removal, whitespace
    collapsing. Diacritics are preserved: stripping them would silently
    merge distinct spellings, which is a merge decision this layer never
    makes on its own.
    """
    text = unicodedata.normalize("NFKC", name)
    text = "".join(ch for ch in text if ch.isalnum() or ch.isspace())
    return " ".join(text.lower().split())


class TtIdentityStore(Protocol):
    """Persistence surface used by the identity service."""

    def participant_by_normalized(self, normalized_name: str) -> list[dict[str, object]]: ...

    def participant_by_id(self, participant_id: int) -> dict[str, object] | None: ...

    def insert_participant(
        self,
        *,
        canonical_name: str,
        normalized_name: str,
        state: str,
        seen_at: datetime,
    ) -> dict[str, object]: ...

    def touch_participant(self, participant_id: int, seen_at: datetime) -> None: ...

    def set_participant_state(self, participant_id: int, state: str) -> None: ...

    def add_alias(
        self,
        *,
        participant_id: int,
        alias_name: str,
        normalized_name: str,
        provider: str,
        raw_ref: str | None,
        seen_at: datetime,
    ) -> None: ...

    def aliases_for(self, participant_id: int) -> list[dict[str, object]]: ...

    def catalog_participants(self, limit: int = 500) -> list[dict[str, object]]: ...


class IdentityService:
    """Resolves provider names to canonical participants, never auto-merging."""

    def __init__(self, store: TtIdentityStore, clock: Any | None = None) -> None:
        self._store = store
        self._clock = clock if clock is not None else (lambda: datetime.now(timezone.utc))

    def resolve(self, name: str, *, provider: str, raw_ref: str | None = None) -> dict[str, object]:
        """Resolve one provider name to a participant record.

        Returns a participant row plus ``identity_state``; AMBIGUOUS
        participants must gate the prediction to NO_ACTION.
        """
        seen_at = self._clock()
        trimmed = name.strip()
        if not trimmed:
            raise ValueError("participant name must not be blank")
        normalized = normalize_participant_name(trimmed)

        candidates = self._store.participant_by_normalized(normalized)
        if len(candidates) == 1:
            participant = candidates[0]
            self._store.touch_participant(int(participant["participant_id"]), seen_at)
            self._store.add_alias(
                participant_id=int(participant["participant_id"]),
                alias_name=trimmed,
                normalized_name=normalized,
                provider=provider,
                raw_ref=raw_ref,
                seen_at=seen_at,
            )
            return self._row(participant, str(participant["identity_state"]))

        if len(candidates) > 1:
            for candidate in candidates:
                self._store.set_participant_state(
                    int(candidate["participant_id"]), IDENTITY_AMBIGUOUS
                )
            return {
                "participant_id": None,
                "canonical_name": trimmed,
                "normalized_name": normalized,
                "identity_state": IDENTITY_AMBIGUOUS,
                "conflict_count": len(candidates),
            }

        participant = self._store.insert_participant(
            canonical_name=trimmed,
            normalized_name=normalized,
            state=IDENTITY_NORMALIZED,
            seen_at=seen_at,
        )
        self._store.add_alias(
            participant_id=int(participant["participant_id"]),
            alias_name=trimmed,
            normalized_name=normalized,
            provider=provider,
            raw_ref=raw_ref,
            seen_at=seen_at,
        )
        return self._row(participant, IDENTITY_NORMALIZED)

    def confirm(self, participant_id: int, *, provider: str, raw_ref: str | None = None) -> dict[str, object]:
        """Explicitly confirm an identity mapping (human or provider verified)."""
        participant = self._store.participant_by_id(participant_id)
        if participant is None:
            raise KeyError(f"no participant with id {participant_id}")
        self._store.set_participant_state(participant_id, IDENTITY_CONFIRMED)
        return self._row(participant, IDENTITY_CONFIRMED)

    def confirm_alias(
        self,
        participant_id: int,
        *,
        alias_name: str,
        provider: str,
        raw_ref: str | None = None,
    ) -> dict[str, object]:
        """Attach an explicit, evidence-backed alias (reversible canonical merge).

        ``alias_name`` must be a distinct spelling of the same human whose
        identity is supported by provider evidence (e.g. a shared provider
        participant ID passed as ``raw_ref``) - never fuzzy name similarity.
        After this call, resolving ``alias_name`` returns this participant
        (state CONFIRMED). Deleting the alias row reverses the mapping.
        """
        participant = self._store.participant_by_id(participant_id)
        if participant is None:
            raise KeyError(f"no participant with id {participant_id}")
        self._store.add_alias(
            participant_id=participant_id,
            alias_name=alias_name,
            normalized_name=normalize_participant_name(alias_name),
            provider=provider,
            raw_ref=raw_ref,
            seen_at=self._clock(),
        )
        self._store.set_participant_state(participant_id, IDENTITY_CONFIRMED)
        return self._row(participant, IDENTITY_CONFIRMED)

    def identity_allows_prediction(self, identity_state: str | None) -> bool:
        return identity_state in _ACCEPTED_STATES

    def _row(self, participant: dict[str, object], state: str) -> dict[str, object]:
        return {
            "participant_id": participant.get("participant_id"),
            "canonical_name": participant.get("canonical_name"),
            "normalized_name": participant.get("normalized_name"),
            "identity_state": state,
            "first_seen": participant.get("first_seen"),
            "last_seen": participant.get("last_seen"),
        }