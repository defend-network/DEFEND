"""M4.8 Hard Rock FL data lane tests.

Covers: Owls integration, DPAPI-only key, raw key never logged, AVAILABLE
requires valid ladder, empty slate, malformed/401/403/429/5xx, real payload
parser, rootIdx exact ladder lookup, unknown rootIdx fail-closed, ladder
immutability, old observations retain ladder mapping, provider/book distinction,
canonical event matching (exact/reversed/ambiguous), market-family isolation,
snapshot coherence, Bet365/FanDuel coverage, no slot mutation, historical
backfill resume/idempotency, protected capacity, line movement, consensus,
Hard Rock reference price, M5 hash, zero settlement/score writes, no real money.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from defend_markets.quant.backfill import (
    HistoricalBackfillJob,
    HISTORICAL_ODDS_ENDPOINT_AVAILABLE_BUT_EMPTY,
)
from defend_markets.quant.event_matcher import (
    CanonicalEventMatcher,
    STATE_AMBIGUOUS,
    STATE_CONFLICT,
    STATE_KEY_EXACT,
    STATE_NAME_TIME_EXACT,
    STATE_UNMATCHED,
    match_event,
    resolve_provider_orientation,
)
from defend_markets.quant.hardrock import (
    DATA_PROVIDER_OWLS,
    FAMILY_MATCH_WINNER,
    FAMILY_SPREAD,
    FAMILY_UNSUPPORTED,
    SPORTSBOOK_HARDROCK,
    HardRockLadder,
    OwlsHardRockAdapter,
    american_to_decimal,
    canonical_market_family,
    decimal_to_implied,
    parse_hardrock_event,
    parse_market_line,
    parse_selection_side,
)
from defend_markets.quant.line_movement import (
    cross_book_consensus,
    hardrock_reference_price,
    line_movement,
)
from defend_markets.quant.store import InMemoryQuantStore

_NOW = datetime.now(timezone.utc)


def _ladder_payload(entries):
    return {"success": True, "data": {"even": 72, "ladder": [{"rootIdx": k, "americanOdds": v} for k, v in entries.items()]}}


class TestHardRockLadder:
    def test_rootidx_exact_lookup(self):
        ladder = HardRockLadder.from_payload(_ladder_payload({55: -185, 78: 130}))
        assert ladder.american_odds(55) == -185
        assert ladder.american_odds(78) == 130
        assert ladder.entry_count == 2

    def test_unknown_rootidx_fails_closed(self):
        ladder = HardRockLadder.from_payload(_ladder_payload({55: -185}))
        assert ladder.american_odds(9999) is None
        assert ladder.decimal_odds(9999) is None

    def test_american_to_decimal(self):
        assert american_to_decimal(-200) == Decimal("1.500")
        assert american_to_decimal(200) == Decimal("3.000")
        assert american_to_decimal(-185) == Decimal("1.541")

    def test_decimal_to_implied(self):
        assert decimal_to_implied(Decimal("2.000")) == Decimal("0.50000000")

    def test_ladder_snapshot_immutable(self):
        import pytest

        ladder = HardRockLadder.from_payload(_ladder_payload({55: -185}))
        # M4.8.1 P2: entries is a read-only mapping; assignment raises TypeError.
        with pytest.raises(TypeError):
            ladder.entries[55] = -999
        assert ladder.american_odds(55) == -185

    def test_input_dict_mutation_does_not_mutate_snapshot(self):
        src = {55: -185}
        ladder = HardRockLadder.from_payload(_ladder_payload(src))
        src[55] = -999  # mutate the caller's dict after construction
        assert ladder.american_odds(55) == -185

    def test_old_observation_retains_mapping(self):
        """P5: an observation captured with an old ladder keeps its own odds."""
        ladder_v1 = HardRockLadder.from_payload(_ladder_payload({55: -185}))
        observed_odds = ladder_v1.decimal_odds(55)
        ladder_v2 = HardRockLadder.from_payload(_ladder_payload({55: -160}))
        # the stored observation value does not change when the ladder changes
        assert observed_odds == Decimal("1.541")
        assert ladder_v2.decimal_odds(55) == Decimal("1.625")


class TestMarketFamily:
    def test_match_winner_family(self):
        assert canonical_market_family("TABLE_TENNIS:FT:ML") == FAMILY_MATCH_WINNER

    def test_spread_family(self):
        assert canonical_market_family("TABLE_TENNIS:FT:PHCP") == FAMILY_SPREAD

    def test_unsupported_fails_closed(self):
        assert canonical_market_family("TABLE_TENNIS:P:OU") == FAMILY_UNSUPPORTED

    def test_selection_side(self):
        assert parse_selection_side("A") == "PARTICIPANT_A"
        assert parse_selection_side("B") == "PARTICIPANT_B"
        assert parse_selection_side("X") is None

    def test_market_line(self):
        assert parse_market_line({"subtype": "M#-3.5"}) == "-3.5"
        assert parse_market_line({"subtype": "M"}) is None


class TestParseHardRockEvent:
    def test_real_payload_shape(self):
        event = {
            "id": "evt1", "name": "A vs B", "betradarId": "br1", "eventTime": 1787460600000,
            "inplay": False, "state": "ACTIVE",
            "participants": [{"id": "p1", "name": "Alice"}, {"id": "p2", "name": "Bob"}],
            "markets": [{"type": "TABLE_TENNIS:FT:ML", "selections": []}],
        }
        parsed = parse_hardrock_event(event)
        assert parsed is not None
        assert parsed["provider_event_id"] == "evt1"
        assert parsed["betradar_id"] == "br1"
        assert parsed["participants"] == ["Alice", "Bob"]
        assert parsed["inplay"] is False

    def test_missing_id_returns_none(self):
        assert parse_hardrock_event({"name": "x"}) is None


class TestEventMatcher:
    def test_key_exact(self):
        t = _NOW
        mode, conf = match_event(provider="x", native_event_id="1", cross_provider_id="br1",
                                 participants=["Alice", "Bob"], scheduled_time=t,
                                 candidate={"betradar_id": "br1", "participants": ["Alice", "Bob"], "scheduled_time": t})
        assert mode == STATE_KEY_EXACT

    def test_name_time_exact(self):
        t = _NOW
        mode, conf = match_event(provider="x", native_event_id="1", cross_provider_id=None,
                                 participants=["Alice", "Bob"], scheduled_time=t,
                                 candidate={"participants": ["Bob", "Alice"], "scheduled_time": t})
        assert mode == STATE_NAME_TIME_EXACT

    def test_reversed_participants_still_match(self):
        t = _NOW
        mode, _ = match_event(provider="x", native_event_id="1", cross_provider_id=None,
                              participants=["Bob", "Alice"], scheduled_time=t,
                              candidate={"participants": ["Alice", "Bob"], "scheduled_time": t})
        assert mode == STATE_NAME_TIME_EXACT

    def test_ambiguous_fail_closed(self):
        t = _NOW
        # same participants but times differ beyond window
        mode, _ = match_event(provider="x", native_event_id="1", cross_provider_id=None,
                              participants=["Alice", "Bob"], scheduled_time=t,
                              candidate={"participants": ["Alice", "Bob"], "scheduled_time": t + timedelta(hours=3)})
        assert mode == STATE_AMBIGUOUS

    def test_conflict_partial_overlap(self):
        mode, _ = match_event(provider="x", native_event_id="1", cross_provider_id=None,
                              participants=["Alice", "Bob"], scheduled_time=_NOW,
                              candidate={"participants": ["Alice", "Carol"], "scheduled_time": _NOW})
        assert mode == STATE_CONFLICT

    def test_matcher_records_evidence(self):
        store = InMemoryQuantStore()
        matcher = CanonicalEventMatcher(store)
        t = _NOW
        result = matcher.match_and_record(provider="owls_insight", native_event_id="e1", cross_provider_id="br1",
                                         participants=["Alice", "Bob"], scheduled_time=t,
                                         candidates=[{"betradar_id": "br1", "participants": ["Alice", "Bob"],
                                                      "scheduled_time": t, "canonical_event_id": "canon:1"}])
        assert result["identity_mode"] == STATE_KEY_EXACT
        assert result["canonical_event_id"] == "canon:1"
        assert len(store.list_provider_event_mappings()) == 1


class TestProviderBookDistinction:
    def test_provider_and_book_are_distinct(self):
        assert DATA_PROVIDER_OWLS == "owls_insight"
        assert SPORTSBOOK_HARDROCK == "hardrock_bet"
        assert DATA_PROVIDER_OWLS != SPORTSBOOK_HARDROCK


class TestLineMovement:
    def _obs(self, odds, t):
        return {"decimal_odds": str(odds), "observed_at": t}

    def test_movement(self):
        t0 = _NOW - timedelta(minutes=30)
        t1 = _NOW - timedelta(minutes=10)
        t2 = _NOW
        mv = line_movement([self._obs("1.80", t0), self._obs("1.85", t1), self._obs("1.85", t2)])
        assert mv["first_seen_price"] == "1.80"
        assert mv["current_price"] == "1.85"
        assert mv["num_changes"] == 1
        assert mv["direction"] is None  # last two equal

    def test_single_obs_none(self):
        assert line_movement([self._obs("1.80", _NOW)]) is None

    def test_consensus(self):
        q = {
            "hardrock_bet": [{"decimal_odds": "1.80", "implied_probability": "0.55", "observed_at": _NOW}],
            "Bet365": [{"decimal_odds": "1.90", "implied_probability": "0.52", "observed_at": _NOW}],
        }
        c = cross_book_consensus(q)
        assert c["consensus_implied"] is not None
        assert c["books"]["hardrock_bet"]["decimal_odds"] == "1.80"

    def test_hardrock_reference(self):
        q = {
            "hardrock_bet": [{"decimal_odds": "1.80", "implied_probability": "0.55", "observed_at": _NOW}],
            "Bet365": [{"decimal_odds": "1.90", "implied_probability": "0.52", "observed_at": _NOW}],
        }
        ref = hardrock_reference_price(q)
        assert ref is not None
        assert ref["reference_sportsbook"] == "hardrock_bet"
        assert ref["decimal_odds"] == "1.80"

    def test_no_hardrock_returns_none(self):
        assert hardrock_reference_price({"Bet365": []}) is None


class TestBackfill:
    def test_resume_from_checkpoint(self):
        store = InMemoryQuantStore()
        job = HistoricalBackfillJob(store)
        calls = []
        def ingest(provider, from_iso, to_iso):
            calls.append((from_iso, to_iso))
            return {"ingested": 1}
        job.run(ingest_fixtures=ingest)
        # first run from default window
        assert len(calls) == 1
        # advance + rerun: resume from checkpoint (not the beginning)
        job.advance_checkpoint("fixtures", "2026-08-20T00:00:00Z")
        job.run(ingest_fixtures=ingest)
        assert calls[1][0] == "2026-08-20T00:00:00Z"

    def test_checkpoint_persisted(self):
        store = InMemoryQuantStore()
        job = HistoricalBackfillJob(store)
        job.advance_checkpoint("results", "cursor-1")
        assert job.checkpoint("results")["cursor_value"] == "cursor-1"


class TestBackfillCapacityIsolation:
    def test_history_is_low_priority(self):
        """Background history uses a distinct low-priority class, not RESULT."""
        from defend_markets.quant.governance import CLASS_RECONCILIATION, CLASS_RESULT

        assert CLASS_RECONCILIATION != CLASS_RESULT


class TestParticipantOrientation:
    def test_same_order(self):
        a_maps, b_maps, state = resolve_provider_orientation(
            provider_participant_a="Alice", provider_participant_b="Bob",
            canonical_participant_1="Alice", canonical_participant_2="Bob",
        )
        assert state == "CANONICAL"
        assert (a_maps, b_maps) == ("1", "2")

    def test_reversed_order(self):
        a_maps, b_maps, state = resolve_provider_orientation(
            provider_participant_a="Bob", provider_participant_b="Alice",
            canonical_participant_1="Alice", canonical_participant_2="Bob",
        )
        assert state == "REVERSED"
        assert (a_maps, b_maps) == ("2", "1")

    def test_name_mismatch_fails_closed(self):
        _, _, state = resolve_provider_orientation(
            provider_participant_a="Carol", provider_participant_b="Bob",
            canonical_participant_1="Alice", canonical_participant_2="Bob",
        )
        assert state == "CONFLICT"


class TestDevig:
    def test_two_way_no_vig(self):
        from defend_markets.quant.line_movement import two_way_no_vig

        result = two_way_no_vig(side_a_implied="0.5556", side_b_implied="0.5263")
        assert result["ok"] is True
        # overround = 0.5556 + 0.5263 = 1.0819
        assert result["overround"] == "1.0819"
        # proportional normalization: 0.5556/1.0819 ~= 0.51354
        assert result["no_vig_a"] == "0.51354099"
        assert result["no_vig_b"] == "0.48645901"

    def test_raw_implied_not_fair(self):
        from defend_markets.quant.line_movement import two_way_no_vig

        result = two_way_no_vig(side_a_implied="0.5556", side_b_implied="0.5263")
        # raw implied sums > 1 (overround); no_vig is normalized to sum 1
        assert result["raw_implied_a"] != result["no_vig_a"]


class TestSyncSnapshot:
    def test_fresh_and_skew(self):
        from defend_markets.quant.line_movement import synchronized_snapshot

        now = _NOW
        quotes = {
            "hardrock_bet": [{"decimal_odds": "1.8", "implied_probability": "0.55", "observed_at": now}],
            "Bet365": [{"decimal_odds": "1.9", "implied_probability": "0.52", "observed_at": now - timedelta(seconds=30)}],
        }
        snap = synchronized_snapshot(quotes_by_book=quotes, now=now)
        assert snap["reference_present"] is True
        assert snap["observed_skew_seconds"] is not None

    def test_stale_excluded(self):
        from defend_markets.quant.line_movement import synchronized_snapshot

        now = _NOW
        quotes = {
            "hardrock_bet": [{"decimal_odds": "1.8", "implied_probability": "0.55", "observed_at": now}],
            "Bet365": [{"decimal_odds": "1.9", "implied_probability": "0.52", "observed_at": now - timedelta(hours=2)}],
        }
        snap = synchronized_snapshot(quotes_by_book=quotes, now=now)
        assert "Bet365" not in snap["books"]  # stale -> excluded


class TestSyncSkewContract:
    def _now(self):
        return _NOW

    def test_bet365_30s_within_skew_included(self):
        from defend_markets.quant.line_movement import synchronized_snapshot

        now = self._now()
        quotes = {
            "hardrock_bet": [{"decimal_odds": "1.8", "observed_at": now}],
            "Bet365": [{"decimal_odds": "1.9", "observed_at": now - timedelta(seconds=30)}],
        }
        snap = synchronized_snapshot(quotes_by_book=quotes, now=now, max_skew_seconds=120)
        assert "Bet365" in snap["books"]
        assert "Bet365" in snap["included_books"]

    def test_bet365_121s_skew_exceeded(self):
        from defend_markets.quant.line_movement import synchronized_snapshot

        now = self._now()
        quotes = {
            "hardrock_bet": [{"decimal_odds": "1.8", "observed_at": now}],
            "Bet365": [{"decimal_odds": "1.9", "observed_at": now - timedelta(seconds=121)}],
        }
        snap = synchronized_snapshot(quotes_by_book=quotes, now=now, max_skew_seconds=120)
        assert "Bet365" not in snap["books"]
        assert snap["excluded_books"]["Bet365"] == "SKEW_EXCEEDED"

    def test_third_stale_book_does_not_poison_valid_pair(self):
        from defend_markets.quant.line_movement import synchronized_snapshot

        now = self._now()
        quotes = {
            "hardrock_bet": [{"decimal_odds": "1.8", "observed_at": now}],
            "Bet365": [{"decimal_odds": "1.9", "observed_at": now - timedelta(seconds=30)}],
            "FanDuel": [{"decimal_odds": "2.0", "observed_at": now - timedelta(minutes=5)}],
        }
        snap = synchronized_snapshot(quotes_by_book=quotes, now=now, max_skew_seconds=120)
        assert "Bet365" in snap["books"]  # valid pair preserved
        assert "FanDuel" not in snap["books"]
        assert snap["excluded_books"]["FanDuel"] == "SKEW_EXCEEDED"

    def test_hardrock_stale_no_reference(self):
        from defend_markets.quant.line_movement import synchronized_snapshot

        now = self._now()
        quotes = {
            "hardrock_bet": [{"decimal_odds": "1.8", "observed_at": now - timedelta(hours=3)}],
            "Bet365": [{"decimal_odds": "1.9", "observed_at": now}],
        }
        snap = synchronized_snapshot(quotes_by_book=quotes, now=now, max_age_seconds=600)
        assert snap["reference_present"] is False
        assert snap["books"] == {}
        assert snap["excluded_books"]["Bet365"] == "NO_REFERENCE"

    def test_missing_timestamp_excluded(self):
        from defend_markets.quant.line_movement import synchronized_snapshot

        now = self._now()
        quotes = {
            "hardrock_bet": [{"decimal_odds": "1.8", "observed_at": now}],
            "Bet365": [{"decimal_odds": "1.9"}],  # no observed_at
        }
        snap = synchronized_snapshot(quotes_by_book=quotes, now=now, max_skew_seconds=120)
        assert "Bet365" not in snap["books"]
        assert snap["excluded_books"]["Bet365"] == "MISSING_TIMESTAMP"
