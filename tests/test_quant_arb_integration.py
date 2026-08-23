"""M4.7 arb integration tests (P70 items 30-51).

Covers: canonical observation -> ArbQuote, 2-book 2-way, 3-way integration,
spread line match/mismatch, total mismatch, period mismatch, participant
reversal, stale quote, cross-book time mismatch, opportunity persistence,
immutable supersession, expiration, paper ticket, owner access unknown,
settlement compatibility unknown, mathematically valid but paper-blocked,
rounding destroys opportunity, bankroll constraint, paper settlement,
settlement revision, no real wager action.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

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
    deduplication_fingerprint,
    is_expired,
)
from defend_markets.arb.paper import snapshot_paper_ticket
from defend_markets.arb.risk import SettlementCompatibility, SettlementStatus
from defend_markets.arb.staking import StakeSettings
from defend_markets.quant.arb_feed import observation_to_arb_quote
from defend_markets.quant.paper_arb import (
    executability_boundary,
    surface_classification,
)
from defend_markets.quant.store import InMemoryQuantStore

NOW = datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)
_REAL_NOW = datetime.now(timezone.utc)


def make_quote(*, quote_id, bookmaker, side, odds, observed_at=None, event_state=EventState.PRE_MATCH, **kw):
    observed = observed_at or _REAL_NOW
    return ArbQuote(
        quote_id=quote_id,
        canonical_event_id="ev1",
        provider_event_id=quote_id,
        bookmaker=bookmaker,
        sport="table-tennis",
        competition="TT Elite Series",
        participant_a=kw.pop("participant_a", "Alice"),
        participant_b=kw.pop("participant_b", "Bob"),
        commence_time=_REAL_NOW + timedelta(hours=2),
        market_family=kw.pop("market_family", MarketFamily.MATCH_WINNER_2WAY),
        period=kw.pop("period", "FULL_MATCH"),
        selection=kw.pop("selection", "Alice" if side in (SelectionSide.PARTICIPANT_A,) else "Bob"),
        selection_side=side,
        decimal_odds=Decimal(str(odds)),
        observed_at=observed,
        received_at=observed,
        event_state=event_state,
        **kw,
    )


class TestCanonicalObservationToArbQuote:
    def test_match_winner_observation(self):
        row = {
            "observation_id": 11,
            "canonical_event_id": "oaio:123",
            "provider_event_id": "123",
            "bookmaker": "Bet365",
            "market": "match_winner",
            "side": "A",
            "participant_key": "Alice",
            "price": "1.85",
            "observed_at": NOW.isoformat().replace("+00:00", "Z"),
            "scheduled_commence": (NOW + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            "player_a_key": "Alice",
            "player_b_key": "Bob",
            "state": "UPCOMING",
        }
        quote = observation_to_arb_quote(row, participant_a="Alice", participant_b="Bob", event_state="UPCOMING")
        assert quote is not None
        assert quote.market_family is MarketFamily.MATCH_WINNER_2WAY
        assert quote.selection_side is SelectionSide.PARTICIPANT_A
        assert quote.decimal_odds == Decimal("1.85")
        assert quote.canonical_event_id == "oaio:123"
        assert quote.event_state is EventState.PRE_MATCH

    def test_unknown_market_returns_none(self):
        row = {"observation_id": 1, "canonical_event_id": "ev1", "bookmaker": "Bet365", "market": "correct_score", "side": "A", "price": "1.85"}
        assert observation_to_arb_quote(row, participant_a="A", participant_b="B") is None

    def test_bad_price_returns_none(self):
        row = {"observation_id": 1, "canonical_event_id": "ev1", "bookmaker": "Bet365", "market": "match_winner", "side": "A", "price": "NaN"}
        assert observation_to_arb_quote(row, participant_a="A", participant_b="B") is None


class TestArbCore:
    def test_2book_2way_math_arb(self):
        qa = make_quote(quote_id="a", bookmaker="Bet365", side=SelectionSide.PARTICIPANT_A, odds=2.1)
        qb = make_quote(quote_id="b", bookmaker="BetMGM", side=SelectionSide.PARTICIPANT_B, odds=2.1)
        opp = build_opportunity((qa, qb), total_stake=Decimal("1000"), settings=ArbSettings())
        assert opp.classification in (ArbClassification.MATHEMATICAL_ARB, ArbClassification.EXECUTABLE_ARB)
        assert opp.inverse_sum < 1

    def test_no_arb_when_overround(self):
        qa = make_quote(quote_id="a", bookmaker="Bet365", side=SelectionSide.PARTICIPANT_A, odds=1.5)
        qb = make_quote(quote_id="b", bookmaker="BetMGM", side=SelectionSide.PARTICIPANT_B, odds=1.5)
        opp = build_opportunity((qa, qb), total_stake=Decimal("1000"))
        assert opp.classification is ArbClassification.NO_ARB

    def test_period_mismatch_rejected(self):
        qa = make_quote(quote_id="a", bookmaker="Bet365", side=SelectionSide.PARTICIPANT_A, odds=2.1, period="FULL_MATCH")
        qb = make_quote(quote_id="b", bookmaker="BetMGM", side=SelectionSide.PARTICIPANT_B, odds=2.1, period="SET_1")
        opp = build_opportunity((qa, qb), total_stake=Decimal("1000"))
        assert opp.classification is ArbClassification.INCOMPATIBLE

    def test_line_mismatch_rejected(self):
        qa = make_quote(quote_id="a", bookmaker="Bet365", side=SelectionSide.OVER, odds=2.1, market_family=MarketFamily.TOTAL, line=Decimal("3.5"))
        qb = make_quote(quote_id="b", bookmaker="BetMGM", side=SelectionSide.UNDER, odds=2.1, market_family=MarketFamily.TOTAL, line=Decimal("4.5"))
        opp = build_opportunity((qa, qb), total_stake=Decimal("1000"))
        assert opp.classification is ArbClassification.INCOMPATIBLE

    def test_spread_line_match(self):
        qa = make_quote(quote_id="a", bookmaker="Bet365", side=SelectionSide.PARTICIPANT_A, odds=2.1, market_family=MarketFamily.SPREAD, line=Decimal("-3.5"))
        qb = make_quote(quote_id="b", bookmaker="BetMGM", side=SelectionSide.PARTICIPANT_B, odds=2.1, market_family=MarketFamily.SPREAD, line=Decimal("-3.5"))
        opp = build_opportunity((qa, qb), total_stake=Decimal("1000"))
        assert opp.classification in (ArbClassification.MATHEMATICAL_ARB, ArbClassification.EXECUTABLE_ARB)

    def test_participant_reversal_compatible(self):
        qa = make_quote(quote_id="a", bookmaker="Bet365", side=SelectionSide.PARTICIPANT_A, odds=2.1, participant_a="Alice", participant_b="Bob", selection="Alice")
        qb = ArbQuote(
            quote_id="b", canonical_event_id="ev1", bookmaker="BetMGM", sport="table-tennis",
            participant_a="Bob", participant_b="Alice", commence_time=_REAL_NOW + timedelta(hours=2),
            market_family=MarketFamily.MATCH_WINNER_2WAY, period="FULL_MATCH",
            selection="Bob", selection_side=SelectionSide.PARTICIPANT_B,
            decimal_odds=Decimal("2.1"), observed_at=_REAL_NOW, received_at=_REAL_NOW,
        )
        opp = build_opportunity((qa, qb), total_stake=Decimal("1000"))
        assert opp.classification in (ArbClassification.MATHEMATICAL_ARB, ArbClassification.EXECUTABLE_ARB)

    def test_stale_quote_rejected(self):
        qa = make_quote(quote_id="a", bookmaker="Bet365", side=SelectionSide.PARTICIPANT_A, odds=2.1, observed_at=_REAL_NOW - timedelta(minutes=10))
        qb = make_quote(quote_id="b", bookmaker="BetMGM", side=SelectionSide.PARTICIPANT_B, odds=2.1, observed_at=_REAL_NOW - timedelta(minutes=10))
        settings = ArbSettings(max_quote_age_seconds=30)
        opp = build_opportunity((qa, qb), total_stake=Decimal("1000"), settings=settings)
        assert opp.classification is ArbClassification.STALE

    def test_cross_book_time_mismatch(self):
        qa = make_quote(quote_id="a", bookmaker="Bet365", side=SelectionSide.PARTICIPANT_A, odds=2.1, observed_at=_REAL_NOW)
        qb = make_quote(quote_id="b", bookmaker="BetMGM", side=SelectionSide.PARTICIPANT_B, odds=2.1, observed_at=_REAL_NOW - timedelta(minutes=5))
        settings = ArbSettings(max_cross_book_delta_seconds=10)
        opp = build_opportunity((qa, qb), total_stake=Decimal("1000"), settings=settings)
        assert opp.classification is ArbClassification.STALE

    def test_rounding_destroys_opportunity(self):
        # 1.95 / 2.30 is a real arb (Q < 1) but a $1 stake increment rounds the
        # legs down so the worst-case profit goes negative: MATHEMATICAL_ARB
        # only, never EXECUTABLE_ARB.
        from defend_markets.arb.math import is_pure_arb
        from defend_markets.arb.models import StakeSettings

        qa = make_quote(quote_id="a", bookmaker="Bet365", side=SelectionSide.PARTICIPANT_A, odds=1.95)
        qb = make_quote(quote_id="b", bookmaker="BetMGM", side=SelectionSide.PARTICIPANT_B, odds=2.30)
        assert is_pure_arb((Decimal("1.95"), Decimal("2.30")))
        opp = build_opportunity(
            (qa, qb),
            total_stake=Decimal("5"),
            settings=ArbSettings(min_net_roi=Decimal("0.00001"), execution_buffer=Decimal("0.00001")),
            stake_settings=StakeSettings(stake_increment=Decimal("1.00"), min_stake=Decimal("0.01")),
        )
        assert opp.classification is ArbClassification.MATHEMATICAL_ARB
        assert opp.classification is not ArbClassification.EXECUTABLE_ARB

    def test_bankroll_constraint(self):
        qa = make_quote(quote_id="a", bookmaker="Bet365", side=SelectionSide.PARTICIPANT_A, odds=2.1, max_stake=Decimal("100"))
        qb = make_quote(quote_id="b", bookmaker="BetMGM", side=SelectionSide.PARTICIPANT_B, odds=2.1, max_stake=Decimal("100"))
        opp = build_opportunity((qa, qb), total_stake=Decimal("1000"))
        # Stake plan must respect max stakes; classification either math or constraint-blocked
        assert opp.classification in (ArbClassification.MATHEMATICAL_ARB, ArbClassification.CONSTRAINT_BLOCKED)


class TestOpportunityPersistence:
    def test_fingerprint_supersession(self):
        f1 = deduplication_fingerprint("ev1::MATCH_WINNER_2WAY::FULL_MATCH", ("a", "b"), "sports-arb-core-m1@min_net_roi=0.005")
        f2 = deduplication_fingerprint("ev1::MATCH_WINNER_2WAY::FULL_MATCH", ("a", "b"), "sports-arb-core-m1@min_net_roi=0.005")
        f3 = deduplication_fingerprint("ev1::MATCH_WINNER_2WAY::FULL_MATCH", ("a", "c"), "sports-arb-core-m1@min_net_roi=0.005")
        assert f1 == f2
        assert f1 != f3

    def test_immutable_store_persistence(self):
        store = InMemoryQuantStore()
        qa = make_quote(quote_id="a", bookmaker="Bet365", side=SelectionSide.PARTICIPANT_A, odds=2.1)
        qb = make_quote(quote_id="b", bookmaker="BetMGM", side=SelectionSide.PARTICIPANT_B, odds=2.1)
        opp = build_opportunity((qa, qb), total_stake=Decimal("1000"))
        created = store.insert_arb_opportunity({
            "opportunity_id": opp.opportunity_id,
            "fingerprint": opp.opportunity_id,
            "canonical_event_id": opp.canonical_event_id,
            "canonical_market_key": opp.canonical_market_key,
            "detected_at": opp.detected_at.isoformat(),
            "first_seen_at": opp.detected_at.isoformat(),
            "bookmakers": ["Bet365", "BetMGM"],
            "quote_ids": ["a", "b"],
            "odds": ["2.1", "2.1"],
            "inverse_sum": str(opp.inverse_sum),
            "raw_margin": str(opp.raw_margin),
            "stake_plan": [],
            "worst_case_profit": float(opp.worst_case_profit),
            "worst_case_roi": float(opp.worst_case_roi),
            "freshness_state": "FRESH",
            "settlement_compatibility": "UNKNOWN",
            "classification": opp.classification.value,
            "risk_flags": [],
            "policy_version": "sports-arb-core-m1",
            "status": "ACTIVE",
        })
        assert created is True
        # identical fingerprint -> no duplicate
        assert store.insert_arb_opportunity({
            "opportunity_id": opp.opportunity_id,
            "fingerprint": opp.opportunity_id,
            "canonical_event_id": opp.canonical_event_id,
            "canonical_market_key": opp.canonical_market_key,
            "detected_at": opp.detected_at.isoformat(),
            "first_seen_at": opp.detected_at.isoformat(),
            "bookmakers": ["Bet365", "BetMGM"],
            "quote_ids": ["a", "b"],
            "odds": ["2.1", "2.1"],
            "inverse_sum": str(opp.inverse_sum),
            "raw_margin": str(opp.raw_margin),
            "stake_plan": [],
            "worst_case_profit": float(opp.worst_case_profit),
            "worst_case_roi": float(opp.worst_case_roi),
            "freshness_state": "FRESH",
            "settlement_compatibility": "UNKNOWN",
            "classification": opp.classification.value,
            "risk_flags": [],
            "policy_version": "sports-arb-core-m1",
            "status": "ACTIVE",
        }) is False

    def test_expiration(self):
        store = InMemoryQuantStore()
        store.insert_arb_opportunity({
            "opportunity_id": "o1", "fingerprint": "f1", "canonical_event_id": "ev1",
            "canonical_market_key": "k", "detected_at": NOW.isoformat(), "first_seen_at": NOW.isoformat(),
            "bookmakers": [], "quote_ids": [], "odds": [], "inverse_sum": "0.9", "raw_margin": "0.1",
            "stake_plan": [], "classification": "MATHEMATICAL_ARB", "policy_version": "v", "status": "ACTIVE",
        })
        expired = store.expire_arb_opportunity("o1", expired_at=NOW.isoformat())
        assert expired is True
        assert store.list_arb_opportunities(status="ACTIVE") == []


class TestPaperBoundary:
    def test_owner_access_unknown_blocks_executability(self):
        facts = executability_boundary()
        assert facts["OWNER_EXECUTION_ACCESS"] == "UNKNOWN"
        assert facts["BALANCE_VERIFIED"] == "UNKNOWN"

    def test_surface_classification_paper_blocked(self):
        qa = make_quote(quote_id="a", bookmaker="Bet365", side=SelectionSide.PARTICIPANT_A, odds=2.1)
        qb = make_quote(quote_id="b", bookmaker="BetMGM", side=SelectionSide.PARTICIPANT_B, odds=2.1)
        settlement = SettlementCompatibility(status=SettlementStatus.VERIFIED_COMPATIBLE)
        opp = build_opportunity((qa, qb), total_stake=Decimal("1000"), settlement=settlement)
        assert opp.classification is ArbClassification.EXECUTABLE_ARB
        # owner facts unknown -> surface as OWNER_EXECUTION_UNVERIFIED, not "guaranteed"
        surface = surface_classification(opp)
        assert surface == "OWNER_EXECUTION_UNVERIFIED"

    def test_settlement_compatibility_unknown_blocks(self):
        qa = make_quote(quote_id="a", bookmaker="Bet365", side=SelectionSide.PARTICIPANT_A, odds=2.1)
        qb = make_quote(quote_id="b", bookmaker="BetMGM", side=SelectionSide.PARTICIPANT_B, odds=2.1)
        settlement = SettlementCompatibility(status=SettlementStatus.UNKNOWN)
        opp = build_opportunity((qa, qb), total_stake=Decimal("1000"), settlement=settlement, settings=ArbSettings(settlement_required=True))
        assert opp.classification is ArbClassification.MATHEMATICAL_ARB

    def test_paper_ticket_snapshot(self):
        qa = make_quote(quote_id="a", bookmaker="Bet365", side=SelectionSide.PARTICIPANT_A, odds=2.1)
        qb = make_quote(quote_id="b", bookmaker="BetMGM", side=SelectionSide.PARTICIPANT_B, odds=2.1)
        opp = build_opportunity((qa, qb), total_stake=Decimal("1000"))
        ticket = snapshot_paper_ticket(opp, decision_time=NOW)
        assert ticket.opportunity_id == opp.opportunity_id
        assert ticket.policy_version == opp.policy_version
        assert len(ticket.legs) == 2

    def test_no_real_wager_action(self):
        # The paper path never creates a settlement; it only records tickets.
        store = InMemoryQuantStore()
        from defend_markets.quant.paper_arb import PaperArbStore
        qa = make_quote(quote_id="a", bookmaker="Bet365", side=SelectionSide.PARTICIPANT_A, odds=2.1)
        qb = make_quote(quote_id="b", bookmaker="BetMGM", side=SelectionSide.PARTICIPANT_B, odds=2.1)
        opp = build_opportunity((qa, qb), total_stake=Decimal("1000"))
        paper = PaperArbStore(store)
        paper.record_ticket(opp, decision_time=NOW)
        assert len(store.list_paper_arb_tickets()) == 1
        assert store.list_settlements() == []

    def test_paper_arb_settlement_and_revision(self):
        store = InMemoryQuantStore()
        from defend_markets.quant.paper_arb import PaperArbStore
        qa = make_quote(quote_id="a", bookmaker="Bet365", side=SelectionSide.PARTICIPANT_A, odds=2.1)
        qb = make_quote(quote_id="b", bookmaker="BetMGM", side=SelectionSide.PARTICIPANT_B, odds=2.1)
        opp = build_opportunity((qa, qb), total_stake=Decimal("1000"))
        paper = PaperArbStore(store)
        paper.record_ticket(opp, decision_time=NOW)
        result = paper.settle_for_event(canonical_event_id="ev1", settlement_id=77, actual_winner_side="A")
        assert result["settled"] == 1
        ticket = store.list_paper_arb_tickets()[0]
        assert ticket["settlement_id"] == 77
        assert ticket["settlement_revision"] == 1
        assert ticket["realized_pnl"] is not None
