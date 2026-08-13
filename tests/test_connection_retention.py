from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
import sys
from types import ModuleType
from types import SimpleNamespace

import pytest

registry_stub = ModuleType("registry")
registry_stub.build_default_registry = lambda memory_manager=None, embedding_client=None: {}
previous_registry = sys.modules.get("registry")
multipart_stub = ModuleType("python_multipart")
multipart_stub.__version__ = "0.0.20"
multipart_parser_stub = ModuleType("python_multipart.multipart")
multipart_parser_stub.parse_options_header = lambda value: (value, {})
previous_multipart = sys.modules.get("python_multipart")
previous_multipart_parser = sys.modules.get("python_multipart.multipart")
sys.modules["registry"] = registry_stub
sys.modules["python_multipart"] = multipart_stub
sys.modules["python_multipart.multipart"] = multipart_parser_stub
try:
    import api_server
finally:
    if previous_registry is None:
        sys.modules.pop("registry", None)
    else:
        sys.modules["registry"] = previous_registry
    if previous_multipart is None:
        sys.modules.pop("python_multipart", None)
    else:
        sys.modules["python_multipart"] = previous_multipart
    if previous_multipart_parser is None:
        sys.modules.pop("python_multipart.multipart", None)
    else:
        sys.modules["python_multipart.multipart"] = previous_multipart_parser


FROZEN_NOW = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)


class FlakyVisitorStore:
    def __init__(self, backing_store, *, failures: int = 1):
        self.backing_store = backing_store
        self.failures = failures
        self.purge_calls = 0

    def purge_connection_history(self, *, before: str) -> int:
        self.purge_calls += 1
        if self.purge_calls <= self.failures:
            raise RuntimeError("sensitive-storage-detail-must-not-be-logged")
        return self.backing_store.purge_connection_history(before=before)


class ReadyIdentityStore:
    def __init__(self):
        self.preflight_calls = 0

    def assert_invitation_transport_ready(self) -> None:
        self.preflight_calls += 1


class FakeDataCore:
    def __init__(self, visitors):
        self.visitors = visitors
        self.identity = ReadyIdentityStore()
        self.memory = object()
        self.conversations = object()
        self.paths = SimpleNamespace(root="test-data-root")
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class FakeAsyncModel:
    def __init__(self):
        self.entered = False
        self.exited = False

    async def __aenter__(self):
        self.entered = True
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        self.exited = True


def seed_connection(store, *, observed_at: datetime) -> str:
    return store.record_connection(
        visitor_id="vis_seed",
        session_id="vsess_seed",
        ip_address="203.0.113.8",
        user_agent="Browser/1",
        client_meta={
            "browser": "other",
            "platform": "other",
            "device": "desktop",
            "language": "en",
        },
        cookie_hash="cookie_hmac",
        observed_at=observed_at.isoformat(),
    )


@pytest.fixture(autouse=True)
def reset_cleanup_guard():
    api_server.state.last_connection_cleanup_at = None
    yield
    api_server.state.last_connection_cleanup_at = None
    api_server.state.model = None
    api_server.state.cp = None
    api_server.state.data = None


def test_cleanup_deletes_only_records_older_than_90_days(visitor_store):
    old = seed_connection(
        visitor_store,
        observed_at=FROZEN_NOW - timedelta(days=90, microseconds=1),
    )
    keep = seed_connection(
        visitor_store,
        observed_at=FROZEN_NOW - timedelta(days=90),
    )

    deleted = api_server._run_connection_retention_cleanup(
        SimpleNamespace(visitors=visitor_store),
        now=FROZEN_NOW,
    )

    assert deleted == 1
    assert visitor_store.connection_detail(old) is None
    assert visitor_store.connection_detail(keep) is not None


def test_cleanup_runs_at_most_once_per_day_and_is_idempotent(visitor_store):
    first = seed_connection(
        visitor_store,
        observed_at=FROZEN_NOW - timedelta(days=91),
    )
    data = SimpleNamespace(visitors=visitor_store)

    assert api_server._run_connection_retention_cleanup(data, now=FROZEN_NOW) == 1
    assert visitor_store.connection_detail(first) is None

    held_by_guard = seed_connection(
        visitor_store,
        observed_at=FROZEN_NOW - timedelta(days=91),
    )
    assert api_server._run_connection_retention_cleanup(
        data,
        now=FROZEN_NOW + timedelta(days=1, microseconds=-1),
    ) == 0
    assert visitor_store.connection_detail(held_by_guard) is not None

    next_day = FROZEN_NOW + timedelta(days=1)
    assert api_server._run_connection_retention_cleanup(data, now=next_day) == 1
    assert visitor_store.connection_detail(held_by_guard) is None
    assert api_server._run_connection_retention_cleanup(data, now=next_day) == 0


