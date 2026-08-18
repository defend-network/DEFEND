from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest

from defend_markets.domain import DecisionType, NoActionReason
from defend_markets.models import (
    ModelRegistry,
    NullReasoner,
    ReasonerRegistry,
    build_default_models,
)
from defend_markets.pipeline import DecisionPipeline, market_instrument_key
from defend_markets.strategies import build_default_registry

from tests.fakes_markets import (
    FakeSportsReader,
    InMemoryJournal,
    InMemoryStore,
    arb_pair,
    default_policies,
    no_arb_pair,
)

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)


def _pipeline(reader: FakeSportsReader, store: InMemoryStore | None = None, journal: InMemoryJournal | None = None):
    store = store if store is not None else InMemoryStore()
    for strategy_key in ("tt_two_way_arb", "tt_clv"):
        store.register_strategy(strategy_key)
    for policy in default_policies().values():
        store.register_policy(policy)
    journal = journal if journal is not None else InMemoryJournal()
    return DecisionPipeline(
        reader=reader,
        registry=build_default_registry(),
        store=store,
        journal=journal,
        clock=lambda: NOW,
    )


def test_market_instrument_key_is_desk_scoped():
    assert market_instrument_key("tt-live-001", "match_winner") == "sports:tt-live-001:match_winner"


class TestNoActionPaths:
    def test_no_eligible_data_when_reader_has_nothing(self):
        pipeline = _pipeline(FakeSportsReader(quotes={}))
        outcome = pipeline.evaluate_sports(
            event_key="tt-live-001", market_key="match_winner"
        )
        assert not outcome.is_opportunity
        assert NoActionReason.NO_ELIGIBLE_DATA in outcome.decision.reason_codes

    def test_costs_unaccounted_when_execution_costs_unknown(self):
        pipeline = _pipeline(FakeSportsReader(quotes={("tt-live-001", "match_winner"): arb_pair()}))
        outcome = pipeline.evaluate_sports(
            event_key="tt-live-001", market_key="match_winner"
        )
        assert not outcome.is_opportunity
        assert NoActionReason.COSTS_UNACCOUNTED in outcome.decision.reason_codes

    def test_insufficient_edge_when_overround_swallows_edge(self):
        pipeline = _pipeline(FakeSportsReader(quotes={("tt-live-001", "match_winner"): no_arb_pair()}))
        outcome = pipeline.evaluate_sports(
            event_key="tt-live-001", market_key="match_winner"
        )
        assert not outcome.is_opportunity
        assert NoActionReason.INSUFFICIENT_EDGE in outcome.decision.reason_codes

    def test_provider_unhealthy_blocks(self):
        reader = FakeSportsReader(quotes={("tt-live-001", "match_winner"): arb_pair(fees="0.001")})
        reader._health["book-a"] = {"status": "UNAVAILABLE", "observed_at": NOW}
        outcome = _pipeline(reader).evaluate_sports(
            event_key="tt-live-001", market_key="match_winner"
        )
        assert not outcome.is_opportunity
        assert NoActionReason.PROVIDER_UNHEALTHY in outcome.decision.reason_codes

    def test_stale_data_blocks(self):
        reader = FakeSportsReader(quotes={("tt-live-001", "match_winner"): arb_pair(fees="0.001")})
        reader._health["book-a"] = {
            "status": "HEALTHY",
            "observed_at": NOW - timedelta(minutes=30),
        }
        outcome = _pipeline(reader).evaluate_sports(
            event_key="tt-live-001", market_key="match_winner"
        )
        assert not outcome.is_opportunity
        assert NoActionReason.STALE_DATA in outcome.decision.reason_codes

    def test_below_risk_policy_when_policy_requires_more_confidence(self):
        store = InMemoryStore()
        for strategy_key in ("tt_two_way_arb", "tt_clv"):
            store.register_strategy(strategy_key)
        policies = default_policies()
        strict = policies["markets_core"]
        from defend_markets.domain import RiskPolicy

        strict = RiskPolicy(
            policy_key=strict.policy_key,
            version=strict.version,
            tier=strict.tier,
            min_data_quality=strict.min_data_quality,
            min_confidence=Decimal("0.95"),
            max_concentration=strict.max_concentration,
            allowed_desks=strict.allowed_desks,
            max_horizon=strict.max_horizon,
            max_loss_pct=strict.max_loss_pct,
        )
        store.register_policy(strict)
        reader = FakeSportsReader(quotes={("tt-live-001", "match_winner"): arb_pair(fees="0.001")})
        outcome = _pipeline(reader, store=store).evaluate_sports(
            event_key="tt-live-001", market_key="match_winner"
        )
        assert not outcome.is_opportunity
        assert NoActionReason.BELOW_RISK_POLICY in outcome.decision.reason_codes

    def test_planned_strategy_cannot_run(self):
        pipeline = _pipeline(FakeSportsReader(quotes={("tt-live-001", "match_winner"): arb_pair(fees="0.001")}))
        outcome = pipeline.evaluate_sports(
            event_key="tt-live-001", market_key="match_winner", strategy_key="tt_clv"
        )
        assert not outcome.is_opportunity
        assert NoActionReason.STRATEGY_NOT_ELIGIBLE in outcome.decision.reason_codes


