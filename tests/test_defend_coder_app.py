from __future__ import annotations

from datetime import timedelta
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from defend_coder.agent_client import (
    AgentChatClient,
    AgentChatResponse,
    ToolCall,
)
from defend_coder.app import build_coder_app
from defend_coder.auth import AuthService
from defend_coder.config import CoderSettings
from defend_coder.db import CoderDatabase
from defend_coder.model_config import CoderModelConfig
from defend_coder.repositories import CoderRepository
from defend_coder.runs import RunsRepository, RunRunner
from defend_coder.tools import CoderToolkit


pytestmark = pytest.mark.skipif(
    not os.environ.get("CODER_TEST_DATABASE_URL"),
    reason="CODER_TEST_DATABASE_URL is not configured",
)


class FakeAgentClient(AgentChatClient):
    """Scripted model: writes a file, runs tests, then answers."""

    def __init__(self, delay_seconds: float = 0.0):
        import time

        self._delay = delay_seconds
        self._time = time
        super().__init__(
            CoderModelConfig(
                alias="defendcoder-heavy",
                model_name="Qwen/Qwen3-Coder-Next",
                base_url="http://127.0.0.1:8001/v1",
            )
        )

    def chat(self, messages, tools=None, **kwargs):
        if self._delay:
            self._time.sleep(self._delay)
        step = sum(
            1 for message in messages if message["role"] == "tool"
        )
        if step == 0:
            return AgentChatResponse(
                content=None,
                tool_calls=(
                    ToolCall(
                        id="call_write",
                        name="write_file",
                        arguments={
                            "path": "index.html",
                            "content": "<h1>Ops Dashboard</h1>",
                        },
                    ),
                ),
            )
        if step == 1:
            return AgentChatResponse(
                content=None,
                tool_calls=(
                    ToolCall(id="call_tests", name="run_tests", arguments={}),
                ),
            )
        return AgentChatResponse(
            content="Dashboard built. No test runner detected in the "
            "empty workspace; verified the file was written.",
            tool_calls=(),
        )


