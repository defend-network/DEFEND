from datetime import datetime, timezone
import types

import pytest

import defend_markets.feeds as feeds_module
from defend_markets.domain import TTMatchResult
from defend_markets.feeds import (
    BinancePublicFeedProvider,
    CoinGeckoFeedProvider,
    FeedDefinition,
    FeedError,
    FeedProbeResult,
    FeedRecord,
    FeedService,
    PolymarketFeedProvider,
    TheOddsApiTTResultsFeedProvider,
    UsTreasuryFeedProvider,
    WorldBankFeedProvider,
)

_NOW = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)


class InMemoryFeedSink:
    def __init__(self) -> None:
        self.feeds: dict[str, FeedDefinition] = {}
        self.probes: list[FeedProbeResult] = []
        self.records: dict[str, list[FeedRecord]] = {}
        self.tt_results: list[TTMatchResult] = []

    def upsert_feed(self, definition: FeedDefinition) -> None:
        self.feeds[definition.provider_id] = definition

    def record_probe(self, result: FeedProbeResult, *, observed_at: datetime) -> None:
        self.probes.append(result)

    def insert_records(
        self, provider_id: str, records: list[FeedRecord], *, received_at: datetime
    ) -> int:
        self.records.setdefault(provider_id, []).extend(records)
        return len(records)

    def record_tt_results(self, results: list[TTMatchResult]) -> int:
        self.tt_results.extend(results)
        return len(results)

    def list_feeds(self) -> list[dict[str, object]]:
        return [{"provider_id": key} for key in self.feeds]

    def list_records(self, provider_id: str, limit: int = 50) -> list[dict[str, object]]:
        return [{"record_key": r.record_key} for r in self.records.get(provider_id, [])][-limit:]


class StubHttp:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, responses: dict[str, tuple[object, int]]) -> None:
        self.responses = responses
        self.calls: list[str] = []

        def fake_get(url: str, **kwargs: object) -> tuple[object, int]:
            self.calls.append(url)
            for prefix, response in self.responses.items():
                if url.startswith(prefix):
                    if isinstance(response, Exception):
                        raise response
                    return response
            raise FeedError(f"unexpected url: {url}")

        monkeypatch.setattr("defend_markets.feeds.http_get_json", fake_get)


def _market_payload(offset: int) -> list[dict[str, object]]:
    return [
        {
            "id": f"m{offset * 100 + i}",
            "question": f"Question {offset * 100 + i}",
            "outcomes": ["Yes", "No"],
            "outcomePrices": ["0.55", "0.45"],
            "volume": "1000",
            "liquidity": "500",
            "endDate": "2026-09-01T00:00:00Z",
            "marketType": "binary",
            "category": "sports",
        }
        for i in range(2)
    ]


def test_polymarket_poll_healthy_paginated(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = StubHttp(monkeypatch, {"https://gamma-api.polymarket.com/markets": (_market_payload(0), 200)})
    provider = PolymarketFeedProvider()
    result = provider.poll(_NOW)
    assert result.ok is True
    assert result.status == "HEALTHY"
    assert result.record_count == 12
    assert len(stub.calls) == 6
    assert "limit=50" in stub.calls[0]
    assert "offset=250" in stub.calls[-1]


def test_world_bank_partial_failure_is_degraded(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, **kwargs: object) -> tuple[object, int]:
        if "SP.POP.TOTL" in url:
            raise FeedError("status 500", status_code=500)
        return [[], [{"date": "2025", "value": 2.4}]], 200

    monkeypatch.setattr("defend_markets.feeds.http_get_json", fake_get)
    result = WorldBankFeedProvider().poll(_NOW)
    assert result.status == "DEGRADED"
    assert result.record_count == 12
    assert result.detail["USA:population"] == "status 500"


def test_us_treasury_poll_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "data": [
            {
                "record_date": "2026-08-01",
                "security_desc": "Treasury Notes",
                "security_type_desc": "Marketable",
                "avg_interest_rate_amt": "4.21",
            }
        ]
    }
    monkeypatch.setattr(
        "defend_markets.feeds.http_get_json",
        lambda url, **kwargs: (payload, 200),
    )
    result = UsTreasuryFeedProvider().poll(_NOW)
    assert result.ok is True
    assert result.status == "HEALTHY"
    assert result.records[0].record_key == "2026-08-01:Treasury Notes"


