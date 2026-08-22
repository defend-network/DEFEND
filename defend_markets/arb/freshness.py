"""Quote freshness policy.

Every opportunity uses contemporaneous quotes. A freshness policy enforces:

* ``max_quote_age_seconds`` — a quote older than this is stale.
* ``max_cross_book_delta_seconds`` — the spread between the youngest and
  oldest *comparable* quotes must be small enough that the odds were
  simultaneously live.
* ``pre_match_only`` — quotes at/after commence time are rejected or
  downgraded.

Historical quotes remain evidence; they are simply not classified as
currently actionable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from defend_markets.arb.models import ArbQuote, EventState


@dataclass(frozen=True)
class FreshnessPolicy:
    max_quote_age_seconds: float = 30.0
    max_cross_book_delta_seconds: float = 10.0
    pre_match_only: bool = True

    def __post_init__(self) -> None:
        for name in ("max_quote_age_seconds", "max_cross_book_delta_seconds"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or value <= 0:
                raise ValueError(f"{name} must be a positive number")


@dataclass(frozen=True)
class QuoteFreshnessResult:
    quote_id: str = ""
    age_seconds: float | None = None
    stale: bool = False
    reason: str | None = None
    timestamp_missing: bool = False
    post_commence: bool = False


@dataclass(frozen=True)
class CrossBookFreshnessResult:
    max_delta_seconds: float | None = None
    ok: bool = True
    reason: str | None = None


@dataclass(frozen=True)
class FreshnessResult:
    ok: bool = True
    stale_quotes: tuple[QuoteFreshnessResult, ...] = ()
    cross_book: CrossBookFreshnessResult = field(default_factory=CrossBookFreshnessResult)
    post_commence_quotes: tuple[QuoteFreshnessResult, ...] = ()
    reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "stale_quotes", tuple(self.stale_quotes))
        object.__setattr__(self, "post_commence_quotes", tuple(self.post_commence_quotes))


def evaluate_freshness(
    quotes: tuple[ArbQuote, ...],
    policy: FreshnessPolicy | None = None,
    *,
    now: datetime | None = None,
) -> FreshnessResult:
    """Evaluate quote freshness against a policy.

    Returns ``ok=False`` when any quote is stale, any quote is missing a
    timestamp, quotes span too wide a window, or any quote is post-commence
    under a pre-match-only policy.
    """
    policy = policy or FreshnessPolicy()
    now_value = now or datetime.now(timezone.utc)

    stale: list[QuoteFreshnessResult] = []
    post_commence: list[QuoteFreshnessResult] = []
    timestamps: list[float] = []

    for quote in quotes:
        reference = quote.observed_at or quote.received_at or quote.provider_updated_at
        if reference is None:
            stale.append(
                QuoteFreshnessResult(
                    quote_id=quote.quote_id,
                    stale=True,
                    timestamp_missing=True,
                    reason="no usable timestamp",
                )
            )
            continue

        age = (now_value - reference).total_seconds()
        entry = QuoteFreshnessResult(quote_id=quote.quote_id, age_seconds=age)

        if policy.pre_match_only and quote.event_state in (
            EventState.POST_COMMENCE,
            EventState.LIVE,
            EventState.CLOSED,
        ):
            entry = QuoteFreshnessResult(
                quote_id=quote.quote_id,
                age_seconds=age,
                post_commence=True,
                reason=f"event state is {quote.event_state.value}",
            )
            post_commence.append(entry)
            continue

        if age > policy.max_quote_age_seconds:
            entry = QuoteFreshnessResult(
                quote_id=quote.quote_id,
                age_seconds=age,
                stale=True,
                reason=f"age {age:.2f}s exceeds {policy.max_quote_age_seconds}s",
            )
            stale.append(entry)
            continue

        timestamps.append(age)

    cross_book = CrossBookFreshnessResult()
    if timestamps and not stale:
        delta = max(timestamps) - min(timestamps)
        cross_book = CrossBookFreshnessResult(
            max_delta_seconds=delta,
            ok=delta <= policy.max_cross_book_delta_seconds,
            reason=(
                None
                if delta <= policy.max_cross_book_delta_seconds
                else f"cross-book delta {delta:.2f}s exceeds {policy.max_cross_book_delta_seconds}s"
            ),
        )

    ok = not stale and not post_commence and cross_book.ok
    reason = None
    if stale:
        reason = f"{len(stale)} stale quote(s)"
    elif post_commence:
        reason = f"{len(post_commence)} post-commence quote(s)"
    elif cross_book.reason:
        reason = cross_book.reason

    return FreshnessResult(
        ok=ok,
        stale_quotes=tuple(stale),
        cross_book=cross_book,
        post_commence_quotes=tuple(post_commence),
        reason=reason,
    )
