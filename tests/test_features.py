from __future__ import annotations

from datetime import datetime, timezone

from defend_markets.domain import ProvenanceStamp
from defend_markets.features import (
    FEATURE_CODE_VERSION,
    FEATURE_SCHEMA_VERSION,
    build_feature_snapshot,
)
from defend_markets.sports_adapter import SportsSelectionQuote
from decimal import Decimal

CUTOFF = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)


def result(
    event_key: str,
    home: str,
    away: str,
    home_score: int,
    away_score: int,
    completed_at: datetime,
) -> dict[str, object]:
    return {
        "event_key": event_key,
        "home_participant_key": home,
        "away_participant_key": away,
        "home_score": home_score,
        "away_score": away_score,
        "completed_at": completed_at,
        "league_key": "table_tennis",
    }


def quote(selection: str, odds: str, observed_at: datetime) -> SportsSelectionQuote:
    return SportsSelectionQuote(
        selection_key=selection,
        display_name=selection,
        decimal_odds=Decimal(odds),
        provenance=ProvenanceStamp(
            source_key="book-a",
            observed_at=observed_at,
            received_at=observed_at,
            raw_ref=f"raw-{selection}-{observed_at.isoformat()}",
            normalization_version=None,
        ),
        selection_id=f"sel-{selection}",
    )


def test_snapshot_excludes_future_results():
    history = [
        result("past-1", "table_tennis:alice", "table_tennis:bob", 3, 1, datetime(2026, 8, 14, 10, 0, tzinfo=timezone.utc)),
        result("future-1", "table_tennis:alice", "table_tennis:bob", 3, 2, datetime(2026, 8, 16, 10, 0, tzinfo=timezone.utc)),
    ]
    snapshot = build_feature_snapshot(
        event_key="tt-live",
        prediction_ts=CUTOFF,
        player_a_key="table_tennis:alice",
        player_a_name="Alice",
        player_a_identity_state="CONFIRMED",
        player_b_key="table_tennis:bob",
        player_b_name="Bob",
        player_b_identity_state="CONFIRMED",
        history_rows=history,
        quotes=[],
        market_state_payload={},
        source_observation_ids=[],
    )
    assert snapshot.player_a.matches == 1
    assert snapshot.data_quality["history_matches"] == 1


def test_snapshot_excludes_the_predicted_event_itself():
    history = [
        result("tt-live", "table_tennis:alice", "table_tennis:bob", 3, 1, datetime(2026, 8, 14, 10, 0, tzinfo=timezone.utc)),
        result("past-1", "table_tennis:alice", "table_tennis:bob", 3, 1, datetime(2026, 8, 14, 10, 0, tzinfo=timezone.utc)),
    ]
    snapshot = build_feature_snapshot(
        event_key="tt-live",
        prediction_ts=CUTOFF,
        player_a_key="table_tennis:alice",
        player_a_name="Alice",
        player_a_identity_state="CONFIRMED",
        player_b_key="table_tennis:bob",
        player_b_name="Bob",
        player_b_identity_state="CONFIRMED",
        history_rows=history,
        quotes=[],
        market_state_payload={},
        source_observation_ids=[],
    )
    assert snapshot.player_a.matches == 1


def test_snapshot_excludes_future_odds():
    quotes = [quote("home", "1.85", datetime(2026, 8, 16, 10, 0, tzinfo=timezone.utc))]
    snapshot = build_feature_snapshot(
        event_key="tt-live",
        prediction_ts=CUTOFF,
        player_a_key="table_tennis:alice",
        player_a_name="Alice",
        player_a_identity_state="CONFIRMED",
        player_b_key="table_tennis:bob",
        player_b_name="Bob",
        player_b_identity_state="CONFIRMED",
        history_rows=[],
        quotes=quotes,
        market_state_payload={},
        source_observation_ids=[],
    )
    assert "odds" in snapshot.data_quality["missing_fields"]


def test_snapshot_tracks_versions_and_source_ids():
    snapshot = build_feature_snapshot(
        event_key="tt-live",
        prediction_ts=CUTOFF,
        player_a_key="table_tennis:alice",
        player_a_name="Alice",
        player_a_identity_state="CONFIRMED",
        player_b_key="table_tennis:bob",
        player_b_name="Bob",
        player_b_identity_state="CONFIRMED",
        history_rows=[
            result("past-1", "table_tennis:alice", "table_tennis:bob", 3, 1, datetime(2026, 8, 14, 10, 0, tzinfo=timezone.utc))
        ],
        quotes=[quote("home", "1.85", CUTOFF)],
        market_state_payload={"consensus_p_home": "0.55"},
        source_observation_ids=["raw-1", "raw-2"],
    )
    payload = snapshot.payload()
    assert snapshot.feature_schema_version == FEATURE_SCHEMA_VERSION
    assert snapshot.feature_code_version == FEATURE_CODE_VERSION
    assert payload["market"] == {"consensus_p_home": "0.55"}
    assert snapshot.source_observation_ids == ("raw-home-2026-08-15T12:00:00+00:00",)


def test_snapshot_recent_form_and_h2h():
    history = [
        result("p1", "table_tennis:alice", "table_tennis:bob", 3, 0, datetime(2026, 8, 14, 10, 0, tzinfo=timezone.utc)),
        result("p2", "table_tennis:alice", "table_tennis:carol", 3, 2, datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)),
        result("p3", "table_tennis:alice", "table_tennis:dave", 0, 3, datetime(2026, 8, 14, 14, 0, tzinfo=timezone.utc)),
    ]
    snapshot = build_feature_snapshot(
        event_key="tt-live",
        prediction_ts=CUTOFF,
        player_a_key="table_tennis:alice",
        player_a_name="Alice",
        player_a_identity_state="CONFIRMED",
        player_b_key="table_tennis:bob",
        player_b_name="Bob",
        player_b_identity_state="CONFIRMED",
        history_rows=history,
        quotes=[],
        market_state_payload={},
        source_observation_ids=[],
    )
    assert snapshot.player_a.matches == 3
    assert snapshot.player_a.wins == 2
    assert snapshot.player_a.h2h_matches == 1
    assert snapshot.player_a.h2h_wins == 1
    assert snapshot.player_a.matches_24h == 2
    assert snapshot.player_a.matches_48h == 3
    assert snapshot.player_a.hours_since_previous == Decimal("2")


def test_snapshot_same_day_matches_counted():
    history = [
        result("p1", "table_tennis:alice", "table_tennis:bob", 3, 0, datetime(2026, 8, 15, 8, 0, tzinfo=timezone.utc)),
        result("p2", "table_tennis:alice", "table_tennis:carol", 3, 0, datetime(2026, 8, 15, 10, 0, tzinfo=timezone.utc)),
    ]
    snapshot = build_feature_snapshot(
        event_key="tt-live",
        prediction_ts=CUTOFF,
        player_a_key="table_tennis:alice",
        player_a_name="Alice",
        player_a_identity_state="CONFIRMED",
        player_b_key="table_tennis:bob",
        player_b_name="Bob",
        player_b_identity_state="CONFIRMED",
        history_rows=history,
        quotes=[],
        market_state_payload={},
        source_observation_ids=[],
    )
    assert snapshot.player_a.same_day_matches == 2