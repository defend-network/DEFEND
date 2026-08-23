from __future__ import annotations

from datetime import datetime, timezone

import pytest

from defend_markets.collector import (
    TtCollector,
    TtCollectorConfig,
    TtCollectorRun,
    tt_collector_config_from_env,
)
from defend_sports.providers.the_odds_api import OddsApiProviderError

from tests.fakes_markets import InMemoryForecastStore

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)


class FakeFeedService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def poll(self, provider_id: str):
        self.calls.append(provider_id)
        return _Result()


class _Result:
    record_count = 0
    tt_results = ()
    status = "HEALTHY"


class FakeSportsDatabase:
    def __init__(self) -> None:
        self.connections = []

    def connect(self):
        return _Connection(self)


class _Connection:
    def __init__(self, db: FakeSportsDatabase) -> None:
        self.db = db
        self.entered = False

    def __enter__(self):
        self.entered = True
        self.db.connections.append(self)
        return self

    def __exit__(self, *args):
        return None

    def transaction(self):
        return self

    def cursor(self):
        return _Cursor()


class _Cursor:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, *args, **kwargs):
        return None

    def fetchone(self):
        return None


class FakeSportsRepository:
    def upsert_source(self, connection, ref, display_name=None):
        return "source-id"

    def record_discovery(self, connection, **kwargs):
        self.discovery = kwargs

    def record_quota(self, connection, **kwargs):
        self.quota = kwargs


def make_collector(**kwargs) -> TtCollector:
    defaults = dict(
        sports_database=FakeSportsDatabase(),
        feed_service=FakeFeedService(),
        markets_forecast=InMemoryForecastStore(),
        sports_repository=FakeSportsRepository(),
        clock=lambda: NOW,
        sleep=lambda _: None,
    )
    defaults.update(kwargs)
    return TtCollector(**defaults)


def test_config_defaults():
    config = TtCollectorConfig()
    assert config.credit_floor == 25
    assert config.active_poll_seconds == 15
    assert config.idle_poll_seconds == 300


def test_config_rejects_bad_intervals():
    with pytest.raises(ValueError):
        TtCollectorConfig(active_poll_seconds=0.5)
    with pytest.raises(ValueError):
        TtCollectorConfig(idle_poll_seconds=10, active_poll_seconds=60)


def test_unconfigured_without_key(monkeypatch):
    monkeypatch.delenv("THE_ODDS_API_KEY", raising=False)
    monkeypatch.setattr("defend_markets.collector.odds_api_key", lambda: "")
    collector = make_collector()
    run = collector.one_shot()
    assert not run.configured
    assert run.status == "UNCONFIGURED"
    state = collector._forecast.get_collector_state()
    assert state["status"] == "UNCONFIGURED"


def test_quota_protected_below_floor(monkeypatch):
    monkeypatch.setenv("THE_ODDS_API_KEY", "test-key")
    collector = make_collector(config=TtCollectorConfig(credit_floor=50))
    collector._quota_state.update({"requests_remaining": "10", "requests_used": "490"})
    run = collector.one_shot()
    assert run.status == "QUOTA_PROTECTED"
    assert run.quota_protected
    assert "below floor" in run.detail


def test_quota_protected_records_state(monkeypatch):
    monkeypatch.setenv("THE_ODDS_API_KEY", "test-key")
    collector = make_collector(config=TtCollectorConfig(credit_floor=50))
    collector._quota_state.update({"requests_remaining": "10"})
    collector.one_shot()
    state = collector._forecast.get_collector_state()
    assert state["status"] == "QUOTA_PROTECTED"


def test_paced_fetch_retries_on_429_and_records_quota(monkeypatch):
    from defend_markets import collector as collector_module
    from defend_markets.collector import _PacedFetch

    calls = {"n": 0}
    monkeypatch.setattr(collector_module.urllib.request, "urlopen", _urlopen(calls, fail_429=2))
    quota: dict[str, object] = {}
    paced = _PacedFetch(
        quota_sink=quota.update,
        clock=lambda: 0.0,
        sleep=lambda _: None,
        random_source=lambda: 0.5,
    )
    payload, status = paced("https://example.test")
    assert calls["n"] == 3
    assert payload == []
    assert status == 200
    assert quota.get("requests_remaining") == 50


def _urlopen(calls: dict[str, int], fail_429: int = 0):
    import io
    import json
    import urllib.error

    class FakeHeaders:
        def items(self):
            return [("x-requests-remaining", "50"), ("x-requests-used", "450")]

    class FakeResponse:
        def __init__(self, body: bytes) -> None:
            self._body = body
            self.headers = FakeHeaders()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, size: int):
            return self._body

    def urlopen(request, timeout=None):
        calls["n"] += 1
        if calls["n"] <= fail_429:
            raise urllib.error.HTTPError("url", 429, "too many requests", {}, io.BytesIO(b""))
        return FakeResponse(json.dumps([]).encode())

    return urlopen


def test_429_exhausts_retries_then_raises(monkeypatch):
    from defend_markets import collector as collector_module
    from defend_markets.collector import _PacedFetch

    monkeypatch.setattr(collector_module.urllib.request, "urlopen", _urlopen({"n": 0}, fail_429=999))
    paced = _PacedFetch(
        quota_sink=lambda _: None,
        clock=lambda: 0.0,
        sleep=lambda _: None,
        random_source=lambda: 0.5,
    )
    with pytest.raises(OddsApiProviderError):
        paced("https://example.test")


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("TT_ODDS_CREDIT_FLOOR", "10")
    monkeypatch.setenv("TT_ODDS_POLL_ACTIVE_SECONDS", "7")
    monkeypatch.setenv("TT_ODDS_POLL_IDLE_SECONDS", "120")
    config = tt_collector_config_from_env()
    assert config.credit_floor == 10
    assert config.active_poll_seconds == 7
    assert config.idle_poll_seconds == 120


def test_run_status_constants():
    run = TtCollectorRun(status="UNCONFIGURED", configured=False)
    assert run.provider == "the_odds_api"
    assert run.mode == "idle"
    assert not run.quota_protected