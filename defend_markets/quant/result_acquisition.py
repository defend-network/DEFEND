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
from typing import Any, Protocol

from defend_markets.quant.forward_evidence import (
    LOGLOSS_EPSILON,
    LOGLOSS_EPSILON_POLICY,
    SCORING_POLICY_VERSION,
    score_prediction,
)

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
    """Bounded provider response for one request."""

    request_kind: str
    events_requested: int
    events_returned: int
    status_code: int | None = None
    ok: bool = False
    error: str | None = None
    events: tuple[ProviderResultEvent, ...] = ()
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
    """
    if not isinstance(payload, dict):
        return ProviderResultEvent(provider_event_id="", status="", schema_ok=False, schema_error="payload not an object")
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
    if state in (PROVIDER_RESULT_REQUESTED_EMPTY, PROVIDER_EVENT_NOT_FOUND):
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
                 parse_recovered_json: Any | None = None) -> None:
        self._key = key
        self._store = store
        self._probe_get = probe_get
        self._parse_recovered_json = parse_recovered_json
        self.last_request_count = 0

    def _load_helpers(self) -> tuple[Any, Any]:
        if self._probe_get is not None and self._parse_recovered_json is not None:
            return self._probe_get, self._parse_recovered_json
        from defend_integrations.probing import probe_get
        from defend_markets.shadow import parse_recovered_json
        return probe_get, parse_recovered_json

    def fetch_recent_results(self, *, from_iso: str, to_iso: str) -> ProviderResultBatch:
        probe_get, parse_recovered_json = self._load_helpers()
        url = (
            f"{self.BASE}/events?sport=table-tennis&from={from_iso}&to={to_iso}&apiKey={self._key}"
        )
        result, evidence, parsed = probe_get(
            "odds_api_io", "result-acquisition", url,
            known_secrets=(self._key,), max_response_bytes=8 * 1024 * 1024,
        )
        self.last_request_count = 1
        if result is None or getattr(result, "status_code", None) is None:
            batch = ProviderResultBatch(
                request_kind="RESULT", events_requested=0, events_returned=0,
                ok=False, error="no provider response", cost_estimate=1.0,
            )
            self._record(batch)
            return batch
        payload, _ = parse_recovered_json(evidence.body or "")
        payload = parsed if payload is None else payload
        if not isinstance(payload, list):
            batch = ProviderResultBatch(
                request_kind="RESULT", events_requested=0, events_returned=0,
                status_code=result.status_code, ok=True, events=(),
                error="non-list payload", cost_estimate=1.0,
            )
            self._record(batch)
            return batch
        events = tuple(parse_result_event(e) for e in payload if isinstance(e, dict))
        batch = ProviderResultBatch(
            request_kind="RESULT",
            events_requested=len(events),
            events_returned=len(events),
            status_code=result.status_code,
            ok=True,
            events=events,
            cost_estimate=1.0,
        )
        self._record(batch)
        return batch

    def fetch_event_result(self, provider_event_id: str) -> ProviderResultBatch:
        probe_get, parse_recovered_json = self._load_helpers()
        url = f"{self.BASE}/events/{provider_event_id}?apiKey={self._key}"
        result, evidence, parsed = probe_get(
            "odds_api_io", "result-acquisition-by-id", url,
            known_secrets=(self._key,), max_response_bytes=8 * 1024 * 1024,
        )
        self.last_request_count = 1
        if result is None or getattr(result, "status_code", None) is None:
            batch = ProviderResultBatch(
                request_kind="RESULT_BY_ID", events_requested=1, events_returned=0,
                ok=False, error="no provider response", cost_estimate=1.0,
            )
            self._record(batch)
            return batch
        status_code = result.status_code
        payload, _ = parse_recovered_json(evidence.body or "")
        payload = parsed if payload is None else payload
        if status_code == 404 or payload is None:
            batch = ProviderResultBatch(
                request_kind="RESULT_BY_ID", events_requested=1, events_returned=0,
                status_code=status_code, ok=True, events=(),
                error="provider event not found", cost_estimate=1.0,
            )
            self._record(batch)
            return batch
        events = (parse_result_event(payload),) if isinstance(payload, dict) else ()
        batch = ProviderResultBatch(
            request_kind="RESULT_BY_ID",
            events_requested=1,
            events_returned=len(events),
            status_code=status_code,
            ok=True,
            events=events,
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
            }
        # participant keys from tt_forward_events (canonical A/B)
        keys = self._participant_keys(event["canonical_event_id"])
        canonical_a = keys.get("player_a_key") or provider_result.home
        canonical_b = keys.get("player_b_key") or provider_result.away
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

    def acquire_and_settle(self, *, recent_window_hours: int = 96, max_events: int | None = None) -> dict[str, Any]:
        """Acquire provider results for unsettled past events, persist local
        results, settle FINAL events and score official predictions.

        Strategy (P3/P4): one bounded feed sweep first (efficient batch), then
        per-event lookup only for events not found in the feed. Local result
        rows are checked first so a genuinely-present local result is never
        reported as provider-empty.
        """
        events = self.past_unsettled_events()
        if max_events is not None:
            events = events[:max_events]
        now = datetime.now(timezone.utc)
        from_iso = (now - timedelta(hours=recent_window_hours)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        to_iso = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")

        local_results = self._local_results_map(events)

        feed_events: dict[str, ProviderResultEvent] = {}
        if events:
            sweep = self._feed.fetch_recent_results(from_iso=from_iso, to_iso=to_iso)
            feed_events = {e.provider_event_id: e for e in sweep.events if e.provider_event_id}

        classified: dict[str, int] = {}
        acquired = 0
        settled = 0
        scores = 0
        errors: list[str] = []
        processed = 0
        for event in events:
            canonical_event_id = event["canonical_event_id"]
            provider_event_id = event.get("provider_event_id")
            local = local_results.get(canonical_event_id)
            if local is not None:
                state = LOCAL_RESULT_PRESENT
                if not self._has_final_settlement(canonical_event_id):
                    normalized = {
                        "home_score": local["home_score"],
                        "away_score": local["away_score"],
                        "winner_side": local["winner_side"],
                        "orientation": "CANONICAL",
                        "state": RESULT_STATE_FINAL,
                        "provider_event_id": provider_event_id,
                    }
                    settled += self._settle_event(event, normalized)
                    scores += self._score_event(event, normalized)
                self._store.upsert_result_acquisition(
                    {
                        "canonical_event_id": canonical_event_id,
                        "provider": event.get("provider") or "odds_api_io",
                        "provider_event_id": provider_event_id,
                        "commence_at": event["commence_at"],
                        "acquisition_state": state,
                        "result_status": "settled",
                        "actual_a": local["home_score"],
                        "actual_b": local["away_score"],
                        "winner_side": local["winner_side"],
                        "orientation": "CANONICAL",
                        "next_poll_at": next_poll_at(state=state, request_count=0).isoformat().replace("+00:00", "Z"),
                        "settled": True,
                    }
                )
                classified[state] = classified.get(state, 0) + 1
                processed += 1
                continue

            provider_result = feed_events.get(provider_event_id) if provider_event_id else None
            state = self.classify_acquisition_state(
                has_local_result=False,
                provider_event_id=provider_event_id,
                provider_batch=(
                    ProviderResultBatch(
                        request_kind="RESULT",
                        events_requested=1,
                        events_returned=1,
                        ok=True,
                        events=(provider_result,),
                    )
                    if provider_result is not None
                    else None
                ),
                provider_status=provider_result.status if provider_result is not None else None,
            )
            # Distinguish genuinely-requested empty (sweep covered the window)
            # from never-requested: if the event is within the swept window but
            # absent, that IS provider-empty evidence for the recent window.
            if state == LOCAL_RESULT_MISSING_NOT_REQUESTED and provider_event_id is None:
                state = PROVIDER_EVENT_IDENTITY_MISMATCH
            elif provider_result is None:
                if self._event_in_window(event, now, recent_window_hours):
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

            if state not in (PROVIDER_RESULT_AVAILABLE,):
                if state in (PROVIDER_RESULT_ERROR, PROVIDER_RESULT_SCHEMA_UNKNOWN, PROVIDER_EVENT_IDENTITY_MISMATCH):
                    errors.append(f"{canonical_event_id}: {state}")
                continue

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
            if normalized["state"] == RESULT_STATE_FINAL and normalized["winner_side"] is not None:
                settled_rows = self._settle_event(event, normalized)
                settled += settled_rows
                scores += self._score_event(event, normalized)
                row.update(
                    acquisition_state=LOCAL_RESULT_PRESENT,
                    result_status="settled",
                    actual_a=normalized["home_score"],
                    actual_b=normalized["away_score"],
                    winner_side=normalized["winner_side"],
                    orientation=normalized["orientation"],
                    settled=True,
                )
            else:
                row.update(
                    acquisition_state=PROVIDER_RESULT_AVAILABLE,
                    result_status=normalized["state"],
                    actual_a=normalized.get("home_score"),
                    actual_b=normalized.get("away_score"),
                    winner_side=normalized.get("winner_side"),
                    orientation=normalized.get("orientation"),
                )
            self._store.upsert_result_acquisition(row)
            processed += 1

        return {
            "classified": classified,
            "events": len(events),
            "acquired": acquired,
            "settled": settled,
            "scores": scores,
            "errors": errors[:20],
            "summary": f"result acquisition: {acquired} acquired, {settled} settled, {scores} scored",
        }

    def _local_results_map(self, events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        if not events:
            return {}
        with self._database.connect() as connection, connection.cursor() as cursor:
            placeholders = ",".join("%s" for _ in events)
            cursor.execute(
                f"SELECT event_key, home_score, away_score FROM tt_match_results "
                f"WHERE event_key IN ({placeholders})",
                [e["canonical_event_id"] for e in events],
            )
            out: dict[str, dict[str, Any]] = {}
            for event_key, hs, aws in cursor.fetchall():
                hs, aws = int(hs), int(aws)
                out[str(event_key)] = {
                    "home_score": hs,
                    "away_score": aws,
                    "winner_side": result_winner(home_score=hs, away_score=aws),
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
        """Insert a FINAL settlement (P7) without overwriting prior revisions."""
        canonical_event_id = event["canonical_event_id"]
        provider_event_id = normalized["provider_event_id"] or event.get("provider_event_id")
        source_result_id = f"oaio:{provider_event_id}" if provider_event_id else canonical_event_id
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
                "orientation_verified": normalized["orientation"] in ("CANONICAL", "REVERSED"),
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
    """P11: unique canonical-event metrics for official forward predictions."""
    scores = store.list_forward_scores(limit=100000)
    m5: dict[str, list[dict[str, Any]]] = {}
    shadow: dict[str, list[dict[str, Any]]] = {}
    for s in scores:
        event = str(s["canonical_event_id"])
        model = str(s["model_id"])
        target = m5 if "M5" in model.upper() else shadow
        target.setdefault(event, []).append(s)
    def _summarize(bucket: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        events = list(bucket.keys())
        if not events:
            return {"events": 0, "brier": None, "logloss": None}
        n = len(events)
        brier = sum(float(s["brier"]) for rows in bucket.values() for s in rows) / n
        logloss = sum(float(s["logloss"]) for rows in bucket.values() for s in rows) / n
        return {"events": n, "brier": round(brier, 8), "logloss": round(logloss, 8)}
    m5_summary = _summarize(m5)
    shadow_summary = _summarize(shadow)
    paired_events = set(m5) & set(shadow)
    paired = None
    if paired_events:
        m5_pairs = [float(bucket[e][0]["brier"]) for e in paired_events for bucket in (m5,)]
        shadow_pairs = [float(bucket[e][0]["brier"]) for e in paired_events for bucket in (shadow,)]
        m5_brier = sum(m5_pairs) / len(m5_pairs)
        shadow_brier = sum(shadow_pairs) / len(shadow_pairs)
        paired = {
            "events": len(paired_events),
            "m5_brier": round(m5_brier, 8),
            "shadow_brier": round(shadow_brier, 8),
            "brier_delta": round(m5_brier - shadow_brier, 8),
        }
    return {
        "m5": m5_summary,
        "shadow": shadow_summary,
        "paired": paired,
        "policy_versions": {"logloss_eps": LOGLOSS_EPSILON_POLICY, "scoring": SCORING_POLICY_VERSION},
    }