class TestOpportunityPath:
    def test_real_arb_with_known_costs_journals_opportunity(self):
        reader = FakeSportsReader(quotes={("tt-live-001", "match_winner"): arb_pair(fees="0.001")})
        journal = InMemoryJournal()
        store = InMemoryStore()
        for strategy_key in ("tt_two_way_arb", "tt_clv"):
            store.register_strategy(strategy_key)
        for policy in default_policies().values():
            store.register_policy(policy)
        pipeline = _pipeline(reader, store=store, journal=journal)
        outcome = pipeline.evaluate_sports(
            event_key="tt-live-001", market_key="match_winner"
        )
        assert outcome.is_opportunity
        assert outcome.decision_id is not None
        assert outcome.opportunity is not None
        assert outcome.opportunity.net_edge is not None
        assert outcome.opportunity.net_edge > Decimal("0")
        assert outcome.opportunity.policy_version == 1
        assert outcome.decision.decision_type is DecisionType.OPPORTUNITY
        assert outcome.decision.policy_version == 1
        assert outcome.decision.opportunity_id is not None
        assert len(journal.entries) == 1
        assert outcome.decision_id == journal.entries[0].decision_id

    def test_opportunity_records_instrument_in_store(self):
        reader = FakeSportsReader(quotes={("tt-live-001", "match_winner"): arb_pair(fees="0.001")})
        store = InMemoryStore()
        for strategy_key in ("tt_two_way_arb", "tt_clv"):
            store.register_strategy(strategy_key)
        for policy in default_policies().values():
            store.register_policy(policy)
        pipeline = _pipeline(reader, store=store)
        pipeline.evaluate_sports(event_key="tt-live-001", market_key="match_winner")
        keys = {item["instrument_key"] for item in store.catalog_instruments()}
        assert "sports:tt-live-001:match_winner" in keys

    def test_no_action_does_not_claim_an_opportunity_id(self):
        reader = FakeSportsReader(quotes={("tt-live-001", "match_winner"): no_arb_pair()})
        outcome = _pipeline(reader).evaluate_sports(
            event_key="tt-live-001", market_key="match_winner"
        )
        assert outcome.opportunity_id is None


class TestReasoning:
    def test_null_reasoner_is_honest_about_being_null(self):
        registry = ReasonerRegistry()
        reasoner = registry.get("null")
        assert isinstance(reasoner, NullReasoner)
        assert reasoner.label == "null"
        assert "decline" in reasoner.capabilities
        result = reasoner.reason("question", {})
        assert isinstance(result, str)
        assert "No model attached" in result

    def test_pipeline_runs_with_null_reasoner(self):
        reader = FakeSportsReader(quotes={("tt-live-001", "match_winner"): no_arb_pair()})
        pipeline = _pipeline(reader)
        pipeline._reasoners = ReasonerRegistry()
        outcome = pipeline.evaluate_sports(
            event_key="tt-live-001", market_key="match_winner",
            reasoner_label="null",
        )
        assert outcome.decision.model_version is None