def test_coingecko_poll_without_key_is_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "bitcoin": {"usd": 64294.0, "usd_24h_change": 1.5},
        "ethereum": {"usd": 3400.0, "usd_24h_change": -2.1},
    }
    calls: list[dict[str, object]] = []

    def fake_get(url: str, **kwargs: object) -> tuple[object, int]:
        calls.append(kwargs)
        return payload, 200

    monkeypatch.setattr("defend_markets.feeds.http_get_json", fake_get)
    monkeypatch.delenv("COINGECKO_API_KEY", raising=False)
    result = CoinGeckoFeedProvider().poll(_NOW)
    assert result.ok is True
    assert result.record_count == 2
    assert calls[0].get("headers") is None


def test_coingecko_sends_key_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_get(url: str, **kwargs: object) -> tuple[object, int]:
        calls.append(kwargs)
        return {"bitcoin": {"usd": 1.0, "usd_24h_change": 0.0}}, 200

    monkeypatch.setattr("defend_markets.feeds.http_get_json", fake_get)
    monkeypatch.setenv("COINGECKO_API_KEY", "demo-key")
    CoinGeckoFeedProvider().poll(_NOW)
    assert calls[0]["headers"] == {"x-cg-demo-api-key": "demo-key"}


def test_binance_poll_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [{"symbol": "BTCUSDT", "lastPrice": "64294.0", "priceChangePercent": "1.2", "volume": "100", "quoteVolume": "6000000"}]
    monkeypatch.setattr(
        "defend_markets.feeds.http_get_json",
        lambda url, **kwargs: (payload, 200),
    )
    result = BinancePublicFeedProvider().poll(_NOW)
    assert result.ok is True
    assert result.records[0].record_key.startswith("BTCUSDT:")


def test_odds_api_unconfigured_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("THE_ODDS_API_KEY", raising=False)
    monkeypatch.setattr("defend_markets.feeds._odds_api_key", lambda: "")
    result = TheOddsApiTTResultsFeedProvider().poll(_NOW)
    assert result.ok is False
    assert result.status == "UNCONFIGURED"
    assert "THE_ODDS_API_KEY" in result.error


def test_odds_api_tt_results_built_from_completed_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THE_ODDS_API_KEY", "test-key")
    sports = [{"key": "tabletennis"}, {"key": "soccer_epl"}]
    scores = [
        {
            "id": "match-1",
            "sport_key": "tabletennis",
            "completed": True,
            "home_team": {"name": "Alice", "home": "true"},
            "away_team": {"name": "Bob", "home": "false"},
            "scores": [
                {"name": "Alice", "score": "11-7"},
                {"name": "Alice", "score": "11-9"},
                {"name": "Bob", "score": "7-11"},
            ],
        },
        {
            "id": "match-2",
            "sport_key": "tabletennis",
            "completed": False,
            "home_team": {"name": "Carol", "home": "true"},
            "away_team": {"name": "Dan", "home": "false"},
            "scores": [{"name": "Carol", "score": "5-5"}],
        },
    ]

    def fake_get(url: str, **kwargs: object) -> tuple[object, int]:
        if "/sports/?apiKey=" in url:
            return sports, 200
        return scores, 200

    monkeypatch.setattr("defend_markets.feeds.http_get_json", fake_get)
    result = TheOddsApiTTResultsFeedProvider().poll(_NOW)
    assert result.status == "HEALTHY"
    assert len(result.tt_results) == 1
    match = result.tt_results[0]
    assert match.event_key == "match-1"
    assert match.league_key == "tabletennis"
    assert match.home_score == 22 and match.away_score == 7
    assert match.home_participant_key == "tabletennis:alice"
    assert match.away_participant_key == "tabletennis:bob"
    assert match.source_provider == "the_odds_api_tt"


