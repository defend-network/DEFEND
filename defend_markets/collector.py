"""Live table-tennis collector: scores + h2h odds with quota governance.

The collector is the live-data gate for the prediction system. It reuses
the existing markets score feed (``the_odds_api_tt`` -> tt_match_results)
and the sports odds provider (h2h -> odds_snapshots), and adds:

* free discovery caching (sports list endpoint, cached for a day)
* quota governor: every response's quota headers are persisted to
  ``provider_quota`` and paid odds pulls stop once remaining credits
  fall below the configured floor (``TT_ODDS_CREDIT_FLOOR``)
* 1 request/second pacing with bounded 429 backoff (exponential + jitter)
* adaptive polling: active interval while live events exist, idle
  interval otherwise, durable state in ``tt_collector_state``
* honest UNCONFIGURED / QUOTA_PROTECTED statuses

Nothing here ever fabricates data: with no key, no events, or no credits
the collector reports the real state and takes no action.
"""

from __future__ import annotations

import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Sequence

from defend_markets.feeds import FeedError, FeedService, odds_api_key

from defend_sports.db import SportsDatabase
from defend_sports.domain import SourceRef
from defend_sports.ingestion import IngestionService
from defend_sports.providers.base import ProviderBatch
from defend_sports.providers.the_odds_api import (
    OddsApiProviderError,
    TheOddsApiSportsProvider,
)
from defend_sports.repositories import SportsRepository

ODDS_API_BASE = "https://api.the-odds-api.com/v4/sports"
PROVIDER_NAME = "the_odds_api"
COLLECTOR_KEY = "tt_collector"
_USER_AGENT = "DEFEND/1.0 (commercial-intelligence-pipeline)"
_MAX_BODY_BYTES = 2 * 1024 * 1024

DEFAULT_CREDIT_FLOOR = 25
DEFAULT_ACTIVE_POLL_SECONDS = 15
DEFAULT_IDLE_POLL_SECONDS = 300
DEFAULT_SCORES_POLL_SECONDS = 600
DEFAULT_DISCOVERY_CACHE_SECONDS = 24 * 3600
MIN_REQUEST_INTERVAL = 1.0
MAX_429_RETRIES = 3
_429_BACKOFF_BASE = 2.0


@dataclass(frozen=True)
class TtCollectorConfig:
    credit_floor: int = DEFAULT_CREDIT_FLOOR
    active_poll_seconds: float = DEFAULT_ACTIVE_POLL_SECONDS
    idle_poll_seconds: float = DEFAULT_IDLE_POLL_SECONDS
    scores_poll_seconds: float = DEFAULT_SCORES_POLL_SECONDS
    discovery_cache_seconds: float = DEFAULT_DISCOVERY_CACHE_SECONDS

    def __post_init__(self) -> None:
        if self.credit_floor < 0:
            raise ValueError("credit floor must be >= 0")
        if self.active_poll_seconds < MIN_REQUEST_INTERVAL:
            raise ValueError("active poll interval must be >= 1s")
        if self.idle_poll_seconds < self.active_poll_seconds:
            raise ValueError("idle poll interval must be >= active poll interval")


def tt_collector_config_from_env() -> TtCollectorConfig:
    def _int(name: str, default: int) -> int:
        raw = os.environ.get(name, "").strip()
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError:
            return default

    return TtCollectorConfig(
        credit_floor=_int("TT_ODDS_CREDIT_FLOOR", DEFAULT_CREDIT_FLOOR),
        active_poll_seconds=_int("TT_ODDS_POLL_ACTIVE_SECONDS", DEFAULT_ACTIVE_POLL_SECONDS),
        idle_poll_seconds=_int("TT_ODDS_POLL_IDLE_SECONDS", DEFAULT_IDLE_POLL_SECONDS),
        scores_poll_seconds=_int("TT_SCORES_POLL_SECONDS", DEFAULT_SCORES_POLL_SECONDS),
    )


@dataclass(frozen=True)
class TtCollectorRun:
    provider: str = PROVIDER_NAME
    configured: bool = True
    status: str = "HEALTHY"
    detail: str = ""
    scores_results: int = 0
    tt_results: int = 0
    events: int = 0
    odds_snapshots: int = 0
    live_observations: int = 0
    credits_remaining: int | None = None
    credits_used: int | None = None
    mode: str = "idle"
    quota_protected: bool = False