@pytest.fixture
def db():
    database = CoderDatabase(os.environ["CODER_TEST_DATABASE_URL"])
    database.migrate()

    with database.connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                TRUNCATE
                    coder_run_messages,
                    coder_runs,
                    coder_audit_events,
                    coder_sessions,
                    coder_workspaces,
                    coder_accounts
                RESTART IDENTITY CASCADE
                """
            )

    return database


@pytest.fixture
def repo(db):
    return CoderRepository(db)


@pytest.fixture
def auth(repo):
    service = AuthService(repo, session_ttl=timedelta(hours=8))
    service.create_account(
        username="admin",
        email="admin@example.test",
        password="admin-password",
        role="admin",
    )
    service.create_account(
        username="consumer",
        email="consumer@example.test",
        password="consumer-password",
        role="consumer",
    )
    return service


@pytest.fixture
def settings(tmp_path):
    return CoderSettings(
        database_url="postgresql://redacted",
        host="127.0.0.1",
        port=8301,
        public_https=True,
        workspace_root=str(tmp_path / "coder-workspaces"),
    )


@pytest.fixture
def runner(db, settings):
    repository = CoderRepository(db)
    runs_repository = RunsRepository(db)

    return RunRunner(
        repository=runs_repository,
        client=FakeAgentClient(),
        toolkit_factory=lambda log_reader: CoderToolkit(
            repository=repository,
            configured_root=settings.workspace_root,
            log_reader=log_reader,
        ),
    )


@pytest.fixture
def client(db, auth, settings, runner):
    app = build_coder_app(
        settings=settings,
        db=db,
        auth=auth,
        runtime_status=lambda: {
            "state": "ready",
            "model": "Qwen/Qwen3-Coder-30B-A3B-Instruct",
            "provider": "Vast.ai",
            "context_used": 120,
            "context_limit": 8192,
            "internal_endpoint": "http://127.0.0.1:9000",
            "instance_id": "12345",
        },
        runner=runner,
        configured_root=settings.workspace_root,
    )
    return TestClient(
        app,
        base_url="https://testserver",
    )


def _login(client, username, password, role):
    response = client.post(
        "/v1/auth/login",
        json={
            "username": username,
            "password": password,
            "role": role,
        },
    )
    return response


def test_health_is_public_safe(client):
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["application_id"] == "coder"

    blob = str(body).lower()
    for banned in ("password", "secret", "token", "postgresql://"):
        assert banned not in blob


def test_admin_login_sets_secure_http_only_cookie(client):
    response = _login(
        client,
        "admin",
        "admin-password",
        "admin",
    )

    assert response.status_code == 200
    assert response.json()["account"]["role"] == "admin"

    cookie = response.headers["set-cookie"].lower()
    assert "defendcoder_session=" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "secure" in cookie


def test_login_cookie_is_host_only_and_proxy_safe(client):
    """Host-only cookie: never pins Domain=localhost/127.0.0.1 so the
    Next rewrite (web 3301 -> API 8301) keeps the session on the public
    host instead of redirecting it to the origin host."""
    response = _login(
        client,
        "admin",
        "admin-password",
        "admin",
    )

    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "path=/" in cookie
    assert "domain=" not in cookie
    assert "localhost" not in cookie
    assert "127.0.0.1" not in cookie


def test_session_roundtrip_with_explicit_cookie_header(client):
    """E2E: login -> Set-Cookie -> workspace SSR forwards the Cookie
    header -> /v1/auth/session and /v1/workspaces authenticate."""
    login = _login(
        client,
        "consumer",
        "consumer-password",
        "consumer",
    )
    assert login.status_code == 200

    cookie_pair = login.headers["set-cookie"].split(";")[0]
    assert cookie_pair.startswith("defendcoder_session=")

    session = client.get(
        "/v1/auth/session",
        headers={"cookie": cookie_pair},
    )
    assert session.status_code == 200
    assert session.json()["account"]["username"] == "consumer"

    workspaces = client.get(
        "/v1/workspaces",
        headers={"cookie": cookie_pair},
    )
    assert workspaces.status_code == 200


def test_session_endpoint_rejects_cookieless_ssr_fetch(client):
    login = _login(
        client,
        "consumer",
        "consumer-password",
        "consumer",
    )
    assert login.status_code == 200

    assert client.get("/v1/auth/session").status_code == 401
    assert client.get("/v1/workspaces").status_code == 401


def test_consumer_login_uses_same_endpoint(client):
    response = _login(
        client,
        "consumer",
        "consumer-password",
        "consumer",
    )

    assert response.status_code == 200
    assert response.json()["account"]["role"] == "consumer"


def test_role_mismatch_is_generic_login_failure(client):
    response = _login(
        client,
        "consumer",
        "consumer-password",
        "admin",
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid credentials"


def test_wrong_username_and_password_are_generic(client):
    missing = _login(client, "missing", "anything", "consumer")
    wrong = _login(client, "consumer", "wrong", "consumer")

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert missing.json()["detail"] == "invalid credentials"
    assert wrong.json()["detail"] == "invalid credentials"


def test_session_endpoint_returns_current_account(client):
    login = _login(
        client,
        "consumer",
        "consumer-password",
        "consumer",
    )
    assert login.status_code == 200

    response = client.get("/v1/auth/session")

    assert response.status_code == 200
    assert response.json()["account"]["username"] == "consumer"
    assert response.json()["account"]["role"] == "consumer"


def test_admin_status_rejects_consumer(client):
    _login(
        client,
        "consumer",
        "consumer-password",
        "consumer",
    )

    response = client.get("/v1/admin/status")

    assert response.status_code == 403


def test_admin_status_returns_safe_runtime_status(client):
    _login(
        client,
        "admin",
        "admin-password",
        "admin",
    )

    response = client.get("/v1/admin/status")

    assert response.status_code == 200
    body = response.json()
    assert body["runtime"]["state"] == "ready"

    blob = str(body).lower()
    for banned in ("password", "secret", "token"):
        assert banned not in blob


def test_runtime_status_requires_session(client):
    response = client.get("/v1/runtime/status")

    assert response.status_code == 401


def test_consumer_runtime_status_returns_safe_projection(client):
    _login(
        client,
        "consumer",
        "consumer-password",
        "consumer",
    )

    response = client.get("/v1/runtime/status")

    assert response.status_code == 200
    body = response.json()
    assert body["application_id"] == "coder"
    assert body["runtime"]["state"] == "ready"
    assert (
        body["runtime"]["model"]
        == "Qwen/Qwen3-Coder-30B-A3B-Instruct"
    )

    blob = str(body).lower()
    for banned in ("password", "secret", "token", "postgresql://"):
        assert banned not in blob


def test_runtime_status_projection_hides_unknown_callback_fields(client):
    _login(
        client,
        "consumer",
        "consumer-password",
        "consumer",
    )

    response = client.get("/v1/runtime/status")

    assert response.status_code == 200
    body = response.json()
    assert set(body["runtime"]) == {
        "state",
        "model",
        "provider",
        "context_used",
        "context_limit",
    }


def test_workspace_list_is_owner_scoped(client):
    _login(
        client,
        "consumer",
        "consumer-password",
        "consumer",
    )

    response = client.get("/v1/workspaces")

    assert response.status_code == 200
    assert response.json()["workspaces"] == []


def test_workspace_create_requires_csrf(client):
    _login(
        client,
        "consumer",
        "consumer-password",
        "consumer",
    )

    response = client.post(
        "/v1/workspaces",
        json={
            "name": "project",
            "workspace_root": r"C:\DEFEND_CODER_DATA\consumer\project",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "csrf validation failed"


def test_workspace_create_with_csrf(client):
    login = _login(
        client,
        "consumer",
        "consumer-password",
        "consumer",
    )

    csrf = login.json()["csrf_token"]

    response = client.post(
        "/v1/workspaces",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": "project",
            "workspace_root": r"C:\DEFEND_CODER_DATA\consumer\project",
            "repository_url": "https://github.com/example/project.git",
            "default_branch": "main",
        },
    )

    assert response.status_code == 201
    body = response.json()["workspace"]
    assert body["name"] == "project"
    assert body["repository_url"] == "https://github.com/example/project.git"


def test_logout_requires_csrf(client):
    login = _login(
        client,
        "consumer",
        "consumer-password",
        "consumer",
    )

    without = client.post("/v1/auth/logout")
    assert without.status_code == 403

    csrf = login.json()["csrf_token"]
    response = client.post(
        "/v1/auth/logout",
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 204

    after = client.get("/v1/auth/session")
    assert after.status_code == 401


def _login_with_csrf(client, username="consumer", password="consumer-password", role="consumer"):
    login = client.post(
        "/v1/auth/login",
        json={
            "username": username,
            "password": password,
            "role": role,
        },
    )
    assert login.status_code == 200
    return login.json()["csrf_token"]


def _create_workspace(client, csrf, name="project", root=None):
    response = client.post(
        "/v1/workspaces",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": name,
            "workspace_root": root or "consumer/project",
        },
    )
    assert response.status_code == 201
    return response.json()["workspace"]["workspace_id"]


def _wait_for_run(client, workspace_id, run_id, timeout_seconds=15):
    import time

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        response = client.get(
            f"/v1/workspaces/{workspace_id}/runs/{run_id}"
        )
        assert response.status_code == 200
        run = response.json()["run"]
        if run["status"] in ("succeeded", "failed"):
            return response.json()
        time.sleep(0.05)
    raise AssertionError("run did not finish in time")


def test_create_run_requires_csrf(client):
    csrf = _login_with_csrf(client)
    workspace_id = _create_workspace(client, csrf, root="consumer/project")

    response = client.post(
        f"/v1/workspaces/{workspace_id}/runs",
        json={"prompt": "Build a dashboard."},
    )

    assert response.status_code == 403


def test_run_without_agent_is_503(client, db, auth, settings):
    app = build_coder_app(
        settings=settings,
        db=db,
        auth=auth,
        runtime_status=lambda: {'state': 'offline'},
    )
    bare = TestClient(app, base_url='https://testserver')
    csrf = _login_with_csrf(bare)
    workspace_id = _create_workspace(bare, csrf, root='consumer/project')

    response = bare.post(
        f'/v1/workspaces/{workspace_id}/runs',
        headers={'X-CSRF-Token': csrf},
        json={'prompt': 'Do it.'},
    )

    assert response.status_code == 503
    assert 'not connected' in response.json()['detail']


def test_run_end_to_end_with_fake_agent(client, settings):
    csrf = _login_with_csrf(client)
    workspace_id = _create_workspace(client, csrf, root='consumer/project')

    response = client.post(
        f'/v1/workspaces/{workspace_id}/runs',
        headers={'X-CSRF-Token': csrf},
        json={'prompt': 'Build an ops dashboard.'},
    )

    assert response.status_code == 201
    run = response.json()['run']
    assert run['status'] in ('queued', 'running')

    detail = _wait_for_run(client, workspace_id, run['run_id'])
    assert detail['run']['status'] == 'succeeded'

    roles = [message['role'] for message in detail['messages']]
    assert 'assistant' in roles
    assert 'tool' in roles
    assert any(
        message.get('tool_name') == 'write_file'
        for message in detail['messages']
    )
    assert any(
        message.get('kind') == 'tests'
        for message in detail['messages']
    )

    written = (
        Path(settings.workspace_root)
        / 'consumer'
        / 'project'
        / 'index.html'
    )
    assert written.read_text(encoding='utf-8') == '<h1>Ops Dashboard</h1>'

    final = [m for m in detail['messages'] if m['role'] == 'assistant'][-1]
    assert 'Dashboard built' in (final['content'] or '')


def test_run_list_is_owner_scoped_and_recent_first(client):
    csrf = _login_with_csrf(client)
    workspace_id = _create_workspace(client, csrf, root='consumer/project')

    for _index in range(3):
        response = client.post(
            f'/v1/workspaces/{workspace_id}/runs',
            headers={'X-CSRF-Token': csrf},
            json={'prompt': 'Task.'},
        )
        assert response.status_code == 201

    response = client.get(f'/v1/workspaces/{workspace_id}/runs')

    assert response.status_code == 200
    runs = response.json()['runs']
    assert len(runs) == 3
    created = [run['created_at'] for run in runs]
    assert created == sorted(created, reverse=True)


def test_run_access_from_other_account_is_404(client):
    csrf = _login_with_csrf(client)
    workspace_id = _create_workspace(client, csrf, root='consumer/project')

    response = client.post(
        f'/v1/workspaces/{workspace_id}/runs',
        headers={'X-CSRF-Token': csrf},
        json={'prompt': 'Task.'},
    )
    assert response.status_code == 201
    run_id = response.json()['run']['run_id']

    other = _login_with_csrf(
        client,
        username="admin",
        password="admin-password",
        role="admin",
    )
    assert other

    response = client.get(
        f'/v1/workspaces/{workspace_id}/runs/{run_id}'
    )
    assert response.status_code == 404


def test_concurrent_run_on_same_workspace_is_409(client, runner, db, auth, settings):
    slow_runner = RunRunner(
        repository=runs_repository(db),
        client=FakeAgentClient(delay_seconds=0.3),
        toolkit_factory=lambda log_reader: CoderToolkit(
            repository=CoderRepository(db),
            configured_root=settings.workspace_root,
            log_reader=log_reader,
        ),
    )
    app = build_coder_app(
        settings=settings,
        db=db,
        auth=auth,
        runtime_status=lambda: {'state': 'ready'},
        runner=slow_runner,
        configured_root=settings.workspace_root,
    )
    slow = TestClient(app, base_url='https://testserver')
    csrf = _login_with_csrf(slow)
    workspace_id = _create_workspace(slow, csrf, root='consumer/project')

    first = slow.post(
        f'/v1/workspaces/{workspace_id}/runs',
        headers={'X-CSRF-Token': csrf},
        json={'prompt': 'First.'},
    )
    assert first.status_code == 201

    second = slow.post(
        f'/v1/workspaces/{workspace_id}/runs',
        headers={'X-CSRF-Token': csrf},
        json={'prompt': 'Second.'},
    )

    assert second.status_code == 409
    assert 'already active' in second.json()['detail']


def test_files_listing_requires_session(client):
    response = client.get('/v1/workspaces/00000000-0000-0000-0000-000000000000/files')

    assert response.status_code == 401


def test_files_listing_shows_workspace_tree(client, settings):
    csrf = _login_with_csrf(client)
    workspace_id = _create_workspace(client, csrf, root='consumer/project')
    root = Path(settings.workspace_root) / 'consumer' / 'project'
    (root / 'src').mkdir(parents=True)
    (root / 'src' / 'app.js').write_text('// x', encoding='utf-8')
    (root / 'index.html').write_text('<html></html>', encoding='utf-8')

    response = client.get(
        f'/v1/workspaces/{workspace_id}/files',
    )

    assert response.status_code == 200
    entries = {
        entry['name']: entry['type']
        for entry in response.json()['entries']
    }
    assert entries['index.html'] == 'file'
    assert entries['src'] == 'directory'


def test_files_listing_rejects_path_escape(client, settings):
    csrf = _login_with_csrf(client)
    workspace_id = _create_workspace(client, csrf, root='consumer/project')

    response = client.get(
        f'/v1/workspaces/{workspace_id}/files',
        params={'path': '../..'},
    )

    assert response.status_code == 400