class TestEloGuardedArb:
    def _pipeline(self, reader: FakeSportsReader, store: InMemoryStore | None = None):
        store = store if store is not None else InMemoryStore()
        for strategy_key in ("tt_two_way_arb", "tt_clv", "tt_elo_arb"):
            store.register_strategy(strategy_key)
        for policy in default_policies().values():
            store.register_policy(policy)
        return DecisionPipeline(
            reader=reader,
            registry=build_default_registry(),
            store=store,
            journal=InMemoryJournal(),
            models=build_default_models(),
            clock=lambda: NOW,
        )

    def test_abstains_when_model_not_registered(self):
        reader = FakeSportsReader(quotes={("tt-live-001", "match_winner"): arb_pair(fees="0.001")})
        pipeline = self._pipeline(reader)
        pipeline._models = ModelRegistry()
        outcome = pipeline.evaluate_sports(
            event_key="tt-live-001",
            market_key="match_winner",
            strategy_key="tt_elo_arb",
        )
        assert not outcome.is_opportunity
        assert NoActionReason.INSUFFICIENT_MODEL_HISTORY in outcome.decision.reason_codes

    def test_abstains_without_match_history(self):
        reader = FakeSportsReader(quotes={("tt-live-001", "match_winner"): arb_pair(fees="0.001")})
        outcome = self._pipeline(reader).evaluate_sports(
            event_key="tt-live-001",
            market_key="match_winner",
            strategy_key="tt_elo_arb",
        )
        assert not outcome.is_opportunity
        assert NoActionReason.INSUFFICIENT_MODEL_HISTORY in outcome.decision.reason_codes
        assert "No model probability available" in outcome.decision.thesis

    def test_abstains_below_minimum_history(self):
        store = InMemoryStore()
        store._tt_results = [
            {
                "event_key": f"e{i}",
                "league_key": "tabletennis",
                "home_participant_key": "tabletennis:alice",
                "away_participant_key": "tabletennis:bob",
                "home_score": 3,
                "away_score": 1,
                "completed_at": NOW,
                "source_provider": "the_odds_api_tt",
                "raw_ref": "tabletennis",
            }
            for i in range(4)
        ]
        reader = FakeSportsReader(quotes={("tt-live-001", "match_winner"): arb_pair(fees="0.001")})
        outcome = self._pipeline(reader, store=store).evaluate_sports(
            event_key="tt-live-001",
            market_key="match_winner",
            strategy_key="tt_elo_arb",
        )
        assert not outcome.is_opportunity
        assert NoActionReason.INSUFFICIENT_MODEL_HISTORY in outcome.decision.reason_codes

    def test_opportunity_with_model_probability_when_history_sufficient(self):
        store = InMemoryStore()
        store._tt_results = [
            {
                "event_key": f"e{i}",
                "league_key": "tabletennis",
                "home_participant_key": "tabletennis:alice",
                "away_participant_key": "tabletennis:bob",
                "home_score": 3,
                "away_score": 1,
                "completed_at": NOW,
                "source_provider": "the_odds_api_tt",
                "raw_ref": "tabletennis",
            }
            for i in range(6)
        ]
        reader = FakeSportsReader(
            quotes={
                ("tt-live-001", "match_winner"): arb_pair(
                    fees="0.001",
                    selection_keys=("tabletennis:alice", "tabletennis:bob"),
                )
            }
        )
        journal = InMemoryJournal()
        store.register_strategy("tt_elo_arb")
        for policy in default_policies().values():
            store.register_policy(policy)
        pipeline = DecisionPipeline(
            reader=reader,
            registry=build_default_registry(),
            store=store,
            journal=journal,
            models=build_default_models(),
            clock=lambda: NOW,
        )
        outcome = pipeline.evaluate_sports(
            event_key="tt-live-001",
            market_key="match_winner",
            strategy_key="tt_elo_arb",
        )
        assert outcome.is_opportunity
        assert outcome.opportunity is not None
        assert outcome.opportunity.model_version == "tt_elo@1.0.0"
        assert outcome.opportunity.model_probability is not None
        assert Decimal("0") < outcome.opportunity.model_probability < Decimal("1")
        assert outcome.opportunity.model_detail.get("available") is True
        assert outcome.opportunity.model_detail.get("home_games") == 6
        assert outcome.opportunity.thesis.startswith("L1 arb gross edge")
        assert outcome.opportunity.thesis.endswith(".")
        assert outcome.decision.model_probability == outcome.opportunity.model_probability
        assert outcome.decision.model_version == "tt_elo@1.0.0"