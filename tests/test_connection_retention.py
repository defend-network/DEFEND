from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import sys
from types import ModuleType
from types import SimpleNamespace

import pytest

registry_stub = ModuleType("registry")
registry_stub.build_default_registry = lambda memory_manager=None: {}
previous_registry = sys.modules.get("registry")
multipart_stub = ModuleType("python_multipart")
multipart_stub.__version__ = "0.0.20"
previous_multipart = sys.modules.get("python_multipart")
sys.modules["registry"] = registry_stub
sys.modules["python_multipart"] = multipart_stub
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


FROZEN_NOW = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)


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
        identity=object(),
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
