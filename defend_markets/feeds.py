"""Live provider feeds for DEFENDmarkets.

Real, read-only ingestion of external data sources into the markets
database. Every provider is honest about its state: a provider with no
credential is recorded as UNCONFIGURED (never UNAVAILABLE, which would
claim a failed probe), a provider that fails is recorded as UNAVAILABLE
with the actual error, and a provider that partially succeeds is
DEGRADED. No provider ever fabricates records.

Providers implemented today (all keyless except the optional CoinGecko
key and the mandatory Odds API key for the TT results feed):

- polymarket: event-contract markets from the public Gamma API.
- world_bank: GDP growth, inflation and population indicator series.
- us_treasury: average interest rates by security type.
- coingecko: spot USD prices with 24h change (key optional).
- binance_public: public 24h tickers (may be geo-blocked; recorded as
  UNAVAILABLE with the HTTP status when so).
- the_odds_api_tt: table tennis completed-match scores used to build the
  L2 rating history. UNCONFIGURED until THE_ODDS_API_KEY is provided.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Protocol, Sequence, runtime_checkable
from uuid import UUID

from defend_markets.domain import TTMatchResult

_USER_AGENT = (
    "DEFENDmarkets feed collector (live ingestion; "
    "chairman@defend-network.org)"
)

_MAX_BODY_BYTES = 512 * 1024


class FeedError(Exception):
    """Provider poll failure carrying a human detail and HTTP status."""

    def __init__(self, detail: str, status_code: int | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def http_get_json(
    url: str,
    *,
    timeout_seconds: float = 20.0,
    headers: Mapping[str, str] | None = None,
    max_body_bytes: int = _MAX_BODY_BYTES,
) -> tuple[object, int]:
    """Fetch and parse JSON with strict size/time discipline.

    Returns ``(payload, status_code)``; raises :class:`FeedError` on
    transport errors, oversized bodies or invalid JSON.
    """
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "application/json",
            **(dict(headers) if headers else {}),
        },
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status = int(response.status)
            body = response.read(max_body_bytes + 1)
    except urllib.error.HTTPError as error:
        raise FeedError(f"status {error.code}", status_code=error.code) from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise FeedError(type(error).__name__) from None
    elapsed_ms = int((time.monotonic() - started) * 1000)
    if len(body) > max_body_bytes:
        raise FeedError("response body exceeds size cap")
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError) as error:
        raise FeedError("invalid JSON response") from None
    return payload, status


@dataclass(frozen=True)
class FeedRecord:
    """One normalized record from a provider poll."""

    record_key: str = ""
    payload: Mapping[str, object] = field(default_factory=dict)
    observed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.record_key, str) or not self.record_key.strip():
            raise ValueError("record_key must not be blank")
        if not isinstance(self.payload, Mapping):
            raise ValueError("payload must be a mapping")
        if self.observed_at is not None and (
            not isinstance(self.observed_at, datetime) or self.observed_at.tzinfo is None
        ):
            raise ValueError("observed_at must be a timezone-aware datetime")


@dataclass(frozen=True)
class FeedProbeResult:
    """Outcome of one provider poll, persisted into ``provider_feeds``."""

    provider_id: str
    ok: bool
    status: str
    latency_ms: int | None = None
    error: str | None = None
    detail: Mapping[str, object] = field(default_factory=dict)
    records: tuple[FeedRecord, ...] = ()
    tt_results: tuple[TTMatchResult, ...] = ()

    @property
    def record_count(self) -> int:
        return len(self.records)


@runtime_checkable
class FeedProvider(Protocol):
    provider_id: str
    display_name: str

    def poll(self, now: datetime) -> FeedProbeResult: ...


@dataclass(frozen=True)
class FeedDefinition:
    provider_id: str
    display_name: str


@runtime_checkable
class FeedSink(Protocol):
    def upsert_feed(self, definition: FeedDefinition) -> None: ...

    def record_probe(self, result: FeedProbeResult, *, observed_at: datetime) -> None: ...

    def insert_records(
        self, provider_id: str, records: Sequence[FeedRecord], *, received_at: datetime
    ) -> int: ...

    def record_tt_results(self, results: Sequence[TTMatchResult]) -> int: ...

    def list_feeds(self) -> list[dict[str, object]]: ...

    def list_records(self, provider_id: str, limit: int = 50) -> list[dict[str, object]]: ...


class FeedService:
    """Runs configured feed providers against a sink with honest status."""

    def __init__(
        self,
        sink: FeedSink,
        providers: Sequence[FeedProvider],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._sink = sink
        self._providers = {provider.provider_id: provider for provider in providers}
        self._clock = clock if clock is not None else (lambda: datetime.now(timezone.utc))

    def list(self) -> tuple[FeedProvider, ...]:
        return tuple(sorted(self._providers.values(), key=lambda p: p.provider_id))

    def get(self, provider_id: str) -> FeedProvider:
        try:
            return self._providers[provider_id]
        except KeyError:
            raise KeyError(f"unknown feed provider: {provider_id}") from None

    def poll(self, provider_id: str) -> FeedProbeResult:
        provider = self.get(provider_id)
        self._sink.upsert_feed(FeedDefinition(provider.provider_id, provider.display_name))
        now = self._clock()
        started = time.monotonic()
        try:
            result = provider.poll(now)
        except FeedError as error:
            latency_ms = int((time.monotonic() - started) * 1000)
            result = FeedProbeResult(
                provider_id=provider_id,
                ok=False,
                status="UNAVAILABLE",
                latency_ms=latency_ms,
                error=error.detail,
                detail={"status_code": error.status_code} if error.status_code else {},
            )
        except Exception as error:  # provider bugs must never crash the loop
            latency_ms = int((time.monotonic() - started) * 1000)
            result = FeedProbeResult(
                provider_id=provider_id,
                ok=False,
                status="UNAVAILABLE",
                latency_ms=latency_ms,
                error=f"{type(error).__name__}: {error}",
            )
        if result.latency_ms is None:
            result = FeedProbeResult(
                provider_id=result.provider_id,
                ok=result.ok,
                status=result.status,
                latency_ms=int((time.monotonic() - started) * 1000),
                error=result.error,
                detail=result.detail,
                records=result.records,
                tt_results=result.tt_results,
            )
        self._sink.record_probe(result, observed_at=now)
        if result.records:
            self._sink.insert_records(provider_id, result.records, received_at=now)
        if result.tt_results:
            self._sink.record_tt_results(result.tt_results)
        return result

    def poll_all(self) -> dict[str, FeedProbeResult]:
        return {provider_id: self.poll(provider_id) for provider_id in self._providers}


def _iso_suffix(now: datetime) -> str:
    return now.strftime("%Y%m%dT%H%M%SZ")


class PolymarketFeedProvider:
    """Event-contract markets from the public Polymarket Gamma API."""

    provider_id = "polymarket"
    display_name = "Polymarket"

    def poll(self, now: datetime) -> FeedProbeResult:
        suffix = _iso_suffix(now)
        records: list[FeedRecord] = []
        for offset in range(0, 300, 50):
            url = (
                "https://gamma-api.polymarket.com/markets"
                f"?limit=50&offset={offset}&order=endDate&ascending=true&closed=false"
            )
            payload, status = http_get_json(url)
            if not isinstance(payload, list):
                raise FeedError("unexpected payload shape (expected list)")
            for market in payload:
                if not isinstance(market, dict):
                    continue
                market_id = str(market.get("id") or market.get("conditionId") or "")
                if not market_id:
                    continue
                records.append(
                    FeedRecord(
                        record_key=f"{market_id}:{suffix}",
                        payload={
                            "market_id": market_id,
                            "question": market.get("question"),
                            "outcomes": market.get("outcomes"),
                            "outcome_prices": market.get("outcomePrices"),
                            "volume": market.get("volume"),
                            "liquidity": market.get("liquidity"),
                            "end_date": market.get("endDate"),
                            "market_type": market.get("marketType"),
                            "category": market.get("category"),
                        },
                        observed_at=now,
                    )
                )
        return FeedProbeResult(
            provider_id=self.provider_id,
            ok=True,
            status="HEALTHY",
            latency_ms=None,
            detail={"records": len(records)},
            records=tuple(records),
        )


_WORLD_BANK_INDICATORS = {
    "NY.GDP.MKTP.KD.ZG": "gdp_growth_pct",
    "FP.CPI.TOTL.ZG": "inflation_pct",
    "SP.POP.TOTL": "population",
}
_WORLD_BANK_COUNTRIES = ("USA", "GBR", "DEU", "FRA", "JPN", "CHN")


class WorldBankFeedProvider:
    """Macro indicator series from the keyless World Bank API."""

    provider_id = "world_bank"
    display_name = "World Bank"

    def poll(self, now: datetime) -> FeedProbeResult:
        records: list[FeedRecord] = []
        detail: dict[str, object] = {}
        for country in _WORLD_BANK_COUNTRIES:
            for indicator, label in _WORLD_BANK_INDICATORS.items():
                url = (
                    "https://api.worldbank.org/v2/country/"
                    f"{country}/indicator/{indicator}?format=json&per_page=100"
                    "&date=2015:2026"
                )
                try:
                    payload, status = http_get_json(url)
                except FeedError as error:
                    detail[f"{country}:{label}"] = error.detail
                    continue
                if not isinstance(payload, list) or len(payload) < 2:
                    detail[f"{country}:{label}"] = "unexpected payload shape"
                    continue
                series = payload[1]
                if not isinstance(series, list):
                    detail[f"{country}:{label}"] = "unexpected payload shape"
                    continue
                for point in series:
                    if not isinstance(point, dict):
                        continue
                    value = point.get("value")
                    year = point.get("date")
                    if value is None or year is None:
                        continue
                    records.append(
                        FeedRecord(
                            record_key=f"{country}:{indicator}:{year}",
                            payload={
                                "country": country,
                                "indicator": indicator,
                                "label": label,
                                "year": year,
                                "value": value,
                            },
                            observed_at=now,
                        )
                    )
        return FeedProbeResult(
            provider_id=self.provider_id,
            ok=True,
            status="DEGRADED" if detail else "HEALTHY",
            latency_ms=None,
            detail=detail or {"records": len(records)},
            records=tuple(records),
        )


class UsTreasuryFeedProvider:
    """Average interest rates from the keyless US Treasury fiscal API."""

    provider_id = "us_treasury"
    display_name = "US Treasury"

    def poll(self, now: datetime) -> FeedProbeResult:
        url = (
            "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
            "/v2/accounting/od/avg_interest_rates?sort=-record_date&limit=50&format=json"
        )
        payload, status = http_get_json(url)
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise FeedError("unexpected payload shape")
        records = [
            FeedRecord(
                record_key=f"{entry.get('record_date')}:{entry.get('security_desc')}",
                payload={
                    "record_date": entry.get("record_date"),
                    "security_type": entry.get("security_type_desc"),
                    "security_desc": entry.get("security_desc"),
                    "avg_interest_rate": entry.get("avg_interest_rate_amt"),
                },
                observed_at=now,
            )
            for entry in data
            if isinstance(entry, dict) and entry.get("record_date")
        ]
        return FeedProbeResult(
            provider_id=self.provider_id,
            ok=True,
            status="HEALTHY",
            latency_ms=None,
            detail={"records": len(records)},
            records=tuple(records),
        )


_COINGECKO_COINS = {
    "bitcoin": "BTC",
    "ethereum": "ETH",
    "solana": "SOL",
    "chainlink": "LINK",
}


class CoinGeckoFeedProvider:
    """Spot crypto prices from CoinGecko (key optional on the free tier)."""

    provider_id = "coingecko"
    display_name = "CoinGecko"

    def poll(self, now: datetime) -> FeedProbeResult:
        suffix = _iso_suffix(now)
        ids = ",".join(_COINGECKO_COINS)
        url = (
            "https://api.coingecko.com/api/v3/simple/price"
            f"?ids={ids}&vs_currencies=usd&include_24hr_change=true"
        )
        key = os.environ.get("COINGECKO_API_KEY", "").strip()
        headers = {"x-cg-demo-api-key": key} if key else None
        payload, status = http_get_json(url, headers=headers)
        if not isinstance(payload, dict):
            raise FeedError("unexpected payload shape")
        records = [
            FeedRecord(
                record_key=f"{coin}:{suffix}",
                payload={
                    "coin": coin,
                    "symbol": symbol,
                    "price_usd": payload.get(coin, {}).get("usd"),
                    "change_24h_pct": payload.get(coin, {}).get("usd_24h_change"),
                },
                observed_at=now,
            )
            for coin, symbol in _COINGECKO_COINS.items()
            if isinstance(payload.get(coin), dict)
        ]
        return FeedProbeResult(
            provider_id=self.provider_id,
            ok=True,
            status="HEALTHY",
            latency_ms=None,
            detail={"records": len(records)},
            records=tuple(records),
        )


class BinancePublicFeedProvider:
    """Public 24h tickers from Binance. May be geo-blocked (HTTP 451)."""

    provider_id = "binance_public"
    display_name = "Binance public data"

    def poll(self, now: datetime) -> FeedProbeResult:
        suffix = _iso_suffix(now)
        symbols = '["BTCUSDT","ETHUSDT","SOLUSDT"]'
        url = (
            "https://api.binance.com/api/v3/ticker/24hr"
            f"?symbols={urllib.parse.quote(symbols)}"
        )
        payload, status = http_get_json(url)
        if not isinstance(payload, list):
            raise FeedError("unexpected payload shape")
        records = [
            FeedRecord(
                record_key=f"{entry.get('symbol')}:{suffix}",
                payload={
                    "symbol": entry.get("symbol"),
                    "last_price": entry.get("lastPrice"),
                    "change_pct_24h": entry.get("priceChangePercent"),
                    "volume_24h": entry.get("volume"),
                    "quote_volume_24h": entry.get("quoteVolume"),
                },
                observed_at=now,
            )
            for entry in payload
            if isinstance(entry, dict) and entry.get("symbol")
        ]
        return FeedProbeResult(
            provider_id=self.provider_id,
            ok=True,
            status="HEALTHY",
            latency_ms=None,
            detail={"records": len(records)},
            records=tuple(records),
        )


_TT_SPORT_KEY_HINTS = ("tabletennis", "table_tennis", "pingpong")


def _odds_api_key() -> str:
    return os.environ.get("THE_ODDS_API_KEY", "").strip()


def _tt_sport_keys(api_key: str) -> list[str]:
    payload, status = http_get_json(f"https://api.the-odds-api.com/v4/sports/?apiKey={api_key}")
    if not isinstance(payload, list):
        raise FeedError("unexpected sports list payload")
    return [
        str(entry["key"])
        for entry in payload
        if isinstance(entry, dict)
        and isinstance(entry.get("key"), str)
        and any(hint in str(entry.get("key", "")).lower() for hint in _TT_SPORT_KEY_HINTS)
    ]


def _parse_tt_score(score: object) -> tuple[int, int] | None:
    if not isinstance(score, str):
        return None
    parts = score.split("-")
    if len(parts) != 2:
        return None
    try:
        home, away = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if home < 0 or away < 0:
        return None
    return home, away


class TheOddsApiTTResultsFeedProvider:
    """Table tennis completed-match scores from The Odds API.

    Consumed by the L2 rating engine to build per-player strength history.
    UNCONFIGURED until THE_ODDS_API_KEY is present; completed matches are
    appended to ``tt_match_results`` through the sink.
    """

    provider_id = "the_odds_api_tt"
    display_name = "The Odds API (table tennis results)"

    def poll(self, now: datetime) -> FeedProbeResult:
        api_key = _odds_api_key()
        if not api_key:
            return FeedProbeResult(
                provider_id=self.provider_id,
                ok=False,
                status="UNCONFIGURED",
                error="missing THE_ODDS_API_KEY",
                detail={},
            )
        try:
            sport_keys = _tt_sport_keys(api_key)
        except FeedError as error:
            raise FeedError(f"sports list failed: {error.detail}") from None

        records: list[FeedRecord] = []
        results: list[TTMatchResult] = []
        failed: dict[str, str] = {}
        for sport_key in sport_keys:
            url = (
                "https://api.the-odds-api.com/v4/sports/"
                f"{urllib.parse.quote(sport_key)}/scores/?daysFrom=3&apiKey={api_key}"
            )
            try:
                payload, status = http_get_json(url)
            except FeedError as error:
                failed[sport_key] = error.detail
                continue
            if not isinstance(payload, list):
                failed[sport_key] = "unexpected payload shape"
                continue
            for match in payload:
                if not isinstance(match, dict):
                    continue
                match_id = str(match.get("id") or "")
                completed = bool(match.get("completed"))
                scores = match.get("scores")
                if not completed or not isinstance(scores, list) or len(scores) < 2:
                    continue
                participants = [
                    (str(p.get("name") or ""), str(p.get("home") or ""))
                    for p in (match.get("home_team"), match.get("away_team"))
                    if isinstance(p, dict)
                ]
                if len(participants) < 2 or not participants[0][0] or not participants[1][0]:
                    continue
                home_key = _participant_key(sport_key, participants[0][0])
                away_key = _participant_key(sport_key, participants[1][0])
                home_points = 0
                away_points = 0
                for entry in scores:
                    if not isinstance(entry, dict):
                        continue
                    name = str(entry.get("name") or "")
                    parsed_score = _parse_tt_score(entry.get("score"))
                    if parsed_score is None:
                        continue
                    if name == participants[0][0]:
                        home_points += parsed_score[0]
                    elif name == participants[1][0]:
                        away_points += parsed_score[0]
                if home_points == 0 and away_points == 0:
                    continue
                results.append(
                    TTMatchResult(
                        event_key=match_id,
                        league_key=sport_key,
                        home_participant_key=home_key,
                        away_participant_key=away_key,
                        home_score=home_points,
                        away_score=away_points,
                        completed_at=now,
                        source_provider=self.provider_id,
                        raw_ref=sport_key,
                    )
                )
                records.append(
                    FeedRecord(
                        record_key=f"{match_id}",
                        payload={
                            "sport_key": sport_key,
                            "home": participants[0][0],
                            "away": participants[1][0],
                            "scores": scores,
                            "completed": True,
                        },
                        observed_at=now,
                    )
                )
        status = "HEALTHY" if not failed else "DEGRADED"
        return FeedProbeResult(
            provider_id=self.provider_id,
            ok=not failed or bool(results),
            status=status,
            latency_ms=None,
            error="; ".join(f"{key}: {detail}" for key, detail in failed.items()) or None,
            detail={"sport_keys": len(sport_keys), "completed_matches": len(results)},
            records=tuple(records),
            tt_results=tuple(results),
        )


def _participant_key(sport_key: str, name: str) -> str:
    slug = "".join(ch for ch in name.lower() if ch.isalnum() or ch in "-_")
    return f"{sport_key}:{slug or 'unknown'}"


def build_default_feed_providers() -> tuple[FeedProvider, ...]:
    return (
        PolymarketFeedProvider(),
        WorldBankFeedProvider(),
        UsTreasuryFeedProvider(),
        CoinGeckoFeedProvider(),
        BinancePublicFeedProvider(),
        TheOddsApiTTResultsFeedProvider(),
    )