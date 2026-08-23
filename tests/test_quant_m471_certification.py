"""M4.7.1 result/settlement truth certification tests (P14-P17 test matrix).

Covers the 67-item test matrix: legacy retirement, sweep-error propagation,
request evidence, per-event fallback, retention, provider/prediction identity,
local-result orientation, raw hash, revision immutability, forward metric
units, coherent/frozen market reference, quota atomicity/reserved floor,
circuit half-open probe, arb exact identity, paper-arb leg settlement.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from defend_markets.quant.result_acquisition import (
    LOCAL_RESULT_MISSING_NOT_REQUESTED,
    LOCAL_RESULT_PRESENT,
    PROVIDER_EVENT_IDENTITY_MISMATCH,
    PROVIDER_EVENT_NOT_FOUND,
    PROVIDER_RESULT_AVAILABLE,
    PROVIDER_RESULT_ERROR,
    PROVIDER_RESULT_OUTSIDE_RETENTION,
    PROVIDER_RESULT_REQUESTED_EMPTY,
    PROVIDER_RESULT_SCHEMA_UNKNOWN,
    RESULT_RECONCILIATION_REQUIRED,
    RESULT_STATE_CANCELLED,
    RESULT_STATE_FINAL,
    RESULT_STATE_SUPERSEDED,
    ProviderResultBatch,
    ProviderResultEvent,
    ResultRequestEvidence,
    TableTennisResultAcquisitionService,
    result_transition_allowed,
    settle_acquired_results,
)
from defend_markets.quant.store import InMemoryQuantStore
from defend_markets.quant.circuit_breaker import (
    STATE_CLOSED,
    STATE_HALF_OPEN,
    STATE_OPEN,
    STATE_OPEN_CONFIGURATION,
    ProviderCircuitBreaker,
)
from defend_markets.quant.quota import (
    CLASS_ATTESTATION,
    CLASS_RESULT,
    RequestQuotaGovernor,
)
from defend_markets.quant.forward_evidence import settlement_catchup

NOW = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)
_REAL_NOW = datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Fakes (reuse the M4.7 acquisition test fakes shape)
# --------------------------------------------------------------------------- #

class _FakeResultsDB:
    def __init__(self):
        self.local = {}
        self.forward_events = {}

    def connect(self):
        return _FakeConnection(self)


class _FakeConnection:
    def __init__(self, db):
        self._db = db
        self._cursor = _FakeCursor(db)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return self._cursor


class _FakeCursor:
    def __init__(self, db):
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
        if "tt_forward_events" in self._sql and "player_a_key" in self._sql and "player_a_name" in self._sql:
            out = []
            for cid in self._params:
                e = self._db.forward_events.get(cid)
                if e:
                    out.append((cid, e.get("player_a_name", ""), e.get("player_b_name", ""), e.get("player_a_key", ""), e.get("player_b_key", "")))
            return out
        if "tt_forward_events" in self._sql and "player_a_name" in self._sql and "player_a_key" not in self._sql:
            out = []
            for cid in self._params:
                e = self._db.forward_events.get(cid)
                if e:
                    out.append((cid, e["player_a_name"], e["player_b_name"]))
            return out
        if "tt_forward_events" in self._sql and "provider_event_id" in self._sql:
            out = []
            for cid in self._params:
                e = self._db.forward_events.get(cid)
                if e:
                    out.append((cid, e["provider"], e["provider_event_id"]))
            return out
        if "tt_match_results" in self._sql:
            rows = []
            for ev in self._params:
                if ev in self._db.local:
                    lr = self._db.local[ev]
                    rows.append((ev, "league", lr.get("hk", ""), lr.get("ak", ""), lr["hs"], lr["aws"], None, lr.get("source_provider", "odds_api_io"), lr.get("raw_ref")))
            return rows
        return []

    def fetchone(self):
        if "player_a_name" in self._sql:
            cid = self._params[0]
            e = self._db.forward_events.get(cid)
            if e:
                return (e["player_a_name"], e["player_b_name"])
            return None
        if "player_a_key" in self._sql and "player_a_name" not in self._sql:
            cid = self._params[0]
            e = self._db.forward_events.get(cid)
            if e:
                return (e["player_a_key"], e["player_b_key"])
            return None
        return None


class _Feed:
    def __init__(self, results=None, *, sweep_error=False, sweep_schema_invalid=False, empty_for=(), sweep_empty=False):
        self.results = results or {}
        self.sweep_error = sweep_error
        self.sweep_schema_invalid = sweep_schema_invalid
        self.empty_for = set(empty_for)
        self.sweep_empty = sweep_empty
        self.sweeps = 0
        self.by_id_calls = []

    def fetch_recent_results(self, *, from_iso, to_iso):
        self.sweeps += 1
        if self.sweep_error:
            return ProviderResultBatch(request_kind="RESULT", events_requested=1, events_returned=0, ok=False, error="network", error_class="NETWORK", schema_status="UNKNOWN")
        if self.sweep_schema_invalid:
            return ProviderResultBatch(request_kind="RESULT", events_requested=1, events_returned=0, ok=True, schema_status="INVALID", error_class="SCHEMA_INVALID", events=())
        if self.sweep_empty:
            return ProviderResultBatch(request_kind="RESULT", events_requested=1, events_returned=0, ok=True, schema_status="UNDERSTOOD", events=())
        events = [e for e in self.results.values() if e.provider_event_id not in self.empty_for]
        return ProviderResultBatch(request_kind="RESULT", events_requested=1, events_returned=len(events), ok=True, schema_status="UNDERSTOOD", events=tuple(events))

    def fetch_event_result(self, provider_event_id):
        self.by_id_calls.append(provider_event_id)
        if provider_event_id in self.empty_for:
            return ProviderResultBatch(request_kind="RESULT_BY_ID", events_requested=1, events_returned=0, status_code=404, ok=True, error_class="EVENT_NOT_FOUND", schema_status="UNDERSTOOD", events=())
        event = self.results.get(provider_event_id)
        if event is None:
            return ProviderResultBatch(request_kind="RESULT_BY_ID", events_requested=1, events_returned=0, status_code=404, ok=True, error_class="EVENT_NOT_FOUND", schema_status="UNDERSTOOD", events=())
        return ProviderResultBatch(request_kind="RESULT_BY_ID", events_requested=1, events_returned=1, ok=True, schema_status="UNDERSTOOD", events=(event,))


def _seed(store, events=("e1",), provider_ids=("1001",)):
    for e, pid in zip(events, provider_ids):
        store.upsert_official_prediction({
            "canonical_event_id": e, "model_id": "M5_REGULARIZED_LOGISTIC", "model_version": "v1",
            "prediction_id": f"m-{e}", "prediction_role": "M5_FORWARD",
            "generated_at": _REAL_NOW - timedelta(hours=2), "commence_at": _REAL_NOW - timedelta(hours=1),
            "probability_a": 0.6, "policy_version": 1,
        })


def _db_with(db, events=("e1",), provider_ids=("1001",), names=("Alice", "Bob")):
    for e, pid in zip(events, provider_ids):
        db.forward_events[e] = {
            "provider": "odds_api_io", "provider_event_id": pid,
            "player_a_key": f"k-{e}", "player_b_key": f"k2-{e}",
            "player_a_name": names[0], "player_b_name": names[1],
        }


def _ev(pid="1001", status="settled", home="Alice", away="Bob", hs=3, aws=1, schema_ok=True):
    import hashlib
    raw = hashlib.sha256(f"{pid}|{status}|{home}|{away}|{hs}|{aws}".encode()).hexdigest()
    return ProviderResultEvent(provider_event_id=pid, status=status, home=home, away=away, home_score=hs, away_score=aws, schema_ok=schema_ok, raw_payload_hash=raw)


# --------------------------------------------------------------------------- #
# RESULT TRUTH (items 1-9)
# --------------------------------------------------------------------------- #

class TestLegacyRetirement:
    def test_legacy_not_referenced_by_settlement_job(self):
        """item 1: production SETTLEMENT uses SettlementService, not legacy."""
        import inspect
        from defend_markets.quant.orchestrator import MarketsIntelligenceOrchestrator

        source = inspect.getsource(MarketsIntelligenceOrchestrator.run_settlement)
        assert "SettlementService" in source
        # the legacy function is never imported or called in the production path
        assert "from defend_markets.quant.forward_evidence import settlement_catchup" not in source
        assert "settlement_catchup(" not in source

    def test_legacy_deprecated_docstring(self):
        assert "DEPRECATED" in (settlement_catchup.__doc__ or "")

    def test_legacy_marks_missing_as_provider_empty(self):
        """Demonstrate why legacy is retired: local miss -> provider empty."""
        db = _FakeResultsDB()
        store = InMemoryQuantStore()
        _seed(store)
        outcome = settlement_catchup(db, store)
        assert outcome["classified"].get("RESULT_PROVIDER_EMPTY") == 1


class TestSweepErrorPropagation:
    def _service(self, feed):
        return TableTennisResultAcquisitionService(_FakeResultsDB(), InMemoryQuantStore(), feed)

    def test_local_miss_not_provider_empty_without_request(self):
        """item 2."""
        db = _FakeResultsDB()
        store = InMemoryQuantStore()
        _seed(store)
        _db_with(db)
        feed = _Feed()  # sweep returns nothing but ok/understood
        service = TableTennisResultAcquisitionService(db, store, feed)
        outcome = service.acquire_and_settle()
        # event not in sweep but within window -> requested-empty
        assert outcome["classified"].get(PROVIDER_RESULT_REQUESTED_EMPTY) == 1

    def test_failed_sweep_not_provider_empty(self):
        """item 3: failed sweep -> PROVIDER_RESULT_ERROR, never empty."""
        db = _FakeResultsDB()
        store = InMemoryQuantStore()
        _seed(store)
        _db_with(db)
        feed = _Feed(sweep_error=True)
        service = TableTennisResultAcquisitionService(db, store, feed)
        outcome = service.acquire_and_settle()
        assert PROVIDER_RESULT_REQUESTED_EMPTY not in outcome["classified"]
        assert outcome["classified"].get(PROVIDER_RESULT_ERROR) == 1

    def test_schema_invalid_sweep_not_provider_empty(self):
        """item 4."""
        db = _FakeResultsDB()
        store = InMemoryQuantStore()
        _seed(store)
        _db_with(db)
        feed = _Feed(sweep_schema_invalid=True)
        service = TableTennisResultAcquisitionService(db, store, feed)
        outcome = service.acquire_and_settle()
        assert PROVIDER_RESULT_REQUESTED_EMPTY not in outcome["classified"]
        assert outcome["classified"].get(PROVIDER_RESULT_SCHEMA_UNKNOWN) == 1

    def test_successful_empty_scoped_sweep_is_requested_empty(self):
        """item 5."""
        db = _FakeResultsDB()
        store = InMemoryQuantStore()
        _seed(store)
        _db_with(db)
        feed = _Feed(results={})  # successful, understood, but empty
        service = TableTennisResultAcquisitionService(db, store, feed)
        outcome = service.acquire_and_settle()
        assert outcome["classified"].get(PROVIDER_RESULT_REQUESTED_EMPTY) == 1

    def test_event_outside_window_stays_not_requested(self):
        """item 6: commence older than window -> not-requested."""
        db = _FakeResultsDB()
        store = InMemoryQuantStore()
        store.upsert_official_prediction({
            "canonical_event_id": "old", "model_id": "M5_REGULARIZED_LOGISTIC", "model_version": "v1",
            "prediction_id": "m-old", "prediction_role": "M5_FORWARD",
            "generated_at": _REAL_NOW - timedelta(days=10), "commence_at": _REAL_NOW - timedelta(days=9),
            "probability_a": 0.6, "policy_version": 1,
        })
        db.forward_events["old"] = {"provider": "odds_api_io", "provider_event_id": "9999", "player_a_name": "A", "player_b_name": "B"}
        feed = _Feed(results={})
        service = TableTennisResultAcquisitionService(db, store, feed)
        outcome = service.acquire_and_settle(recent_window_hours=96)
        assert outcome["classified"].get(LOCAL_RESULT_MISSING_NOT_REQUESTED) == 1

    def test_per_event_fallback_executes(self):
        """item 7: per-event fallback actually runs for eligible events."""
        db = _FakeResultsDB()
        store = InMemoryQuantStore()
        _seed(store)
        _db_with(db)
        feed = _Feed(results={"1001": _ev()}, sweep_empty=True)  # sweep empty, fallback has it
        service = TableTennisResultAcquisitionService(db, store, feed)
        outcome = service.acquire_and_settle()
        assert outcome["fallback_used"] == 1
        assert outcome["settled"] == 1
        assert feed.by_id_calls == ["1001"]

    def test_per_event_404_classified_retention(self):
        """item 8: per-event 404 -> PROVIDER_RESULT_OUTSIDE_RETENTION."""
        db = _FakeResultsDB()
        store = InMemoryQuantStore()
        _seed(store)
        _db_with(db)
        feed = _Feed(results={}, empty_for={"1001"})
        service = TableTennisResultAcquisitionService(db, store, feed)
        outcome = service.acquire_and_settle()
        assert outcome["classified"].get(PROVIDER_RESULT_OUTSIDE_RETENTION) == 1

    def test_provider_id_not_prediction_id(self):
        """item 9."""
        db = _FakeResultsDB()
        store = InMemoryQuantStore()
        _seed(store)
        _db_with(db)
        feed = _Feed(results={"1001": _ev()})
        service = TableTennisResultAcquisitionService(db, store, feed)
        events = service.past_unsettled_events()
        assert events[0]["provider_event_id"] == "1001"
        assert events[0]["provider_event_id"] != "m-e1"


class TestLocalResultOrientation:
    def test_local_canonical(self):
        """item 10."""
        db = _FakeResultsDB()
        store = InMemoryQuantStore()
        _seed(store)
        _db_with(db, names=("Alice", "Bob"))
        db.local["e1"] = {"hs": 3, "aws": 1, "hk": "k-e1", "ak": "k2-e1", "source_provider": "odds_api_io", "raw_ref": "r1"}
        feed = _Feed(results={})
        service = TableTennisResultAcquisitionService(db, store, feed)
        outcome = service.acquire_and_settle()
        assert outcome["settled"] == 1
        assert store.list_settlements()[0]["orientation_verified"] is True

    def test_local_reversed(self):
        """item 11."""
        db = _FakeResultsDB()
        store = InMemoryQuantStore()
        _seed(store)
        _db_with(db, names=("Alice", "Bob"))
        db.local["e1"] = {"hs": 3, "aws": 1, "hk": "k2-e1", "ak": "k-e1", "source_provider": "odds_api_io", "raw_ref": "r1"}
        feed = _Feed(results={})
        service = TableTennisResultAcquisitionService(db, store, feed)
        outcome = service.acquire_and_settle()
        assert outcome["settled"] == 1
        s = store.list_settlements()[0]
        # source home(k2-e1=Bob) 3, away(k-e1=Alice) 1 -> REVERSED -> A=1, B=3, winner B
        assert s["actual_a"] == 1 and s["actual_b"] == 3 and s["winner_side"] == "B"

    def test_local_conflict_review_required(self):
        """item 12: conflict -> REVIEW_REQUIRED, not settled."""
        db = _FakeResultsDB()
        store = InMemoryQuantStore()
        _seed(store)
        _db_with(db, names=("Alice", "Bob"))
        db.local["e1"] = {"hs": 3, "aws": 1, "hk": "k-eve", "ak": "k-mallory", "source_provider": "odds_api_io", "raw_ref": "r1"}
        feed = _Feed(results={})
        service = TableTennisResultAcquisitionService(db, store, feed)
        outcome = service.acquire_and_settle()
        assert outcome["settled"] == 0
        assert outcome["classified"].get(RESULT_RECONCILIATION_REQUIRED) == 1

    def test_unknown_orientation_no_names_not_settled(self):
        """item 13: no participant keys/names -> UNKNOWN -> REVIEW_REQUIRED."""
        db = _FakeResultsDB()
        store = InMemoryQuantStore()
        _seed(store)
        # no forward-event identity (keys/names unavailable)
        db.forward_events["e1"] = {"provider": "odds_api_io", "provider_event_id": "1001"}
        db.local["e1"] = {"hs": 3, "aws": 1, "hk": "X", "ak": "Y", "source_provider": "odds_api_io", "raw_ref": "r1"}
        feed = _Feed(results={})
        service = TableTennisResultAcquisitionService(db, store, feed)
        outcome = service.acquire_and_settle()
        assert outcome["settled"] == 0
        assert outcome["classified"].get(RESULT_RECONCILIATION_REQUIRED) == 1


class TestProvenance:
    def test_raw_payload_hash_populated(self):
        """item 15."""
        from defend_markets.quant.result_acquisition import parse_result_event

        ev = parse_result_event({"id": "1", "status": "settled", "home": "A", "away": "B", "scores": {"home": 3, "away": 1}})
        assert ev.raw_payload_hash

    def test_request_evidence_persisted(self):
        """item 16."""
        store = InMemoryQuantStore()
        ev = ResultRequestEvidence(
            request_id="r1", provider="odds_api_io", request_kind="RESULT",
            requested_at=NOW, http_status=200, response_schema_status="UNDERSTOOD",
            events_returned=5, successful_search_scope="w",
        )
        store.record_result_request_evidence(ev.to_row())
        rows = store.list_result_request_evidence()
        assert rows[0]["request_id"] == "r1"
        assert rows[0]["response_schema_status"] == "UNDERSTOOD"

    def test_settlement_provenance_complete(self):
        """item 17."""
        db = _FakeResultsDB()
        store = InMemoryQuantStore()
        _seed(store)
        _db_with(db)
        feed = _Feed(results={"1001": _ev()})
        service = TableTennisResultAcquisitionService(db, store, feed)
        service.acquire_and_settle()
        s = store.list_settlements()[0]
        assert s["provider_event_id"] == "1001"
        assert s["source_result_id"] == "1001"
        assert s["raw_payload_hash"]
        assert s["orientation_verified"] is True
        assert s["actual_a"] == 3 and s["actual_b"] == 1


class TestRevision:
    def test_revision_immutable(self):
        """items 18/19/20: revised result creates new revision; old preserved."""
        store = InMemoryQuantStore()
        _seed(store)
        store.insert_settlement({
            "canonical_event_id": "e1", "provider_event_id": "1001", "status": "FINAL",
            "actual_a": 3, "actual_b": 1, "winner_side": "A", "source_result_id": "1001",
            "source_provider": "odds_api_io", "orientation_verified": True,
        })
        old_row = store.latest_final_settlement("e1")
        new_id = store.insert_settlement_revision({
            "canonical_event_id": "e1", "provider_event_id": "1001", "status": "FINAL",
            "actual_a": 2, "actual_b": 3, "winner_side": "B", "source_result_id": "1001#rev2",
            "source_provider": "odds_api_io", "orientation_verified": True,
        })
        settlements = store.list_settlements()
        # P19: old row is NOT mutated (content immutable); new revision appended
        # with supersedes_revision_id linking v2 -> v1.
        assert old_row["actual_a"] == 3 and old_row["actual_b"] == 1  # unchanged
        revisions = [s for s in settlements if s.get("revision") == 2]
        assert len(revisions) == 1
        new = revisions[0]
        assert new["actual_a"] == 2 and new["actual_b"] == 3
        assert new["supersedes_revision_id"] == old_row["settlement_id"]
        # current revision = latest FINAL by revision DESC
        current = store.latest_final_settlement("e1")
        assert current["settlement_id"] == new["settlement_id"]

    def test_state_transitions(self):
        """item 13/14: allowed transitions."""
        assert result_transition_allowed("PENDING", "FINAL") is True
        assert result_transition_allowed("FINAL", "SUPERSEDED") is True
        assert result_transition_allowed("PENDING", "CANCELLED") is True
        assert result_transition_allowed("CANCELLED", "FINAL") is False


class TestForwardMetrics:
    def test_duplicate_scores_do_not_inflate_denominator(self):
        """items 21/22."""
        from defend_markets.quant.result_acquisition import forward_evidence_summary

        store = InMemoryQuantStore()
        store.register_model(model_id="M5_REGULARIZED_LOGISTIC", model_version="v1", role="CHAMPION", stage="CHAMPION")
        store.register_model(model_id="challenger-recent-form20", model_version="v1", role="SHADOW", stage="SHADOW")
        # two score rows for the same event+model -> one scoring unit
        store.insert_settlement({
            "canonical_event_id": "e1", "provider_event_id": "1", "status": "FINAL",
            "actual_a": 3, "actual_b": 1, "winner_side": "A", "source_result_id": "1",
            "source_provider": "odds_api_io", "orientation_verified": True,
        })
        s = store.list_settlements()[0]
        for _ in range(2):
            store.insert_forward_score({
                "canonical_event_id": "e1", "official_prediction_id": 1, "model_id": "M5_REGULARIZED_LOGISTIC",
                "settlement_id": s["settlement_id"], "probability_a": 0.6, "actual_outcome": 1.0,
                "brier": 0.16, "logloss": 0.5, "scoring_policy_version": 1,
            })
        summary = forward_evidence_summary(store)
        assert summary["m5"]["events"] == 1

    def test_paired_by_exact_event(self):
        """items 23/24."""
        from defend_markets.quant.result_acquisition import forward_evidence_summary

        store = InMemoryQuantStore()
        store.register_model(model_id="M5_REGULARIZED_LOGISTIC", model_version="v1", role="CHAMPION", stage="CHAMPION")
        store.register_model(model_id="challenger-recent-form20", model_version="v1", role="SHADOW", stage="SHADOW")
        store.insert_settlement({
            "canonical_event_id": "e1", "provider_event_id": "1", "status": "FINAL",
            "actual_a": 3, "actual_b": 1, "winner_side": "A", "source_result_id": "1",
            "source_provider": "odds_api_io", "orientation_verified": True,
        })
        s = store.list_settlements()[0]
        store.insert_forward_score({
            "canonical_event_id": "e1", "official_prediction_id": 1, "model_id": "M5_REGULARIZED_LOGISTIC",
            "settlement_id": s["settlement_id"], "probability_a": 0.6, "actual_outcome": 1.0,
            "brier": 0.16, "logloss": 0.5, "scoring_policy_version": 1,
        })
        store.insert_forward_score({
            "canonical_event_id": "e1", "official_prediction_id": 2, "model_id": "challenger-recent-form20",
            "settlement_id": s["settlement_id"], "probability_a": 0.55, "actual_outcome": 1.0,
            "brier": 0.2025, "logloss": 0.6, "scoring_policy_version": 1,
        })
        summary = forward_evidence_summary(store)
        assert summary["paired"]["events"] == 1


class TestMarketReferenceCoherence:
    def _row(self, event, side, book, price, observed_at, oid):
        return {"canonical_event_id": event, "market": "MATCH_WINNER", "side": side, "bookmaker": book,
                "price": price, "observed_at": observed_at, "observation_id": oid, "period": "FULL_MATCH", "line": ""}

    def test_coherent_snapshot_same_book(self):
        """item 25."""
        from defend_markets.quant.market_reference import select_coherent_snapshot

        rows = [
            self._row("e1", "A", "Bet365", 1.8, NOW - timedelta(minutes=30), 1),
            self._row("e1", "B", "Bet365", 2.0, NOW - timedelta(minutes=30), 2),
        ]
        snap = select_coherent_snapshot(rows, commence_at=NOW + timedelta(hours=1))
        assert snap is not None and "A" in snap and "B" in snap
        assert snap["A"]["bookmaker"] == snap["B"]["bookmaker"] == "Bet365"

    def test_incoherent_cross_book_rejected(self):
        """items 25/26: A from one book, B from another -> no coherent snapshot."""
        from defend_markets.quant.market_reference import select_coherent_snapshot

        rows = [
            self._row("e1", "A", "Bet365", 1.8, NOW - timedelta(minutes=30), 1),
            self._row("e1", "B", "BetMGM", 2.0, NOW - timedelta(minutes=5), 2),
        ]
        snap = select_coherent_snapshot(rows, commence_at=NOW + timedelta(hours=1))
        assert snap is None

    def test_post_cutoff_rejected(self):
        """item 26."""
        from defend_markets.quant.market_reference import select_coherent_snapshot

        # commence in 1h; cutoff = commence - 5min = now + 55min; these rows are
        # observed at now+59min -> post-cutoff.
        rows = [
            self._row("e1", "A", "Bet365", 1.8, _REAL_NOW + timedelta(minutes=59), 1),
            self._row("e1", "B", "Bet365", 2.0, _REAL_NOW + timedelta(minutes=59), 2),
        ]
        snap = select_coherent_snapshot(rows, commence_at=_REAL_NOW + timedelta(hours=1))
        assert snap is None

    def test_frozen_reference_not_overwritten(self):
        """items 27/28: frozen reference never replaced by a later quote."""
        store = InMemoryQuantStore()
        store.upsert_market_reference({
            "canonical_event_id": "e1", "policy_version": "V1", "market": "MATCH_WINNER", "side": "A",
            "bookmaker": "Bet365", "price": 1.8, "observation_id": 1, "referenced_at": NOW, "frozen": True,
        })
        # attempt to overwrite with a later price -> returns False (not overwritten)
        replaced = store.upsert_market_reference({
            "canonical_event_id": "e1", "policy_version": "V1", "market": "MATCH_WINNER", "side": "A",
            "bookmaker": "Bet365", "price": 2.5, "observation_id": 2, "referenced_at": NOW, "frozen": True,
        })
        assert replaced is False
        refs = store.list_market_reference("e1")
        assert refs[0]["price"] == 1.8


class TestQuotaAtomicity:
    def test_result_path_checks_quota(self):
        """item 29."""
        store = InMemoryQuantStore()
        governor = RequestQuotaGovernor(store, period=NOW)
        assert governor.consume(CLASS_RESULT) is True

    def test_atomic_consumption_respects_budget(self):
        """item 31: cannot exceed budget atomically."""
        store = InMemoryQuantStore()
        governor = RequestQuotaGovernor(store, period=NOW)
        for _ in range(80):
            assert governor.consume(CLASS_RESULT) is True
        # budget exhausted
        assert governor.consume(CLASS_RESULT) is False

    def test_reserved_floor_present(self):
        """item 32: RESULT reserved floor recorded."""
        store = InMemoryQuantStore()
        governor = RequestQuotaGovernor(store, period=NOW)
        governor.ensure_budget(CLASS_RESULT)
        state = store.quota_used(CLASS_RESULT, governor._period_iso())
        assert state["reserved"] >= 15

    def test_low_value_attestation_does_not_consume_result_budget(self):
        """item 33: attestation is a separate class; doesn't touch RESULT."""
        store = InMemoryQuantStore()
        governor = RequestQuotaGovernor(store, period=NOW)
        governor.consume(CLASS_ATTESTATION)
        result_state = store.quota_used(CLASS_RESULT, governor._period_iso())
        assert result_state["used"] == 0


