from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from defend_markets.domain import ProvenanceStamp
from defend_markets.feeds import participant_key
from defend_markets.identity import IdentityService
from defend_markets.pipeline import DecisionPipeline
from defend_markets.predict_service import TtPredictionService
from defend_markets.settle_service import TtSettlementService
from defend_markets.sports_adapter import SportsSelectionQuote

from tests.fakes_markets import (
    FakeSportsReader,
    InMemoryForecastStore,
    InMemoryJournal,
    InMemoryStore,
    default_policies,
)

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)
EVENT = "tt-live-001"
ALICE = participant_key("table_tennis", "Player A")
BOB = participant_key("table_tennis", "Player B")


def quote(book: str, selection: str, odds: str, hour: int = 11) -> SportsSelectionQuote:
    return SportsSelectionQuote(
        selection_key=selection,
        display_name=selection,
        decimal_odds=Decimal(odds),
        provenance=ProvenanceStamp(
            source_key=book,
            observed_at=datetime(2026, 8, 15, hour, 0, tzinfo=timezone.utc),
            received_at=datetime(2026, 8, 15, hour, 1, tzinfo=timezone.utc),
            raw_ref=f"raw-{book}-{selection}-{hour}",
            normalization_version=None,
        ),
        selection_id=f"sel-{book}-{selection}",
    )


def make_reader(with_odds: bool = True) -> FakeSportsReader:
    reader = FakeSportsReader()
    if with_odds:
        reader._quotes[(EVENT, "match_winner")] = [
            quote("book-a", "home", "1.85"),
            quote("book-a", "away", "2.35"),
            quote("book-b", "home", "1.90"),
            quote("book-b", "away", "2.30"),
        ]
    return reader


def make_stack(reader: FakeSportsReader) -> dict[str, object]:
    store = InMemoryStore()
    for policy in default_policies().values():
        store.register_policy(policy)
    store.register_strategy("tt_elo_arb")
    forecast = InMemoryForecastStore()
    pipeline = DecisionPipeline(
        reader=reader,
        registry=_registry(),
        store=store,
        journal=InMemoryJournal(),
    )
    identity = IdentityService(forecast, clock=lambda: NOW)
    predict = TtPredictionService(
        reader=reader,
        store=store,
        forecast=forecast,
        pipeline=pipeline,
        identity=identity,
        clock=lambda: NOW,
    )
    settle = TtSettlementService(
        reader=reader,
        store=store,
        forecast=forecast,
        clock=lambda: NOW,
    )
    return {
        "store": store,
        "forecast": forecast,
        "pipeline": pipeline,
        "predict": predict,
        "settle": settle,
    }


def _registry():
    from defend_markets.strategies import build_default_registry

    return build_default_registry()


def seed_result(store: InMemoryStore, *, winner: str = ALICE) -> None:
    home_wins = winner == ALICE
    store.seed_tt_results(
        [
            {
                "result_id": 1,
                "event_key": EVENT,
                "league_key": "table_tennis",
                "home_participant_key": ALICE,
                "away_participant_key": BOB,
                "home_score": 3 if home_wins else 1,
                "away_score": 1 if home_wins else 3,
                "completed_at": NOW,
                "source_provider": "the_odds_api",
            }
        ]
    )


def make_opportunity_prediction(forecast: InMemoryForecastStore, *, decision: str = "OPPORTUNITY"):
    from defend_markets.forecast import PredictionRecord
    from uuid import uuid4

    record = PredictionRecord(
        prediction_id=uuid4(),
        created_ts=NOW,
        event_key=EVENT,
        sport_key="table_tennis",
        player_a_name_at_prediction="Player A",
        player_b_name_at_prediction="Player B",
        decision=decision,
        consensus_p_a=Decimal("0.55"),
        consensus_p_b=Decimal("0.45"),
        best_price_a=Decimal("1.90"),
        best_price_b=Decimal("2.35"),
    )
    return forecast.insert_prediction(record)


