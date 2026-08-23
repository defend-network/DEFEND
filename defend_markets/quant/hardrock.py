"""M4.8 Hard Rock FL first-class data lane.

Hard Rock Bet (Florida) via Owls Insight is the PRIMARY execution/reference
book. This module provides:

* :class:`HardRockLadder` — point-in-time rootIdx -> American odds -> decimal ->
  implied probability normalization. rootIdx is resolved against an immutable
  ladder snapshot; old observations retain the ladder mapping that was valid at
  observation time (P4/P5).
* :class:`OwlsHardRockAdapter` — production ingestion adapter: fetch the FL
  TABLE_TENNIS board + ladder, parse events/markets/selections, normalize Hard
  Rock prices, and emit canonical provider observations (P6). All HTTP goes
  through the M4.7.2 governed ProviderRequestExecutor; this adapter NEVER
  settles events and NEVER scores models (P24).

Provider identity (P7): data_provider = owls_insight, sportsbook = hardrock_bet,
state = fl, sport = TABLE_TENNIS. Owls is the DATA PROVIDER, Hard Rock is the
BOOK/venue — they are never collapsed into one semantic field.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

DATA_PROVIDER_OWLS = "owls_insight"
SPORTSBOOK_HARDROCK = "hardrock_bet"
STATE_FL = "fl"
SPORT_TABLE_TENNIS = "TABLE_TENNIS"

# canonical market families (fail-closed; first pass = MATCH_WINNER_2WAY)
FAMILY_MATCH_WINNER = "MATCH_WINNER_2WAY"
FAMILY_SPREAD = "SPREAD"
FAMILY_TOTAL = "TOTAL"
FAMILY_UNSUPPORTED = "UNSUPPORTED"

# Owls market type -> canonical family
_MARKET_TYPE_FAMILY = {
    "TABLE_TENNIS:FT:ML": FAMILY_MATCH_WINNER,
    "TABLE_TENNIS:FT:PHCP": FAMILY_SPREAD,
    "TABLE_TENNIS:FT:OU": FAMILY_TOTAL,
}

# period mapping: Hard Rock "M" = full match. Game/set periods are NOT first-pass.
_PERIOD_MAP = {"M": "FULL_MATCH"}


def canonical_market_family(owls_market_type: str) -> str:
    return _MARKET_TYPE_FAMILY.get(str(owls_market_type).upper(), FAMILY_UNSUPPORTED)


def american_to_decimal(american: int) -> Decimal:
    """Deterministic American -> decimal odds."""
    a = int(american)
    if a > 0:
        return (Decimal("1") + Decimal(a) / Decimal("100")).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    if a < 0:
        return (Decimal("1") + Decimal("100") / Decimal(abs(a))).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    return Decimal("1.000")


def decimal_to_implied(decimal_odds: Decimal) -> Decimal:
    if decimal_odds <= Decimal("1"):
        return Decimal("0")
    return (Decimal("1") / decimal_odds).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class HardRockLadder:
    """Immutable rootIdx -> American odds ladder snapshot (P4/P5)."""

    entries: dict[int, int]
    retrieved_at: datetime
    raw_response_sha256: str | None = None
    canonical_response_sha256: str | None = None
    ladder_identity: str | None = None

    def american_odds(self, root_idx: int) -> int | None:
        return self.entries.get(int(root_idx))

    def decimal_odds(self, root_idx: int) -> Decimal | None:
        american = self.american_odds(root_idx)
        if american is None:
            return None
        return american_to_decimal(american)

    def implied_probability(self, root_idx: int) -> Decimal | None:
        dec = self.decimal_odds(root_idx)
        if dec is None:
            return None
        return decimal_to_implied(dec)

    @property
    def entry_count(self) -> int:
        return len(self.entries)

    @classmethod
    def from_payload(cls, payload: dict[str, Any], *, retrieved_at: datetime | None = None,
                     raw_response_sha256: str | None = None, canonical_response_sha256: str | None = None) -> "HardRockLadder":
        data = payload.get("data") or {}
        ladder = data.get("ladder") or []
        entries: dict[int, int] = {}
        for row in ladder:
            if not isinstance(row, dict):
                continue
            if "rootIdx" not in row:
                continue
            american = row.get("americanOdds")
            if not isinstance(american, int):
                continue
            entries[int(row["rootIdx"])] = american
        return cls(
            entries=entries,
            retrieved_at=retrieved_at or datetime.now(timezone.utc),
            raw_response_sha256=raw_response_sha256,
            canonical_response_sha256=canonical_response_sha256,
            ladder_identity=str(payload.get("etag") or ""),
        )


def parse_hardrock_event(event: dict[str, Any]) -> dict[str, Any] | None:
    """Parse one Hard Rock event dict into a normalized canonical event record."""
    event_id = str(event.get("id") or "")
    if not event_id:
        return None
    participants = event.get("participants") or []
    names = []
    for p in participants:
        if isinstance(p, dict) and p.get("name"):
            names.append(str(p["name"]))
    scheduled = None
    event_time = event.get("eventTime")
    if isinstance(event_time, (int, float)):
        scheduled = datetime.fromtimestamp(int(event_time) / 1000, tz=timezone.utc)
    return {
        "provider_event_id": event_id,
        "betradar_id": str(event.get("betradarId") or ""),
        "name": str(event.get("name") or ""),
        "participants": names,
        "competition": None,  # Owls board does not expose tournament grouping here
        "scheduled_time": scheduled,
        "inplay": bool(event.get("inplay")),
        "state": str(event.get("state") or ""),
        "markets": event.get("markets") or [],
    }


def parse_selection_side(selection_type: str) -> str | None:
    """Hard Rock selection type -> canonical side. 'A'/'B' for 2-way; 'AH'/'BH'
    for handicap; 'OVER'/'UNDER' handled via market type."""
    t = str(selection_type or "").upper()
    if t == "A":
        return "PARTICIPANT_A"
    if t == "B":
        return "PARTICIPANT_B"
    if t == "OVER":
        return "OVER"
    if t == "UNDER":
        return "UNDER"
    return None


def parse_market_line(market: dict[str, Any]) -> str | None:
    """Extract an exact line from an Owls market subtype (e.g. 'M#-3.5' -> '-3.5')."""
    subtype = str(market.get("subtype") or "")
    if "#" in subtype:
        return subtype.split("#", 1)[1]
    return None


class OwlsHardRockAdapter:
    """Production Owls/Hard Rock ingestion adapter (P6).

    Read-only. Fetches the FL TABLE_TENNIS board and the ladder, normalizes Hard
    Rock prices, and emits canonical quote observations. Never settles, never
    scores.
    """

    BASE = "https://api.owlsinsight.com/api/v2/hardrock"

    def __init__(self, key: str, store: Any, *, executor: Any | None = None,
                 fetch: Any | None = None) -> None:
        self._key = key
        self._store = store
        self._executor = executor
        self._fetch = fetch
        self._browser_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

    def _load_fetch(self):
        if self._fetch is not None:
            return self._fetch
        from defend_integrations.http import fetch
        return fetch

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "User-Agent": self._browser_ua,
            "Authorization": f"Bearer {self._key}",
        }

    def fetch_ladder(self) -> HardRockLadder | None:
        """Fetch + normalize the Hard Rock price ladder (governed HTTP)."""
        fetch = self._load_fetch()
        url = f"{self.BASE}/ladder"
        headers = self._headers()
        result = self._governed_fetch(url, headers)
        if result is None or not result.ok or not result.body:
            return None
        import json as _json
        try:
            payload = _json.loads(result.body)
        except ValueError:
            return None
        raw_sha, canon_sha = _hashes(result.body)
        return HardRockLadder.from_payload(
            payload,
            raw_response_sha256=raw_sha,
            canonical_response_sha256=canon_sha,
        )

    def fetch_board(self) -> dict[str, Any] | None:
        """Fetch the FL TABLE_TENNIS board (governed HTTP)."""
        fetch = self._load_fetch()
        url = f"{self.BASE}/fl/TABLE_TENNIS"
        headers = self._headers()
        result = self._governed_fetch(url, headers)
        if result is None or not result.ok or not result.body:
            return None
        import json as _json
        try:
            return _json.loads(result.body)
        except ValueError:
            return None

    def _governed_fetch(self, url: str, headers: dict[str, str]):
        fetch = self._load_fetch()
        if self._executor is None:
            return fetch(url, timeout_seconds=55.0, headers=headers, retries=1,
                         backoff_seconds=1.0, known_secrets=(self._key,), capture_error_body=True,
                         max_response_bytes=8 * 1024 * 1024, max_output_bytes=8 * 1024 * 1024)
        governed = self._executor.execute(
            provider=DATA_PROVIDER_OWLS,
            request_class="CURRENT_EVENT",
            operation="hardrock-fl-tt",
            request_metadata={},
            callable=lambda: fetch(url, timeout_seconds=55.0, headers=headers, retries=1,
                                   backoff_seconds=1.0, known_secrets=(self._key,), capture_error_body=True,
                                   max_response_bytes=8 * 1024 * 1024, max_output_bytes=8 * 1024 * 1024),
        )
        if not governed.allowed:
            return None
        return governed.payload

    def ingest(self) -> dict[str, Any]:
        """Fetch board + ladder, normalize, emit canonical observations (P6).

        Returns a sanitized summary. Never writes settlements or scores.
        """
        ladder = self.fetch_ladder()
        board = self.fetch_board()
        if board is None:
            return {"ok": False, "reason": "board unavailable", "ladder_entries": ladder.entry_count if ladder else 0}
        if ladder is None:
            return {"ok": False, "reason": "ladder unavailable"}
        # persist the ladder snapshot first so every quote links to its exact
        # PIT ladder identity (P5).
        ladder_snapshot_id = None
        if self._store is not None and hasattr(self._store, "insert_hardrock_ladder_snapshot"):
            ladder_snapshot_id = self._store.insert_hardrock_ladder_snapshot(
                {
                    "data_provider": DATA_PROVIDER_OWLS,
                    "sportsbook": SPORTSBOOK_HARDROCK,
                    "state": STATE_FL,
                    "retrieved_at": ladder.retrieved_at,
                    "raw_response_sha256": ladder.raw_response_sha256,
                    "canonical_response_sha256": ladder.canonical_response_sha256,
                    "entry_count": ladder.entry_count,
                    "ladder_identity": ladder.ladder_identity,
                    "entries": ladder.entries,
                }
            )
        events = board.get("data") or []
        events_parsed = 0
        markets_parsed = 0
        quotes = 0
        for event in events:
            if not isinstance(event, dict):
                continue
            parsed = parse_hardrock_event(event)
            if parsed is None:
                continue
            events_parsed += 1
            for market in parsed["markets"]:
                if not isinstance(market, dict):
                    continue
                family = canonical_market_family(str(market.get("type") or ""))
                if family == FAMILY_UNSUPPORTED:
                    continue
                # first production pass: MATCH_WINNER_2WAY only (P10)
                if family != FAMILY_MATCH_WINNER:
                    continue
                period = _PERIOD_MAP.get(str(market.get("period") or ""), "")
                if not period:
                    continue
                markets_parsed += 1
                for sel in market.get("selections", []):
                    if not isinstance(sel, dict):
                        continue
                    root_idx = sel.get("rootIdx")
                    if not isinstance(root_idx, int):
                        continue
                    american = ladder.american_odds(root_idx)
                    if american is None:
                        continue  # unknown rootIdx -> fail closed (no fabrication)
                    side = parse_selection_side(str(sel.get("type") or ""))
                    if side is None:
                        continue
                    dec = american_to_decimal(american)
                    implied = decimal_to_implied(dec)
                    observed_at = datetime.now(timezone.utc)
                    quote = {
                        "canonical_event_id": f"hardrock:{parsed['provider_event_id']}",
                        "data_provider": DATA_PROVIDER_OWLS,
                        "sportsbook": SPORTSBOOK_HARDROCK,
                        "state": STATE_FL,
                        "provider_event_id": parsed["provider_event_id"],
                        "market_family": family,
                        "period": period,
                        "line": None,
                        "selection": str(sel.get("name") or ""),
                        "selection_side": side,
                        "root_idx": root_idx,
                        "ladder_snapshot_id": ladder_snapshot_id or ladder.entry_count,
                        "american_odds": american,
                        "decimal_odds": dec,
                        "implied_probability": implied,
                        "observed_at": observed_at,
                        "raw_payload_hash": None,
                    }
                    if self._store and hasattr(self._store, "insert_hardrock_quote"):
                        self._store.insert_hardrock_quote(quote)
                    quotes += 1
        return {
            "ok": True,
            "events": events_parsed,
            "markets": markets_parsed,
            "quotes": quotes,
            "ladder_entries": ladder.entry_count,
            "ladder_snapshot_id": ladder_snapshot_id,
        }


def _hashes(body: str) -> tuple[str | None, str | None]:
    raw = hashlib.sha256(body.encode("utf-8")).hexdigest()
    try:
        canon = hashlib.sha256(json.dumps(json.loads(body), sort_keys=True, default=str).encode("utf-8")).hexdigest()
    except ValueError:
        canon = None
    return raw, canon
