"""M4.8.2 decision board assembler tests (P2-P6, P31)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from defend_markets.quant.board import (
    ACTIONABLE,
    CONFLICT,
    NO_COMPARISON,
    NO_MODEL,
    UNMATCHED,
    LiveTTBoardService,
    classify_actionability,
)
from defend_markets.quant.store import InMemoryQuantStore

_NOW = datetime.now(timezone.utc)


def _seed_hardrock(store, event, p1, p2, *, p1_american=-185, p2_american=130, p1_dec="1.541", p2_dec="2.300"):
    store.insert_hardrock_quote({
        "canonical_event_id": event, "data_provider": "owls_insight", "sportsbook": "hardrock_bet", "state": "fl",
        "provider_event_id": event, "market_family": "MATCH_WINNER_2WAY", "period": "FULL_MATCH", "line": None,
        "selection": p1, "selection_side": "PARTICIPANT_A", "root_idx": 55, "ladder_snapshot_id": 1,
        "american_odds": p1_american, "decimal_odds": p1_dec, "implied_probability": None,
        "observed_at": _NOW, "raw_payload_hash": None,
    })
    store.insert_hardrock_quote({
        "canonical_event_id": event, "data_provider": "owls_insight", "sportsbook": "hardrock_bet", "state": "fl",
        "provider_event_id": event, "market_family": "MATCH_WINNER_2WAY", "period": "FULL_MATCH", "line": None,
        "selection": p2, "selection_side": "PARTICIPANT_B", "root_idx": 78, "ladder_snapshot_id": 1,
        "american_odds": p2_american, "decimal_odds": p2_dec, "implied_probability": None,
        "observed_at": _NOW, "raw_payload_hash": None,
    })


def _seed_bet365(store, event, p1, p2, *, p1_dec="1.90", p2_dec="1.95", p1_side="PARTICIPANT_A"):
    store._bet365_observations = [
        {"canonical_event_id": event, "provider_event_id": f"b-{event}", "selection_side": p1_side,
         "selection": p1, "decimal_odds": p1_dec, "observed_at": _NOW - timedelta(seconds=30)},
        {"canonical_event_id": event, "provider_event_id": f"b-{event}", "selection_side": "PARTICIPANT_B",
         "selection": p2, "decimal_odds": p2_dec, "observed_at": _NOW - timedelta(seconds=30)},
    ]


def _seed_m5(store, event, p_a=0.62):
    store.register_model(model_id="M5_REGULARIZED_LOGISTIC", model_version="v1", role="CHAMPION", stage="CHAMPION")
    store.upsert_official_prediction({
        "canonical_event_id": event, "model_id": "M5_REGULARIZED_LOGISTIC", "model_version": "v1",
        "prediction_id": f"m-{event}", "prediction_role": "M5_FORWARD",
        "generated_at": _NOW - timedelta(hours=1), "commence_at": _NOW + timedelta(hours=1),
        "probability_a": p_a, "policy_version": 1,
    })


def _seed_mapping(store, event, mode="KEY_EXACT"):
    store.upsert_provider_event_mapping({
        "provider": "owls_insight", "native_event_id": event, "canonical_event_id": event,
        "identity_mode": mode, "confidence": "HIGH",
    })


class TestClassifyActionability:
    def test_full_actionable(self):
        state, reasons = classify_actionability(
            has_model=True, has_hardrock_pair=True, hardrock_fresh=True,
            has_bet365=True, bet365_valid=True, match_state="KEY_EXACT", orientation="CANONICAL", skew_ok=True,
        )
        assert state == ACTIONABLE

    def test_no_model(self):
        state, _ = classify_actionability(
            has_model=False, has_hardrock_pair=True, hardrock_fresh=True,
            has_bet365=True, bet365_valid=True, match_state="KEY_EXACT", orientation="CANONICAL", skew_ok=True,
        )
        assert state == NO_MODEL

    def test_no_comparison(self):
        state, _ = classify_actionability(
            has_model=True, has_hardrock_pair=True, hardrock_fresh=True,
            has_bet365=False, bet365_valid=False, match_state="KEY_EXACT", orientation="CANONICAL", skew_ok=True,
        )
        assert state == NO_COMPARISON

    def test_ambiguous_not_actionable(self):
        state, _ = classify_actionability(
            has_model=True, has_hardrock_pair=True, hardrock_fresh=True,
            has_bet365=True, bet365_valid=True, match_state="AMBIGUOUS", orientation="CANONICAL", skew_ok=True,
        )
        assert state == "AMBIGUOUS"

    def test_conflict_not_actionable(self):
        state, _ = classify_actionability(
            has_model=True, has_hardrock_pair=True, hardrock_fresh=True,
            has_bet365=True, bet365_valid=True, match_state="CONFLICT", orientation="CANONICAL", skew_ok=True,
        )
        assert state == CONFLICT

    def test_unmatched(self):
        state, _ = classify_actionability(
            has_model=True, has_hardrock_pair=True, hardrock_fresh=True,
            has_bet365=True, bet365_valid=True, match_state="UNMATCHED", orientation="CANONICAL", skew_ok=True,
        )
        assert state == UNMATCHED


class TestBoardAssembler:
    def test_board_contract(self):
        store = InMemoryQuantStore()
        _seed_hardrock(store, "ev1", "Alice", "Bob")
        _seed_bet365(store, "ev1", "Alice", "Bob")
        _seed_m5(store, "ev1")
        service = LiveTTBoardService(store)
        board = service.board()
        assert board["count"] >= 1
        e = board["events"][0]
        assert e["canonical_event_id"] == "ev1"
        assert e["participant_1"] == "Alice"
        assert e["participant_2"] == "Bob"
        assert e["hardrock"]["side_1"]["american"] == -185
        assert e["m5"]["p1"] is not None
        # no-vig + consensus present
        assert e["hardrock"]["no_vig_pair"] is not None
        assert e["consensus_no_vig_p1"] is not None
        assert e["edge_hr"] is not None

    def test_unmatched_keeps_provider_local_identity(self):
        store = InMemoryQuantStore()
        _seed_hardrock(store, "hardrock:evX", "Carol", "Dave")
        service = LiveTTBoardService(store)
        board = service.board()
        assert board["events"][0]["canonical_event_id"] == "hardrock:evX"
        assert board["events"][0]["cross_book_match_state"] == "UNMATCHED"

    def test_no_model_shows_no_model_state(self):
        store = InMemoryQuantStore()
        _seed_hardrock(store, "ev1", "Alice", "Bob")
        _seed_mapping(store, "ev1", "KEY_EXACT")
        service = LiveTTBoardService(store)
        e = service.board()["events"][0]
        assert e["m5"]["p1"] is None
        assert e["actionability"] == NO_MODEL

    def test_no_bet365_shows_no_comparison(self):
        store = InMemoryQuantStore()
        _seed_hardrock(store, "ev1", "Alice", "Bob")
        _seed_mapping(store, "ev1", "KEY_EXACT")
        _seed_m5(store, "ev1")
        service = LiveTTBoardService(store)
        e = service.board()["events"][0]
        assert e["bet365"] is None
        assert e["actionability"] == NO_COMPARISON

    def test_reversed_orientation_maps_correctly(self):
        store = InMemoryQuantStore()
        _seed_hardrock(store, "ev1", "Alice", "Bob")
        _seed_mapping(store, "ev1", "KEY_EXACT")
        # Bet365 lists Bob as side A, Alice as side B (reversed)
        _seed_bet365(store, "ev1", "Bob", "Alice", p1_side="PARTICIPANT_A")
        _seed_m5(store, "ev1")
        service = LiveTTBoardService(store)
        e = service.board()["events"][0]
        # Bet365 view must map to canonical Alice/Bob, not provider sides
        assert e["bet365"] is not None
        assert e["bet365"]["orientation"] == "REVERSED"

    def test_hardrock_history_bounded(self):
        store = InMemoryQuantStore()
        _seed_hardrock(store, "ev1", "Alice", "Bob")
        service = LiveTTBoardService(store)
        history = service.hardrock_history("ev1", limit=10)
        assert history["canonical_event_id"] == "ev1"
        assert len(history["observations"]) <= 10

    def test_event_detail_returns_event(self):
        store = InMemoryQuantStore()
        _seed_hardrock(store, "ev1", "Alice", "Bob")
        _seed_m5(store, "ev1")
        service = LiveTTBoardService(store)
        detail = service.event_detail("ev1")
        assert detail is not None
        assert detail["canonical_event_id"] == "ev1"


class TestConsensusIsNoVig:
    def test_consensus_mean_of_no_vig(self):
        store = InMemoryQuantStore()
        _seed_hardrock(store, "ev1", "Alice", "Bob", p1_dec="1.541", p2_dec="2.300")
        _seed_bet365(store, "ev1", "Alice", "Bob", p1_dec="1.90", p2_dec="1.95")
        _seed_m5(store, "ev1")
        service = LiveTTBoardService(store)
        e = service.board()["events"][0]
        # consensus = mean of Hard Rock no-vig p1 and Bet365 no-vig p1
        # HR raw implied: 1/1.541=0.6489, 1/2.3=0.4348, overround=1.0837
        # HR no-vig p1 = 0.6489/1.0837 = 0.5988
        # Bet365 raw: 1/1.9=0.5263, 1/1.95=0.5128, overround=1.0391, no-vig p1=0.5065
        # consensus ~ (0.5988 + 0.5065)/2 = 0.5526
        consensus = float(e["consensus_no_vig_p1"])
        assert 0.54 < consensus < 0.56
        # raw implied p1 = 1/1.541 = 0.6489; consensus no-vig is lower (must NOT equal raw avg)
        assert consensus < 0.60
