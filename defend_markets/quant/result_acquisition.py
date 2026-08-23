"""M4.7 result acquisition truth.

Splits the old "RESULT_PROVIDER_EMPTY" conflation into precise acquisition
states. A missing row in the local results table is NEVER treated as proof the
external provider returned no result: that requires an actual provider request
producing empty evidence.

Layers (kept separable per P1):

* provider acquisition — a :class:`CanonicalResultFeed` adapter queries the
  provider for settled/final event data (OddsApiIOResultAdapter first).
* normalization — provider "home"/"away" maps onto canonical participant
  orientation via the existing market-truth orientation system (P6).
* persistence — a normalized result is written to tt_match_results only when
  identity and orientation resolve.
* settlement — FINAL settlement records (revisions never overwrite history).
* scoring — official forward predictions are scored per unique canonical event.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol

from defend_markets.quant.forward_evidence import (
    LOGLOSS_EPSILON,
    LOGLOSS_EPSILON_POLICY,
    SCORING_POLICY_VERSION,
    score_prediction,
)
from defend_markets.quant.normalize import canonical_result_fingerprint

RESULT_ACQUISITION_POLICY_VERSION = "RESULT_ACQUISITION_POLICY_V1"
RESULT_POLL_POLICY_VERSION = "RESULT_POLL_POLICY_V1"

# P0 precise acquisition states.
LOCAL_RESULT_PRESENT = "LOCAL_RESULT_PRESENT"
LOCAL_RESULT_MISSING_NOT_REQUESTED = "LOCAL_RESULT_MISSING_NOT_REQUESTED"
PROVIDER_RESULT_REQUESTED_EMPTY = "PROVIDER_RESULT_REQUESTED_EMPTY"
PROVIDER_RESULT_AVAILABLE = "PROVIDER_RESULT_AVAILABLE"
PROVIDER_RESULT_ERROR = "PROVIDER_RESULT_ERROR"
PROVIDER_RESULT_SCHEMA_UNKNOWN = "PROVIDER_RESULT_SCHEMA_UNKNOWN"
PROVIDER_EVENT_NOT_FOUND = "PROVIDER_EVENT_NOT_FOUND"
PROVIDER_EVENT_IDENTITY_MISMATCH = "PROVIDER_EVENT_IDENTITY_MISMATCH"
RESULT_RECONCILIATION_REQUIRED = "RESULT_RECONCILIATION_REQUIRED"
# P5: provider 404 may represent retention, not an empty result search.
PROVIDER_RESULT_OUTSIDE_RETENTION = "PROVIDER_RESULT_OUTSIDE_RETENTION"

_ACQUISITION_STATES = (
    LOCAL_RESULT_PRESENT,
    LOCAL_RESULT_MISSING_NOT_REQUESTED,
    PROVIDER_RESULT_REQUESTED_EMPTY,
    PROVIDER_RESULT_AVAILABLE,
    PROVIDER_RESULT_ERROR,
    PROVIDER_RESULT_SCHEMA_UNKNOWN,
    PROVIDER_EVENT_NOT_FOUND,
    PROVIDER_EVENT_IDENTITY_MISMATCH,
    RESULT_RECONCILIATION_REQUIRED,
    PROVIDER_RESULT_OUTSIDE_RETENTION,
)

# P7 result state machine (persisted in quant_settlements.status).
RESULT_STATE_PENDING = "PENDING"
RESULT_STATE_PROVISIONAL = "PROVISIONAL"
RESULT_STATE_FINAL = "FINAL"
RESULT_STATE_VOID = "VOID"
RESULT_STATE_CANCELLED = "CANCELLED"
RESULT_STATE_POSTPONED = "POSTPONED"
RESULT_STATE_ABANDONED = "ABANDONED"
RESULT_STATE_REVIEW_REQUIRED = "REVIEW_REQUIRED"
RESULT_STATE_SUPERSEDED = "SUPERSEDED"

# provider "status" literal -> canonical result state
_PROVIDER_STATUS_TO_RESULT = {
    "settled": RESULT_STATE_FINAL,
    "cancelled": RESULT_STATE_CANCELLED,
    "postponed": RESULT_STATE_POSTPONED,
    "abandoned": RESULT_STATE_ABANDONED,
    "void": RESULT_STATE_VOID,
    "pending": RESULT_STATE_PENDING,
    "live": RESULT_STATE_PENDING,
}

# P13 allowed state transitions. A result may move only along these edges.
ALLOWED_RESULT_TRANSITIONS: dict[str, frozenset[str]] = {
    RESULT_STATE_PENDING: frozenset({RESULT_STATE_FINAL, RESULT_STATE_CANCELLED, RESULT_STATE_POSTPONED, RESULT_STATE_ABANDONED, RESULT_STATE_VOID, RESULT_STATE_REVIEW_REQUIRED, RESULT_STATE_PROVISIONAL}),
    RESULT_STATE_PROVISIONAL: frozenset({RESULT_STATE_FINAL, RESULT_STATE_VOID, RESULT_STATE_CANCELLED, RESULT_STATE_REVIEW_REQUIRED}),
    RESULT_STATE_FINAL: frozenset({RESULT_STATE_SUPERSEDED}),
    RESULT_STATE_VOID: frozenset({RESULT_STATE_FINAL}),
    RESULT_STATE_CANCELLED: frozenset(),
    RESULT_STATE_POSTPONED: frozenset({RESULT_STATE_FINAL, RESULT_STATE_CANCELLED, RESULT_STATE_ABANDONED}),
    RESULT_STATE_ABANDONED: frozenset(),
    RESULT_STATE_REVIEW_REQUIRED: frozenset({RESULT_STATE_FINAL, RESULT_STATE_VOID, RESULT_STATE_CANCELLED}),
    RESULT_STATE_SUPERSEDED: frozenset(),
}


def result_transition_allowed(from_state: str, to_state: str) -> bool:
    return to_state in ALLOWED_RESULT_TRANSITIONS.get(from_state, frozenset())


@dataclass(frozen=True)
class ResultRequestEvidence:
    """P2: first-class immutable request evidence.

    A per-event state may use PROVIDER_RESULT_REQUESTED_EMPTY only when this
    evidence shows the request genuinely succeeded, the response schema was
    understood, and the request scope actually included that event.
    """

    request_id: str
    provider: str
    request_kind: str
    requested_at: datetime
    window_start: str | None = None
    window_end: str | None = None
    target_event_count: int = 0
    http_status: int | None = None
    provider_request_status: str | None = None
    response_schema_status: str = "UNKNOWN"  # UNDERSTOOD / UNKNOWN / INVALID
    events_returned: int = 0
    events_matched: int = 0
    raw_payload_hash: str | None = None
    raw_response_sha256: str | None = None
    canonical_response_sha256: str | None = None
    error_class: str | None = None
    successful_search_scope: str | None = None

    def to_row(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "provider": self.provider,
            "request_kind": self.request_kind,
            "requested_at": self.requested_at.isoformat().replace("+00:00", "Z"),
            "window_start": self.window_start,
            "window_end": self.window_end,
            "target_event_count": self.target_event_count,
            "http_status": self.http_status,
            "provider_request_status": self.provider_request_status,
            "response_schema_status": self.response_schema_status,
            "events_returned": self.events_returned,
            "events_matched": self.events_matched,
            "raw_payload_hash": self.raw_payload_hash,
            "raw_response_sha256": self.raw_response_sha256,
            "canonical_response_sha256": self.canonical_response_sha256,
            "error_class": self.error_class,
            "successful_search_scope": self.successful_search_scope,
        }


@dataclass(frozen=True)
class ProviderResultEvent:
    """Normalized provider result evidence for one event."""

    provider_event_id: str
    status: str  # provider literal (settled/cancelled/...)
    home: str = ""
    away: str = ""
    home_score: int | None = None
    away_score: int | None = None
    completed_at: datetime | None = None
    raw_payload_hash: str = ""
    schema_ok: bool = True
    schema_error: str | None = None


@dataclass(frozen=True)
class ProviderResultBatch:
    """Bounded provider response for one request (P6 request-count truth)."""

    request_kind: str
    events_requested: int = 0  # HTTP request count
    events_returned: int = 0
    target_events_considered: int = 0
    events_matched: int = 0
    status_code: int | None = None
    ok: bool = False
    error: str | None = None
    error_class: str | None = None
    schema_status: str = "UNKNOWN"  # UNDERSTOOD / UNKNOWN / INVALID
    events: tuple[ProviderResultEvent, ...] = ()
    evidence: ResultRequestEvidence | None = None
    cost_estimate: float | None = None


class CanonicalResultFeed(Protocol):
    """Result-provider abstraction (P66). OddsApiIOResultAdapter is first."""

    def fetch_recent_results(self, *, from_iso: str, to_iso: str) -> ProviderResultBatch: ...
    def fetch_event_result(self, provider_event_id: str) -> ProviderResultBatch: ...


def parse_result_event(payload: dict[str, Any]) -> ProviderResultEvent:
    """Parse one provider event dict into normalized result evidence.

    Scores come from the top-level ``scores.home/away`` (set count for table
    tennis). Missing/invalid score structure is surfaced as schema_ok=False so
    it can be classified PROVIDER_RESULT_SCHEMA_UNKNOWN rather than guessed.
    The raw payload hash is always populated (P10) so provenance is
    reconstructable.
    """
    import hashlib
    import json

    raw_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    if not isinstance(payload, dict):
        return ProviderResultEvent(provider_event_id="", status="", raw_payload_hash=raw_hash, schema_ok=False, schema_error="payload not an object")
    event_id = str(payload.get("id") or "")
    status = str(payload.get("status") or "")
    home = str(payload.get("home") or "")
    away = str(payload.get("away") or "")
    scores = payload.get("scores")
    home_score: int | None = None
    away_score: int | None = None
    schema_error: str | None = None
    if isinstance(scores, dict):
        try:
            home_score = int(scores.get("home"))
            away_score = int(scores.get("away"))
        except (TypeError, ValueError):
            schema_error = "scores.home/away not integral"
            home_score = None
            away_score = None
    elif status == "settled":
        schema_error = "settled event missing scores object"
    completed_at = None
    date_value = payload.get("date")
    if isinstance(date_value, str) and date_value.strip():
        try:
            parsed = datetime.fromisoformat(date_value.replace("Z", "+00:00"))
            completed_at = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            completed_at = None
    return ProviderResultEvent(
        provider_event_id=event_id,
        status=status,
        home=home,
        away=away,
        home_score=home_score,
        away_score=away_score,
        completed_at=completed_at,
        raw_payload_hash=raw_hash,
        schema_ok=schema_error is None,
        schema_error=schema_error,
    )


def canonical_result_state(provider_status: str) -> str:
    """Map a provider status literal onto the canonical result state machine."""
    return _PROVIDER_STATUS_TO_RESULT.get(str(provider_status).strip().casefold(), RESULT_STATE_REVIEW_REQUIRED)


def result_winner(*, home_score: int, away_score: int) -> str | None:
    if home_score == away_score:
        return None
    return "A" if home_score > away_score else "B"


def next_poll_at(*, state: str, request_count: int, now: datetime | None = None) -> datetime:
    """State-aware polling cadence (P10). Backs off on provider-empty events."""
    now = now or datetime.now(timezone.utc)
    if state in (LOCAL_RESULT_PRESENT, PROVIDER_RESULT_AVAILABLE):
        return now + timedelta(hours=24)
    if state in (PROVIDER_RESULT_ERROR, PROVIDER_RESULT_SCHEMA_UNKNOWN, PROVIDER_EVENT_IDENTITY_MISMATCH):
        return now + timedelta(minutes=15)
    if state in (PROVIDER_RESULT_REQUESTED_EMPTY, PROVIDER_EVENT_NOT_FOUND, PROVIDER_RESULT_OUTSIDE_RETENTION):
        delays = [timedelta(hours=1), timedelta(hours=6), timedelta(hours=24), timedelta(days=3), timedelta(days=7)]
        return now + delays[min(request_count, len(delays) - 1)]
    return now + timedelta(minutes=30)


class OddsApiIOResultAdapter:
    """Result acquisition for the Odds-API.io provider.

    Empirical contract (M4.7 P2): ``GET /v3/events?sport=table-tennis`` with a
    from/to window and NO bookmaker filter returns settled/cancelled events with
    full scores (``scores.home/away``, ``scores.periods.ft``) keyed by the same
    numeric event id used in tt_forward_events.provider_event_id. Per-event
    lookup ``GET /v3/events/{id}`` works only while the event remains in the
    provider feed (404 once it falls out of retention).
    """

    BASE = "https://api.odds-api.io/v3"

    def __init__(self, key: str, *, store: Any, probe_get: Any | None = None,
                 parse_recovered_json: Any | None = None, executor: Any | None = None) -> None:
        self._key = key
        self._store = store
        self._probe_get = probe_get
        self._parse_recovered_json = parse_recovered_json
        self._executor = executor
        self.last_request_count = 0

    def _load_helpers(self) -> tuple[Any, Any]:
        if self._probe_get is not None and self._parse_recovered_json is not None:
            return self._probe_get, self._parse_recovered_json
        from defend_integrations.probing import probe_get
        from defend_markets.shadow import parse_recovered_json
        return probe_get, parse_recovered_json

    def _governed_http(self, *, request_class: str, operation: str, request_id: str,
                       callable: Callable[[], Any], schema_understood: bool = True):
        """Route one HTTP attempt through the shared governance boundary (P5).

        Returns the raw probe_get result tuple, or None when blocked.
        """
        if self._executor is None:
            return callable()
        governed = self._executor.execute(
            provider="odds_api_io",
            request_class=request_class,
            operation=operation,
            request_metadata={"request_id": request_id, "schema_understood": schema_understood},
            callable=callable,
        )
        if not governed.allowed:
            return None
        return governed.payload

    @staticmethod
    def _response_hashes(evidence: Any, parsed: Any) -> tuple[str | None, str | None]:
        """P35/P36: compute raw-response SHA256 and canonical JSON SHA256.

        RAW_RESPONSE_SHA256 hashes the exact response bytes as received;
        CANONICAL_RESPONSE_SHA256 hashes a semantic canonicalization (sort-keys)
        for dedupe. They are distinct and clearly labeled.
        """
        import hashlib
        import json

        raw_sha: str | None = None
        canon_sha: str | None = None
        body = getattr(evidence, "body", None) if evidence is not None else None
        if isinstance(body, str) and body:
            raw_sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
        elif isinstance(body, (bytes, bytearray)):
            raw_sha = hashlib.sha256(bytes(body)).hexdigest()
        if parsed is not None:
            try:
                canon_sha = hashlib.sha256(
                    json.dumps(parsed, sort_keys=True, default=str).encode("utf-8")
                ).hexdigest()
            except (TypeError, ValueError):
                canon_sha = None
        return raw_sha, canon_sha

    def fetch_recent_results(self, *, from_iso: str, to_iso: str) -> ProviderResultBatch:
        probe_get, parse_recovered_json = self._load_helpers()
        url = (
            f"{self.BASE}/events?sport=table-tennis&from={from_iso}&to={to_iso}&apiKey={self._key}"
        )
        requested_at = datetime.now(timezone.utc)
        import uuid

        request_id = f"oaio-result-{uuid.uuid4().hex}"
        result, evidence, parsed = self._governed_http(
            request_class="RESULT",
            operation="result-acquisition",
            request_id=request_id,
            callable=lambda: probe_get(
                "odds_api_io", "result-acquisition", url,
                known_secrets=(self._key,), max_response_bytes=8 * 1024 * 1024,
            ),
        )
        self.last_request_count = 1
        raw_sha, canon_sha = self._response_hashes(evidence, parsed)
        if result is None or getattr(result, "status_code", None) is None:
            req_evidence = ResultRequestEvidence(
                request_id=request_id, provider="odds_api_io", request_kind="RESULT",
                requested_at=requested_at, window_start=from_iso, window_end=to_iso,
                error_class="NO_RESPONSE", raw_response_sha256=raw_sha,
            )
            batch = ProviderResultBatch(
                request_kind="RESULT", events_requested=1, events_returned=0,
                ok=False, error="no provider response", error_class="NO_RESPONSE",
                evidence=req_evidence, cost_estimate=1.0,
            )
            self._record(batch)
            return batch
        status_code = result.status_code
        payload, _ = parse_recovered_json(evidence.body or "")
        payload = parsed if payload is None else payload
        if not isinstance(payload, list):
            req_evidence = ResultRequestEvidence(
                request_id=request_id, provider="odds_api_io", request_kind="RESULT",
                requested_at=requested_at, window_start=from_iso, window_end=to_iso,
                http_status=status_code, response_schema_status="INVALID",
                error_class="SCHEMA_INVALID", raw_response_sha256=raw_sha, canonical_response_sha256=canon_sha,
            )
            batch = ProviderResultBatch(
                request_kind="RESULT", events_requested=1, events_returned=0,
                status_code=status_code, ok=True, events=(), schema_status="INVALID",
                error="non-list payload", error_class="SCHEMA_INVALID",
                evidence=req_evidence, cost_estimate=1.0,
            )
            self._record(batch)
            return batch
        events = tuple(parse_result_event(e) for e in payload if isinstance(e, dict))
        req_evidence = ResultRequestEvidence(
            request_id=request_id, provider="odds_api_io", request_kind="RESULT",
            requested_at=requested_at, window_start=from_iso, window_end=to_iso,
            http_status=status_code, response_schema_status="UNDERSTOOD",
            events_returned=len(events),
            successful_search_scope=f"window {from_iso}..{to_iso}",
            raw_response_sha256=raw_sha, canonical_response_sha256=canon_sha,
        )
        batch = ProviderResultBatch(
            request_kind="RESULT",
            events_requested=1,
            events_returned=len(events),
            status_code=status_code,
            ok=True,
            schema_status="UNDERSTOOD",
            events=events,
            evidence=req_evidence,
            cost_estimate=1.0,
        )
        self._record(batch)
        return batch

    def fetch_event_result(self, provider_event_id: str) -> ProviderResultBatch:
        probe_get, parse_recovered_json = self._load_helpers()
        url = f"{self.BASE}/events/{provider_event_id}?apiKey={self._key}"
        requested_at = datetime.now(timezone.utc)
        import uuid

        request_id = f"oaio-result-byid-{uuid.uuid4().hex}"
        result, evidence, parsed = self._governed_http(
            request_class="RESULT",
            operation="result-acquisition-by-id",
            request_id=request_id,
            callable=lambda: probe_get(
                "odds_api_io", "result-acquisition-by-id", url,
                known_secrets=(self._key,), max_response_bytes=8 * 1024 * 1024,
            ),
        )
        self.last_request_count = 1
        raw_sha, canon_sha = self._response_hashes(evidence, parsed)
        if result is None or getattr(result, "status_code", None) is None:
            req_evidence = ResultRequestEvidence(
                request_id=request_id, provider="odds_api_io", request_kind="RESULT_BY_ID",
                requested_at=requested_at, target_event_count=1, error_class="NO_RESPONSE",
                raw_response_sha256=raw_sha,
            )
            batch = ProviderResultBatch(
                request_kind="RESULT_BY_ID", events_requested=1, events_returned=0,
                ok=False, error="no provider response", error_class="NO_RESPONSE",
                evidence=req_evidence, cost_estimate=1.0,
            )
            self._record(batch)
            return batch
        status_code = result.status_code
        payload, _ = parse_recovered_json(evidence.body or "")
        payload = parsed if payload is None else payload
        if status_code == 404 or payload is None:
            req_evidence = ResultRequestEvidence(
                request_id=request_id, provider="odds_api_io", request_kind="RESULT_BY_ID",
                requested_at=requested_at, target_event_count=1, http_status=status_code,
                response_schema_status="UNDERSTOOD", error_class="EVENT_NOT_FOUND",
                raw_response_sha256=raw_sha, canonical_response_sha256=canon_sha,
            )
            batch = ProviderResultBatch(
                request_kind="RESULT_BY_ID", events_requested=1, events_returned=0,
                status_code=status_code, ok=True, events=(),
                error_class="EVENT_NOT_FOUND", evidence=req_evidence, cost_estimate=1.0,
            )
            self._record(batch)
            return batch
        events = (parse_result_event(payload),) if isinstance(payload, dict) else ()
        req_evidence = ResultRequestEvidence(
            request_id=request_id, provider="odds_api_io", request_kind="RESULT_BY_ID",
            requested_at=requested_at, target_event_count=1, http_status=status_code,
            response_schema_status="UNDERSTOOD", events_returned=len(events),
            raw_response_sha256=raw_sha, canonical_response_sha256=canon_sha,
        )
        batch = ProviderResultBatch(
            request_kind="RESULT_BY_ID",
            events_requested=1,
            events_returned=len(events),
            status_code=status_code,
            ok=True,
            schema_status="UNDERSTOOD",
            events=events,
            evidence=req_evidence,
            cost_estimate=1.0,
        )
        self._record(batch)
        return batch

    def _record(self, batch: ProviderResultBatch) -> None:
        self._store.record_result_request(
            {
                "provider": "odds_api_io",
                "request_kind": batch.request_kind,
                "events_requested": batch.events_requested,
                "events_returned": batch.events_returned,
                "status_code": batch.status_code,
                "ok": batch.ok,
                "error": batch.error,
                "cost_estimate": batch.cost_estimate,
            }
        )
        if batch.evidence is not None:
            self._store.record_result_request_evidence(batch.evidence.to_row())


class TableTennisResultAcquisitionService:
    """P1: identify past unsettled canonical events, acquire provider results,
    normalize, persist local results, settle and score.

    Layers remain separable: feed/adapter = acquisition, this service =
    normalization + orchestration, settlement_catchup/settlement = settlement,
    forward_evidence scoring = scoring.
    """

    def __init__(self, database: Any, store: Any, feed: CanonicalResultFeed) -> None:
        self._database = database
        self._store = store
        self._feed = feed

    # ------------------------------------------------------------------ #
    # Event identification
    # ------------------------------------------------------------------ #

    def past_unsettled_events(self) -> list[dict[str, Any]]:
        """Canonical events with an official forward prediction that have
        commenced but are not yet FINAL-settled."""
        official = self._store.list_official_predictions(limit=100000)
        settled = {str(s["canonical_event_id"]) for s in self._store.list_settlements(limit=100000) if s.get("status") == "FINAL"}
        by_event: dict[str, dict[str, Any]] = {}
        for p in official:
            commence = _parse_dt(p.get("commence_at"))
            if commence is None or commence >= datetime.now(timezone.utc):
                continue
            event = str(p["canonical_event_id"])
            if event in settled:
                continue
            entry = by_event.setdefault(
                event,
                {"canonical_event_id": event, "commence_at": commence, "provider": None, "provider_event_id": None},
            )
            entry.setdefault("prediction_ids", []).append(str(p.get("prediction_id")))
        # provider event identity from tt_forward_events (never prediction_id).
        if by_event:
            with self._database.connect() as connection, connection.cursor() as cursor:
                placeholders = ",".join("%s" for _ in by_event)
                cursor.execute(
                    f"SELECT canonical_event_id, provider, provider_event_id FROM tt_forward_events "
                    f"WHERE canonical_event_id IN ({placeholders})",
                    list(by_event),
                )
                for row in cursor.fetchall():
                    event = str(row[0])
                    if event in by_event:
                        by_event[event]["provider"] = str(row[1])
                        by_event[event]["provider_event_id"] = str(row[2])
        return list(by_event.values())

    # ------------------------------------------------------------------ #
    # Acquisition state classification
    # ------------------------------------------------------------------ #

    def classify_acquisition_state(
        self,
        *,
        has_local_result: bool,
        provider_event_id: str | None,
        provider_batch: ProviderResultBatch | None,
        provider_status: str | None,
    ) -> str:
        """P0: precise state. Provider-empty requires an actual empty request."""
        if has_local_result:
            return LOCAL_RESULT_PRESENT
        if provider_batch is None:
            return LOCAL_RESULT_MISSING_NOT_REQUESTED
        if provider_event_id is None:
            return PROVIDER_EVENT_IDENTITY_MISMATCH
        if not provider_batch.ok:
            return PROVIDER_RESULT_ERROR
        if provider_batch.status_code == 404:
            return PROVIDER_EVENT_NOT_FOUND
        if not provider_batch.events:
            return PROVIDER_RESULT_REQUESTED_EMPTY
        if not provider_batch.events[0].schema_ok:
            return PROVIDER_RESULT_SCHEMA_UNKNOWN
        if provider_batch.events[0].provider_event_id and provider_batch.events[0].provider_event_id != provider_event_id:
            return PROVIDER_EVENT_IDENTITY_MISMATCH
        return PROVIDER_RESULT_AVAILABLE

    # ------------------------------------------------------------------ #
    # Result normalization + persistence
    # ------------------------------------------------------------------ #

    def normalize_result(self, event: dict[str, Any], provider_result: ProviderResultEvent) -> dict[str, Any] | None:
        """Map a provider result onto canonical orientation (P6).

        Returns a normalized result dict (or None when identity conflicts).
        """
        provider_event_id = event.get("provider_event_id")
        if provider_event_id is None:
            return None
        result_state = canonical_result_state(provider_result.status)
        if provider_result.home_score is None or provider_result.away_score is None:
            return {
                "provider_event_id": provider_result.provider_event_id or provider_event_id,
                "state": result_state,
                "canonical_event_id": event["canonical_event_id"],
                "home": provider_result.home,
                "away": provider_result.away,
                "home_score": None,
                "away_score": None,
                "orientation": None,
                "winner_side": None,
                "scores_present": False,
                "raw_payload_hash": provider_result.raw_payload_hash,
                "provider_result_id": provider_result.provider_event_id or provider_event_id,
            }
        # participant names from tt_forward_events (canonical A/B)
        names = self._participant_keys(event["canonical_event_id"])
        canonical_a = names.get("player_a_key") or provider_result.home
        canonical_b = names.get("player_b_key") or provider_result.away
        from defend_markets.quant.market import participant_orientation

        orientation, home_maps_to, _ = participant_orientation(
            provider_home=provider_result.home,
            provider_away=provider_result.away,
            canonical_a=canonical_a,
            canonical_b=canonical_b,
        )
        if orientation == "CONFLICT":
            return {
                "provider_event_id": provider_result.provider_event_id or provider_event_id,
                "state": RESULT_STATE_REVIEW_REQUIRED,
                "canonical_event_id": event["canonical_event_id"],
                "home": provider_result.home,
                "away": provider_result.away,
                "home_score": provider_result.home_score,
                "away_score": provider_result.away_score,
                "orientation": "CONFLICT",
                "winner_side": None,
                "scores_present": True,
                "conflict": True,
                "raw_payload_hash": provider_result.raw_payload_hash,
                "provider_result_id": provider_result.provider_event_id or provider_event_id,
            }
        home_score = provider_result.home_score
        away_score = provider_result.away_score
        if orientation == "REVERSED":
            home_score, away_score = away_score, home_score
        winner = result_winner(home_score=home_score, away_score=away_score)
        return {
            "provider_event_id": provider_result.provider_event_id or provider_event_id,
            "state": result_state,
            "canonical_event_id": event["canonical_event_id"],
            "home": provider_result.home,
            "away": provider_result.away,
            "home_score": home_score,
            "away_score": away_score,
            "orientation": orientation,
            "winner_side": winner,
            "scores_present": True,
            "raw_payload_hash": provider_result.raw_payload_hash,
            "provider_result_id": provider_result.provider_event_id or provider_event_id,
        }

    def _participant_keys(self, canonical_event_id: str) -> dict[str, str]:
        """Return canonical participant display names (NOT keys) for orientation.

        The provider returns display names (\"Kosar, Vaclav\"); matching must
        use tt_forward_events.player_a_name/player_b_name, never the
        ``table_tennis:`` participant key.
        """
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT player_a_name, player_b_name FROM tt_forward_events WHERE canonical_event_id = %s",
                (canonical_event_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return {}
            names = [str(value) for value in row if value]
            if len(names) == 2 and names[0] != names[1]:
                return {"player_a_key": names[0], "player_b_key": names[1]}
            # fall back to participant keys only when names are missing/blank
            cursor.execute(
                "SELECT player_a_key, player_b_key FROM tt_forward_events WHERE canonical_event_id = %s",
                (canonical_event_id,),
            )
            row2 = cursor.fetchone()
            if row2 is None:
                return {}
            return {"player_a_key": str(row2[0]), "player_b_key": str(row2[1])}

    # ------------------------------------------------------------------ #
    # Orchestration
    # ------------------------------------------------------------------ #

    def acquire_results(
        self,
        *,
        recent_window_hours: int = 96,
        max_events: int | None = None,
        fallback_limit: int | None = None,
    ) -> dict[str, Any]:
        """P0: acquire results ONLY.

        Selects eligible canonical events, performs governed provider requests,
        persists request evidence, normalizes provider/local result identity,
        verifies participant orientation, and persists immutable acquired-result
        evidence/state. It NEVER inserts quant_settlements or
        quant_forward_scores — settlement and scoring are separate authorities.
        """
        events = self.past_unsettled_events()
        if max_events is not None:
            events = events[:max_events]
        now = datetime.now(timezone.utc)
        from_iso = (now - timedelta(hours=recent_window_hours)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        to_iso = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")

        local_results = self._local_results_map(events)

        # -------- sweep phase (Finding B) --------
        sweep: ProviderResultBatch | None = None
        feed_events: dict[str, ProviderResultEvent] = {}
        sweep_successful = False
        sweep_schema_understood = False
        if events:
            sweep = self._feed.fetch_recent_results(from_iso=from_iso, to_iso=to_iso)
            sweep_successful = bool(sweep.ok)
            sweep_schema_understood = sweep.schema_status == "UNDERSTOOD"
            if sweep_successful and sweep_schema_understood:
                feed_events = {e.provider_event_id: e for e in sweep.events if e.provider_event_id}

        classified: dict[str, int] = {}
        acquired = 0
        fallback_used = 0
        for event in events:
            canonical_event_id = event["canonical_event_id"]
            provider_event_id = event.get("provider_event_id")

            # -------- local result path (P7/P12) --------
            local = local_results.get(canonical_event_id)
            if local is not None:
                local_state = self._classify_local_result(event, local)
                if local_state == RESULT_STATE_REVIEW_REQUIRED:
                    self._store.upsert_result_acquisition(
                        {
                            "canonical_event_id": canonical_event_id,
                            "provider": local.get("source_provider") or event.get("provider") or "odds_api_io",
                            "provider_event_id": provider_event_id,
                            "commence_at": event["commence_at"],
                            "acquisition_state": RESULT_RECONCILIATION_REQUIRED,
                            "result_status": "review_required",
                            "actual_a": local["home_score"],
                            "actual_b": local["away_score"],
                            "orientation": local["orientation"],
                            "next_poll_at": next_poll_at(state=RESULT_RECONCILIATION_REQUIRED, request_count=0).isoformat().replace("+00:00", "Z"),
                            "settled": False,
                        }
                    )
                    classified[RESULT_RECONCILIATION_REQUIRED] = classified.get(RESULT_RECONCILIATION_REQUIRED, 0) + 1
                    continue
                # persist acquired-result evidence (NO settlement/score write).
                fingerprint = canonical_result_fingerprint(
                    provider=str(local.get("source_provider") or "odds_api_io"),
                    provider_event_id=str(provider_event_id or ""),
                    canonical_event_id=canonical_event_id,
                    status=RESULT_STATE_FINAL,
                    actual_a=local["home_score"],
                    actual_b=local["away_score"],
                    orientation=local["orientation"],
                    source_result_id=local.get("source_result_id", ""),
                )
                self._store.upsert_result_acquisition(
                    {
                        "canonical_event_id": canonical_event_id,
                        "provider": local.get("source_provider") or event.get("provider") or "odds_api_io",
                        "provider_event_id": provider_event_id,
                        "commence_at": event["commence_at"],
                        "acquisition_state": LOCAL_RESULT_PRESENT,
                        "result_status": "settled",
                        "actual_a": local["home_score"],
                        "actual_b": local["away_score"],
                        "winner_side": local["winner_side"],
                        "orientation": local["orientation"],
                        "provider_result_id": local.get("source_result_id"),
                        "raw_provenance_hash": local.get("raw_payload_hash"),
                        "normalized_result_fingerprint": fingerprint,
                        "next_poll_at": next_poll_at(state=LOCAL_RESULT_PRESENT, request_count=0).isoformat().replace("+00:00", "Z"),
                        "settled": False,
                    }
                )
                classified[LOCAL_RESULT_PRESENT] = classified.get(LOCAL_RESULT_PRESENT, 0) + 1
                continue

            # -------- provider sweep result --------
            provider_result = feed_events.get(provider_event_id) if provider_event_id else None
            if provider_result is not None:
                state = PROVIDER_RESULT_AVAILABLE
            elif sweep is None:
                state = LOCAL_RESULT_MISSING_NOT_REQUESTED
            elif provider_event_id is None:
                state = PROVIDER_EVENT_IDENTITY_MISMATCH
            elif not sweep_successful:
                state = PROVIDER_RESULT_ERROR  # failed sweep must NOT be "empty"
            elif not sweep_schema_understood:
                state = PROVIDER_RESULT_SCHEMA_UNKNOWN
            elif self._event_in_window(event, now, recent_window_hours):
                state = PROVIDER_RESULT_REQUESTED_EMPTY
            else:
                state = LOCAL_RESULT_MISSING_NOT_REQUESTED

            row = {
                "canonical_event_id": canonical_event_id,
                "provider": event.get("provider") or "odds_api_io",
                "provider_event_id": provider_event_id,
                "commence_at": event["commence_at"],
                "acquisition_state": state,
                "request_count": 1 if provider_result is not None or state in (PROVIDER_RESULT_REQUESTED_EMPTY,) else 0,
                "last_requested_at": now.isoformat().replace("+00:00", "Z"),
                "next_poll_at": next_poll_at(state=state, request_count=1).isoformat().replace("+00:00", "Z"),
                "settled": False,
            }
            self._store.upsert_result_acquisition(row)
            classified[state] = classified.get(state, 0) + 1

            if state == PROVIDER_RESULT_AVAILABLE:
                normalized = self.normalize_result(event, provider_result)
                if normalized is None:
                    classified[PROVIDER_EVENT_IDENTITY_MISMATCH] = classified.get(PROVIDER_EVENT_IDENTITY_MISMATCH, 0) + 1
                    self._store.upsert_result_acquisition(dict(row, acquisition_state=PROVIDER_EVENT_IDENTITY_MISMATCH))
                    continue
                if normalized.get("conflict"):
                    classified[RESULT_RECONCILIATION_REQUIRED] = classified.get(RESULT_RECONCILIATION_REQUIRED, 0) + 1
                    self._store.upsert_result_acquisition(dict(row, acquisition_state=RESULT_RECONCILIATION_REQUIRED))
                    continue
                if not normalized["scores_present"]:
                    classified[PROVIDER_RESULT_SCHEMA_UNKNOWN] = classified.get(PROVIDER_RESULT_SCHEMA_UNKNOWN, 0) + 1
                    self._store.upsert_result_acquisition(dict(row, acquisition_state=PROVIDER_RESULT_SCHEMA_UNKNOWN))
                    continue
                acquired += 1
                fingerprint = canonical_result_fingerprint(
                    provider=event.get("provider") or "odds_api_io",
                    provider_event_id=str(provider_event_id or ""),
                    canonical_event_id=canonical_event_id,
                    status=normalized["state"],
                    actual_a=normalized.get("home_score"),
                    actual_b=normalized.get("away_score"),
                    orientation=normalized.get("orientation") or "",
                    source_result_id=normalized.get("provider_result_id") or "",
                )
                row.update(
                    acquisition_state=LOCAL_RESULT_PRESENT if (normalized["state"] == RESULT_STATE_FINAL and normalized["winner_side"] is not None) else PROVIDER_RESULT_AVAILABLE,
                    result_status=normalized["state"],
                    actual_a=normalized.get("home_score"),
                    actual_b=normalized.get("away_score"),
                    winner_side=normalized.get("winner_side"),
                    orientation=normalized.get("orientation"),
                    provider_result_id=normalized.get("provider_result_id"),
                    raw_provenance_hash=normalized.get("raw_payload_hash"),
                    normalized_result_fingerprint=fingerprint,
                )
                self._store.upsert_result_acquisition(row)
                continue

            # -------- per-event fallback (P4/P5) --------
            if state == PROVIDER_RESULT_REQUESTED_EMPTY and provider_event_id is not None and self._fallback_eligible(event, fallback_limit, fallback_used):
                fallback_used += 1
                fb = self._feed.fetch_event_result(provider_event_id)
                if fb.ok and fb.events:
                    fb_event = fb.events[0]
                    if not fb_event.schema_ok:
                        classified[PROVIDER_RESULT_SCHEMA_UNKNOWN] = classified.get(PROVIDER_RESULT_SCHEMA_UNKNOWN, 0) + 1
                        self._store.upsert_result_acquisition(dict(row, acquisition_state=PROVIDER_RESULT_SCHEMA_UNKNOWN, request_count=2))
                    elif fb_event.provider_event_id and fb_event.provider_event_id != provider_event_id:
                        classified[PROVIDER_EVENT_IDENTITY_MISMATCH] = classified.get(PROVIDER_EVENT_IDENTITY_MISMATCH, 0) + 1
                        self._store.upsert_result_acquisition(dict(row, acquisition_state=PROVIDER_EVENT_IDENTITY_MISMATCH, request_count=2))
                    else:
                        normalized = self.normalize_result(event, fb_event)
                        if normalized is None:
                            classified[PROVIDER_EVENT_IDENTITY_MISMATCH] = classified.get(PROVIDER_EVENT_IDENTITY_MISMATCH, 0) + 1
                            self._store.upsert_result_acquisition(dict(row, acquisition_state=PROVIDER_EVENT_IDENTITY_MISMATCH, request_count=2))
                        elif normalized.get("conflict"):
                            classified[RESULT_RECONCILIATION_REQUIRED] = classified.get(RESULT_RECONCILIATION_REQUIRED, 0) + 1
                            self._store.upsert_result_acquisition(dict(row, acquisition_state=RESULT_RECONCILIATION_REQUIRED, request_count=2))
                        elif not normalized["scores_present"]:
                            classified[PROVIDER_RESULT_SCHEMA_UNKNOWN] = classified.get(PROVIDER_RESULT_SCHEMA_UNKNOWN, 0) + 1
                            self._store.upsert_result_acquisition(dict(row, acquisition_state=PROVIDER_RESULT_SCHEMA_UNKNOWN, request_count=2))
                        else:
                            acquired += 1
                            fingerprint = canonical_result_fingerprint(
                                provider=event.get("provider") or "odds_api_io",
                                provider_event_id=str(provider_event_id or ""),
                                canonical_event_id=canonical_event_id,
                                status=normalized["state"],
                                actual_a=normalized.get("home_score"),
                                actual_b=normalized.get("away_score"),
                                orientation=normalized.get("orientation") or "",
                                source_result_id=normalized.get("provider_result_id") or "",
                            )
                            classified[PROVIDER_RESULT_AVAILABLE] = classified.get(PROVIDER_RESULT_AVAILABLE, 0) + 1
                            self._store.upsert_result_acquisition(dict(row, acquisition_state=PROVIDER_RESULT_AVAILABLE, result_status=normalized["state"], actual_a=normalized.get("home_score"), actual_b=normalized.get("away_score"), winner_side=normalized.get("winner_side"), orientation=normalized.get("orientation"), provider_result_id=normalized.get("provider_result_id"), raw_provenance_hash=normalized.get("raw_payload_hash"), normalized_result_fingerprint=fingerprint, request_count=2))
                elif fb.ok and fb.status_code == 404:
                    classified[PROVIDER_RESULT_OUTSIDE_RETENTION] = classified.get(PROVIDER_RESULT_OUTSIDE_RETENTION, 0) + 1
                    self._store.upsert_result_acquisition(dict(row, acquisition_state=PROVIDER_RESULT_OUTSIDE_RETENTION, request_count=2, next_poll_at=next_poll_at(state=PROVIDER_RESULT_OUTSIDE_RETENTION, request_count=1).isoformat().replace("+00:00", "Z")))
                elif not fb.ok:
                    classified[PROVIDER_RESULT_ERROR] = classified.get(PROVIDER_RESULT_ERROR, 0) + 1
                    self._store.upsert_result_acquisition(dict(row, acquisition_state=PROVIDER_RESULT_ERROR, request_count=2, next_poll_at=next_poll_at(state=PROVIDER_RESULT_ERROR, request_count=1).isoformat().replace("+00:00", "Z")))

        return {
            "classified": classified,
            "events": len(events),
            "acquired": acquired,
            "fallback_used": fallback_used,
            "summary": f"result acquisition: {acquired} acquired",
        }

    def acquire_and_settle(
        self,
        *,
        recent_window_hours: int = 96,
        max_events: int | None = None,
        fallback_limit: int | None = None,
    ) -> dict[str, Any]:
        """DEPRECATED (M4.7.2 P0): compatibility wrapper.

        Runs acquisition then delegates to the single settlement + scoring
        authorities. Production scheduler/API MUST call acquire_results(),
        SettlementService.settle() and ForwardScoringService.score() separately.
        """
        result = self.acquire_results(
            recent_window_hours=recent_window_hours,
            max_events=max_events,
            fallback_limit=fallback_limit,
        )
        from defend_markets.quant.settlement import ForwardScoringService, SettlementService

        settle = SettlementService(self._store).settle()
        score = ForwardScoringService(self._store).score()
        return {
            **result,
            "settled": settle["settled"],
            "scores": score["scores"],
        }

    def _classify_local_result(self, event: dict[str, Any], local: dict[str, Any]) -> str:
        """P7: run the same canonical orientation resolver for local results.

        A local tt_match_results row is evidence, not canonical truth. Only
        CANONICAL/REVERSED may settle; CONFLICT/UNKNOWN -> REVIEW_REQUIRED.
        """
        orientation = local.get("orientation")
        if orientation in ("CANONICAL", "REVERSED"):
            return RESULT_STATE_FINAL
        return RESULT_STATE_REVIEW_REQUIRED

    def _fallback_eligible(self, event: dict[str, Any], fallback_limit: int | None, fallback_used: int) -> bool:
        if fallback_limit is not None and fallback_used >= fallback_limit:
            return False
        # A per-event 404 is only worth one probe per recent sweep; retention
        # policy is enforced by next_poll_at cadence (caller passes fallback_limit).
        return event.get("provider_event_id") is not None

    def _local_results_map(self, events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Read local result rows with provenance and resolve orientation (P7).

        A local row is evidence, not canonical truth: participant identity and
        scores are loaded, then the SAME canonical orientation resolver used
        for provider results decides CANONICAL / REVERSED / CONFLICT / UNKNOWN.
        """
        if not events:
            return {}
        with self._database.connect() as connection, connection.cursor() as cursor:
            placeholders = ",".join("%s" for _ in events)
            cursor.execute(
                f"SELECT event_key, league_key, home_participant_key, away_participant_key, "
                f"home_score, away_score, completed_at, source_provider, raw_ref "
                f"FROM tt_match_results WHERE event_key IN ({placeholders})",
                [e["canonical_event_id"] for e in events],
            )
            rows = list(cursor.fetchall())
            # participant names AND keys per canonical event
            cursor.execute(
                f"SELECT canonical_event_id, player_a_name, player_b_name, player_a_key, player_b_key "
                f"FROM tt_forward_events WHERE canonical_event_id IN ({placeholders})",
                [e["canonical_event_id"] for e in events],
            )
            names = {str(row[0]): (str(row[1] or ""), str(row[2] or ""), str(row[3] or ""), str(row[4] or "")) for row in cursor.fetchall()}
        from defend_markets.quant.normalize import normalize_participant_orientation, normalize_result_scores

        out: dict[str, dict[str, Any]] = {}
        for event_key, league, hk, ak, hs, aws, completed, source_provider, raw_ref in rows:
            hs, aws = int(hs), int(aws)
            entry = names.get(str(event_key), ("", "", "", ""))
            canonical_a_name, canonical_b_name, canonical_a_key, canonical_b_key = entry
            # P12/P14: one normalizer for local results — keys first, then names.
            orientation, match_mode = normalize_participant_orientation(
                source_home=str(hk or ""),
                source_away=str(ak or ""),
                canonical_a=canonical_a_name,
                canonical_b=canonical_b_name,
                canonical_a_key=canonical_a_key or None,
                canonical_b_key=canonical_b_key or None,
            )
            canon_hs, canon_aws, winner = normalize_result_scores(
                source_home_score=hs,
                source_away_score=aws,
                orientation=orientation,
            )
            out[str(event_key)] = {
                "home_score": canon_hs if canon_hs is not None else hs,
                "away_score": canon_aws if canon_aws is not None else aws,
                "winner_side": winner if winner is not None else result_winner(home_score=hs, away_score=aws),
                "orientation": orientation,
                "identity_match_mode": match_mode,
                "source_provider": str(source_provider or ""),
                "source_result_id": str(raw_ref or "") or str(event_key),
                "completed_at": completed,
                "participant_home": str(hk or ""),
                "participant_away": str(ak or ""),
            }
        return out

    def _has_final_settlement(self, canonical_event_id: str) -> bool:
        settlements = self._store.list_settlements(limit=100000)
        return any(
            str(s["canonical_event_id"]) == canonical_event_id and s.get("status") == "FINAL"
            for s in settlements
        )

    def _event_in_window(self, event: dict[str, Any], now: datetime, window_hours: int) -> bool:
        commence = event.get("commence_at")
        if not isinstance(commence, datetime):
            return False
        return (now - commence).total_seconds() <= window_hours * 3600

    def _settle_event(self, event: dict[str, Any], normalized: dict[str, Any]) -> int:
        """Insert a FINAL settlement (P7) without overwriting prior revisions.

        P11: provenance fields are persisted (provider_event_id, source_result_id,
        raw_payload_hash, observed_at, orientation, winner) — never left null
        merely because scores are known.
        """
        canonical_event_id = event["canonical_event_id"]
        provider_event_id = normalized["provider_event_id"] or event.get("provider_event_id")
        source_result_id = normalized.get("provider_result_id") or (f"oaio:{provider_event_id}" if provider_event_id else canonical_event_id)
        created = self._store.insert_settlement(
            {
                "canonical_event_id": canonical_event_id,
                "provider_event_id": provider_event_id,
                "status": RESULT_STATE_FINAL,
                "actual_a": normalized["home_score"],
                "actual_b": normalized["away_score"],
                "winner_side": normalized["winner_side"],
                "source_result_id": source_result_id,
                "source_provider": "odds_api_io",
                "observed_at": normalized.get("completed_at"),
                "raw_payload_hash": normalized.get("raw_payload_hash"),
                "orientation_verified": normalized["orientation"] in ("CANONICAL", "REVERSED"),
                "provider_result_id": normalized.get("provider_result_id"),
            }
        )
        return 1 if created else 0

    def _score_event(self, event: dict[str, Any], normalized: dict[str, Any]) -> int:
        """Score every official forward prediction for a settled event (P11)."""
        canonical_event_id = event["canonical_event_id"]
        official = self._store.list_official_predictions(limit=100000)
        event_predictions = [p for p in official if str(p["canonical_event_id"]) == canonical_event_id]
        if not event_predictions:
            return 0
        settlements = self._store.list_settlements(limit=100000)
        settlement = next(
            (s for s in settlements if str(s["canonical_event_id"]) == canonical_event_id and s.get("status") == "FINAL"),
            None,
        )
        if settlement is None:
            return 0
        actual = 1.0 if normalized["winner_side"] == "A" else 0.0
        scored = 0
        for p in event_predictions:
            brier, logloss, clipped = score_prediction(
                probability_a=float(p["probability_a"]), actual_outcome=actual
            )
            created = self._store.insert_forward_score(
                {
                    "canonical_event_id": canonical_event_id,
                    "official_prediction_id": p["official_prediction_id"],
                    "model_id": p["model_id"],
                    "settlement_id": settlement["settlement_id"],
                    "probability_a": float(p["probability_a"]),
                    "actual_outcome": actual,
                    "brier": round(brier, 8),
                    "logloss": round(logloss, 8),
                    "effective_clipped_p": clipped,
                    "logloss_eps_policy": LOGLOSS_EPSILON_POLICY,
                    "scoring_policy_version": SCORING_POLICY_VERSION,
                }
            )
            if created:
                scored += 1
        return scored


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def forward_evidence_summary(store: Any) -> dict[str, Any]:
    """P14/P33/P34: unique canonical-event metrics for official forward predictions.

    The scoring unit is ONE official score per (canonical event, model identity).
    Champion vs shadow is classified by persisted model ROLE (registry identity),
    never by a "M5" substring in model_id. M5-vs-shadow pairing is by exact
    event with a uniqueness assertion, computing paired Brier AND paired logloss.
    """
    from defend_markets.quant.settlement import model_role

    scores = store.list_forward_scores(limit=100000)
    m5: dict[str, dict[str, dict[str, Any]]] = {}
    shadow: dict[str, dict[str, dict[str, Any]]] = {}
    for s in scores:
        event = str(s["canonical_event_id"])
        model = str(s["model_id"])
        role = model_role(store, model)
        target = m5 if role == "CHAMPION" else shadow
        target.setdefault(event, {}).setdefault(model, s)

    def _summarize(bucket: dict[str, dict[str, dict[str, Any]]]) -> dict[str, Any]:
        # one scoring unit per event per model identity
        units = [s for models in bucket.values() for s in models.values()]
        events = len(bucket)
        if not units:
            return {"events": 0, "brier": None, "logloss": None}
        n = len(units)
        brier = sum(float(s["brier"]) for s in units) / n
        logloss = sum(float(s["logloss"]) for s in units) / n
        return {"events": events, "brier": round(brier, 8), "logloss": round(logloss, 8)}

    m5_summary = _summarize(m5)
    shadow_summary = _summarize(shadow)
    paired_events = set(m5) & set(shadow)
    paired = None
    if paired_events:
        m5_briers: list[float] = []
        shadow_briers: list[float] = []
        m5_loglosses: list[float] = []
        shadow_loglosses: list[float] = []
        for event in paired_events:
            m5_models = m5[event]
            shadow_models = shadow[event]
            # uniqueness assertion: one champion and one shadow identity per event
            if len(m5_models) != 1 or len(shadow_models) != 1:
                continue
            m5_s = next(iter(m5_models.values()))
            sh_s = next(iter(shadow_models.values()))
            m5_briers.append(float(m5_s["brier"]))
            shadow_briers.append(float(sh_s["brier"]))
            m5_loglosses.append(float(m5_s["logloss"]))
            shadow_loglosses.append(float(sh_s["logloss"]))
        if m5_briers:
            m5_brier = sum(m5_briers) / len(m5_briers)
            shadow_brier = sum(shadow_briers) / len(shadow_briers)
            m5_logloss = sum(m5_loglosses) / len(m5_loglosses)
            shadow_logloss = sum(shadow_loglosses) / len(shadow_loglosses)
            paired = {
                "events": len(m5_briers),
                "m5_brier": round(m5_brier, 8),
                "shadow_brier": round(shadow_brier, 8),
                "brier_delta": round(m5_brier - shadow_brier, 8),
                "m5_logloss": round(m5_logloss, 8),
                "shadow_logloss": round(shadow_logloss, 8),
                "logloss_delta": round(m5_logloss - shadow_logloss, 8),
            }
    return {
        "m5": m5_summary,
        "shadow": shadow_summary,
        "paired": paired,
        "policy_versions": {"logloss_eps": LOGLOSS_EPSILON_POLICY, "scoring": SCORING_POLICY_VERSION},
    }


def settle_acquired_results(store: Any) -> dict[str, Any]:
    """P0: the production settlement job.

    Consumes already-acquired, normalized canonical results (from the
    acquisition ledger) and settles those that are FINAL with a verified
    orientation, then scores official forward predictions. This is the ONLY
    production settlement authority; it never queries tt_match_results directly
    and never labels a local miss as provider-empty.
    """
    acquisitions = store.list_result_acquisition(limit=100000)
    settled = 0
    scores = 0
    for acq in acquisitions:
        state = str(acq.get("acquisition_state") or "")
        if state not in (LOCAL_RESULT_PRESENT, PROVIDER_RESULT_AVAILABLE):
            continue
        if str(acq.get("result_status") or "") not in ("settled", "FINAL"):
            continue
        winner_side = acq.get("winner_side")
        if winner_side is None:
            continue
        orientation = str(acq.get("orientation") or "")
        if orientation not in ("CANONICAL", "REVERSED"):
            continue
        canonical_event_id = str(acq["canonical_event_id"])
        if store.latest_final_settlement(canonical_event_id) is not None:
            continue
        provider_event_id = acq.get("provider_event_id")
        provider_result_id = acq.get("provider_result_id") or provider_event_id
        source_result_id = provider_result_id or (f"oaio:{provider_event_id}" if provider_event_id else canonical_event_id)
        created = store.insert_settlement(
            {
                "canonical_event_id": canonical_event_id,
                "provider_event_id": provider_event_id,
                "status": RESULT_STATE_FINAL,
                "actual_a": acq.get("actual_a"),
                "actual_b": acq.get("actual_b"),
                "winner_side": winner_side,
                "source_result_id": source_result_id,
                "source_provider": acq.get("provider") or "odds_api_io",
                "observed_at": None,
                "raw_payload_hash": acq.get("raw_provenance_hash"),
                "orientation_verified": True,
                "provider_result_id": provider_result_id,
            }
        )
        if created:
            settled += 1
        settlement = store.latest_final_settlement(canonical_event_id)
        if settlement is None:
            continue
        actual = 1.0 if winner_side == "A" else 0.0
        official = store.list_official_predictions(limit=100000)
        for p in official:
            if str(p["canonical_event_id"]) != canonical_event_id:
                continue
            brier, logloss, clipped = score_prediction(probability_a=float(p["probability_a"]), actual_outcome=actual)
            scored = store.insert_forward_score(
                {
                    "canonical_event_id": canonical_event_id,
                    "official_prediction_id": p["official_prediction_id"],
                    "model_id": p["model_id"],
                    "settlement_id": settlement["settlement_id"],
                    "probability_a": float(p["probability_a"]),
                    "actual_outcome": actual,
                    "brier": round(brier, 8),
                    "logloss": round(logloss, 8),
                    "effective_clipped_p": clipped,
                    "logloss_eps_policy": LOGLOSS_EPSILON_POLICY,
                    "scoring_policy_version": SCORING_POLICY_VERSION,
                }
            )
            if scored:
                scores += 1
    return {"settled": settled, "scores": scores, "summary": f"settlement: {settled} settled, {scores} scored"}
