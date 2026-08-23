"""M4.7 result acquisition truth tests (P68 items 1-20).

Covers: local-missing != provider-empty, provider request empty classification,
result available, request error, schema drift, provider-event identity,
prediction-id not confused with provider-event-id, participant reversal,
result conflict, FINAL settlement, cancelled, postponed, abandoned, revision,
idempotent result ingestion / settlement / score, scheduler job, backoff, quota.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from defend_markets.quant.result_acquisition import (
    LOCAL_RESULT_MISSING_NOT_REQUESTED,
    LOCAL_RESULT_PRESENT,
    PROVIDER_EVENT_IDENTITY_MISMATCH,
    PROVIDER_EVENT_NOT_FOUND,
    PROVIDER_RESULT_AVAILABLE,
    PROVIDER_RESULT_ERROR,
    PROVIDER_RESULT_REQUESTED_EMPTY,
    PROVIDER_RESULT_SCHEMA_UNKNOWN,
    RESULT_RECONCILIATION_REQUIRED,
    OddsApiIOResultAdapter,
    ProviderResultBatch,
    ProviderResultEvent,
    TableTennisResultAcquisitionService,
    canonical_result_state,
    next_poll_at,
    parse_result_event,
    result_winner,
)
from defend_markets.quant.store import InMemoryQuantStore

NOW = datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)


class _FakeResultsDB:
    """Stands in for MarketsDatabase.connect()."""

    def __init__(self):
        self.local = {}  # canonical_event_id -> (home_score, away_score)
        self.forward_events = {}  # canonical_event_id -> {"provider":..., "provider_event_id":..., "player_a_key":..., "player_b_key":...}

    def connect(self):
        return _FakeConnection(self)


class _FakeConnection:
    def __init__(self, db: _FakeResultsDB):
        self._db = db
        self._cursor = _FakeCursor(db)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return self._cursor


class _FakeCursor:
    def __init__(self, db: _FakeResultsDB):
        self._db = db
        self._sql = ""
        self._params = ()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        self._sql = sql
        self._params = tuple(params) if params else ()
        return self

    def fetchall(self):
        if "tt_forward_events" in self._sql and "player_a_key" in self._sql:
            return []
        if "tt_forward_events" in self._sql and "provider_event_id" in self._sql:
            cid = self._params[0]
            entry = self._db.forward_events.get(cid)
            return [(cid, entry["provider"], entry["provider_event_id"])] if entry else []
        if "tt_match_results" in self._sql:
            events = self._params
            rows = []
            for ev in events:
                if ev in self._db.local:
                    hs, aws = self._db.local[ev]
                    rows.append((ev, hs, aws))
            return rows
        return []

    def fetchone(self):
        if "player_a_name" in self._sql:
            cid = self._params[0]
            entry = self._db.forward_events.get(cid)
            if entry:
                return (entry["player_a_name"], entry["player_b_name"])
            return None
        if "player_a_key" in self._sql:
            cid = self._params[0]
            entry = self._db.forward_events.get(cid)
            if entry:
                return (entry["player_a_key"], entry["player_b_key"])
            return None
        return None


class _FakeFeed:
    def __init__(self, results: dict[str, ProviderResultEvent], *, empty_for: set[str] | None = None, error=None):
        self.results = results
        self.empty_for = empty_for or set()
        self.error = error
        self.sweeps = 0
        self.by_id_calls = []

    def fetch_recent_results(self, *, from_iso: str, to_iso: str) -> ProviderResultBatch:
        self.sweeps += 1
        if self.error:
            return ProviderResultBatch(request_kind="RESULT", events_requested=1, events_returned=0, ok=False, error=self.error, schema_status="UNKNOWN")
        events = [e for e in self.results.values() if e.provider_event_id not in self.empty_for]
        return ProviderResultBatch(
            request_kind="RESULT", events_requested=1, events_returned=len(events), ok=True, schema_status="UNDERSTOOD", events=tuple(events)
        )

    def fetch_event_result(self, provider_event_id: str) -> ProviderResultBatch:
        self.by_id_calls.append(provider_event_id)
        if self.error:
            return ProviderResultBatch(request_kind="RESULT_BY_ID", events_requested=1, events_returned=0, ok=False, error=self.error, schema_status="UNKNOWN")
        if provider_event_id in self.empty_for:
            return ProviderResultBatch(request_kind="RESULT_BY_ID", events_requested=1, events_returned=0, ok=True, events=(), error="provider event not found", schema_status="UNDERSTOOD")
        event = self.results.get(provider_event_id)
        if event is None:
            return ProviderResultBatch(request_kind="RESULT_BY_ID", events_requested=1, events_returned=0, ok=True, events=(), error="provider event not found", schema_status="UNDERSTOOD")
        return ProviderResultBatch(request_kind="RESULT_BY_ID", events_requested=1, events_returned=1, ok=True, events=(event,), schema_status="UNDERSTOOD")


def _seed_store(store: InMemoryQuantStore, *, events, provider_ids, m5=True, shadow=True):
    for event, provider_id in zip(events, provider_ids):
        if m5:
            store.upsert_official_prediction({
                "canonical_event_id": event, "model_id": "M5_REGULARIZED_LOGISTIC", "model_version": "v1",
                "prediction_id": f"m-{event}", "prediction_role": "M5_FORWARD",
                "generated_at": NOW - timedelta(hours=2), "commence_at": NOW - timedelta(hours=1),
                "probability_a": 0.6, "policy_version": 1,
            })
        if shadow:
            store.upsert_official_prediction({
                "canonical_event_id": event, "model_id": "challenger-recent-form20", "model_version": "v1",
                "prediction_id": f"s-{event}", "prediction_role": "SHADOW_FORWARD",
                "generated_at": NOW - timedelta(hours=2), "commence_at": NOW - timedelta(hours=1),
                "probability_a": 0.55, "policy_version": 1,
            })


def _db_with_events(db: _FakeResultsDB, events, provider_ids):
    for event, pid in zip(events, provider_ids):
        db.forward_events[event] = {
            "provider": "odds_api_io",
            "provider_event_id": pid,
            "player_a_key": f"a-{event}",
            "player_b_key": f"b-{event}",
            "player_a_name": f"a-{event}",
            "player_b_name": f"b-{event}",
        }


# --------------------------------------------------------------------------- #
# P68 items 1-5: state classification
# --------------------------------------------------------------------------- #

class TestAcquisitionStates:
    def test_local_missing_is_not_provider_empty(self):
        service = TableTennisResultAcquisitionService(None, InMemoryQuantStore(), None)
        state = service.classify_acquisition_state(has_local_result=False, provider_event_id="p1", provider_batch=None, provider_status=None)
        assert state == LOCAL_RESULT_MISSING_NOT_REQUESTED
        assert state != PROVIDER_RESULT_REQUESTED_EMPTY

    def test_provider_requested_empty_only_after_request(self):
        service = TableTennisResultAcquisitionService(None, InMemoryQuantStore(), None)
        batch = ProviderResultBatch(request_kind="RESULT", events_requested=1, events_returned=0, ok=True, events=())
        state = service.classify_acquisition_state(has_local_result=False, provider_event_id="p1", provider_batch=batch, provider_status=None)
        assert state == PROVIDER_RESULT_REQUESTED_EMPTY

    def test_provider_result_available(self):
        service = TableTennisResultAcquisitionService(None, InMemoryQuantStore(), None)
        event = ProviderResultEvent(provider_event_id="p1", status="settled", home_score=3, away_score=1)
        batch = ProviderResultBatch(request_kind="RESULT", events_requested=1, events_returned=1, ok=True, events=(event,))
        state = service.classify_acquisition_state(has_local_result=False, provider_event_id="p1", provider_batch=batch, provider_status="settled")
        assert state == PROVIDER_RESULT_AVAILABLE

    def test_provider_request_error(self):
        service = TableTennisResultAcquisitionService(None, InMemoryQuantStore(), None)
        batch = ProviderResultBatch(request_kind="RESULT", events_requested=0, events_returned=0, ok=False, error="boom")
        state = service.classify_acquisition_state(has_local_result=False, provider_event_id="p1", provider_batch=batch, provider_status=None)
        assert state == PROVIDER_RESULT_ERROR

    def test_schema_drift(self):
        service = TableTennisResultAcquisitionService(None, InMemoryQuantStore(), None)
        event = ProviderResultEvent(provider_event_id="p1", status="settled", schema_ok=False, schema_error="scores missing")
        batch = ProviderResultBatch(request_kind="RESULT", events_requested=1, events_returned=1, ok=True, events=(event,))
        state = service.classify_acquisition_state(has_local_result=False, provider_event_id="p1", provider_batch=batch, provider_status="settled")
        assert state == PROVIDER_RESULT_SCHEMA_UNKNOWN

    def test_provider_event_not_found_404(self):
        service = TableTennisResultAcquisitionService(None, InMemoryQuantStore(), None)
        batch = ProviderResultBatch(request_kind="RESULT_BY_ID", events_requested=1, events_returned=0, ok=True, status_code=404, events=())
        state = service.classify_acquisition_state(has_local_result=False, provider_event_id="p1", provider_batch=batch, provider_status=None)
        assert state == PROVIDER_EVENT_NOT_FOUND

    def test_identity_mismatch(self):
        service = TableTennisResultAcquisitionService(None, InMemoryQuantStore(), None)
        event = ProviderResultEvent(provider_event_id="different", status="settled", home_score=3, away_score=1)
        batch = ProviderResultBatch(request_kind="RESULT", events_requested=1, events_returned=1, ok=True, events=(event,))
        state = service.classify_acquisition_state(has_local_result=False, provider_event_id="p1", provider_batch=batch, provider_status="settled")
        assert state == PROVIDER_EVENT_IDENTITY_MISMATCH


# --------------------------------------------------------------------------- #
# P68 items 6-9: identity / orientation
# --------------------------------------------------------------------------- #

class TestIdentityAndOrientation:
    def test_prediction_id_not_used_as_provider_event_id(self):
        """P5: the service derives provider_event_id from tt_forward_events,
        never from prediction_id ('m-e1' style ids)."""
        db = _FakeResultsDB()
        store = InMemoryQuantStore()
        events = ["e1"]
        provider_ids = ["1001"]
        _seed_store(store, events=events, provider_ids=provider_ids)
        _db_with_events(db, events, provider_ids)
        feed = _FakeFeed({"1001": ProviderResultEvent(provider_event_id="1001", status="settled", home="a-e1", away="b-e1", home_score=3, away_score=1, schema_ok=True)})
        service = TableTennisResultAcquisitionService(db, store, feed)
        past = service.past_unsettled_events()
        assert past[0]["provider_event_id"] == "1001"
        assert past[0]["provider_event_id"] != "m-e1"
        result = service.acquire_and_settle()
        assert result["settled"] == 1
        settlements = store.list_settlements()
        assert settlements[0]["provider_event_id"] == "1001"

    def test_participant_reversal_maps_explicitly(self):
        """P6: provider lists reversed home/away; scores are swapped to A/B."""
        db = _FakeResultsDB()
        store = InMemoryQuantStore()
        events = ["e1"]
        provider_ids = ["1001"]
        _seed_store(store, events=events, provider_ids=provider_ids)
        db.forward_events["e1"] = {"provider": "odds_api_io", "provider_event_id": "1001", "player_a_key": "Alice", "player_b_key": "Bob", "player_a_name": "Alice", "player_b_name": "Bob"}
        # provider home = Bob, away = Alice (reversed); provider score 1-3 => canonical 3-1 (A wins)
        feed = _FakeFeed({"1001": ProviderResultEvent(provider_event_id="1001", status="settled", home="Bob", away="Alice", home_score=1, away_score=3, schema_ok=True)})
        service = TableTennisResultAcquisitionService(db, store, feed)
        result = service.acquire_and_settle()
        assert result["settled"] == 1
        settlements = store.list_settlements()
        assert settlements[0]["actual_a"] == 3
        assert settlements[0]["actual_b"] == 1
        assert settlements[0]["winner_side"] == "A"
        assert settlements[0]["orientation_verified"] is True

    def test_participant_conflict_no_guess(self):
        """P6/P7: identity conflict -> RESULT_RECONCILIATION_REQUIRED, never settled."""
        db = _FakeResultsDB()
        store = InMemoryQuantStore()
        events = ["e1"]
        provider_ids = ["1001"]
        _seed_store(store, events=events, provider_ids=provider_ids)
        db.forward_events["e1"] = {"provider": "odds_api_io", "provider_event_id": "1001", "player_a_key": "Alice", "player_b_key": "Bob", "player_a_name": "Alice", "player_b_name": "Bob"}
        feed = _FakeFeed({"1001": ProviderResultEvent(provider_event_id="1001", status="settled", home="Eve", away="Mallory", home_score=3, away_score=1, schema_ok=True)})
        service = TableTennisResultAcquisitionService(db, store, feed)
        result = service.acquire_and_settle()
        assert result["settled"] == 0
        assert RESULT_RECONCILIATION_REQUIRED in result["classified"]
        assert store.list_settlements() == []

    def test_result_winner(self):
        assert result_winner(home_score=3, away_score=1) == "A"
        assert result_winner(home_score=1, away_score=3) == "B"
        assert result_winner(home_score=2, away_score=2) is None


# --------------------------------------------------------------------------- #
# P68 items 10-14: state machine / revisions
# --------------------------------------------------------------------------- #

class TestResultStateMachine:
    def test_canonical_result_state_mapping(self):
        assert canonical_result_state("settled") == "FINAL"
        assert canonical_result_state("cancelled") == "CANCELLED"
        assert canonical_result_state("postponed") == "POSTPONED"
        assert canonical_result_state("abandoned") == "ABANDONED"
        assert canonical_result_state("unknown-status") == "REVIEW_REQUIRED"

    def test_cancelled_not_scored(self):
        db = _FakeResultsDB()
        store = InMemoryQuantStore()
        events = ["e1"]
        _seed_store(store, events=events, provider_ids=["1001"])
        _db_with_events(db, events, ["1001"])
        feed = _FakeFeed({"1001": ProviderResultEvent(provider_event_id="1001", status="cancelled", home_score=3, away_score=1, schema_ok=True)})
        service = TableTennisResultAcquisitionService(db, store, feed)
        result = service.acquire_and_settle()
        assert result["settled"] == 0
        assert store.list_settlements() == []
        assert store.list_forward_scores() == []

    def test_postponed_not_scored(self):
        db = _FakeResultsDB()
        store = InMemoryQuantStore()
        _seed_store(store, events=["e1"], provider_ids=["1001"])
        _db_with_events(db, ["e1"], ["1001"])
        feed = _FakeFeed({"1001": ProviderResultEvent(provider_event_id="1001", status="postponed", home_score=3, away_score=1, schema_ok=True)})
        service = TableTennisResultAcquisitionService(db, store, feed)
        result = service.acquire_and_settle()
        assert result["settled"] == 0

    def test_abandoned_not_scored(self):
        db = _FakeResultsDB()
        store = InMemoryQuantStore()
        _seed_store(store, events=["e1"], provider_ids=["1001"])
        _db_with_events(db, ["e1"], ["1001"])
        feed = _FakeFeed({"1001": ProviderResultEvent(provider_event_id="1001", status="abandoned", home_score=1, away_score=0, schema_ok=True)})
        service = TableTennisResultAcquisitionService(db, store, feed)
        result = service.acquire_and_settle()
        assert result["settled"] == 0

    def test_revision_does_not_overwrite(self):
        """P8: a corrected provider result inserts a new revision; the original
        settlement record remains (never silently overwritten)."""
        db = _FakeResultsDB()
        store = InMemoryQuantStore()
        _seed_store(store, events=["e1"], provider_ids=["1001"])
        _db_with_events(db, ["e1"], ["1001"])
        feed = _FakeFeed({"1001": ProviderResultEvent(provider_event_id="1001", status="settled", home="a-e1", away="b-e1", home_score=3, away_score=1, schema_ok=True)})
        service = TableTennisResultAcquisitionService(db, store, feed)
        service.acquire_and_settle()
        first = store.list_settlements()
        assert len(first) == 1
        # A corrected result uses a distinct source_result_id so it never
        # overwrites the original row (additive revision boundary).
        created = store.insert_settlement({
            "canonical_event_id": "e1",
            "provider_event_id": "1001",
            "status": "FINAL",
            "actual_a": 3, "actual_b": 2, "winner_side": "A",
            "source_result_id": "oaio:1001#rev2",
            "source_provider": "odds_api_io",
            "orientation_verified": True,
        })
        assert created is True
        settlements = store.list_settlements()
        assert len(settlements) == 2


# --------------------------------------------------------------------------- #
# P68 items 15-17: idempotency
# --------------------------------------------------------------------------- #

class TestIdempotency:
    def test_idempotent_result_ingestion(self):
        db = _FakeResultsDB()
        store = InMemoryQuantStore()
        _seed_store(store, events=["e1"], provider_ids=["1001"])
        _db_with_events(db, ["e1"], ["1001"])
        feed = _FakeFeed({"1001": ProviderResultEvent(provider_event_id="1001", status="settled", home="a-e1", away="b-e1", home_score=3, away_score=1, schema_ok=True)})
        service = TableTennisResultAcquisitionService(db, store, feed)
        r1 = service.acquire_and_settle()
        r2 = service.acquire_and_settle()
        assert r1["settled"] == 1
        assert r2["settled"] == 0  # already settled -> no new settlement
        assert len(store.list_settlements()) == 1
        assert len(store.list_forward_scores()) == 2  # M5 + shadow, not duplicated

    def test_idempotent_settlement(self):
        db = _FakeResultsDB()
        store = InMemoryQuantStore()
        _seed_store(store, events=["e1"], provider_ids=["1001"])
        _db_with_events(db, ["e1"], ["1001"])
        feed = _FakeFeed({"1001": ProviderResultEvent(provider_event_id="1001", status="settled", home="a-e1", away="b-e1", home_score=3, away_score=1, schema_ok=True)})
        service = TableTennisResultAcquisitionService(db, store, feed)
        normalized = {"home_score": 3, "away_score": 1, "winner_side": "A", "orientation": "CANONICAL", "state": "FINAL", "provider_event_id": "1001"}
        event = {"canonical_event_id": "e1", "provider_event_id": "1001", "commence_at": NOW - timedelta(hours=1)}
        assert service._settle_event(event, normalized) == 1
        assert service._settle_event(event, normalized) == 0

    def test_idempotent_score(self):
        db = _FakeResultsDB()
        store = InMemoryQuantStore()
        _seed_store(store, events=["e1"], provider_ids=["1001"])
        _db_with_events(db, ["e1"], ["1001"])
        feed = _FakeFeed({"1001": ProviderResultEvent(provider_event_id="1001", status="settled", home="a-e1", away="b-e1", home_score=3, away_score=1, schema_ok=True)})
        service = TableTennisResultAcquisitionService(db, store, feed)
        normalized = {"home_score": 3, "away_score": 1, "winner_side": "A", "orientation": "CANONICAL", "state": "FINAL", "provider_event_id": "1001"}
        event = {"canonical_event_id": "e1", "provider_event_id": "1001", "commence_at": NOW - timedelta(hours=1)}
        service._settle_event(event, normalized)
        assert service._score_event(event, normalized) == 2
        assert service._score_event(event, normalized) == 0


# --------------------------------------------------------------------------- #
# P68 items 18-20: scheduler / backoff / quota
# --------------------------------------------------------------------------- #

class TestCadenceAndQuota:
    def test_next_poll_backoff(self):
        base = NOW
        empty_state = PROVIDER_RESULT_REQUESTED_EMPTY
        d1 = next_poll_at(state=empty_state, request_count=0, now=base)
        d2 = next_poll_at(state=empty_state, request_count=1, now=base)
        d3 = next_poll_at(state=empty_state, request_count=4, now=base)
        assert d1 < d2 < d3
        present = next_poll_at(state=LOCAL_RESULT_PRESENT, request_count=0, now=base)
        assert present > d1

    def test_quota_reservation_and_consume(self):
        store = InMemoryQuantStore()
        period = NOW.replace(hour=0, minute=0, second=0, microsecond=0)
        store.reserve_quota("RESULT", period, 20)
        assert store.quota_used("RESULT", period)["budget"] == 20
        store.consume_quota("RESULT", period)
        store.consume_quota("RESULT", period)
        assert store.quota_used("RESULT", period)["used"] == 2

    def test_request_ledger_recorded(self):
        store = InMemoryQuantStore()
        adapter = OddsApiIOResultAdapter(key="k", store=store)
        adapter._record(ProviderResultBatch(request_kind="RESULT", events_requested=5, events_returned=5, ok=True, status_code=200))
        rows = store.list_result_requests()
        assert len(rows) == 1
        assert rows[0]["events_returned"] == 5


# --------------------------------------------------------------------------- #
# parse_result_event
# --------------------------------------------------------------------------- #

class TestParseResultEvent:
    def test_settled_with_scores(self):
        event = parse_result_event({"id": "7", "status": "settled", "home": "A", "away": "B", "scores": {"home": 3, "away": 1}})
        assert event.provider_event_id == "7"
        assert event.home_score == 3
        assert event.away_score == 1
        assert event.schema_ok is True

    def test_settled_missing_scores(self):
        event = parse_result_event({"id": "7", "status": "settled", "home": "A", "away": "B"})
        assert event.schema_ok is False
        assert event.schema_error is not None

    def test_non_integral_scores(self):
        event = parse_result_event({"id": "7", "status": "settled", "scores": {"home": "x", "away": "1"}})
        assert event.schema_ok is False
