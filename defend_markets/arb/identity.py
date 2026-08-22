"""Canonical market identity and participant orientation.

Arbitrage comparisons require identical economic markets: same event, same
market family, same period, same line where applicable, and a complete,
mutually consistent selection universe.

Participant A/B orientation is canonical and independent of provider order.
Two books that return participants in opposite order must still map to the
same canonical outcomes; when outcome identity is ambiguous the engine must
abstain (``AMBIGUOUS_IDENTITY``) rather than guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from defend_markets.arb.models import ArbQuote, MarketFamily

AMBIGUOUS_IDENTITY = "AMBIGUOUS_IDENTITY"


class IdentityState(str, Enum):
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class CanonicalMarketKey:
    """Identity of the economic market a set of quotes must share."""

    canonical_event_id: str = ""
    market_family: MarketFamily = MarketFamily.MATCH_WINNER_2WAY
    period: str = "FULL_MATCH"
    line: Decimal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.canonical_event_id, str) or not self.canonical_event_id.strip():
            raise ValueError("canonical_event_id must not be blank")
        if not isinstance(self.period, str) or not self.period.strip():
            raise ValueError("period must not be blank")
        if not isinstance(self.market_family, MarketFamily):
            raise ValueError("market_family must be a MarketFamily")

    @classmethod
    def from_quote(cls, quote: ArbQuote) -> "CanonicalMarketKey":
        return cls(
            canonical_event_id=quote.canonical_event_id,
            market_family=quote.market_family,
            period=quote.period,
            line=quote.line,
        )

    def matches(self, other: "CanonicalMarketKey") -> bool:
        return (
            self.canonical_event_id == other.canonical_event_id
            and self.market_family is other.market_family
            and self.period == other.period
            and self.line == other.line
        )

    def without_line(self) -> "CanonicalMarketKey":
        return CanonicalMarketKey(
            canonical_event_id=self.canonical_event_id,
            market_family=self.market_family,
            period=self.period,
            line=None,
        )

    def human_key(self) -> str:
        line_part = "" if self.line is None else f"@{self.line}"
        return f"{self.canonical_event_id}::{self.market_family.value}::{self.period}{line_part}"


@dataclass(frozen=True)
class ParticipantOrientation:
    """Canonical participant mapping. ``participant_a`` is always HOME / A."""

    participant_a: str = ""
    participant_b: str = ""
    source: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.participant_a, str) or not self.participant_a.strip():
            raise ValueError("participant_a must not be blank")
        if not isinstance(self.participant_b, str) or not self.participant_b.strip():
            raise ValueError("participant_b must not be blank")
        if self.participant_a == self.participant_b:
            raise ValueError("participant_a and participant_b must differ")

    def maps_side(self, side: str, selection_name: str) -> bool:
        """Return True when ``selection_name`` maps to the canonical ``side``.

        ``side`` is the canonical participant label (PARTICIPANT_A or
        PARTICIPANT_B); selection names match the canonical participant by
        exact identity, never by provider order.
        """
        normalized = (selection_name or "").strip()
        if side == "PARTICIPANT_A":
            return normalized == self.participant_a
        if side == "PARTICIPANT_B":
            return normalized == self.participant_b
        return False


@dataclass(frozen=True)
class MarketIdentity:
    """Resolved canonical identity for a group of quotes."""

    canonical_key: CanonicalMarketKey
    orientation: ParticipantOrientation | None = None
    state: IdentityState = IdentityState.RESOLVED
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.canonical_key, CanonicalMarketKey):
            raise ValueError("canonical_key must be a CanonicalMarketKey")
        object.__setattr__(self, "notes", tuple(self.notes))

    @property
    def resolved(self) -> bool:
        return self.state is IdentityState.RESOLVED and self.orientation is not None

    def maps_side(self, quote: ArbQuote) -> bool:
        """True when the quote's selection/selection_side are orientation-consistent."""
        if not self.resolved:
            return False
        if self.canonical_key.market_family is MarketFamily.TOTAL:
            return quote.selection_side.value in ("OVER", "UNDER")
        if quote.selection_side.value in ("DRAW", "OVER", "UNDER"):
            return True
        return self.orientation.maps_side(quote.selection_side.value, quote.selection)