class TestPredictService:
    def test_result_known_blocks_prediction(self):
        stack = make_stack(make_reader())
        seed_result(stack["store"])
        outcome = stack["predict"].predict(EVENT)
        assert outcome.blocked
        assert outcome.blocked_reason == "result_known"
        assert stack["forecast"].catalog_predictions() == []

    def test_unknown_event_blocks(self):
        stack = make_stack(make_reader())
        outcome = stack["predict"].predict("tt-unknown")
        assert outcome.blocked
        assert outcome.blocked_reason == "event_not_found"

    def test_ambiguous_identity_forces_no_action_without_journal(self):
        reader = FakeSportsReader()
        reader.set_tt_event_participants(EVENT, ["Chris Jones", "Player B"])
        reader._quotes[(EVENT, "match_winner")] = [
            quote("book-a", "home", "1.85", hour=11),
            quote("book-a", "away", "2.35", hour=11),
        ]
        stack = make_stack(reader)
        forecast = stack["forecast"]
        forecast.insert_participant(
            canonical_name="Chris Jones",
            normalized_name="chris jones",
            state="CONFIRMED",
            seen_at=NOW,
        )
        forecast.insert_participant(
            canonical_name="Chris Jones II",
            normalized_name="chris jones",
            state="CONFIRMED",
            seen_at=NOW,
        )
        outcome = stack["predict"].predict(EVENT)
        assert outcome.decision == "NO_ACTION"
        assert "low_identity_confidence" in outcome.reason_codes
        assert outcome.journal_ref is None
        rows = stack["forecast"].predictions_for_event(EVENT)
        assert rows
        assert rows[0]["identity_state"] == "AMBIGUOUS"

    def test_happy_path_records_prediction_snapshot_and_shadow(self):
        stack = make_stack(make_reader())
        outcome = stack["predict"].predict(EVENT)
        assert not outcome.blocked
        rows = stack["forecast"].predictions_for_event(EVENT)
        assert len(rows) == 1
        row = rows[0]
        assert row["event_key"] == EVENT
        assert row["player_a_name_at_prediction"] == "Player A"
        assert row["model_id"] == "tt_elo"
        assert row["market_method_version"] == "market_state.v1"
        assert row["book_count"] == 2
        assert row["decision"] in ("OPPORTUNITY", "NO_ACTION")
        shadows = stack["forecast"].shadows_for_event(EVENT)
        assert len(shadows) == 1
        assert shadows[0]["prediction_id"] == row["prediction_id"]

    def test_falls_back_to_quote_names_without_participant_source(self):
        reader = FakeSportsReader()
        reader.set_tt_event_participants(EVENT, [])
        reader._quotes[(EVENT, "match_winner")] = [
            quote("book-a", "home", "1.85", hour=11),
            quote("book-a", "away", "2.35", hour=11),
        ]
        stack = make_stack(reader)
        outcome = stack["predict"].predict(EVENT)
        assert not outcome.blocked


class TestSettleService:
    def test_settles_correct_prediction_and_is_idempotent(self):
        stack = make_stack(make_reader())
        prediction_id = make_opportunity_prediction(stack["forecast"])
        seed_result(stack["store"], winner=ALICE)
        outcomes = stack["settle"].settle(EVENT)
        assert len(outcomes) == 1
        assert outcomes[0].settled
        assert outcomes[0].correct is True
        rows = stack["forecast"].settlements_for_prediction(prediction_id)
        assert len(rows) == 1
        assert rows[0]["paper_pnl_gross"] == Decimal("0.90")
        again = stack["settle"].settle(EVENT)
        assert again[0].reason == "already_settled"
        assert len(stack["forecast"].settlements_for_prediction(prediction_id)) == 1

    def test_settles_incorrect_prediction_negative_pnl(self):
        stack = make_stack(make_reader())
        make_opportunity_prediction(stack["forecast"])
        seed_result(stack["store"], winner=BOB)
        outcomes = stack["settle"].settle(EVENT)
        assert outcomes[0].correct is False
        assert outcomes[0].raw_ref == f"{EVENT}:1"
        rows = stack["forecast"].catalog_settlements()
        assert rows[0]["paper_pnl_gross"] == Decimal("-1")

    def test_unmapped_prediction_left_open(self):
        stack = make_stack(make_reader())
        prediction_id = make_opportunity_prediction(stack["forecast"])
        store = stack["store"]
        store.seed_tt_results(
            [
                {
                    "result_id": 1,
                    "event_key": EVENT,
                    "league_key": "table_tennis",
                    "home_participant_key": "table_tennis:someone-else",
                    "away_participant_key": BOB,
                    "home_score": 3,
                    "away_score": 1,
                    "completed_at": NOW,
                    "source_provider": "the_odds_api",
                }
            ]
        )
        outcomes = stack["settle"].settle(EVENT)
        assert outcomes[0].reason == "unmapped"
        assert stack["forecast"].settlements_for_prediction(prediction_id) == []

    def test_closing_prices_used_for_clv(self):
        stack = make_stack(make_reader())
        prediction_id = make_opportunity_prediction(stack["forecast"])
        seed_result(stack["store"], winner=ALICE)
        reader = stack["pipeline"]._reader
        reader.set_odds_history(
            EVENT,
            "match_winner",
            [
                quote("book-a", "home", "1.80", hour=11),
                quote("book-a", "away", "2.40", hour=11),
            ],
        )
        outcomes = stack["settle"].settle(EVENT)
        assert outcomes[0].correct is True
        rows = stack["forecast"].settlements_for_prediction(prediction_id)
        assert rows[0]["closing_market_p"] is not None
        assert rows[0]["clv"] is not None

    def test_no_result_returns_empty(self):
        stack = make_stack(make_reader())
        assert stack["settle"].settle(EVENT) == []

    def test_no_action_predictions_are_not_settled(self):
        stack = make_stack(make_reader())
        make_opportunity_prediction(stack["forecast"], decision="NO_ACTION")
        seed_result(stack["store"], winner=ALICE)
        outcomes = stack["settle"].settle(EVENT)
        assert outcomes == []
        assert stack["forecast"].catalog_settlements() == []