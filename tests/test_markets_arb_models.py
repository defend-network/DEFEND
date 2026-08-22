"""Arb core: Decimal normalization, invalid inputs, quote immutability."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from defend_markets.arb.models import (
    ArbQuote,
    BookmakerLimits,
    EventState,
    ExecutionCosts,
    MarketFamily,
    SelectionSide,
    validate_decimal_odds,
    validate_money_amount,
)
from tests.fakes_arb import make_quote


class TestDecimalNormalization:
    def test_string_odds_normalize_to_decimal(self):
        value = validate_decimal_odds("odds", "2.105")
        assert isinstance(value, Decimal)
        assert value == Decimal("2.105")

    def test_float_odds_normalize_to_decimal(self):
        value = validate_decimal_odds("odds", 2.1)
        assert value == Decimal("2.100")

    def test_odds_quantized_to_three_places(self):
        value = validate_decimal_odds("odds", "2.123456")
        assert value == Decimal("2.123")

    def test_money_quantized_to_two_places(self):
        value = validate_money_amount("stake", "100.999")
        assert value == Decimal("101.00")


class TestInvalidInputs:
    @pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", "nan"])
    def test_non_finite_odds_rejected(self, bad):
        with pytest.raises(ValueError):
            validate_decimal_odds("odds", bad)

    @pytest.mark.parametrize("bad", [1.0, "1.00", "0.5", "0"])
    def test_odds_at_or_below_1_rejected(self, bad):
        with pytest.raises(ValueError, match="greater than 1.0"):
            validate_decimal_odds("odds", bad)

    def test_negative_money_rejected(self):
        with pytest.raises(ValueError):
            validate_money_amount("stake", "-5")

    def test_nan_money_rejected(self):
        with pytest.raises(ValueError):
            validate_money_amount("stake", "NaN")

    def test_negative_bankroll_rejected(self):
        with pytest.raises(ValueError):
            validate_money_amount("bankroll", "-100")

    def test_negative_fixed_cost_rejected(self):
        with pytest.raises(ValueError):
            ExecutionCosts(fixed_cost=Decimal("-1"))

    def test_bad_fee_rate_rejected(self):
        with pytest.raises(ValueError):
            ExecutionCosts(commission_rate=Decimal("1.5"))

    def test_blank_quote_fields_rejected(self):
        with pytest.raises(ValueError):
            ArbQuote(quote_id="", canonical_event_id="e", bookmaker="b", sport="s", participant_a="a", participant_b="b", selection="a")

    def test_min_stake_above_max_rejected(self):
        with pytest.raises(ValueError):
            BookmakerLimits(max_stake=Decimal("10"), min_stake=Decimal("50"))


class TestQuoteImmutability:
    def test_quote_is_frozen(self):
        quote = make_quote()
        with pytest.raises(Exception):
            quote.decimal_odds = Decimal("9.99")

    def test_quote_rejects_naive_datetime(self):
        naive = datetime(2026, 8, 20, 12, 0)
        with pytest.raises(ValueError):
            make_quote(observed_at=naive)

    def test_quote_raw_hash_stable(self):
        fixed = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)
        q1 = make_quote(quote_id="stable-1", observed_at=fixed, received_at=fixed, provider_updated_at=fixed, commence_time=fixed + timedelta(hours=2))
        q2 = make_quote(quote_id="stable-1", observed_at=fixed, received_at=fixed, provider_updated_at=fixed, commence_time=fixed + timedelta(hours=2))
        assert q1.raw_hash == q2.raw_hash
        assert len(q1.raw_hash) == 64

    def test_quote_raw_hash_changes_on_odds(self):
        q1 = make_quote(quote_id="stable-1", odds="2.10")
        q2 = make_quote(quote_id="stable-1", odds="2.20")
        assert q1.raw_hash != q2.raw_hash

    def test_quote_timestamps_aware(self):
        quote = make_quote()
        assert quote.observed_at.tzinfo is not None
        assert quote.received_at.tzinfo is not None

    def test_event_state_default(self):
        assert make_quote().event_state is EventState.PRE_MATCH