def resolve_canonical_identity(
    quotes: tuple[ArbQuote, ...],
    *,
    known_orientation: ParticipantOrientation | None = None,
) -> MarketIdentity:
    """Resolve the canonical identity for a group of quotes.

    Rules:

    * All quotes must share the same canonical event / family / period / line,
      otherwise the group is not a single market (callers group by key first).
    * Participant orientation is derived from the quotes when no known
      orientation is supplied. Provider order cannot determine identity: the
      canonical participant A/B pair is chosen deterministically.
    * If selection names are inconsistent with a single orientation, or a
      quote's selection names cannot be mapped, the result is AMBIGUOUS and
      no arbitrage may proceed.
    """
    if not quotes:
        return MarketIdentity(
            canonical_key=CanonicalMarketKey(),
            state=IdentityState.UNRESOLVED,
            notes=("no quotes supplied",),
        )

    canonical_key = CanonicalMarketKey.from_quote(quotes[0])
    for quote in quotes[1:]:
        other = CanonicalMarketKey.from_quote(quote)
        if not canonical_key.matches(other):
            return MarketIdentity(
                canonical_key=canonical_key,
                state=IdentityState.UNRESOLVED,
                notes=("quotes span more than one canonical market",),
            )

    if canonical_key.market_family is MarketFamily.TOTAL:
        # Over/Under have no participant orientation dependency.
        if known_orientation is None:
            a, b = _derive_orientation(quotes)
            orientation = ParticipantOrientation(participant_a=a, participant_b=b, source="derived")
        else:
            orientation = known_orientation
        return MarketIdentity(
            canonical_key=canonical_key,
            orientation=orientation,
            state=IdentityState.RESOLVED,
        )

    names_a = {q.participant_a for q in quotes}
    names_b = {q.participant_b for q in quotes}

    if known_orientation is not None:
        if not _orientation_consistent(known_orientation, quotes):
            return MarketIdentity(
                canonical_key=canonical_key,
                state=IdentityState.AMBIGUOUS,
                notes=("known orientation conflicts with quote participant names",),
            )
        return MarketIdentity(
            canonical_key=canonical_key,
            orientation=known_orientation,
            state=IdentityState.RESOLVED,
        )

    # A 2-way market describes exactly two distinct participants. A quote
    # group whose participant names span more than two distinct identities
    # cannot be a single canonical market: abstain.
    universe = (names_a | names_b) - {"", "UNKNOWN"}
    if len(universe) != 2:
        return MarketIdentity(
            canonical_key=canonical_key,
            state=IdentityState.AMBIGUOUS,
            notes=(f"participant universe has {len(universe)} distinct names; expected 2",),
        )

    a_name, b_name = sorted(universe)
    candidates = [(a_name, b_name), (b_name, a_name)]
    consistent: list[tuple[str, str]] = []
    for a, b in candidates:
        probe = ParticipantOrientation(participant_a=a, participant_b=b, source="derived")
        if _orientation_consistent(probe, quotes):
            consistent.append((a, b))

    if len(consistent) == 1:
        a, b = consistent[0]
        return MarketIdentity(
            canonical_key=canonical_key,
            orientation=ParticipantOrientation(participant_a=a, participant_b=b, source="derived"),
            state=IdentityState.RESOLVED,
        )

    return MarketIdentity(
        canonical_key=canonical_key,
        state=IdentityState.AMBIGUOUS,
        notes=("participant orientation ambiguous across quotes",),
    )


def _derive_orientation(quotes: tuple[ArbQuote, ...]) -> tuple[str, str]:
    names_a = {q.participant_a for q in quotes}
    names_b = {q.participant_b for q in quotes}
    if len(names_a) == 1 and len(names_b) == 1 and names_a != names_b:
        return next(iter(names_a)), next(iter(names_b))
    if len(names_a) == 2 and names_a == names_b:
        ordered = sorted(names_a)
        return ordered[0], ordered[1]
    fallback = sorted((names_a | names_b) - {"", "UNKNOWN"})
    if len(fallback) == 2:
        return fallback[0], fallback[1]
    return "UNKNOWN", "UNKNOWN"


def _orientation_consistent(orientation: ParticipantOrientation, quotes: tuple[ArbQuote, ...]) -> bool:
    for quote in quotes:
        if quote.market_family is MarketFamily.TOTAL:
            continue
        if quote.selection_side.value in ("DRAW", "OVER", "UNDER"):
            continue
        if not orientation.maps_side(quote.selection_side.value, quote.selection):
            return False
    return True