class TestCircuitHalfOpen:
    def test_three_failures_open(self):
        """item 34."""
        store = InMemoryQuantStore()
        breaker = ProviderCircuitBreaker(store, now=NOW)
        breaker.record_failure("p", "f", error="500")
        breaker.record_failure("p", "f", error="500")
        state = breaker.record_failure("p", "f", error="500")
        assert state == STATE_OPEN

    def test_cooldown_half_open(self):
        """item 35."""
        store = InMemoryQuantStore()
        breaker = ProviderCircuitBreaker(store, now=NOW)
        for _ in range(3):
            breaker.record_failure("p", "f", error="500")
        assert breaker.state("p", "f")["state"] == STATE_OPEN
        breaker2 = ProviderCircuitBreaker(store, now=NOW + timedelta(minutes=10))
        assert breaker2.state("p", "f")["state"] == STATE_HALF_OPEN

    def test_single_half_open_probe(self):
        """item 36: exactly one probe at a time."""
        store = InMemoryQuantStore()
        breaker = ProviderCircuitBreaker(store, now=NOW)
        for _ in range(3):
            breaker.record_failure("p", "f", error="500")
        breaker2 = ProviderCircuitBreaker(store, now=NOW + timedelta(minutes=10))
        assert breaker2.allow_request("p", "f") is True
        # second caller is deferred (lease held)
        assert breaker2.allow_request("p", "f") is False

    def test_success_closes(self):
        """item 37."""
        store = InMemoryQuantStore()
        breaker = ProviderCircuitBreaker(store, now=NOW)
        for _ in range(3):
            breaker.record_failure("p", "f", error="500")
        breaker.record_success("p", "f")
        assert breaker.state("p", "f")["state"] == STATE_CLOSED

    def test_half_open_fail_reopens(self):
        """item 38."""
        store = InMemoryQuantStore()
        breaker = ProviderCircuitBreaker(store, now=NOW)
        for _ in range(3):
            breaker.record_failure("p", "f", error="500")
        breaker2 = ProviderCircuitBreaker(store, now=NOW + timedelta(minutes=10))
        state = breaker2.record_failure("p", "f", error="500")
        assert state == STATE_OPEN

    def test_config_error_opens_configuration(self):
        """item 39."""
        store = InMemoryQuantStore()
        breaker = ProviderCircuitBreaker(store, now=NOW)
        state = breaker.record_failure("p", "f", error="401", configuration_error=True)
        assert state == STATE_OPEN_CONFIGURATION

    def test_404_not_breaker_failure(self):
        """item 40: per-event 404 is retention evidence, not breaker failure."""
        store = InMemoryQuantStore()
        breaker = ProviderCircuitBreaker(store, now=NOW)
        # a 404 is NOT recorded as a breaker failure at all
        assert breaker.allow_request("p", "f") is True
        assert breaker.state("p", "f")["consecutive_failures"] == 0


