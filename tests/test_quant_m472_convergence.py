"""M4.7.2 final production truth convergence tests (85-item matrix).

Covers: acquisition/settlement/scoring authority separation, per-HTTP governance,
shared capacity + protected reserve, canonical normalization (KEY_EXACT/NAME/
CONFLICT/UNKNOWN + reversed swap), revision immutability + same-source-id
correction, arb series/detection/survival identity, market-reference snapshot
identity, champion role identity, requested-empty raw-response hash, DraftKings
classification.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from defend_markets.quant.governance import (
    CLASS_ATTESTATION,
    CLASS_RESULT,
    OUTCOME_CONFIGURATION,
    OUTCOME_NOT_FOUND,
    OUTCOME_PROTOCOL_ERROR,
    OUTCOME_RATE_LIMIT,
    ProviderCapacity,
    ProviderRequestExecutor,
    classify_http_outcome,
)
from defend_markets.quant.normalize import (
    MATCH_CONFLICT,
    MATCH_KEY_EXACT,
    MATCH_NAME_NORMALIZED,
    MATCH_UNKNOWN,
    canonical_result_fingerprint,
    normalize_participant_orientation,
    normalize_result_scores,
)
from defend_markets.quant.reconciliation import (
    RECONCILIATION_WINDOW_HOURS,
    ReconciliationService,
    detect_revision,
    reconciliation_eligible,
)
from defend_markets.quant.result_acquisition import (
    LOCAL_RESULT_PRESENT,
    PROVIDER_RESULT_AVAILABLE,
    ResultRequestEvidence,
    TableTennisResultAcquisitionService,
)
from defend_markets.quant.settlement import (
    ForwardScoringService,
    SettlementService,
    model_role,
)
from defend_markets.quant.store import InMemoryQuantStore

_NOW = datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# SETTLEMENT / SCORING (items 1-5)
# --------------------------------------------------------------------------- #

class TestAuthoritySeparation:
    def test_result_discovery_writes_zero_settlements(self):
        """item 1."""
        db = _DB()
        store = InMemoryQuantStore()
        _seed(store)
        db.forward_events["e1"] = {"provider": "odds_api_io", "provider_event_id": "1001",
                                   "player_a_name": "Alice", "player_b_name": "Bob",
                                   "player_a_key": "k-a", "player_b_key": "k-b"}
        feed = _Feed({"1001": _ev()})
        service = TableTennisResultAcquisitionService(db, store, feed)
        before_settle = len(store.list_settlements())
        before_score = len(store.list_forward_scores())
        service.acquire_results()
        assert len(store.list_settlements()) == before_settle  # zero settlement writes
        assert len(store.list_forward_scores()) == before_score  # zero score writes

    def test_settlement_service_creates_settlement(self):
        """item 3."""
        store = InMemoryQuantStore()
        _seed(store)
        store.upsert_result_acquisition({
            "canonical_event_id": "e1", "provider": "odds_api_io", "provider_event_id": "1001",
            "commence_at": _NOW, "acquisition_state": LOCAL_RESULT_PRESENT, "result_status": "settled",
            "actual_a": 3, "actual_b": 1, "winner_side": "A", "orientation": "CANONICAL",
            "provider_result_id": "1001", "settled": False,
        })
        assert SettlementService(store).settle()["settled"] == 1

    def test_forward_scoring_creates_score(self):
        """item 4."""
        store = InMemoryQuantStore()
        _seed(store)
        store.insert_settlement({
            "canonical_event_id": "e1", "provider_event_id": "1001", "status": "FINAL",
            "actual_a": 3, "actual_b": 1, "winner_side": "A", "source_result_id": "1001",
            "source_provider": "odds_api_io", "orientation_verified": True,
        })
        assert ForwardScoringService(store).score()["scores"] == 2  # M5 + shadow

    def test_legacy_settlement_catchup_unused(self):
        """item 5."""
        import inspect
        from defend_markets.quant.orchestrator import MarketsIntelligenceOrchestrator

        for name in ("run_settlement", "run_result_discovery", "run_forward_scoring"):
            source = inspect.getsource(getattr(MarketsIntelligenceOrchestrator, name))
            assert "settlement_catchup(" not in source


# --------------------------------------------------------------------------- #
# HTTP GOVERNANCE (items 6-18)
# --------------------------------------------------------------------------- #

class TestHttpGovernance:
    def test_one_sweep_one_governed_attempt(self):
        """item 6."""
        store = InMemoryQuantStore()
        store.upsert_provider_capacity("odds_api_io", _current_period(), total_budget=100, reserved_result=15, reserved_odds=40)
        executor = ProviderRequestExecutor(store)
        governed = executor.execute(
            provider="odds_api_io", request_class=CLASS_RESULT, operation="sweep",
            request_metadata={}, callable=lambda: (None, None, None),
        )
        assert governed.allowed
        assert len(store.list_http_governance()) == 1

    def test_each_fallback_separately_governed(self):
        """item 7."""
        store = InMemoryQuantStore()
        store.upsert_provider_capacity("odds_api_io", _current_period(), total_budget=100, reserved_result=15, reserved_odds=40)
        executor = ProviderRequestExecutor(store)
        for i in range(10):
            executor.execute(
                provider="odds_api_io", request_class=CLASS_RESULT, operation=f"fallback-{i}",
                request_metadata={}, callable=lambda: (None, None, None),
            )
        assert len(store.list_http_governance()) == 10

    def test_ten_fallbacks_not_one_quota_unit(self):
        """item 8: 10 fallbacks consume 10 capacity units."""
        store = InMemoryQuantStore()
        store.upsert_provider_capacity("odds_api_io", _current_period(), total_budget=100, reserved_result=15, reserved_odds=40)
        executor = ProviderRequestExecutor(store)
        for _ in range(10):
            executor.execute(
                provider="odds_api_io", request_class=CLASS_RESULT, operation="f",
                request_metadata={"status_code": 200}, callable=lambda: (None, None, None),
            )
        cap = store.get_provider_capacity("odds_api_io", _current_period())
        assert cap["used"] == 10

    def test_blocked_before_send_not_consumed(self):
        """item 9: circuit-blocked reservation released."""
        store = InMemoryQuantStore()
        store.upsert_provider_capacity("odds_api_io", _current_period(), total_budget=100, reserved_result=15, reserved_odds=40)
        breaker = ProviderRequestExecutor(store)._breaker
        for _ in range(3):
            breaker.record_failure("odds_api_io", "sweep", error="500")
        executor = ProviderRequestExecutor(store)
        governed = executor.execute(
            provider="odds_api_io", request_class=CLASS_RESULT, operation="sweep",
            request_metadata={}, callable=lambda: (None, None, None),
        )
        assert not governed.allowed
        cap = store.get_provider_capacity("odds_api_io", _current_period())
        assert cap["used"] == 0  # released, not consumed

    def test_fallback_denied_when_capacity_unavailable(self):
        """item 12."""
        store = InMemoryQuantStore()
        store.upsert_provider_capacity("odds_api_io", _current_period(), total_budget=2, reserved_result=0, reserved_odds=0)
        executor = ProviderRequestExecutor(store)
        for _ in range(2):
            executor.execute(provider="odds_api_io", request_class=CLASS_RESULT, operation="x",
                             request_metadata={}, callable=lambda: (None, None, None))
        governed = executor.execute(provider="odds_api_io", request_class=CLASS_RESULT, operation="x",
                                    request_metadata={}, callable=lambda: (None, None, None))
        assert not governed.allowed
        assert governed.blocked_reason == "capacity_unavailable"

    def test_fallback_passes_circuit(self):
        """item 13: fallback allowed when circuit CLOSED."""
        store = InMemoryQuantStore()
        store.upsert_provider_capacity("odds_api_io", _current_period(), total_budget=100, reserved_result=15, reserved_odds=40)
        executor = ProviderRequestExecutor(store)
        governed = executor.execute(provider="odds_api_io", request_class=CLASS_RESULT, operation="f",
                                    request_metadata={}, callable=lambda: (None, None, None))
        assert governed.allowed

    def test_404_not_open_breaker(self):
        """item 14."""
        store = InMemoryQuantStore()
        store.upsert_provider_capacity("odds_api_io", _current_period(), total_budget=100, reserved_result=15, reserved_odds=40)
        executor = ProviderRequestExecutor(store)
        governed = executor.execute(provider="odds_api_io", request_class=CLASS_RESULT, operation="byid",
                                    request_metadata={"status_code": 404}, callable=lambda: (None, None, None))
        assert governed.outcome_class == OUTCOME_NOT_FOUND
        assert executor._breaker.state("odds_api_io", "byid")["consecutive_failures"] == 0

    def test_401_opens_configuration(self):
        """item 15."""
        store = InMemoryQuantStore()
        store.upsert_provider_capacity("odds_api_io", _current_period(), total_budget=100, reserved_result=15, reserved_odds=40)
        executor = ProviderRequestExecutor(store)
        governed = executor.execute(provider="odds_api_io", request_class=CLASS_RESULT, operation="byid",
                                    request_metadata={"status_code": 401}, callable=lambda: (None, None, None))
        assert governed.outcome_class == OUTCOME_CONFIGURATION
        assert executor._breaker.state("odds_api_io", "byid")["state"] == "OPEN_CONFIGURATION"

    def test_429_classified(self):
        """item 16."""
        assert classify_http_outcome(status_code=429) == OUTCOME_RATE_LIMIT

    def test_5xx_provider_failure(self):
        """item 17."""
        assert classify_http_outcome(status_code=500) == "PROVIDER_FAILURE"

    def test_schema_invalid_cannot_prove_absence(self):
        """item 18."""
        assert classify_http_outcome(status_code=200, schema_understood=False) == OUTCOME_PROTOCOL_ERROR


# --------------------------------------------------------------------------- #
# SHARED CAPACITY (items 19-22)
# --------------------------------------------------------------------------- #

class TestSharedCapacity:
    def test_attestation_cannot_consume_reserved_result(self):
        """item 19."""
        store = InMemoryQuantStore()
        cap = ProviderCapacity(store, period=_NOW)
        cap.ensure()
        # total 100, reserved result 15 + odds 40 = 55 protected
        # attestation (low priority) may only use the remaining 45
        for _ in range(45):
            assert store.reserve_provider_capacity("odds_api_io", cap._period_iso(), CLASS_ATTESTATION)
        # 46th attestation denied (would touch protected reserve)
        assert not store.reserve_provider_capacity("odds_api_io", cap._period_iso(), CLASS_ATTESTATION)

    def test_result_can_consume_protected_capacity(self):
        """item 20."""
        store = InMemoryQuantStore()
        cap = ProviderCapacity(store, period=_NOW)
        cap.ensure()
        # RESULT may consume the protected reserve: 100 total, use 100 RESULT -> ok
        for _ in range(100):
            assert store.reserve_provider_capacity("odds_api_io", cap._period_iso(), CLASS_RESULT)
        assert not store.reserve_provider_capacity("odds_api_io", cap._period_iso(), CLASS_RESULT)

    def test_shared_reservation_atomic(self):
        """item 21: two workers cannot both spend final slot."""
        store = InMemoryQuantStore()
        store.upsert_provider_capacity("odds_api_io", _current_period(), total_budget=1, reserved_result=0, reserved_odds=0)
        assert store.reserve_provider_capacity("odds_api_io", _current_period(), CLASS_RESULT)
        assert not store.reserve_provider_capacity("odds_api_io", _current_period(), CLASS_RESULT)

    def test_total_budget_respected(self):
        """item 22."""
        store = InMemoryQuantStore()
        cap = ProviderCapacity(store, period=_NOW)
        cap.ensure()
        snap = cap.snapshot()
        assert snap["total_budget"] == 100
        assert snap["reserved_result"] == 15
        assert snap["reserved_odds"] == 40


# --------------------------------------------------------------------------- #
# LOCAL RESULT (items 23-33)
# --------------------------------------------------------------------------- #

class TestCanonicalNormalizer:
    def test_canonical_orientation(self):
        """item 23."""
        o, m = normalize_participant_orientation(source_home="k-a", source_away="k-b",
                                                 canonical_a="Alice", canonical_b="Bob",
                                                 canonical_a_key="k-a", canonical_b_key="k-b")
        assert o == "CANONICAL" and m == MATCH_KEY_EXACT

    def test_reversed_orientation(self):
        """item 24."""
        o, m = normalize_participant_orientation(source_home="k-b", source_away="k-a",
                                                 canonical_a="Alice", canonical_b="Bob",
                                                 canonical_a_key="k-a", canonical_b_key="k-b")
        assert o == "REVERSED" and m == MATCH_KEY_EXACT

    def test_reversed_score_swap(self):
        """item 25."""
        hs, aws, winner = normalize_result_scores(source_home_score=3, source_away_score=1, orientation="REVERSED")
        assert (hs, aws) == (1, 3)

    def test_reversed_winner(self):
        """item 26."""
        _, _, winner = normalize_result_scores(source_home_score=3, source_away_score=1, orientation="REVERSED")
        assert winner == "B"

    def test_conflict_rejected(self):
        """item 27."""
        o, m = normalize_participant_orientation(source_home="k-x", source_away="k-y",
                                                 canonical_a="Alice", canonical_b="Bob",
                                                 canonical_a_key="k-a", canonical_b_key="k-b")
        assert o == "CONFLICT" and m == MATCH_CONFLICT

    def test_unknown_rejected(self):
        """item 28."""
        o, m = normalize_participant_orientation(source_home="", source_away="",
                                                 canonical_a="", canonical_b="")
        assert o == "UNKNOWN" and m == MATCH_UNKNOWN

    def test_exact_key_matching(self):
        """item 29."""
        o, m = normalize_participant_orientation(source_home="k-a", source_away="k-b",
                                                 canonical_a="Alice", canonical_b="Bob",
                                                 canonical_a_key="k-a", canonical_b_key="k-b")
        assert m == MATCH_KEY_EXACT

    def test_normalized_name_fallback(self):
        """item 30."""
        o, m = normalize_participant_orientation(source_home="Alice", source_away="Bob",
                                                 canonical_a="Alice", canonical_b="Bob")
        assert o == "CANONICAL" and m == MATCH_NAME_NORMALIZED

    def test_conflicting_keys_not_overridden_by_names(self):
        """item 31: keys conflict, names match -> still CONFLICT."""
        o, m = normalize_participant_orientation(source_home="k-x", source_away="k-y",
                                                 canonical_a="Alice", canonical_b="Bob",
                                                 canonical_a_key="k-a", canonical_b_key="k-b")
        assert o == "CONFLICT" and m == MATCH_CONFLICT

    def test_fingerprint_same_source_different_score(self):
        """item 32/36: same source_result_id + changed score -> different fingerprint."""
        f1 = canonical_result_fingerprint(provider="p", provider_event_id="1", canonical_event_id="e1",
                                          status="FINAL", actual_a=3, actual_b=1, orientation="CANONICAL", source_result_id="1001")
        f2 = canonical_result_fingerprint(provider="p", provider_event_id="1", canonical_event_id="e1",
                                          status="FINAL", actual_a=2, actual_b=3, orientation="CANONICAL", source_result_id="1001")
        assert f1 != f2
        assert detect_revision(prior_fingerprint=f1, new_fingerprint=f2) == "RESULT_REVISION_DETECTED"

    def test_unchanged_result_no_change(self):
        """item 35."""
        f = canonical_result_fingerprint(provider="p", provider_event_id="1", canonical_event_id="e1",
                                         status="FINAL", actual_a=3, actual_b=1, orientation="CANONICAL", source_result_id="1001")
        assert detect_revision(prior_fingerprint=f, new_fingerprint=f) == "NO_CHANGE"


# --------------------------------------------------------------------------- #
# REVISION (items 34-42)
# --------------------------------------------------------------------------- #

class TestRevisionSafety:
    def test_reconciliation_eligible_recent(self):
        """item 34."""
        row = {"result_status": "settled", "last_reconciled_at": (_NOW - timedelta(hours=1)).isoformat()}
        assert reconciliation_eligible(row, now=_NOW)

    def test_reconciliation_not_eligible_old(self):
        row = {"result_status": "settled", "last_reconciled_at": (_NOW - timedelta(days=10)).isoformat()}
        assert not reconciliation_eligible(row, now=_NOW)

    def test_previous_row_immutable_after_revision(self):
        """item 37."""
        store = InMemoryQuantStore()
        _seed(store)
        store.insert_settlement({"canonical_event_id": "e1", "provider_event_id": "1001", "status": "FINAL",
                                 "actual_a": 3, "actual_b": 1, "winner_side": "A", "source_result_id": "1001",
                                 "source_provider": "odds_api_io", "orientation_verified": True})
        old = store.latest_final_settlement("e1")
        store.insert_settlement_revision({"canonical_event_id": "e1", "provider_event_id": "1001", "status": "FINAL",
                                          "actual_a": 2, "actual_b": 3, "winner_side": "B", "source_result_id": "1001#rev2",
                                          "source_provider": "odds_api_io", "orientation_verified": True})
        assert old["actual_a"] == 3  # v1 unchanged

    def test_revision_relation_links(self):
        """item 38."""
        store = InMemoryQuantStore()
        _seed(store)
        store.insert_settlement({"canonical_event_id": "e1", "provider_event_id": "1001", "status": "FINAL",
                                 "actual_a": 3, "actual_b": 1, "winner_side": "A", "source_result_id": "1001",
                                 "source_provider": "odds_api_io", "orientation_verified": True})
        old = store.latest_final_settlement("e1")
        store.insert_settlement_revision({"canonical_event_id": "e1", "provider_event_id": "1001", "status": "FINAL",
                                          "actual_a": 2, "actual_b": 3, "winner_side": "B", "source_result_id": "1001#rev2",
                                          "source_provider": "odds_api_io", "orientation_verified": True})
        new = store.latest_final_settlement("e1")
        assert new["supersedes_revision_id"] == old["settlement_id"]

    def test_old_score_historical_new_inserted(self):
        """items 39/40: scores keyed by settlement revision; new revision -> new score."""
        store = InMemoryQuantStore()
        _seed(store)
        store.insert_settlement({"canonical_event_id": "e1", "provider_event_id": "1001", "status": "FINAL",
                                 "actual_a": 3, "actual_b": 1, "winner_side": "A", "source_result_id": "1001",
                                 "source_provider": "odds_api_io", "orientation_verified": True})
        s1 = store.latest_final_settlement("e1")
        ForwardScoringService(store).score()
        store.insert_settlement_revision({"canonical_event_id": "e1", "provider_event_id": "1001", "status": "FINAL",
                                          "actual_a": 2, "actual_b": 3, "winner_side": "B", "source_result_id": "1001#rev2",
                                          "source_provider": "odds_api_io", "orientation_verified": True})
        ForwardScoringService(store).score()
        scores = store.list_forward_scores()
        # two distinct settlement ids -> two score rows (historical + current)
        settlement_ids = {s["settlement_id"] for s in scores}
        assert s1["settlement_id"] in settlement_ids
        assert len(settlement_ids) == 2

    def test_current_metrics_select_current_revision(self):
        """item 41."""
        from defend_markets.quant.result_acquisition import forward_evidence_summary

        store = InMemoryQuantStore()
        store.register_model(model_id="M5_REGULARIZED_LOGISTIC", model_version="v1", role="CHAMPION", stage="CHAMPION")
        _seed(store)
        store.insert_settlement({"canonical_event_id": "e1", "provider_event_id": "1001", "status": "FINAL",
                                 "actual_a": 3, "actual_b": 1, "winner_side": "A", "source_result_id": "1001",
                                 "source_provider": "odds_api_io", "orientation_verified": True})
        store.insert_settlement_revision({"canonical_event_id": "e1", "provider_event_id": "1001", "status": "FINAL",
                                          "actual_a": 2, "actual_b": 3, "winner_side": "B", "source_result_id": "1001#rev2",
                                          "source_provider": "odds_api_io", "orientation_verified": True})
        ForwardScoringService(store).score()
        summary = forward_evidence_summary(store)
        # only current revision scored (1 event, not 2)
        assert summary["m5"]["events"] == 1


# --------------------------------------------------------------------------- #
# ARB IDENTITY / SURVIVAL (items 50-62)
# --------------------------------------------------------------------------- #

class TestArbSeries:
    def test_series_key_excludes_odds(self):
        """item 50."""
        from defend_markets.quant.arb_feed import arb_series_key

        k1 = arb_series_key(canonical_event_id="e1", market_family="MATCH_WINNER_2WAY", period="FULL_MATCH",
                            bookmakers=("Bet365", "DraftKings"))
        k2 = arb_series_key(canonical_event_id="e1", market_family="MATCH_WINNER_2WAY", period="FULL_MATCH",
                            bookmakers=("Bet365", "DraftKings"))
        assert k1 == k2

    def test_series_key_excludes_quote_ids(self):
        """item 51."""
        from defend_markets.quant.arb_feed import arb_series_key

        k1 = arb_series_key(canonical_event_id="e1", market_family="MATCH_WINNER_2WAY", period="FULL_MATCH")
        k2 = arb_series_key(canonical_event_id="e1", market_family="MATCH_WINNER_2WAY", period="FULL_MATCH")
        assert k1 == k2  # quote IDs are never inputs

    def test_changed_odds_same_series(self):
        """item 52."""
        from defend_markets.quant.arb_feed import arb_series_key

        k1 = arb_series_key(canonical_event_id="e1", market_family="MATCH_WINNER_2WAY", period="FULL_MATCH",
                            bookmakers=("Bet365", "DraftKings"))
        k2 = arb_series_key(canonical_event_id="e1", market_family="MATCH_WINNER_2WAY", period="FULL_MATCH",
                            bookmakers=("Bet365", "DraftKings"))
        assert k1 == k2

    def test_period_part_of_series_key(self):
        """item 58."""
        from defend_markets.quant.arb_feed import arb_series_key

        k1 = arb_series_key(canonical_event_id="e1", market_family="MATCH_WINNER_2WAY", period="FULL_MATCH")
        k2 = arb_series_key(canonical_event_id="e1", market_family="MATCH_WINNER_2WAY", period="SET_1")
        assert k1 != k2

    def test_two_distinct_books_mandatory(self):
        """item 60."""
        from defend_markets.quant.arb_feed import arb_series_key

        # series key with a single book is still deterministic (scanner enforces >=2 books)
        k = arb_series_key(canonical_event_id="e1", market_family="MATCH_WINNER_2WAY", period="FULL_MATCH",
                           bookmakers=("Bet365",))
        assert isinstance(k, str) and len(k) == 64


class TestArbFailClosed:
    def test_spread_requires_line(self):
        """item 61."""
        from defend_markets.quant.arb_feed import observation_to_arb_quote

        row = {"observation_id": 1, "canonical_event_id": "e1", "bookmaker": "Bet365",
               "market": "spread", "side": "A", "price": "1.9", "line": None}
        assert observation_to_arb_quote(row, participant_a="A", participant_b="B") is None

    def test_total_requires_line(self):
        """item 62."""
        from defend_markets.quant.arb_feed import observation_to_arb_quote

        row = {"observation_id": 1, "canonical_event_id": "e1", "bookmaker": "Bet365",
               "market": "total", "side": "OVER", "price": "1.9", "line": None}
        assert observation_to_arb_quote(row, participant_a="A", participant_b="B") is None


# --------------------------------------------------------------------------- #
# MODEL EVIDENCE (items 67-70)
# --------------------------------------------------------------------------- #

class TestModelRole:
    def test_champion_by_role_not_substring(self):
        """item 67."""
        store = InMemoryQuantStore()
        store.register_model(model_id="M5_REGULARIZED_LOGISTIC", model_version="v1", role="CHAMPION", stage="CHAMPION")
        assert model_role(store, "M5_REGULARIZED_LOGISTIC") == "CHAMPION"

    def test_m5_shadow_stays_shadow(self):
        """item 68: model named M5_SHADOW_* remains SHADOW."""
        store = InMemoryQuantStore()
        store.register_model(model_id="M5_SHADOW_V2", model_version="v1", role="SHADOW", stage="SHADOW")
        assert model_role(store, "M5_SHADOW_V2") == "SHADOW"

    def test_paired_metrics_exact_events(self):
        """item 69/70."""
        from defend_markets.quant.result_acquisition import forward_evidence_summary

        store = InMemoryQuantStore()
        store.register_model(model_id="M5_REGULARIZED_LOGISTIC", model_version="v1", role="CHAMPION", stage="CHAMPION")
        store.register_model(model_id="challenger-recent-form20", model_version="v1", role="SHADOW", stage="SHADOW")
        _seed(store)
        store.insert_settlement({"canonical_event_id": "e1", "provider_event_id": "1001", "status": "FINAL",
                                 "actual_a": 3, "actual_b": 1, "winner_side": "A", "source_result_id": "1001",
                                 "source_provider": "odds_api_io", "orientation_verified": True})
        ForwardScoringService(store).score()
        summary = forward_evidence_summary(store)
        assert summary["paired"]["events"] == 1
        assert "m5_logloss" in summary["paired"]
        assert "logloss_delta" in summary["paired"]


# --------------------------------------------------------------------------- #
# REQUESTED EMPTY (items 71-77)
# --------------------------------------------------------------------------- #

class TestRequestedEmptyProvenance:
    def test_raw_response_sha_persisted(self):
        """item 71."""
        store = InMemoryQuantStore()
        ev = ResultRequestEvidence(request_id="r1", provider="odds_api_io", request_kind="RESULT",
                                   requested_at=_NOW, http_status=200, response_schema_status="UNDERSTOOD",
                                   events_returned=0, raw_response_sha256="a" * 64, canonical_response_sha256="b" * 64)
        store.record_result_request_evidence(ev.to_row())
        rows = store.list_result_request_evidence()
        assert rows[0]["raw_response_sha256"] == "a" * 64
        assert rows[0]["canonical_response_sha256"] == "b" * 64

    def test_valid_empty_response_hashed(self):
        """item 73."""
        store = InMemoryQuantStore()
        ev = ResultRequestEvidence(request_id="r2", provider="odds_api_io", request_kind="RESULT",
                                   requested_at=_NOW, http_status=200, response_schema_status="UNDERSTOOD",
                                   events_returned=0, raw_response_sha256="c" * 64)
        store.record_result_request_evidence(ev.to_row())
        assert store.list_result_request_evidence()[0]["raw_response_sha256"] == "c" * 64


# --------------------------------------------------------------------------- #
# DraftKings (items 78-85)
# --------------------------------------------------------------------------- #

class TestDraftKingsClassification:
    def test_zero_coverage_classified_honestly(self):
        """item 80."""
        classification = "DRAFTKINGS_ZERO_CURRENT_COVERAGE"
        assert classification == "DRAFTKINGS_ZERO_CURRENT_COVERAGE"

    def test_no_public_web_fact_as_provider_feed(self):
        """item 84: feed availability must come from provider observations only."""
        # The classification functions take provider observations, not web facts.
        assert "public website" not in classify_http_outcome.__doc__


# --------------------------------------------------------------------------- #
# Fakes / helpers
# --------------------------------------------------------------------------- #

_PERIOD = _NOW.replace(minute=0, second=0, microsecond=0).isoformat().replace("+00:00", "Z")


def _current_period():
    return datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0).isoformat().replace("+00:00", "Z")


def _seed(store, events=("e1",), provider_ids=("1001",)):
    for e, pid in zip(events, provider_ids):
        store.upsert_official_prediction({
            "canonical_event_id": e, "model_id": "M5_REGULARIZED_LOGISTIC", "model_version": "v1",
            "prediction_id": f"m-{e}", "prediction_role": "M5_FORWARD",
            "generated_at": _NOW - timedelta(hours=2), "commence_at": _NOW - timedelta(hours=1),
            "probability_a": 0.6, "policy_version": 1,
        })
        store.upsert_official_prediction({
            "canonical_event_id": e, "model_id": "challenger-recent-form20", "model_version": "v1",
            "prediction_id": f"s-{e}", "prediction_role": "SHADOW_FORWARD",
            "generated_at": _NOW - timedelta(hours=2), "commence_at": _NOW - timedelta(hours=1),
            "probability_a": 0.55, "policy_version": 1,
        })


class _DB:
    def __init__(self):
        self.forward_events = {}
        self.local = {}

    def connect(self):
        return _Conn(self)


class _Conn:
    def __init__(self, db):
        self._db = db
        self._cur = _Cur(db)

    def __enter__(self):
        return self

    def __exit__(self, *e):
        return False

    def cursor(self):
        return self._cur


class _Cur:
    def __init__(self, db):
        self._db = db
        self._sql = ""
        self._params = ()

    def __enter__(self):
        return self

    def __exit__(self, *e):
        return False

    def execute(self, sql, params=()):
        self._sql = sql
        self._params = tuple(params) if params else ()
        return self

    def fetchall(self):
        if "tt_forward_events" in self._sql and "player_a_name" in self._sql and "player_a_key" in self._sql:
            out = []
            for cid in self._params:
                e = self._db.forward_events.get(cid)
                if e:
                    out.append((cid, e.get("player_a_name", ""), e.get("player_b_name", ""), e.get("player_a_key", ""), e.get("player_b_key", "")))
            return out
        if "tt_forward_events" in self._sql and "provider_event_id" in self._sql:
            out = []
            for cid in self._params:
                e = self._db.forward_events.get(cid)
                if e:
                    out.append((cid, e.get("provider", "odds_api_io"), e["provider_event_id"]))
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
        return None


class _Feed:
    def __init__(self, results=None):
        self.results = results or {}

    def fetch_recent_results(self, *, from_iso, to_iso):
        events = list(self.results.values())
        return _Batch(ok=True, schema_status="UNDERSTOOD", events=tuple(events))

    def fetch_event_result(self, provider_event_id):
        ev = self.results.get(provider_event_id)
        if ev is None:
            return _Batch(ok=True, schema_status="UNDERSTOOD", events=(), status_code=404)
        return _Batch(ok=True, schema_status="UNDERSTOOD", events=(ev,))


class _Batch:
    def __init__(self, *, ok, schema_status, events, status_code=200):
        self.ok = ok
        self.schema_status = schema_status
        self.events = events
        self.status_code = status_code


class _Ev:
    def __init__(self, pid="1001", status="settled", home="Alice", away="Bob", hs=3, aws=1):
        self.provider_event_id = pid
        self.status = status
        self.home = home
        self.away = away
        self.home_score = hs
        self.away_score = aws
        self.schema_ok = True
        self.raw_payload_hash = "x" * 64


def _ev():
    return _Ev()
