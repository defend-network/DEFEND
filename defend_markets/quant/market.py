"""Commercial-grade market truth: canonical market identity, odds math,
participant orientation, quote freshness, and settlement safeguards.

An odds number is meaningless without market identity. Every price comparison,
no-vig calculation, edge estimate, and cross-book comparison must operate on
compatible canonical market keys with explicit participant orientation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


def parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Canonical market identity
# --------------------------------------------------------------------------- #

MATCH_WINNER = "MATCH_WINNER"
SPREAD = "SPREAD"
TOTAL = "TOTAL"
FULL_MATCH = "FULL_MATCH"


def canonical_market_key(*, event_id: str, family: str, period: str, selection: str, line: Any = None) -> str:
    line_part = "" if line is None else f"|{line}"
    return f"{event_id}|{family}|{period}|{selection}{line_part}"


def market_family_from_name(name: str) -> str:
    normalized = str(name or "").strip().casefold()
    if normalized in ("ml", "moneyline", "money line", "match winner", "1x2", "h2h"):
        return MATCH_WINNER
    if normalized in ("spread", "handicap", "spread ht"):
        return SPREAD
    if normalized in ("totals", "total", "over under"):
        return TOTAL
    return normalized


def markets_compatible(a: str, b: str) -> bool:
    return a == b


# --------------------------------------------------------------------------- #
# Odds / implied probability (deterministic, versioned)
# --------------------------------------------------------------------------- #

NO_VIG_METHOD = "PROPORTIONAL_V1"


def decimal_implied(odds: Any) -> float | None:
    try:
        value = float(odds)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value <= 1:
        return None
    return 1.0 / value


@dataclass(frozen=True)
class TwoSidedMarket:
    completeness: str
    p_a_raw: float | None = None
    p_b_raw: float | None = None
    overround: float | None = None
    no_vig_p_a: float | None = None
    no_vig_p_b: float | None = None
    method: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "completeness": self.completeness,
            "p_a_raw": self.p_a_raw,
            "p_b_raw": self.p_b_raw,
            "overround": self.overround,
            "no_vig_p_a": self.no_vig_p_a,
            "no_vig_p_b": self.no_vig_p_b,
            "method": self.method,
        }


def two_sided_no_vig(odds_a: Any, odds_b: Any) -> TwoSidedMarket:
    p_a = decimal_implied(odds_a)
    p_b = decimal_implied(odds_b)
    if p_a is None or p_b is None:
        return TwoSidedMarket(completeness="INCOMPLETE")
    total = p_a + p_b
    if total <= 0:
        return TwoSidedMarket(completeness="INCOMPLETE")
    return TwoSidedMarket(
        completeness="COMPLETE",
        p_a_raw=round(p_a, 10),
        p_b_raw=round(p_b, 10),
        overround=round(total - 1.0, 10),
        no_vig_p_a=round(p_a / total, 10),
        no_vig_p_b=round(p_b / total, 10),
        method=NO_VIG_METHOD,
    )


def incomplete_market(odds_a: Any, odds_b: Any) -> bool:
    return two_sided_no_vig(odds_a, odds_b).completeness == "INCOMPLETE"


# --------------------------------------------------------------------------- #
# Participant orientation
# --------------------------------------------------------------------------- #

PARTICIPANT_ORIENTATION_GUARD_VERSION = "V1"


def participant_orientation(
    *,
    provider_home: str,
    provider_away: str,
    canonical_a: str,
    canonical_b: str,
) -> tuple[str, str, str]:
    """Map provider selections onto canonical A/B.

    Returns (orientation, home_maps_to, away_maps_to) where orientation is
    CANONICAL / REVERSED / CONFLICT. Never infer first-returned = A.
    """
    home_n = compact(provider_home)
    away_n = compact(provider_away)
    a_n = compact(canonical_a)
    b_n = compact(canonical_b)
    if home_n == a_n and away_n == b_n:
        return "CANONICAL", "A", "B"
    if home_n == b_n and away_n == a_n:
        return "REVERSED", "B", "A"
    return "CONFLICT", "", ""


def compact(name: str) -> str:
    import unicodedata
    import re

    text = unicodedata.normalize("NFKD", str(name))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


# --------------------------------------------------------------------------- #
# Quote freshness (versioned policy)
# --------------------------------------------------------------------------- #

QUOTE_FRESHNESS_POLICY_VERSION = "V1"


@dataclass(frozen=True)
class FreshnessPolicy:
    fresh_max_seconds: float = 60.0
    stale_after_seconds: float = 300.0

    def state(self, observed_at: Any, now: datetime | None = None) -> str:
        observed = parse_dt(observed_at)
        if observed is None:
            return "UNKNOWN_TIMESTAMP"
        now = now or utc_now()
        age = (now - observed).total_seconds()
        if age < 0:
            return "UNKNOWN_TIMESTAMP"
        if age <= self.fresh_max_seconds:
            return "FRESH"
        if age <= self.stale_after_seconds:
            return "AGING"
        return "STALE"


def quote_age_seconds(observed_at: Any, now: datetime | None = None) -> float | None:
    observed = parse_dt(observed_at)
    if observed is None:
        return None
    now = now or utc_now()
    return (now - observed).total_seconds()


def cross_book_comparable(age_a: float | None, age_b: float | None, *, max_delta_seconds: float = 300.0) -> str:
    if age_a is None or age_b is None:
        return "NO"
    if age_a < 0 or age_b < 0:
        return "NO"
    if abs(age_a - age_b) > max_delta_seconds:
        return "NO"
    return "YES"


# --------------------------------------------------------------------------- #
# Settlement safeguards
# --------------------------------------------------------------------------- #

def settlement_orientation_ok(*, provider_home: str, provider_away: str, canonical_a: str, canonical_b: str) -> tuple[bool, str]:
    orientation, _, _ = participant_orientation(
        provider_home=provider_home,
        provider_away=provider_away,
        canonical_a=canonical_a,
        canonical_b=canonical_b,
    )
    if orientation == "CONFLICT":
        return False, "SETTLEMENT_AMBIGUOUS"
    return True, orientation


def is_valid_close(observed_at: Any, commence_at: Any) -> bool:
    observed = parse_dt(observed_at)
    commence = parse_dt(commence_at)
    if observed is None or commence is None:
        return False
    return observed < commence


def market_metrics_status(price_observation_count: int) -> str:
    return "AVAILABLE" if price_observation_count > 0 else "NOT_AVAILABLE"