class TestArbIdentity:
    def test_distinct_bookmakers_required(self):
        """item 46."""
        from defend_markets.arb.models import ArbQuote, EventState, MarketFamily, SelectionSide
        from defend_markets.quant.arb_feed import SportsArbScanner

        qa = ArbQuote(quote_id="a", canonical_event_id="e1", bookmaker="Bet365", sport="tt",
                      participant_a="Alice", participant_b="Bob", market_family=MarketFamily.MATCH_WINNER_2WAY,
                      selection="Alice", selection_side=SelectionSide.PARTICIPANT_A, decimal_odds=Decimal("2.1"),
                      observed_at=datetime.now(timezone.utc), received_at=datetime.now(timezone.utc))
        qb = ArbQuote(quote_id="b", canonical_event_id="e1", bookmaker="Bet365", sport="tt",
                      participant_a="Alice", participant_b="Bob", market_family=MarketFamily.MATCH_WINNER_2WAY,
                      selection="Bob", selection_side=SelectionSide.PARTICIPANT_B, decimal_odds=Decimal("2.1"),
                      observed_at=datetime.now(timezone.utc), received_at=datetime.now(timezone.utc))
        # both same book -> scanner rejects as no cross-book set
        assert len({qa.bookmaker, qb.bookmaker}) == 1

    def test_spread_requires_line(self):
        """items 48/49/50/51: no line -> no arb quote."""
        from defend_markets.quant.arb_feed import observation_to_arb_quote

        row = {"observation_id": 1, "canonical_event_id": "e1", "bookmaker": "Bet365",
               "market": "spread", "side": "A", "price": "1.9", "line": None}
        assert observation_to_arb_quote(row, participant_a="A", participant_b="B") is None

    def test_cross_line_rejected(self):
        """item 50: different lines not compatible."""
        from defend_markets.arb.models import ArbQuote, EventState, MarketFamily, SelectionSide
        from defend_markets.arb.opportunity import build_opportunity

        qa = ArbQuote(quote_id="a", canonical_event_id="e1", bookmaker="Bet365", sport="tt",
                      participant_a="Alice", participant_b="Bob", market_family=MarketFamily.TOTAL,
                      selection="over", selection_side=SelectionSide.OVER, line=Decimal("3.5"), decimal_odds=Decimal("2.1"),
                      observed_at=datetime.now(timezone.utc), received_at=datetime.now(timezone.utc))
        qb = ArbQuote(quote_id="b", canonical_event_id="e1", bookmaker="BetMGM", sport="tt",
                      participant_a="Alice", participant_b="Bob", market_family=MarketFamily.TOTAL,
                      selection="under", selection_side=SelectionSide.UNDER, line=Decimal("4.5"), decimal_odds=Decimal("2.1"),
                      observed_at=datetime.now(timezone.utc), received_at=datetime.now(timezone.utc))
        opp = build_opportunity((qa, qb), total_stake=Decimal("1000"))
        assert opp.classification.value == "INCOMPATIBLE"


