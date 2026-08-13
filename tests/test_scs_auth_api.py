from dataclasses import dataclass

from fastapi.testclient import TestClient
import pytest

from scs_api.app import build_scs_app
from scs_data.identity import ScsIdentityStore
from scs_data.mailer import DeliveryResult, invitation_activation_url
from scs_data.config import ScsPaths
from shared_platform.application import ApplicationContext


@dataclass
class FakeMailer:
    succeed: bool = True

    def __post_init__(self):
        self.urls = []

    def send_invitation(self, email: str, activation_url: str) -> DeliveryResult:
        self.urls.append((email, activation_url))
        return DeliveryResult(self.succeed, "sent" if self.succeed else "failed")


@pytest.fixture
def api(tmp_path):
    context = ApplicationContext(
        "scs", (tmp_path / "SCS_DATA").resolve(), "SCS", "SCS",
        "scs_employee_session", "https://ai.sunshineclimatesolutions.com", 8100, 3100,
    )
    paths = ScsPaths.from_context(context).ensure()
    identity = ScsIdentityStore(paths.database)
    owner = identity.bootstrap_owner("owner@example.com", "owner", "Owner", "owner-password")
    mailer = FakeMailer()
    app = build_scs_app(context, identity, mailer)
    with TestClient(app, base_url="https://ai.sunshineclimatesolutions.com") as client:
        yield client, identity, owner, mailer
    identity.close()


def login(client, identifier="owner", password="owner-password"):
    return client.post("/api/scs/auth/login", json={"identifier": identifier, "password": password})


def test_scs_has_no_registration_and_uses_only_scs_cookie(api):
    client, _identity, _owner, _mailer = api
    assert client.post("/api/scs/auth/register", json={}).status_code == 404

    response = login(client)
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "scs_employee_session=" in cookie
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie
    assert "Path=/" in cookie
    assert "defend_" not in cookie


def test_defend_cookie_never_authenticates_and_login_failure_is_generic(api):
    client, identity, _owner, _mailer = api
    client.cookies.set("defend_account_session", "session_defend-private")
    assert client.get("/api/scs/auth/session").status_code == 401
    failed = login(client, "owner", "wrong-password")
    assert failed.status_code == 401
    assert failed.json()["detail"] == "Invalid credentials"
    assert "owner" not in failed.text
    assert identity.conn.execute(
        "SELECT COUNT(*) FROM scs_audit_events WHERE event_type='auth.login_failed'"
    ).fetchone()[0] == 1


def test_owner_invitation_sends_fragment_url_without_returning_token(api):
    client, identity, _owner, mailer = api
    assert login(client).status_code == 200
    response = client.post("/api/scs/admin/invitations", json={
        "email": "tech@example.com", "display_name": "Tech", "roles": ["read_only"]
    })
    assert response.status_code == 201
    body = response.json()
    assert body["delivery"] == "sent"
    assert "manual_activation_url" not in body
    url = mailer.urls[0][1]
    assert url.startswith("https://ai.sunshineclimatesolutions.com/activate#token=")
    assert "?token=" not in url
    raw_token = url.split("#token=", 1)[1]
    assert raw_token not in repr(identity.conn.execute("SELECT * FROM scs_invitations").fetchall())


def test_failed_delivery_returns_authorized_manual_copy_and_can_retry(api):
    client, _identity, _owner, mailer = api
    login(client)
    mailer.succeed = False
    created = client.post("/api/scs/admin/invitations", json={
        "email": "tech@example.com", "display_name": "Tech", "roles": ["read_only"]
    })
    assert created.status_code == 201
    assert created.json()["delivery"] == "failed"
    assert "#token=" in created.json()["manual_activation_url"]

    mailer.succeed = True
    retried = client.post(f"/api/scs/admin/invitations/{created.json()['invitation_id']}/retry")
    assert retried.status_code == 200
    assert retried.json()["delivery"] == "sent"
    assert "manual_activation_url" not in retried.json()


def test_activation_login_session_and_logout_round_trip(api):
    client, identity, owner, _mailer = api
    invitation, token = identity.invite_employee(owner.employee_id, "worker@example.com", "Worker", ("read_only",))
    activated = client.post("/api/scs/auth/activate", json={
        "token": token, "username": "worker", "password": "worker-password"
    })
    assert activated.status_code == 200
    assert login(client, "worker", "worker-password").status_code == 200
    assert client.get("/api/scs/auth/session").json()["employee"]["username"] == "worker"
    logged_out = client.post("/api/scs/auth/logout")
    assert logged_out.status_code == 204
    assert "Max-Age=0" in logged_out.headers["set-cookie"]
    assert client.get("/api/scs/auth/session").status_code == 401


def test_activation_url_rejects_non_scs_origin():
    with pytest.raises(ValueError, match="SCS origin"):
        invitation_activation_url("https://ai.defend-network.org", "scsinvite_private")