def test_feed_service_poll_persists_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THE_ODDS_API_KEY", "test-key")

    def fake_get(url: str, **kwargs: object) -> tuple[object, int]:
        if "/sports/?apiKey=" in url:
            return [{"key": "tabletennis"}], 200
        return [
            {
                "id": "m1",
                "sport_key": "tabletennis",
                "completed": True,
                "home_team": {"name": "Alice", "home": "true"},
                "away_team": {"name": "Bob", "home": "false"},
                "scores": [
                    {"name": "Alice", "score": "11-7"},
                    {"name": "Bob", "score": "5-11"},
                ],
            }
        ], 200

    monkeypatch.setattr("defend_markets.feeds.http_get_json", fake_get)
    sink = InMemoryFeedSink()
    service = FeedService(
        sink,
        [TheOddsApiTTResultsFeedProvider()],
        clock=lambda: _NOW,
    )
    result = service.poll("the_odds_api_tt")
    assert result.ok is True
    assert sink.feeds["the_odds_api_tt"].display_name == "The Odds API (table tennis results)"
    assert sink.probes[-1].status == "HEALTHY"
    assert sink.probes[-1].latency_ms is not None
    assert len(sink.records["the_odds_api_tt"]) == 1
    assert len(sink.tt_results) == 1


def test_feed_service_records_unavailable_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("THE_ODDS_API_KEY", raising=False)
    monkeypatch.setattr("defend_markets.feeds._odds_api_key", lambda: "")
    sink = InMemoryFeedSink()
    service = FeedService(
        sink,
        [TheOddsApiTTResultsFeedProvider()],
        clock=lambda: _NOW,
    )
    result = service.poll("the_odds_api_tt")
    assert result.ok is False
    assert result.status == "UNCONFIGURED"
    assert sink.probes[-1].status == "UNCONFIGURED"
    assert sink.records.get("the_odds_api_tt") is None


def test_feed_service_records_unavailable_on_transport_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THE_ODDS_API_KEY", "test-key")

    def fake_get(url: str, **kwargs: object) -> tuple[object, int]:
        raise FeedError("status 500", status_code=500)

    monkeypatch.setattr("defend_markets.feeds.http_get_json", fake_get)
    sink = InMemoryFeedSink()
    service = FeedService(sink, [TheOddsApiTTResultsFeedProvider()], clock=lambda: _NOW)
    result = service.poll("the_odds_api_tt")
    assert result.status == "UNAVAILABLE"
    assert "sports list failed" in result.error
    assert "status 500" in result.error
    assert result.detail == {}
    assert "sports list failed" in sink.probes[-1].error


def test_feed_service_poll_all_and_unknown_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("THE_ODDS_API_KEY", raising=False)
    sink = InMemoryFeedSink()
    service = FeedService(sink, [TheOddsApiTTResultsFeedProvider()], clock=lambda: _NOW)
    results = service.poll_all()
    assert set(results) == {"the_odds_api_tt"}
    with pytest.raises(KeyError):
        service.poll("nope")


def test_feed_record_validation() -> None:
    with pytest.raises(ValueError):
        FeedRecord(record_key="", payload={})
    with pytest.raises(ValueError):
        FeedRecord(record_key="k", payload="not-a-mapping")
    with pytest.raises(ValueError):
        FeedRecord(record_key="k", payload={}, observed_at=datetime(2026, 1, 1))
    valid = FeedRecord(record_key="k", payload={"a": 1}, observed_at=_NOW)
    assert valid.record_key == "k"


