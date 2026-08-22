"""Arb core: freshness policy, stale quotes, cross-book time guards."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from defend_markets.arb.freshness import (
    FreshnessPolicy,
    evaluate_freshness,
)
from defend_markets.arb.models import EventState, SelectionSide
from tests.fakes_arb import make_arb_pair, make_quote, utc_now


class TestFreshnessPolicy:
    def test_fresh_quotes_ok(self):
        now = utc_now()
        qa, qb = make_arb_pair()
        result = evaluate_freshness((qa, qb), now=now)
        assert result.ok

    def test_stale_quote_detected(self):
        now = utc_now()
        qa, qb = make_arb_pair()
        old = make_quote(
            quote_id="stale-1",
            bookmaker="BookC",
            selection_side=SelectionSide.PARTICIPANT_B,
            odds="2.10",
            observed_at=now - timedelta(seconds=120),
            received_at=now - timedelta(seconds=120),
        )
        result = evaluate_freshness((qa, old), policy=FreshnessPolicy(max_quote_age_seconds=30), now=now)
        assert not result.ok
        assert len(result.stale_quotes) == 1
        assert result.reason is not None

    def test_stale_quote_profitable_math_is_not_executable(self):
        now = utc_now()
        qa, qb = make_arb_pair()
        old = make_quote(
            quote_id="stale-2",
            bookmaker="BookC",
            selection_side=SelectionSide.PARTICIPANT_B,
            odds="2.10",
            observed_at=now - timedelta(seconds=120),
        )
        result = evaluate_freshness((qa, old), now=now)
        assert not result.ok

    def test_cross_book_time_mismatch(self):
        now = utc_now()
        qa = make_quote(
            quote_id="a",
            selection_side=SelectionSide.PARTICIPANT_A,
            observed_at=now - timedelta(seconds=30),
        )
        qb = make_quote(
            quote_id="b",
            selection_side=SelectionSide.PARTICIPANT_B,
            observed_at=now - timedelta(seconds=1),
        )
        policy = FreshnessPolicy(max_quote_age_seconds=60, max_cross_book_delta_seconds=5)
        result = evaluate_freshness((qa, qb), policy=policy, now=now)
        assert not result.ok
        assert not result.cross_book.ok
        assert result.cross_book.max_delta_seconds == 29.0

    def test_post_commence_rejected_when_pre_match_only(self):
        now = utc_now()
        qa = make_quote(
            quote_id="a",
            selection_side=SelectionSide.PARTICIPANT_A,
            event_state=EventState.POST_COMMENCE,
            observed_at=now - timedelta(seconds=2),
        )
        qb = make_quote(
            quote_id="b",
            selection_side=SelectionSide.PARTICIPANT_B,
            observed_at=now - timedelta(seconds=1),
        )
        policy = FreshnessPolicy(pre_match_only=True)
        result = evaluate_freshness((qa, qb), policy=policy, now=now)
        assert not result.ok
        assert len(result.post_commence_quotes) == 1

    def test_missing_timestamp_is_stale(self):
        from defend_markets.arb.models import ArbQuote

        now = utc_now()
        qa = ArbQuote(
            quote_id="a",
            canonical_event_id="evt-1",
            bookmaker="BookA",
            sport="table_tennis",
            participant_a="Player A",
            participant_b="Player B",
            selection="Player A",
            selection_side=SelectionSide.PARTICIPANT_A,
            decimal_odds=Decimal("2.10"),
            observed_at=None,
            received_at=None,
            provider_updated_at=None,
        )
        qb = make_quote(
            quote_id="b",
            selection_side=SelectionSide.PARTICIPANT_B,
            observed_at=now - timedelta(seconds=1),
        )
        result = evaluate_freshness((qa, qb), now=now)
        assert not result.ok
        assert result.stale_quotes[0].timestamp_missing

    def test_live_event_rejected_when_pre_match_only(self):
        now = utc_now()
        qa = make_quote(
            quote_id="a",
            selection_side=SelectionSide.PARTICIPANT_A,
            event_state=EventState.LIVE,
        )
        qb = make_quote(
            quote_id="b",
            selection_side=SelectionSide.PARTICIPANT_B,
        )
        result = evaluate_freshness((qa, qb), policy=FreshnessPolicy(pre_match_only=True), now=now)
        assert not result.ok
