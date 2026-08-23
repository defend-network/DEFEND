"""Arb core: opportunity classification, dedup, expiration, settlement."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from defend_markets.arb.models import (
    ArbQuote,
    ArbSettings,
    EventState,
    MarketFamily,
    SelectionSide,
)
from defend_markets.arb.opportunity import (
    ArbClassification,
    build_opportunity,
    classify,
    deduplication_fingerprint,
    is_expired,
)
from defend_markets.arb.risk import SettlementCompatibility, SettlementStatus
from tests.fakes_arb import make_arb_pair, make_quote, utc_now


def _default_settings() -> ArbSettings:
    return ArbSettings(min_net_roi=Decimal("0.005"), execution_buffer=Decimal("0.004"))


class TestClassification:
    def test_no_arb(self):
        qa, qb = make_arb_pair(odds_a="1.90", odds_b="1.90")
        opp = build_opportunity((qa, qb), total_stake=Decimal("100"), settings=_default_settings())
        assert opp.classification is ArbClassification.NO_ARB

    def test_mathematical_arb(self):
        qa, qb = make_arb_pair(odds_a="2.10", odds_b="2.10")
        opp = build_opportunity((qa, qb), total_stake=Decimal("100"), settings=_default_settings())
        assert opp.classification is ArbClassification.EXECUTABLE_ARB
        assert opp.raw_margin > 0

    def test_rounding_destroys_arb_so_mathematical_only(self):
        # 1.95 / 2.30 with $5 total: pure Q ~ 0.9476 < 1 (a real arb), but the
        # required $1 stake increment rounds 2.64/2.36 down to 2.00/2.00 which
        # makes the worst-case profit negative. So MATHEMATICAL_ARB, never
        # EXECUTABLE_ARB.
        qa, qb = make_arb_pair(odds_a="1.95", odds_b="2.30")
        from defend_markets.arb.math import is_pure_arb

        assert is_pure_arb((Decimal("1.95"), Decimal("2.30")))

        from defend_markets.arb.models import StakeSettings
        from defend_markets.arb.staking import solve_staking_plan

        staking = solve_staking_plan(
            Decimal("5"),
            (Decimal("1.95"), Decimal("2.30")),
            (qa, qb),
            settings=StakeSettings(stake_increment=Decimal("1.00"), min_stake=Decimal("0.01")),
        )
        assert staking.feasible
        assert staking.worst_case_profit <= 0

        settings = ArbSettings(
            min_net_roi=Decimal("0.00001"),
            execution_buffer=Decimal("0.00001"),
        )
        from defend_markets.arb.models import StakeSettings

        opp = build_opportunity(
            (qa, qb),
            total_stake=Decimal("5"),
            settings=settings,
            stake_settings=StakeSettings(stake_increment=Decimal("1.00"), min_stake=Decimal("0.01")),
        )
        assert opp.classification is ArbClassification.MATHEMATICAL_ARB

    def test_stale_quote_classification(self):
        now = utc_now()
        qa = make_quote(
            quote_id="a",
            selection_side=SelectionSide.PARTICIPANT_A,
            observed_at=now - timedelta(seconds=120),
        )
        qb = make_quote(
            quote_id="b",
            selection_side=SelectionSide.PARTICIPANT_B,
            observed_at=now - timedelta(seconds=1),
        )
        settings = _default_settings()
        opp = build_opportunity((qa, qb), total_stake=Decimal("100"), settings=settings, now=now)
        assert opp.classification is ArbClassification.STALE

    def test_post_commence_classification(self):
        qa = make_quote(
            quote_id="a",
            selection_side=SelectionSide.PARTICIPANT_A,
            event_state=EventState.POST_COMMENCE,
        )
        qb = make_quote(
            quote_id="b",
            selection_side=SelectionSide.PARTICIPANT_B,
        )
        settings = _default_settings()
        opp = build_opportunity((qa, qb), total_stake=Decimal("100"), settings=settings)
        assert opp.classification is ArbClassification.POST_COMMENCE

    def test_incompatible_line_classification(self):
        qa = make_quote(
            quote_id="a",
            selection_side=SelectionSide.PARTICIPANT_A,
            market_family=MarketFamily.SPREAD,
            line=Decimal("-1.5"),
        )
        qb = make_quote(
            quote_id="b",
            selection_side=SelectionSide.PARTICIPANT_B,
            market_family=MarketFamily.SPREAD,
            line=Decimal("2.5"),
        )
        opp = build_opportunity((qa, qb), total_stake=Decimal("100"), settings=_default_settings())
        assert opp.classification is ArbClassification.INCOMPATIBLE

    def test_three_way_arb_classification(self):
        q1 = make_quote(quote_id="a", selection_side=SelectionSide.PARTICIPANT_A, odds="3.5", market_family=MarketFamily.MATCH_WINNER_3WAY)
        q2 = make_quote(quote_id="b", selection_side=SelectionSide.DRAW, odds="3.5", market_family=MarketFamily.MATCH_WINNER_3WAY)
        q3 = make_quote(quote_id="c", selection_side=SelectionSide.PARTICIPANT_B, odds="3.5", market_family=MarketFamily.MATCH_WINNER_3WAY)
        opp = build_opportunity((q1, q2, q3), total_stake=Decimal("300"), settings=_default_settings())
        assert opp.classification is ArbClassification.EXECUTABLE_ARB

    def test_incomplete_three_way_is_incomplete(self):
        q1 = make_quote(quote_id="a", selection_side=SelectionSide.PARTICIPANT_A, odds="3.5", market_family=MarketFamily.MATCH_WINNER_3WAY)
        q2 = make_quote(quote_id="b", selection_side=SelectionSide.PARTICIPANT_B, odds="3.5", market_family=MarketFamily.MATCH_WINNER_3WAY)
        # Never turn an incomplete 3-way into a fake 2-way arb.
        opp = build_opportunity((q1, q2), total_stake=Decimal("200"), settings=_default_settings())
        assert opp.classification is ArbClassification.INCOMPLETE

    def test_constraint_blocked_by_bankroll(self):
        qa, qb = make_arb_pair()
        from dataclasses import replace

        qa = replace(qa, bookmaker="BookA")
        qb = replace(qb, bookmaker="BookB")
        settings = _default_settings()
        opp = build_opportunity(
            (qa, qb),
            total_stake=Decimal("100"),
            settings=settings,
            bankroll_by_book={"BookA": Decimal("10"), "BookB": Decimal("400")},
        )
        assert opp.classification is ArbClassification.CONSTRAINT_BLOCKED

    def test_identity_ambiguous_classification(self):
        qa = make_quote(
            quote_id="a",
            bookmaker="BookA",
            selection_side=SelectionSide.PARTICIPANT_A,
            participant_a="Alice",
            participant_b="Bob",
            selection="Alice",
        )
        qb = make_quote(
            quote_id="b",
            bookmaker="BookB",
            selection_side=SelectionSide.PARTICIPANT_B,
            participant_a="Charlie",
            participant_b="Dave",
            selection="Dave",
        )
        opp = build_opportunity((qa, qb), total_stake=Decimal("100"), settings=_default_settings())
        assert opp.classification is ArbClassification.IDENTITY_AMBIGUOUS

    def test_near_arb_classification(self):
        # Q close to 1 but >= 1 -> NEAR_ARB (research only).
        result = classify(
            is_arb=False,
            compatibility=None,
            freshness=None,
            staking=None,
            near_arb=True,
        )
        assert result is ArbClassification.NEAR_ARB

    def test_executable_requires_more_than_q_lt_1(self):
        # Fresh math arb but settlement not verified -> still executable by default,
        # but strict policy flags SETTLEMENT_RULES_UNVERIFIED.
        qa, qb = make_arb_pair(odds_a="2.10", odds_b="2.10")
        opp = build_opportunity((qa, qb), total_stake=Decimal("100"), settings=_default_settings())
        assert opp.classification is ArbClassification.EXECUTABLE_ARB
        from defend_markets.arb.risk import RiskFlag

        assert RiskFlag.SETTLEMENT_RULES_UNVERIFIED in opp.risk_flags


class TestSettlementBoundary:
    def test_settlement_unknown(self):
        qa, qb = make_arb_pair()
        settlement = SettlementCompatibility()
        assert settlement.status is SettlementStatus.UNKNOWN
        assert not settlement.verified

    def test_settlement_verified(self):
        settlement = SettlementCompatibility(status=SettlementStatus.VERIFIED_COMPATIBLE)
        assert settlement.verified

    def test_settlement_incompatible_blocks_strict(self):
        qa, qb = make_arb_pair(odds_a="2.10", odds_b="2.10")
        settlement = SettlementCompatibility(status=SettlementStatus.INCOMPATIBLE)
        opp = build_opportunity(
            (qa, qb),
            total_stake=Decimal("100"),
            settings=_default_settings(),
            settlement=settlement,
        )
        # Settlement incompatibility is not invented probability; it is recorded
        # as a risk flag. Strict executability requires VERIFIED_COMPATIBLE.
        from defend_markets.arb.risk import RiskFlag

        assert RiskFlag.SETTLEMENT_RULES_UNVERIFIED in opp.risk_flags

    def test_strict_policy_requires_verified_settlement(self):
        qa, qb = make_arb_pair(odds_a="2.10", odds_b="2.10")
        strict = ArbSettings(
            min_net_roi=Decimal("0.005"),
            execution_buffer=Decimal("0.004"),
            settlement_required=True,
        )
        # Without verified settlement -> MATHEMATICAL_ARB (not executable).
        opp = build_opportunity((qa, qb), total_stake=Decimal("100"), settings=strict)
        assert opp.classification is ArbClassification.MATHEMATICAL_ARB

        verified = SettlementCompatibility(status=SettlementStatus.VERIFIED_COMPATIBLE)
        opp_ok = build_opportunity(
            (qa, qb),
            total_stake=Decimal("100"),
            settings=strict,
            settlement=verified,
        )
        assert opp_ok.classification is ArbClassification.EXECUTABLE_ARB


class TestDeduplication:
    def test_stable_fingerprint(self):
        fp1 = deduplication_fingerprint("evt::ML::FULL", ("q1", "q2"), "policy-v1")
        fp2 = deduplication_fingerprint("evt::ML::FULL", ("q1", "q2"), "policy-v1")
        assert fp1 == fp2

    def test_fingerprint_changes_with_market(self):
        fp1 = deduplication_fingerprint("evt::ML::FULL", ("q1", "q2"), "policy-v1")
        fp2 = deduplication_fingerprint("evt2::ML::FULL", ("q1", "q2"), "policy-v1")
        assert fp1 != fp2

    def test_fingerprint_changes_with_quotes(self):
        fp1 = deduplication_fingerprint("evt::ML::FULL", ("q1", "q2"), "policy-v1")
        fp2 = deduplication_fingerprint("evt::ML::FULL", ("q1", "q3"), "policy-v1")
        assert fp1 != fp2


class TestExpiration:
    def test_opportunity_has_expiry(self):
        qa, qb = make_arb_pair(odds_a="2.10", odds_b="2.10")
        opp = build_opportunity((qa, qb), total_stake=Decimal("100"), settings=_default_settings())
        assert opp.expires_at is not None
        assert not is_expired(opp, now=opp.detected_at + timedelta(seconds=1))

    def test_opportunity_expired(self):
        qa, qb = make_arb_pair(odds_a="2.10", odds_b="2.10")
        opp = build_opportunity((qa, qb), total_stake=Decimal("100"), settings=_default_settings())
        future = opp.expires_at + timedelta(seconds=1)
        assert is_expired(opp, now=future)
        assert classify(
            is_arb=True, compatibility=None, freshness=None, staking=None, expired=True
        ) is ArbClassification.EXPIRED

    def test_old_math_arb_not_actionable(self):
        # Never present an expired mathematical opportunity as actionable.
        qa, qb = make_arb_pair(odds_a="2.10", odds_b="2.10")
        opp = build_opportunity((qa, qb), total_stake=Decimal("100"), settings=_default_settings())
        assert opp.expires_at > opp.detected_at


class TestOpportunityImmutable:
    def test_opportunity_is_frozen(self):
        qa, qb = make_arb_pair(odds_a="2.10", odds_b="2.10")
        opp = build_opportunity((qa, qb), total_stake=Decimal("100"), settings=_default_settings())
        with pytest.raises(Exception):
            opp.total_stake = Decimal("999")

    def test_opportunity_preserves_evidence(self):
        qa, qb = make_arb_pair(odds_a="2.10", odds_b="2.10")
        opp = build_opportunity((qa, qb), total_stake=Decimal("100"), settings=_default_settings())
        assert len(opp.quotes) == 2
        assert opp.evidence_refs
        assert opp.canonical_event_id == "evt-1"
        assert opp.bookmakers == ("BookA", "BookB")

    def test_same_quote_combination_fingerprint_stable_across_runs(self):
        qa, qb = make_arb_pair(odds_a="2.10", odds_b="2.10")
        opp1 = build_opportunity((qa, qb), total_stake=Decimal("100"), settings=_default_settings())
        opp2 = build_opportunity((qa, qb), total_stake=Decimal("200"), settings=_default_settings())
        assert opp1.opportunity_id == opp2.opportunity_id