def test_cleanup_normalizes_aware_times_to_utc_and_rejects_naive_times(
    visitor_store,
):
    eastern_now = FROZEN_NOW.astimezone(timezone(timedelta(hours=-4)))
    keep = seed_connection(
        visitor_store,
        observed_at=FROZEN_NOW - timedelta(days=90),
    )
    data = SimpleNamespace(visitors=visitor_store)

    assert api_server._run_connection_retention_cleanup(data, now=eastern_now) == 0
    assert api_server.state.last_connection_cleanup_at == FROZEN_NOW
    assert visitor_store.connection_detail(keep) is not None

    api_server.state.last_connection_cleanup_at = None
    with pytest.raises(ValueError, match="timezone-aware"):
        api_server._run_connection_retention_cleanup(
            data,
            now=datetime(2026, 8, 10, 12, 0),
        )


def test_lifespan_runs_connection_cleanup_at_startup(visitor_store, monkeypatch):
    old = seed_connection(
        visitor_store,
        observed_at=FROZEN_NOW - timedelta(days=91),
    )
    keep = seed_connection(
        visitor_store,
        observed_at=FROZEN_NOW - timedelta(days=90),
    )
    data = SimpleNamespace(
        visitors=visitor_store,
        identity=ReadyIdentityStore(),
        memory=object(),
        conversations=object(),
        paths=SimpleNamespace(root="test-data-root"),
        close=lambda: None,
    )
    app = SimpleNamespace(state=SimpleNamespace())

    monkeypatch.setattr(api_server, "DataCore", lambda _root: data)
    monkeypatch.setattr(api_server, "configure_identity_store", lambda _store: None)
    monkeypatch.setattr(api_server, "build_default_registry", lambda **_kwargs: {})
    monkeypatch.setattr(api_server, "build_model_client", lambda: object())
    monkeypatch.setattr(
        api_server,
        "ControlPlane",
        lambda **_kwargs: SimpleNamespace(tools={}),
    )
    monkeypatch.setattr(api_server, "_connection_retention_now", lambda: FROZEN_NOW)

    async def exercise_lifespan():
        async with api_server.lifespan(app):
            assert visitor_store.connection_detail(old) is None
            assert visitor_store.connection_detail(keep) is not None

    asyncio.run(exercise_lifespan())
    assert data.identity.preflight_calls == 1


def test_lifespan_refuses_traffic_when_invitation_transport_preflight_blocks(
    visitor_store,
    monkeypatch,
):
    class BlockingIdentityStore:
        def assert_invitation_transport_ready(self) -> None:
            raise RuntimeError("legacy invitation rollout required")

    close_calls = []
    data = SimpleNamespace(
        visitors=visitor_store,
        identity=BlockingIdentityStore(),
        memory=object(),
        conversations=object(),
        paths=SimpleNamespace(root="test-data-root"),
        close=lambda: close_calls.append(True),
    )
    app = SimpleNamespace(state=SimpleNamespace())
    model_builds = []

    monkeypatch.setattr(api_server, "DataCore", lambda _root: data)
    monkeypatch.setattr(
        api_server,
        "build_model_client",
        lambda: model_builds.append(True),
    )

    async def exercise_lifespan():
        async with api_server.lifespan(app):
            raise AssertionError("lifespan must not yield after a blocked preflight")

    with pytest.raises(RuntimeError, match="rollout required"):
        asyncio.run(exercise_lifespan())

    assert model_builds == []
    assert close_calls == [True]
    assert getattr(app.state, "defend_data", None) is None


def test_request_check_runs_cleanup_when_daily_guard_expires(
    visitor_store,
    monkeypatch,
):
    old = seed_connection(
        visitor_store,
        observed_at=FROZEN_NOW - timedelta(days=91),
    )
    data = SimpleNamespace(visitors=visitor_store)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(defend_data=data)))
    api_server.state.last_connection_cleanup_at = FROZEN_NOW - timedelta(days=1)
    monkeypatch.setattr(api_server, "_connection_retention_now", lambda: FROZEN_NOW)

    async def call_next(received_request):
        assert received_request is request
        return "response"

    response = asyncio.run(
        api_server.connection_retention_cleanup_middleware(request, call_next)
    )

    assert response == "response"
    assert visitor_store.connection_detail(old) is None


