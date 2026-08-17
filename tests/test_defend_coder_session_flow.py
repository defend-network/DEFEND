"""Session continuity E2E: browser login -> cookie -> workspace SSR fetch.

Hermetic: the repository is an in-memory fake, so these tests always run
without a PostgreSQL test database. They pin the exact production path:

    POST /v1/auth/login (Set-Cookie)
        -> browser holds HttpOnly session cookie
        -> /workspace server fetch forwards the incoming Cookie header
        -> GET /v1/auth/session + GET /v1/workspaces authenticate

A server-component fetch does NOT carry cookies automatically; if the
Cookie header is not forwarded the SSR call 401s and /workspace renders
"Session required" even though login succeeded.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from defend_coder.app import CSRF_COOKIE, SESSION_COOKIE, build_coder_app
from defend_coder.auth import AuthService
from defend_coder.config import CoderSettings
from defend_coder.repositories import (
    AccountRecord,
    CoderRepository,
    SessionRecord,
    WorkspaceRecord,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class _FakeAudit:
    event_type: str
    actor_account_id: UUID | None
    target_type: str


class FakeCoderRepository(CoderRepository):
    """In-memory CoderRepository — same contract, no PostgreSQL."""

    def __init__(self) -> None:
        self.accounts: dict[str, AccountRecord] = {}
        self.sessions: dict[str, SessionRecord] = {}
        self.workspaces: list[WorkspaceRecord] = []
        self.audit: list[_FakeAudit] = []

    def create_account(
        self,
        *,
        username: str,
        email: str | None,
        password_hash: str,
        role: str,
    ) -> AccountRecord:
        now = _now()
        record = AccountRecord(
            account_id=uuid4(),
            username=username,
            email=email,
            password_hash=password_hash,
            role=role,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        self.accounts[username] = record
        return record

    def get_account_by_username(
        self, username: str
    ) -> AccountRecord | None:
        return self.accounts.get(username)

    def get_account(self, account_id: UUID) -> AccountRecord | None:
        for record in self.accounts.values():
            if record.account_id == account_id:
                return record
        return None

    def create_session(
        self,
        *,
        account_id: UUID,
        token_hash: str,
        expires_at: datetime,
    ) -> SessionRecord:
        now = _now()
        record = SessionRecord(
            session_id=uuid4(),
            account_id=account_id,
            token_hash=token_hash,
            created_at=now,
            expires_at=expires_at,
            revoked_at=None,
            last_seen_at=now,
        )
        self.sessions[token_hash] = record
        return record

    def get_session_by_hash(
        self, token_hash: str
    ) -> SessionRecord | None:
        return self.sessions.get(token_hash)

    def revoke_session(self, session_id: UUID) -> None:
        for record in self.sessions.values():
            if record.session_id == session_id:
                record = SessionRecord(
                    session_id=record.session_id,
                    account_id=record.account_id,
                    token_hash=record.token_hash,
                    created_at=record.created_at,
                    expires_at=record.expires_at,
                    revoked_at=_now(),
                    last_seen_at=record.last_seen_at,
                )
                self.sessions[record.token_hash] = record
                break

    def touch_session_last_seen(self, session_id: UUID) -> None:
        for record in list(self.sessions.values()):
            if (
                record.session_id == session_id
                and record.revoked_at is None
            ):
                self.sessions[record.token_hash] = SessionRecord(
                    session_id=record.session_id,
                    account_id=record.account_id,
                    token_hash=record.token_hash,
                    created_at=record.created_at,
                    expires_at=record.expires_at,
                    revoked_at=record.revoked_at,
                    last_seen_at=_now(),
                )
                break

    def _role_for(self, account_id: UUID) -> str | None:
        for record in self.accounts.values():
            if record.account_id == account_id:
                return record.role
        return None

    def list_expired_idle_sessions(
        self, threshold: datetime
    ) -> tuple[SessionRecord, ...]:
        return tuple(
            record
            for record in self.sessions.values()
            if record.revoked_at is None
            and record.expires_at > _now()
            and record.last_seen_at < threshold
            and self._role_for(record.account_id) == "consumer"
        )

    def create_workspace(
        self,
        *,
        owner_account_id: UUID,
        name: str,
        workspace_root: str,
        repository_url: str | None = None,
        default_branch: str | None = None,
    ) -> WorkspaceRecord:
        now = _now()
        record = WorkspaceRecord(
            workspace_id=uuid4(),
            owner_account_id=owner_account_id,
            name=name,
            workspace_root=workspace_root,
            repository_url=repository_url,
            default_branch=default_branch,
            created_at=now,
            updated_at=now,
        )
        self.workspaces.append(record)
        return record

    def list_workspaces_for_owner(
        self, owner_account_id: UUID
    ) -> tuple[WorkspaceRecord, ...]:
        return tuple(
            record
            for record in self.workspaces
            if record.owner_account_id == owner_account_id
        )

    def append_audit_event(
        self,
        *,
        actor_account_id: UUID | None,
        event_type: str,
        target_type: str,
        target_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        del target_id, detail
        self.audit.append(
            _FakeAudit(event_type, actor_account_id, target_type)
        )


def _make_client() -> tuple[TestClient, object, FakeCoderRepository]:
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
        ),
        db=object(),  # type: ignore[arg-type]
        auth=auth,
        repository=repository,
        runtime_status=lambda: {"state": "ready"},
    )
    return TestClient(app, base_url="https://testserver"), app, repository


def _login(client: TestClient, username: str, password: str, role: str):
    return client.post(
        "/v1/auth/login",
        json={
            "username": username,
            "password": password,
            "role": role,
        },
    )


def test_login_sets_host_only_http_only_lax_session_cookie():
    client, _auth, _repo = _make_client()

    response = _login(client, "admin", "admin-password", "admin")

    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert f"{SESSION_COOKIE}=" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "secure" in cookie
    assert "path=/" in cookie
    assert "domain=" not in cookie


def test_login_cookie_roundtrip_authenticates_workspace_ssr_fetch():
    client, _auth, _repo = _make_client()

    login = _login(client, "consumer", "consumer-password", "consumer")
    assert login.status_code == 200

    cookie_pair = login.headers["set-cookie"].split(";")[0]
    assert cookie_pair.startswith(f"{SESSION_COOKIE}=")

    session = client.get(
        "/v1/auth/session",
        headers={"cookie": cookie_pair},
    )
    assert session.status_code == 200
    assert session.json()["account"]["username"] == "consumer"
    assert session.json()["account"]["role"] == "consumer"

    workspaces = client.get(
        "/v1/workspaces",
        headers={"cookie": cookie_pair},
    )
    assert workspaces.status_code == 200
    assert workspaces.json()["workspaces"] == []


def test_workspace_ssr_fetch_without_cookie_is_rejected():
    client, app, _repo = _make_client()

    login = _login(client, "consumer", "consumer-password", "consumer")
    assert login.status_code == 200

    cookieless = TestClient(app, base_url="https://testserver")
    assert cookieless.get("/v1/auth/session").status_code == 401
    assert cookieless.get("/v1/workspaces").status_code == 401


def test_cookie_uses_same_name_api_expects_for_session():
    client, _auth, _repo = _make_client()

    login = _login(client, "admin", "admin-password", "admin")
    assert login.status_code == 200

    cookie = login.headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    assert cookie.startswith("defendcoder_session=")

    assert CSRF_COOKIE == "defendcoder_csrf"
    assert "defendcoder_csrf=" in cookie.lower()


def test_public_proxy_arrangement_keeps_host_only_cookies():
    """Production is web 3301 (Next rewrite) -> API 8301.

    The API must never pin Domain=localhost/127.0.0.1, otherwise the
    proxied Set-Cookie would be stored for the origin host instead of the
    public host and every request would arrive cookieless.
    """
    client, _auth, _repo = _make_client()

    login = _login(client, "consumer", "consumer-password", "consumer")
    assert login.status_code == 200

    cookie = login.headers["set-cookie"]
    assert "domain=" not in cookie.lower()
    assert "127.0.0.1" not in cookie.lower()
    assert "localhost" not in cookie.lower()