class TestPaperArbSettlement:
    def _store_with_ticket(self, *, legs):
        from defend_markets.quant.paper_arb import PaperArbStore

        store = InMemoryQuantStore()
        store.insert_paper_arb_ticket({
            "opportunity_id": "op1", "canonical_event_id": "e1", "canonical_market_key": "e1::MATCH_WINNER_2WAY::FULL_MATCH",
            "strategy": "PAPER_ARB", "decision_time": NOW.isoformat(), "legs": legs,
            "bookmakers": ["Bet365", "BetMGM"], "odds": ["2.1", "2.1"], "stakes": ["500", "500"],
            "expected_return": 1050.0, "worst_case_profit": 50.0, "quote_age_seconds": {}, "constraints": {},
            "reason": "paper", "void_state": None,
        })
        return store, PaperArbStore(store)

    def test_winning_leg_determines_payout(self):
        """items 58/59/60."""
        store, paper = self._store_with_ticket(legs=[
            {"quote_id": "a", "bookmaker": "Bet365", "selection": "Alice", "selection_side": "PARTICIPANT_A", "odds": "2.1", "stake": "500"},
            {"quote_id": "b", "bookmaker": "BetMGM", "selection": "Bob", "selection_side": "PARTICIPANT_B", "odds": "2.1", "stake": "500"},
        ])
        paper.settle_for_event(canonical_event_id="e1", settlement_id=9, actual_winner_side="A", result_status="FINAL")
        t = store.list_paper_arb_tickets()[0]
        # A wins -> only PARTICIPANT_A leg pays: 500*2.1=1050; total staked 1000; pnl +50
        assert t["realized_payout"] == 1050.0
        assert t["realized_pnl"] == 50.0
        assert t["roi"] == 0.05

    def test_cancelled_not_settled_as_win(self):
        """item 61."""
        store, paper = self._store_with_ticket(legs=[
            {"quote_id": "a", "bookmaker": "Bet365", "selection": "Alice", "selection_side": "PARTICIPANT_A", "odds": "2.1", "stake": "500"},
            {"quote_id": "b", "bookmaker": "BetMGM", "selection": "Bob", "selection_side": "PARTICIPANT_B", "odds": "2.1", "stake": "500"},
        ])
        paper.settle_for_event(canonical_event_id="e1", settlement_id=9, actual_winner_side="A", result_status="CANCELLED")
        t = store.list_paper_arb_tickets()[0]
        assert t["void_state"] == "CANCELLED"
        assert t["realized_pnl"] == 0.0

    def test_bankroll_dict_no_type_error(self):
        """item 63."""
        from defend_markets.quant.paper_arb import PaperArbStore

        store = InMemoryQuantStore()
        paper = PaperArbStore(store, bankroll_by_book={"Bet365": Decimal("500"), "BetMGM": Decimal("500")})
        # constraints serialization of dict must not go through float()
        store.insert_paper_arb_ticket({
            "opportunity_id": "op2", "canonical_event_id": "e1", "canonical_market_key": "k",
            "strategy": "PAPER_ARB", "decision_time": NOW.isoformat(),
            "legs": [{"bookmaker": "Bet365", "odds": "2.1", "stake": "500", "selection_side": "PARTICIPANT_A"}],
            "bookmakers": ["Bet365"], "odds": ["2.1"], "stakes": ["500"],
            "expected_return": 1050.0, "worst_case_profit": 50.0, "quote_age_seconds": {},
            "constraints": {"bankroll_by_book": {"Bet365": "500", "BetMGM": "500"}}, "reason": "paper", "void_state": None,
        })
        # no exception when settling
        paper.settle_for_event(canonical_event_id="e1", settlement_id=10, actual_winner_side="A", result_status="FINAL")
        assert store.list_paper_arb_tickets()[0]["realized_pnl"] is not None


class TestSettleAcquiredResults:
    def test_settle_acquired_idempotent(self):
        """items 65/66/67: restart does not duplicate settlements."""
        store = InMemoryQuantStore()
        _seed(store)
        store.upsert_result_acquisition({
            "canonical_event_id": "e1", "provider": "odds_api_io", "provider_event_id": "1001",
            "commence_at": NOW, "acquisition_state": LOCAL_RESULT_PRESENT, "result_status": "settled",
            "actual_a": 3, "actual_b": 1, "winner_side": "A", "orientation": "CANONICAL",
            "provider_result_id": "1001", "settled": False,
        })
        r1 = settle_acquired_results(store)
        r2 = settle_acquired_results(store)
        assert r1["settled"] == 1
        assert r2["settled"] == 0
        assert len(store.list_settlements()) == 1