def test_lifespan_contains_failed_purge_and_allows_later_retry(
    visitor_store,
    monkeypatch,
    caplog,
):
    old = seed_connection(
        visitor_store,
        observed_at=FROZEN_NOW - timedelta(days=91),
    )
    flaky_visitors = FlakyVisitorStore(visitor_store)
    data = FakeDataCore(flaky_visitors)
    app = SimpleNamespace(state=SimpleNamespace())

    monkeypatch.setattr(api_server, "DataCore", lambda _root: data)
    monkeypatch.setattr(api_server, "configure_identity_store", lambda _store: None)
    monkeypatch.setattr(api_server, "build_default_registry", lambda **_kwargs: {})
    monkeypatch.setattr(api_server, "build_model_client", lambda: object())
    monkeypatch.setattr(
        api_server,
        "ControlPlane",
        lambda **_kwargs: SimpleNamespace(tools={}),
    )
    monkeypatch.setattr(api_server, "_connection_retention_now", lambda: FROZEN_NOW)

    async def exercise_lifespan():
        async with api_server.lifespan(app):
            assert api_server.state.last_connection_cleanup_at is None
            assert visitor_store.connection_detail(old) is not None
            assert api_server._run_connection_retention_cleanup(data) == 1
            assert visitor_store.connection_detail(old) is None

    with caplog.at_level(logging.WARNING, logger="api_server"):
        asyncio.run(exercise_lifespan())

    assert data.close_calls == 1
    assert flaky_visitors.purge_calls == 2
    assert "RuntimeError" in caplog.text
    assert "sensitive-storage-detail-must-not-be-logged" not in caplog.text


def test_middleware_contains_failed_purge_and_retries_on_next_request(
    visitor_store,
    monkeypatch,
    caplog,
):
    old = seed_connection(
        visitor_store,
        observed_at=FROZEN_NOW - timedelta(days=91),
    )
    flaky_visitors = FlakyVisitorStore(visitor_store)
    data = FakeDataCore(flaky_visitors)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(defend_data=data)))
    monkeypatch.setattr(api_server, "_connection_retention_now", lambda: FROZEN_NOW)
    handled_requests = []

    async def call_next(received_request):
        handled_requests.append(received_request)
        return "response"

    with caplog.at_level(logging.WARNING, logger="api_server"):
        first_response = asyncio.run(
            api_server.connection_retention_cleanup_middleware(request, call_next)
        )

    assert first_response == "response"
    assert handled_requests == [request]
    assert api_server.state.last_connection_cleanup_at is None
    assert visitor_store.connection_detail(old) is not None

    second_response = asyncio.run(
        api_server.connection_retention_cleanup_middleware(request, call_next)
    )

    assert second_response == "response"
    assert handled_requests == [request, request]
    assert flaky_visitors.purge_calls == 2
    assert api_server.state.last_connection_cleanup_at == FROZEN_NOW
    assert visitor_store.connection_detail(old) is None
    assert "RuntimeError" in caplog.text
    assert "sensitive-storage-detail-must-not-be-logged" not in caplog.text


def test_lifespan_closes_open_resources_when_later_startup_step_fails(
    visitor_store,
    monkeypatch,
):
    data = FakeDataCore(visitor_store)
    model = FakeAsyncModel()
    app = SimpleNamespace(state=SimpleNamespace())

    monkeypatch.setattr(api_server, "DataCore", lambda _root: data)
    monkeypatch.setattr(api_server, "configure_identity_store", lambda _store: None)
    monkeypatch.setattr(api_server, "build_default_registry", lambda **_kwargs: {})
    monkeypatch.setattr(api_server, "build_model_client", lambda: model)
    monkeypatch.setattr(
        api_server,
        "ControlPlane",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("startup failed")),
    )
    monkeypatch.setattr(api_server, "_connection_retention_now", lambda: FROZEN_NOW)

    async def exercise_lifespan():
        async with api_server.lifespan(app):
            raise AssertionError("lifespan must not yield after startup failure")

    with pytest.raises(RuntimeError, match="startup failed"):
        asyncio.run(exercise_lifespan())

    assert model.entered is True
    assert model.exited is True
    assert data.close_calls == 1
    assert api_server.state.model is None
    assert api_server.state.cp is None
    assert api_server.state.data is None
    assert app.state.defend_data is None
