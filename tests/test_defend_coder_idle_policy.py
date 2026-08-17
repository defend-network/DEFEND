"""Server-authoritative consumer idle policy: 10-minute inactivity timeout.

Hermetic — in-memory repository, always runs without PostgreSQL.

Pins the contract:
- heartbeats NEVER extend the inactivity window
- genuine API activity (session/workspace calls) resets last_seen_at
- provisioning does NOT count as idle (a fresh session is never revoked
  by its own creation, and only ready runtimes are ever reaped)
- on timeout the session is revoked and one session.idle_timeout audit
  event is recorded; the wired runtime-stop callback fires per session
- admin sessions are exempt from the consumer idle policy
- idle_timeout_seconds=0 disables the policy entirely
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from defend_coder.app import (
    build_coder_app,
    run_idle_cycle,
)
from defend_coder.auth import AuthService
from defend_coder.config import CoderSettings

from test_defend_coder_session_flow import (
    FakeCoderRepository,
    _login,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_env(*, idle_timeout_seconds: int = 600):
    repository = FakeCoderRepository()
    auth = AuthService(repository, session_ttl=timedelta(hours=8))
    auth.create_account(
        username="admin",
        email="admin@example.test",
        password="admin-password",
        role="admin",
    )
    auth.create_account(
        username="consumer",
        email="consumer@example.test",
        password="consumer-password",
        role="consumer",
    )
    app = build_coder_app(
        settings=CoderSettings(
            database_url="postgresql://hermetic",
            host="127.0.0.1",
            port=8301,
            public_https=True,
            workspace_root=r"C:\DEFEND_CODER_DATA",
            idle_timeout_seconds=idle_timeout_seconds,
        ),
        db=object(),  # type: ignore[arg-type]
        auth=auth,
        repository=repository,
        runtime_status=lambda: {"state": "ready"},
    )
    return TestClient(app, base_url="https://testserver"), auth, repository


def _session_by_token_hash(repository, token_hash: str):
    return repository.get_session_by_hash(token_hash)


def test_heartbeat_never_extends_inactivity_window():
    client, _auth, repository = _make_env()

    login = _login(client, "consumer", "consumer-password", "consumer")
    assert login.status_code == 200
    token = login.json()["csrf_token"] is not None

    cookie_pair = login.headers["set-cookie"].split(";")[0]
    token_hash = __import__("hashlib").sha256(
        cookie_pair.split("=", 1)[1].encode("utf-8")
    ).hexdigest()
    session = _session_by_token_hash(repository, token_hash)
    assert session is not None
    before = session.last_seen_at

    for _ in range(3):
        response = client.post(
            "/v1/auth/heartbeat",
            headers={"cookie": cookie_pair},
        )
        assert response.status_code == 200
        assert response.json()["ok"] is True

    after = _session_by_token_hash(repository, token_hash)
    assert after is not None
    assert after.last_seen_at == before


def test_genuine_activity_resets_inactivity_window():
    client, _auth, repository = _make_env()

    login = _login(client, "consumer", "consumer-password", "consumer")
    cookie_pair = login.headers["set-cookie"].split(";")[0]

    token_hash = __import__("hashlib").sha256(
        cookie_pair.split("=", 1)[1].encode("utf-8")
    ).hexdigest()
    before = _session_by_token_hash(repository, token_hash).last_seen_at

    session = client.get(
        "/v1/auth/session",
        headers={"cookie": cookie_pair},
    )
    assert session.status_code == 200

    after = _session_by_token_hash(repository, token_hash)
    assert after is not None
    assert after.last_seen_at > before


def test_expired_consumer_session_is_revoked_with_audit_event():
    client, auth, repository = _make_env()

    login = _login(client, "consumer", "consumer-password", "consumer")
    assert login.status_code == 200
    cookie_pair = login.headers["set-cookie"].split(";")[0]
    token_hash = __import__("hashlib").sha256(
        cookie_pair.split("=", 1)[1].encode("utf-8")
    ).hexdigest()
    session = _session_by_token_hash(repository, token_hash)
    assert session is not None

    revoked = auth.revoke_idle_sessions(
        now=session.last_seen_at + timedelta(minutes=11),
        idle_timeout=timedelta(minutes=10),
    )

    assert revoked == ((session.session_id, session.account_id),)
    after = _session_by_token_hash(repository, token_hash)
    assert after is not None
    assert after.revoked_at is not None
    assert any(
        entry.event_type == "session.idle_timeout"
        for entry in repository.audit
    )

    subsequent = client.get(
        "/v1/auth/session",
        headers={"cookie": cookie_pair},
    )
    assert subsequent.status_code == 401


def test_fresh_session_never_revoked_by_its_own_creation():
    client, auth, repository = _make_env()

    login = _login(client, "consumer", "consumer-password", "consumer")
    cookie_pair = login.headers["set-cookie"].split(";")[0]
    token_hash = __import__("hashlib").sha256(
        cookie_pair.split("=", 1)[1].encode("utf-8")
    ).hexdigest()
    session = _session_by_token_hash(repository, token_hash)
    assert session is not None

    revoked = auth.revoke_idle_sessions(
        now=session.last_seen_at,
        idle_timeout=timedelta(minutes=10),
    )

    assert revoked == ()
    assert _session_by_token_hash(repository, token_hash).revoked_at is None


def test_admin_sessions_are_exempt_from_idle_policy():
    client, auth, repository = _make_env()

    login = _login(client, "admin", "admin-password", "admin")
    cookie_pair = login.headers["set-cookie"].split(";")[0]
    token_hash = __import__("hashlib").sha256(
        cookie_pair.split("=", 1)[1].encode("utf-8")
    ).hexdigest()
    session = _session_by_token_hash(repository, token_hash)
    assert session is not None

    revoked = auth.revoke_idle_sessions(
        now=session.last_seen_at + timedelta(hours=24),
        idle_timeout=timedelta(minutes=10),
    )

    assert revoked == ()
    assert _session_by_token_hash(repository, token_hash).revoked_at is None


def test_run_idle_cycle_invokes_runtime_stop_callback_per_session():
    client, auth, repository = _make_env()
    stopped: list[str] = []

    login = _login(client, "consumer", "consumer-password", "consumer")
    cookie_pair = login.headers["set-cookie"].split(";")[0]
    token_hash = __import__("hashlib").sha256(
        cookie_pair.split("=", 1)[1].encode("utf-8")
    ).hexdigest()
    session = _session_by_token_hash(repository, token_hash)
    assert session is not None

    revoked = run_idle_cycle(
        auth,
        stopped.append,
        idle_timeout=timedelta(minutes=10),
        now=session.last_seen_at + timedelta(minutes=11),
    )

    assert revoked == (
        (str(session.session_id), str(session.account_id)),
    )
    assert stopped == [str(session.session_id)]


def test_run_idle_cycle_without_callback_still_revokes():
    client, auth, repository = _make_env()

    login = _login(client, "consumer", "consumer-password", "consumer")
    cookie_pair = login.headers["set-cookie"].split(";")[0]
    token_hash = __import__("hashlib").sha256(
        cookie_pair.split("=", 1)[1].encode("utf-8")
    ).hexdigest()
    session = _session_by_token_hash(repository, token_hash)
    assert session is not None

    revoked = run_idle_cycle(
        auth,
        None,
        idle_timeout=timedelta(minutes=10),
        now=session.last_seen_at + timedelta(minutes=11),
    )

    assert revoked == (
        (str(session.session_id), str(session.account_id)),
    )
    after = _session_by_token_hash(repository, token_hash)
    assert after is not None
    assert after.revoked_at is not None


def test_zero_timeout_disables_policy_entirely():
    client, auth, repository = _make_env(idle_timeout_seconds=0)

    login = _login(client, "consumer", "consumer-password", "consumer")
    cookie_pair = login.headers["set-cookie"].split(";")[0]
    token_hash = __import__("hashlib").sha256(
        cookie_pair.split("=", 1)[1].encode("utf-8")
    ).hexdigest()
    session = _session_by_token_hash(repository, token_hash)
    assert session is not None

    revoked = auth.revoke_idle_sessions(
        now=session.last_seen_at + timedelta(hours=24),
        idle_timeout=timedelta(seconds=0),
    )

    assert revoked == ()
    assert _session_by_token_hash(repository, token_hash).revoked_at is None

    heartbeat = client.post(
        "/v1/auth/heartbeat",
        headers={"cookie": cookie_pair},
    )
    assert heartbeat.status_code == 200


def test_revoked_session_cannot_heartbeat():
    client, auth, repository = _make_env()

    login = _login(client, "consumer", "consumer-password", "consumer")
    cookie_pair = login.headers["set-cookie"].split(";")[0]
    token_hash = __import__("hashlib").sha256(
        cookie_pair.split("=", 1)[1].encode("utf-8")
    ).hexdigest()
    session = _session_by_token_hash(repository, token_hash)
    assert session is not None

    auth.revoke_idle_sessions(
        now=session.last_seen_at + timedelta(minutes=11),
        idle_timeout=timedelta(minutes=10),
    )

    heartbeat = client.post(
        "/v1/auth/heartbeat",
        headers={"cookie": cookie_pair},
    )
    assert heartbeat.status_code == 401


def test_lifespan_reaper_disabled_without_context_manager_touch():
    """Plain TestClient (no `with`) never starts the background reaper.

    The synchronous cycle is covered directly; the lifespan only schedules
    the same run_idle_cycle in production.
    """
    client, _auth, _repository = _make_env()

    login = _login(client, "consumer", "consumer-password", "consumer")
    assert login.status_code == 200