class _PacedFetch:
    """1 req/s pacing + bounded 429 backoff with jitter; captures quota headers."""

    def __init__(
        self,
        *,
        quota_sink: Callable[[dict[str, object]], None],
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        random_source: Callable[[], float] = random.random,
    ) -> None:
        self._quota_sink = quota_sink
        self._clock = clock
        self._sleep = sleep
        self._random = random_source
        self._last_request_at: float | None = None

    def __call__(self, url: str) -> tuple[object, int]:
        self._pace()
        request = urllib.request.Request(
            url,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
        )
        for attempt in range(MAX_429_RETRIES + 1):
            try:
                with urllib.request.urlopen(request, timeout=20.0) as response:
                    payload = response.read(_MAX_BODY_BYTES + 1)
                    headers = {key.lower(): value for key, value in response.headers.items()}
            except urllib.error.HTTPError as error:
                if error.code == 429 and attempt < MAX_429_RETRIES:
                    self._backoff(attempt)
                    continue
                raise OddsApiProviderError(f"status {error.code}") from None
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                raise OddsApiProviderError(type(error).__name__) from None
            self._last_request_at = self._clock()
            self._quota_sink(_quota_headers(headers))
            return json_bytes(payload), 200

    def _pace(self) -> None:
        if self._last_request_at is None:
            return
        elapsed = self._clock() - self._last_request_at
        wait = MIN_REQUEST_INTERVAL - elapsed
        if wait > 0:
            self._sleep(wait)

    def _backoff(self, attempt: int) -> None:
        jitter = self._random() * 0.5 + 0.75
        self._sleep(_429_BACKOFF_BASE * (2 ** attempt) * jitter)


def json_bytes(payload: bytes) -> object:
    import json

    try:
        return json.loads(payload)
    except ValueError as error:
        raise OddsApiProviderError("invalid JSON in provider payload") from error


def _quota_headers(headers: dict[str, str]) -> dict[str, object]:
    def _int(name: str) -> int | None:
        raw = headers.get(name)
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    return {
        "requests_remaining": _int("x-requests-remaining"),
        "requests_used": _int("x-requests-used"),
        "requests_last": headers.get("x-requests-last"),
    }


