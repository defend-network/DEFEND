"""M4.5 commercial-grade market truth tests: identity, odds math, orientation,
freshness, cross-book guards, settlement safeguards."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from defend_markets.quant.market import (
    MATCH_WINNER,
    SPREAD,
    TOTAL,
    FreshnessPolicy,
    TwoSidedMarket,
    canonical_market_key,
    cross_book_comparable,
    decimal_implied,
    incomplete_market,
    markets_compatible,
    participant_orientation,
    quote_age_seconds,
    settlement_orientation_ok,
    two_sided_no_vig,
)

NOW = datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)


class TestImpliedProbability:
    def test_decimal_implied(self):
        assert decimal_implied("1.80") == 1 / 1.8
        assert decimal_implied(2.0) == 0.5

    def test_reject_invalid_odds(self):
        assert decimal_implied("1.00") is None
        assert decimal_implied("0.9") is None
        assert decimal_implied("abc") is None
        assert decimal_implied(None) is None


class TestTwoSidedMarket:
    def test_proportional_no_vig(self):
        market = two_sided_no_vig("1.80", "2.05")
        assert market.completeness == "COMPLETE"
        assert market.no_vig_p_a == pytest.approx((1 / 1.8) / (1 / 1.8 + 1 / 2.05))
        assert market.overround == pytest.approx(1 / 1.8 + 1 / 2.05 - 1)
        assert market.method == "PROPORTIONAL_V1"

    def test_incomplete_market_guard(self):
        market = two_sided_no_vig("1.80", None)
        assert market.completeness == "INCOMPLETE"
        assert market.no_vig_p_a is None
        assert incomplete_market("1.80", None) is True
        assert incomplete_market("1.80", "2.05") is False


class TestMarketIdentity:
    def test_canonical_market_key_distinguishes_line(self):
        assert canonical_market_key(event_id="e1", family=MATCH_WINNER, period="FULL_MATCH", selection="PLAYER_A") != canonical_market_key(
            event_id="e1", family=MATCH_WINNER, period="FULL_MATCH", selection="PLAYER_B"
        )
        total_a = canonical_market_key(event_id="e1", family=TOTAL, period="FULL_MATCH", selection="OVER", line=74.5)
        total_b = canonical_market_key(event_id="e1", family=TOTAL, period="FULL_MATCH", selection="OVER", line=75.5)
        assert total_a != total_b
        assert markets_compatible(total_a, total_a) is True
        assert markets_compatible(total_a, total_b) is False


class TestParticipantOrientation:
    def test_canonical_orientation(self):
        assert participant_orientation(provider_home="A Player", provider_away="B Player", canonical_a="a player", canonical_b="b player") == ("CANONICAL", "A", "B")

    def test_reversed_provider_ordering(self):
        assert participant_orientation(provider_home="B Player", provider_away="A Player", canonical_a="a player", canonical_b="b player") == ("REVERSED", "B", "A")

    def test_conflict_orientation(self):
        assert participant_orientation(provider_home="C Player", provider_away="D Player", canonical_a="a player", canonical_b="b player")[0] == "CONFLICT"

    def test_settlement_ambiguous_abstains(self):
        ok, orientation = settlement_orientation_ok(provider_home="X", provider_away="Y", canonical_a="a", canonical_b="b")
        assert ok is False
        assert orientation == "SETTLEMENT_AMBIGUOUS"


class TestQuoteFreshness:
    def test_freshness_states(self):
        policy = FreshnessPolicy(fresh_max_seconds=60, stale_after_seconds=300)
        assert policy.state((NOW - timedelta(seconds=10)).isoformat(), NOW) == "FRESH"
        assert policy.state((NOW - timedelta(seconds=120)).isoformat(), NOW) == "AGING"
        assert policy.state((NOW - timedelta(seconds=400)).isoformat(), NOW) == "STALE"
        assert policy.state(None, NOW) == "UNKNOWN_TIMESTAMP"

    def test_cross_book_age_guard(self):
        assert cross_book_comparable(10, 20, max_delta_seconds=300) == "YES"
        assert cross_book_comparable(10, 17 * 60, max_delta_seconds=300) == "NO"
        assert cross_book_comparable(None, 20) == "NO"

    def test_quote_age(self):
        assert quote_age_seconds((NOW - timedelta(seconds=30)).isoformat(), NOW) == 30
        assert quote_age_seconds(None, NOW) is None


import pytest  # noqa: E402  (imported at bottom to satisfy isort placement)
