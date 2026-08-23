"""Bookmaker-agnostic provider truth.

No bookmaker-specific operational truth is hard-coded. Bookmaker state derives
from the live selected-books endpoint, bookmaker-filtered event discovery, and
windowed persisted attestation evidence (quant_bookmaker_coverage).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class BookmakerCoverage:
    bookmaker_id: str
    selected: bool = False
    attestation_state: str = "UNKNOWN"
    filtered_events: int = 0
    pending_events: int = 0
    live_events: int = 0
    priced_events: int = 0
    observations: int = 0
    competitions: dict[str, int] = field(default_factory=dict)
    market_types: list[str] = field(default_factory=list)
    coverage_window_start: str = ""
    coverage_window_end: str = ""
    first_observation_at: str | None = None
    last_observation_at: str | None = None
    last_attested_at: str = ""
    error_state: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "bookmaker_id": self.bookmaker_id,
            "selected": self.selected,
            "attestation_state": self.attestation_state,
            "filtered_events": self.filtered_events,
            "pending_events": self.pending_events,
            "live_events": self.live_events,
            "priced_events": self.priced_events,
            "observations": self.observations,
            "competitions": self.competitions,
            "market_types": self.market_types,
            "coverage_window_start": self.coverage_window_start,
            "coverage_window_end": self.coverage_window_end,
            "first_observation_at": self.first_observation_at,
            "last_observation_at": self.last_observation_at,
            "last_attested_at": self.last_attested_at,
            "error_state": self.error_state,
        }


class ProviderTruthService:
    """Reads live selected books and windowed attestations; no hardcoded books."""

    def __init__(self, store: Any, database: Any) -> None:
        self._store = store
        self._database = database

    def selected_bookmakers(self) -> list[str]:
        from defend_integrations.stores import SecretRegistry, default_secret_path
        from defend_control.secrets import DpapiSecretStore
        from defend_integrations.probing import probe_get
        from defend_markets.shadow import parse_recovered_json

        key = SecretRegistry(DpapiSecretStore(default_secret_path())).get("ODDS_API_IO_API_KEY")
        if not key:
            return []
        url = "https://api.odds-api.io/v3/bookmakers/selected?apiKey=" + key
        result, evidence, parsed = probe_get(
            "odds_api_io", "selected", url, known_secrets=(key,), max_response_bytes=65536
        )
        payload, _ = parse_recovered_json(evidence.body or "")
        payload = parsed if payload is None else payload
        if isinstance(payload, dict) and isinstance(payload.get("bookmakers"), list):
            return [str(b) for b in payload["bookmakers"] if isinstance(b, str)]
        return []

    def snapshot(self, selected: list[str] | None = None) -> dict[str, dict[str, Any]]:
        if selected is None:
            selected = self.selected_bookmakers()
        selected_set = set(selected)
        snapshots: dict[str, dict[str, Any]] = {}
        for row in self._store.list_bookmaker_coverage(limit=200):
            entry = dict(row)
            bookmaker_id = str(entry["bookmaker_id"])
            entry["selected"] = bookmaker_id in selected_set
            snapshots[bookmaker_id] = entry
        for bookmaker_id in selected:
            snapshots.setdefault(
                bookmaker_id,
                {"bookmaker_id": bookmaker_id, "selected": True, "attestation_state": "UNKNOWN"},
            )
        return snapshots

    def attest(
        self,
        bookmaker_id: str,
        sport_slug: str,
        *,
        window_hours: int = 72,
    ) -> dict[str, Any]:
        from defend_integrations.stores import SecretRegistry, default_secret_path
        from defend_control.secrets import DpapiSecretStore
        from defend_integrations.probing import probe_get
        from defend_markets.shadow import parse_recovered_json

        key = SecretRegistry(DpapiSecretStore(default_secret_path())).get("ODDS_API_IO_API_KEY")
        now = datetime.now(timezone.utc)
        window_start = now.isoformat().replace("+00:00", "Z")
        window_end = (now + timedelta(hours=window_hours)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        url = (
            "https://api.odds-api.io/v3/events?sport=" + sport_slug
            + "&bookmaker=" + bookmaker_id.replace(" ", "%20")
            + "&from=" + window_start + "&to=" + window_end + "&apiKey=" + key
        )
        result, evidence, parsed = probe_get(
            "odds_api_io", "attest-" + bookmaker_id, url,
            known_secrets=(key,), max_response_bytes=8 * 1024 * 1024,
        )
        payload, _ = parse_recovered_json(evidence.body or "")
        payload = parsed if payload is None else payload
        events = payload if isinstance(payload, list) else []
        ids = [str(e.get("id")) for e in events if isinstance(e, dict)]
        competitions: dict[str, int] = {}
        pending = 0
        live = 0
        for event in events:
            if not isinstance(event, dict):
                continue
            comp = str((event.get("league") or {}).get("name"))
            competitions[comp] = competitions.get(comp, 0) + 1
            if event.get("status") == "pending":
                pending += 1
            elif event.get("status") == "live":
                live += 1
        priced = 0
        observations = 0
        if ids:
            placeholders = ",".join("%s" for _ in ids)
            with self._database.connect() as connection, connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT count(DISTINCT provider_event_id), count(*) FROM tt_market_observations "
                    f"WHERE bookmaker = %s AND provider_event_id IN ({placeholders})",
                    (bookmaker_id, *ids),
                )
                row = cursor.fetchone()
                priced = int(row[0] or 0)
                observations = int(row[1] or 0)
        state = (
            "AVAILABLE" if observations > 0 else
            "ZERO_CURRENT_COVERAGE" if not ids else
            "PARTIAL_CURRENT_COVERAGE" if priced > 0 else
            "UNKNOWN"
        )
        coverage = BookmakerCoverage(
            bookmaker_id=bookmaker_id,
            selected=True,
            attestation_state=state,
            filtered_events=len(ids),
            pending_events=pending,
            live_events=live,
            priced_events=priced,
            observations=observations,
            competitions=competitions,
            coverage_window_start=window_start,
            coverage_window_end=window_end,
            last_attested_at=utc_now_iso(),
        )
        self._store.upsert_bookmaker_coverage(coverage.to_dict())
        return coverage.to_dict()

    def record_known_zero(self, bookmaker_id: str, *, window_days: int = 1) -> None:
        now = datetime.now(timezone.utc)
        coverage = BookmakerCoverage(
            bookmaker_id=bookmaker_id,
            selected=False,
            attestation_state="ZERO_CURRENT_COVERAGE",
            coverage_window_start=(now - timedelta(days=window_days)).isoformat().replace("+00:00", "Z"),
            coverage_window_end=now.isoformat().replace("+00:00", "Z"),
            last_attested_at=utc_now_iso(),
            error_state="ZERO_CURRENT_COVERAGE: zero during tested window; does not imply bookmaker never offers TT",
        )
        self._store.upsert_bookmaker_coverage(coverage.to_dict())