class TtCollector:
    """Orchestrates scores + odds collection with quota governance."""

    def __init__(
        self,
        *,
        sports_database: SportsDatabase,
        feed_service: FeedService,
        markets_forecast: Any,
        sports_repository: SportsRepository | None = None,
        config: TtCollectorConfig | None = None,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._sports_database = sports_database
        self._feed_service = feed_service
        self._forecast = markets_forecast
        self._repository = sports_repository if sports_repository is not None else SportsRepository()
        self._config = config if config is not None else tt_collector_config_from_env()
        self._clock = clock if clock is not None else (lambda: datetime.now(timezone.utc))
        self._sleep = sleep
        self._discovery_cache: tuple[datetime, tuple[str, ...]] | None = None
        self._quota_state: dict[str, object] = {}

    def one_shot(self) -> TtCollectorRun:
        api_key = odds_api_key()
        if not api_key:
            self._set_state(status="UNCONFIGURED", detail="missing THE_ODDS_API_KEY")
            return TtCollectorRun(configured=False, status="UNCONFIGURED", detail="missing THE_ODDS_API_KEY")

        remaining = self._quota_state.get("requests_remaining")
        if remaining is not None and int(remaining) < self._config.credit_floor:
            run = TtCollectorRun(
                credits_remaining=int(remaining),
                credits_used=self._quota_state.get("requests_used"),
                quota_protected=True,
                mode="protected",
                status="QUOTA_PROTECTED",
                detail=(
                    f"credits remaining {remaining} below floor {self._config.credit_floor}"
                ),
            )
            self._set_state(status="QUOTA_PROTECTED", detail=run.detail, run=run)
            return run

        run = TtCollectorRun()
        try:
            self._record_discovery(api_key)
        except OddsApiProviderError as error:
            self._set_state(status="UNAVAILABLE", detail=error.detail)
            return TtCollectorRun(configured=True, status="UNAVAILABLE", detail=error.detail)

        remaining = self._quota_state.get("requests_remaining")
        run = replace(
            run,
            credits_remaining=int(remaining) if remaining is not None else None,
            credits_used=self._quota_state.get("requests_used"),
        )
        if remaining is not None and int(remaining) < self._config.credit_floor:
            run = replace(run, quota_protected=True, mode="protected", status="QUOTA_PROTECTED",
                          detail=f"credits remaining {remaining} below floor {self._config.credit_floor}")
            self._set_state(status="QUOTA_PROTECTED", detail=run.detail, run=run)
            return run

        scores = self._poll_scores(api_key)
        run = replace(run, scores_results=scores.record_count, tt_results=len(scores.tt_results))

        self._sleep(1.0)
        odds = self._poll_odds(api_key)
        run = replace(
            run,
            events=odds.events,
            odds_snapshots=odds.odds_snapshots,
            live_observations=odds.live_observations,
            mode="active" if (odds.events > 0 or odds.live_observations > 0) else "idle",
        )
        self._set_state(status="HEALTHY", detail="ok", run=run)
        return run

    def loop(self, *, stop: Callable[[], bool] | None = None) -> None:
        while True:
            run = self.one_shot()
            interval = (
                self._config.active_poll_seconds
                if run.mode == "active"
                else self._config.idle_poll_seconds
            )
            deadline = self._clock() + timedelta(seconds=interval)
            while True:
                if stop is not None and stop():
                    return
                if self._clock() >= deadline:
                    break
                self._sleep(1.0)

    # ------------------------------------------------------------------
    def _poll_scores(self, api_key: str) -> Any:
        return self._feed_service.poll("the_odds_api_tt")

    def _poll_odds(self, api_key: str) -> Any:
        paced = _PacedFetch(
            quota_sink=self._quota_state.update,
            clock=lambda: time.monotonic(),
        )
        provider = TheOddsApiSportsProvider(api_key=api_key, http_get=paced, clock=self._clock)
        batch: ProviderBatch = provider.poll()
        if not batch.raw_events:
            return _OddsTotals(0, 0, 0)
        ingested = IngestionService(self._sports_database).ingest(batch)
        return _OddsTotals(ingested.events, ingested.odds_snapshots, ingested.live_observations)

    def _record_discovery(self, api_key: str) -> None:
        now = self._clock()
        if self._discovery_cache is not None:
            cached_at, keys = self._discovery_cache
            if now - cached_at < timedelta(seconds=self._config.discovery_cache_seconds):
                return
        paced = _PacedFetch(
            quota_sink=self._quota_state.update,
            clock=lambda: time.monotonic(),
        )
        url = f"{ODDS_API_BASE}/?apiKey={urllib.parse.quote(api_key)}"
        payload, _status = paced(url)
        if not isinstance(payload, list):
            raise OddsApiProviderError("unexpected sports list payload")
        keys = tuple(
            sorted(
                {
                    str(entry["key"])
                    for entry in payload
                    if isinstance(entry, dict)
                    and isinstance(entry.get("key"), str)
                    and any(
                        hint in str(entry.get("key", "")).lower()
                        for hint in ("tabletennis", "table_tennis", "pingpong")
                    )
                }
            )
        )
        self._discovery_cache = (now, keys)
        with self._sports_database.connect() as connection:
            with connection.transaction():
                source_id = self._repository.upsert_source(
                    connection,
                    SourceRef(provider=PROVIDER_NAME, external_id=PROVIDER_NAME),
                    display_name="The Odds API",
                )
                self._repository.record_discovery(
                    connection,
                    source_id=source_id,
                    provider=PROVIDER_NAME,
                    payload=[dict(entry) for entry in payload if isinstance(entry, dict)],
                    observed_at=now,
                    received_at=now,
                )

    def _set_state(self, *, status: str, detail: str, run: TtCollectorRun | None = None) -> None:
        now = self._clock()
        try:
            self._forecast.set_collector_state(
                collector_key=COLLECTOR_KEY,
                last_cycle_at=now,
                quota_status=status,
                last_quota_remaining=self._quota_state.get("requests_remaining"),
                last_quota_used=self._quota_state.get("requests_used"),
                last_quota_last=self._quota_state.get("requests_last"),
                last_error=detail if status != "HEALTHY" else None,
            )
        except Exception:
            pass
        if status not in ("HEALTHY", "UNAVAILABLE"):
            return
        try:
            with self._sports_database.connect() as connection:
                with connection.transaction():
                    source_id = self._repository.upsert_source(
                        connection,
                        SourceRef(provider=PROVIDER_NAME, external_id=PROVIDER_NAME),
                        display_name="The Odds API",
                    )
                    self._repository.record_provider_health(
                        connection,
                        source_id=source_id,
                        status=status,
                        detail={"collector": detail},
                        observed_at=now,
                        received_at=now,
                    )
                    if self._quota_state.get("requests_remaining") is not None:
                        self._repository.record_quota(
                            connection,
                            source_id=source_id,
                            provider=PROVIDER_NAME,
                            requests_remaining=self._quota_state.get("requests_remaining"),
                            requests_used=self._quota_state.get("requests_used"),
                            requests_last=self._quota_state.get("requests_last"),
                            status=status,
                            observed_at=now,
                            received_at=now,
                        )
        except Exception:
            pass


@dataclass(frozen=True)
class _OddsTotals:
    events: int = 0
    odds_snapshots: int = 0
    live_observations: int = 0