class TestOddsApiKeyResolution:
    def test_odds_api_key_prefers_process_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("THE_ODDS_API_KEY", "env-key")
        monkeypatch.setattr(feeds_module, "_resolve_secret_from_store", lambda name: "store-key")
        assert feeds_module.odds_api_key() == "env-key"

    def test_odds_api_key_falls_back_to_secret_store(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("THE_ODDS_API_KEY", raising=False)
        monkeypatch.setattr(feeds_module, "_resolve_secret_from_store", lambda name: "store-key")
        assert feeds_module.odds_api_key() == "store-key"

    def test_odds_api_key_empty_when_unconfigured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("THE_ODDS_API_KEY", raising=False)
        monkeypatch.setattr(feeds_module, "_resolve_secret_from_store", lambda name: None)
        assert feeds_module.odds_api_key() == ""

    def test_resolver_bridges_setup_integrations_store(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import sys
        import types

        calls: list[object] = []

        class _Registry:
            def __init__(self, backend: object) -> None:
                calls.append(backend)
                self._secrets = {"THE_ODDS_API_KEY": "store-key"}

            def get(self, name: str) -> str | None:
                return self._secrets.get(name)

        stores_module = types.ModuleType("defend_integrations.stores")
        stores_module.SecretRegistry = _Registry
        stores_module.default_secret_path = lambda: "C:\\fake\\secrets.dpapi"
        secrets_module = types.ModuleType("defend_control.secrets")

        class _DpapiSecretStore:
            def __init__(self, path: str) -> None:
                calls.append(path)

        secrets_module.DpapiSecretStore = _DpapiSecretStore
        monkeypatch.setitem(sys.modules, "defend_integrations.stores", stores_module)
        monkeypatch.setitem(sys.modules, "defend_control.secrets", secrets_module)

        assert feeds_module._resolve_secret_from_store("THE_ODDS_API_KEY") == "store-key"
        assert len(calls) == 2
        assert calls[0] == "C:\\fake\\secrets.dpapi"
        assert isinstance(calls[1], _DpapiSecretStore)

    def test_resolver_returns_none_when_store_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import sys

        stores_module = types.ModuleType("defend_integrations.stores")

        def boom() -> object:
            raise RuntimeError("secrets unavailable")

        stores_module.SecretRegistry = boom
        stores_module.default_secret_path = boom
        monkeypatch.setitem(sys.modules, "defend_integrations.stores", stores_module)
        monkeypatch.setitem(sys.modules, "defend_control.secrets", types.ModuleType("defend_control.secrets"))

        assert feeds_module._resolve_secret_from_store("THE_ODDS_API_KEY") is None


class TestOddsApiQuotaProbe:
    def test_probe_reports_quota_headers_and_tt_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import json
        import urllib.request

        sports = [
            {"key": "tabletennis_superliga", "title": "Table Tennis"},
            {"key": "soccer_epl", "title": "Soccer"},
        ]

        class FakeResponse:
            def __init__(self) -> None:
                self.headers = {
                    "x-requests-remaining": "482",
                    "x-requests-used": "18",
                    "x-requests-last": "2026-08-17T10:00:00Z",
                }

            def read(self, limit: int = -1) -> bytes:
                return json.dumps(sports).encode()

            def __enter__(self) -> FakeResponse:
                return self

            def __exit__(self, *exc_info: object) -> None:
                return None

        def fake_urlopen(request: object, timeout: float = 20.0) -> FakeResponse:
            url = str(getattr(request, "full_url", request))
            assert url.startswith("https://api.the-odds-api.com/v4/sports/?apiKey=")
            return FakeResponse()

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        result = feeds_module.probe_odds_api_quota("test-key")
        assert result["status"] == 200
        assert result["sport_count"] == 2
        assert result["tt_sport_keys"] == ["tabletennis_superliga"]
        assert result["requests_remaining"] == "482"
        assert result["requests_used"] == "18"
        assert result["requests_last"] == "2026-08-17T10:00:00Z"

    def test_probe_raises_feed_error_on_rejection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import urllib.error
        import urllib.request

        def fake_urlopen(request: object, timeout: float = 20.0) -> object:
            raise urllib.error.HTTPError(
                "https://api.the-odds-api.com/v4/sports/?apiKey=x", 401, "Unauthorized", None, None
            )

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        with pytest.raises(FeedError) as exc:
            feeds_module.probe_odds_api_quota("bad-key")
        assert exc.value.status_code == 401