from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import admin_auth
from api_identity_admin_routes import router
from defend_data.conversation_store import ConversationStore
from defend_data.identity_store import IdentityStore
from defend_data.visitor_store import VisitorStore


def _activate(identity: IdentityStore, owner, *, email: str, role: str):
    account = identity.create_account(
        email=email,
        display_name=email.split("@", 1)[0].replace(".", " ").title(),
        role=role,
        created_by=owner.account_id,
    )
    _, token = identity.create_invitation(
        account_id=account.account_id,
        created_by=owner.account_id,
    )
    return identity.consume_invitation(token, password=f"valid password for {email}")


@pytest.fixture
def admin_api(data_paths, monkeypatch):
    monkeypatch.setenv("DEFEND_OWNER_USER", "Chairman")
    monkeypatch.setenv("DEFEND_OWNER_EMAIL", "chairman@defend-network.org")
    monkeypatch.setenv("DEFEND_OWNER_PASS", "valid owner password")
    monkeypatch.setenv(
        "DEFEND_VISITOR_HMAC_KEY",
        "test-key-with-at-least-thirty-two-characters",
    )
    identity = IdentityStore(data_paths)
    visitors = VisitorStore(data_paths)
    conversations = ConversationStore(data_paths)
    admin_auth.configure_identity_store(identity)
    owner = identity.get_account("chairman@defend-network.org")
    assert owner is not None
    admin = _activate(
        identity,
        owner,
        email="operations.admin@example.com",
        role="admin",
    )
    expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    owner_token = identity.create_session(owner.account_id, expires_at=expires)
    admin_token = identity.create_session(admin.account_id, expires_at=expires)

    app = FastAPI()
    app.state.defend_data = SimpleNamespace(
        identity=identity,
        visitors=visitors,
        conversations=conversations,
    )
    app.include_router(router)
    with TestClient(app) as client:
        yield SimpleNamespace(
            client=client,
            identity=identity,
            visitors=visitors,
            conversations=conversations,
            owner=owner,
            admin=admin,
            owner_headers={"Authorization": f"Bearer {owner_token}"},
            admin_headers={"Authorization": f"Bearer {admin_token}"},
        )
    conversations.close()
    visitors.close()
    identity.close()


def test_account_search_is_bounded_parameterized_and_omits_secrets(admin_api):
    account = admin_api.identity.create_account(
        email="jane+ops@example.com",
        display_name="Jane Operations",
        role="user",
        created_by=admin_api.admin.account_id,
    )

    response = admin_api.client.get(
        "/api/admin/accounts",
        params={"q": "jane+ops@example.com", "limit": 1, "offset": 0},
        headers=admin_api.admin_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["limit"] == 1
    assert payload["offset"] == 0
    assert payload["items"][0]["account_id"] == account.account_id
    assert "password_hash" not in payload["items"][0]
    assert admin_api.client.get(
        "/api/admin/accounts", params={"q": "%' OR 1=1 --"}, headers=admin_api.admin_headers
    ).json()["total"] == 0
    assert admin_api.client.get(
        "/api/admin/accounts", params={"limit": 101}, headers=admin_api.admin_headers
    ).status_code == 422
    assert admin_api.client.get(
        "/api/admin/accounts", params={"offset": 1_000_001}, headers=admin_api.admin_headers
    ).status_code == 422


def test_admin_cannot_manage_admin_and_failure_is_audited(admin_api):
    target = _activate(
        admin_api.identity,
        admin_api.owner,
        email="target.admin@example.com",
        role="admin",
    )

    response = admin_api.client.patch(
        f"/api/admin/accounts/{target.account_id}",
        json={"status": "disabled"},
        headers=admin_api.admin_headers,
    )

    assert response.status_code == 403
    assert admin_api.identity.get_account(target.account_id).status == "active"
    events = admin_api.identity.list_audit_events(query="account.update")
    assert events[0]["target_id"] == target.account_id
    assert events[0]["outcome"] == "failure"


def test_account_detail_includes_bounded_linked_telemetry_without_secrets(admin_api):
    user = _activate(
        admin_api.identity,
        admin_api.owner,
        email="detail.member@example.com",
        role="user",
    )
    visitor_id = admin_api.visitors.ensure_visitor(
        None,
        fingerprint="fp_account_detail",
        client_meta={"browser": "edge", "platform": "windows", "device": "desktop"},
    )
    session_id = admin_api.visitors.ensure_session(
        None, visitor_id, client_meta={"browser": "edge"}
    )
    admin_api.visitors.record_connection(
        visitor_id=visitor_id,
        session_id=session_id,
        ip_address="198.51.100.44",
        user_agent="Edge/128",
        client_meta={"browser": "edge", "platform": "windows", "device": "desktop"},
        cookie_hash="cookie_private_correlation",
    )
    admin_api.identity.link_visitor(account_id=user.account_id, visitor_id=visitor_id)

    response = admin_api.client.get(
        f"/api/admin/accounts/{user.account_id}", headers=admin_api.admin_headers
    )

    assert response.status_code == 200
    linked = response.json()["linked_visitors"][0]
    assert linked["visitor"]["visitor_id"] == visitor_id
    assert linked["connections"][0]["ip_address"] == "198.51.100.44"
    assert len(linked["sessions"]) <= 200
    assert len(linked["connections"]) <= 200
    assert "cookie_private_correlation" not in response.text
    assert "password_hash" not in response.text
    assert "session_hash" not in response.text
    assert "token_hash" not in response.text

    missing = admin_api.client.get(
        "/api/admin/accounts/acct_missing", headers=admin_api.admin_headers
    )
    assert missing.status_code == 404
    assert admin_api.identity.list_audit_events(query="acct_missing")[0]["outcome"] == "failure"


def test_account_update_and_owner_only_destructive_actions_are_audited(admin_api):
    user = _activate(
        admin_api.identity,
        admin_api.owner,
        email="member@example.com",
        role="user",
    )
    admin_api.identity.link_visitor(account_id=user.account_id, visitor_id="vis_member")

    updated = admin_api.client.patch(
        f"/api/admin/accounts/{user.account_id}",
        json={"display_name": "Updated Member", "status": "disabled"},
        headers=admin_api.admin_headers,
    )
    denied = admin_api.client.post(
        f"/api/admin/accounts/{user.account_id}/anonymize",
        headers=admin_api.admin_headers,
    )
    anonymized = admin_api.client.post(
        f"/api/admin/accounts/{user.account_id}/anonymize",
        headers=admin_api.owner_headers,
    )

    assert updated.status_code == 200
    assert updated.json()["account"]["display_name"] == "Updated Member"
    assert denied.status_code == 403
    assert anonymized.status_code == 200
    record = anonymized.json()["account"]
    assert record["status"] == "anonymized"
    assert record["email"] != "member@example.com"
    assert admin_api.identity.list_linked_visitors(user.account_id) == []
    assert [event["outcome"] for event in admin_api.identity.list_audit_events(query="account.anonymize")][:2] == ["success", "failure"]

    removable = admin_api.identity.create_account(
        email="remove@example.com",
        display_name="Remove Me",
        role="user",
        created_by=admin_api.admin.account_id,
    )
    deleted = admin_api.client.delete(
        f"/api/admin/accounts/{removable.account_id}", headers=admin_api.owner_headers
    )
    assert deleted.status_code == 204
    assert admin_api.identity.get_account(removable.account_id) is None
    assert admin_api.identity.list_audit_events(query=removable.account_id)[0]["outcome"] == "success"


def test_owner_role_and_self_boundaries_are_enforced(admin_api):
    assert admin_api.client.patch(
        f"/api/admin/accounts/{admin_api.owner.account_id}",
        json={"role": "admin"},
        headers=admin_api.owner_headers,
    ).status_code == 403
    assert admin_api.client.delete(
        f"/api/admin/accounts/{admin_api.owner.account_id}",
        headers=admin_api.owner_headers,
    ).status_code == 403
    assert admin_api.client.patch(
        f"/api/admin/accounts/{admin_api.admin.account_id}",
        json={"role": "user"},
        headers=admin_api.admin_headers,
    ).status_code == 403


def test_visitor_search_detail_and_failed_lookup_are_audited(admin_api):
    visitor_id = admin_api.visitors.ensure_visitor(
        None,
        fingerprint="fp_seeded",
        client_meta={
            "browser": "firefox",
            "platform": "linux",
            "device": "desktop",
            "language": "en-us",
        },
    )
    session_id = admin_api.visitors.ensure_session(
        None, visitor_id, client_meta={"browser": "firefox"}
    )
    admin_api.visitors.record_connection(
        visitor_id=visitor_id,
        session_id=session_id,
        ip_address="203.0.113.8",
        user_agent="Firefox/128",
        client_meta={
            "browser": "firefox",
            "platform": "linux",
            "device": "desktop",
            "language": "en-us",
        },
        cookie_hash="cookie_safe_hash",
    )
    account = admin_api.identity.create_account(
        email="linked.person@example.com",
        display_name="Linked Person",
        role="user",
        created_by=admin_api.admin.account_id,
    )
    admin_api.identity.link_visitor(account_id=account.account_id, visitor_id=visitor_id)

    listing = admin_api.client.get(
        "/api/admin/visitors",
        params={"q": "linked.person@example.com"},
        headers=admin_api.admin_headers,
    )
    detail = admin_api.client.get(
        f"/api/admin/visitors/{visitor_id}", headers=admin_api.admin_headers
    )
    missing = admin_api.client.get(
        "/api/admin/visitors/vis_missing", headers=admin_api.admin_headers
    )

    assert listing.status_code == 200
    assert listing.json()["items"][0]["visitor_id"] == visitor_id
    assert listing.json()["items"][0]["linked_account"]["account_id"] == account.account_id
    assert detail.status_code == 200
    assert len(detail.json()["sessions"]) <= 200
    assert len(detail.json()["connections"]) <= 200
    assert detail.json()["linked_account"]["email"] == "linked.person@example.com"
    assert "cookie_hash" not in detail.text
    assert missing.status_code == 404
    event = admin_api.identity.list_audit_events(query="vis_missing")[0]
    assert event["action"] == "visitor.view"
    assert event["outcome"] == "failure"


def test_legacy_usage_metadata_is_recursively_sanitized_on_both_detail_paths(
    admin_api,
):
    visitor_id = admin_api.visitors.ensure_visitor(
        None,
        fingerprint="fp_legacy_metadata",
        client_meta={"browser": "firefox"},
    )
    account = admin_api.identity.create_account(
        email="legacy-metadata@example.com",
        display_name="Legacy Metadata",
        role="user",
        created_by=admin_api.admin.account_id,
    )
    admin_api.identity.link_visitor(account_id=account.account_id, visitor_id=visitor_id)
    leaked_values = {
        "password": "legacy-password-value",
        "token": "legacy-token-value",
        "cookie": "legacy-cookie-value",
        "authorization": "legacy-authorization-value",
        "secret": "legacy-secret-value",
    }
    admin_api.visitors.record_event(
        event_type="legacy_import",
        visitor_id=visitor_id,
        metadata={
            "safe": {
                "Password": leaked_values["password"],
                "nested": [
                    {"AUTHORIZATION": leaked_values["authorization"]},
                    {"safe_note": "preserved"},
                ],
            },
            "access_TOKEN": leaked_values["token"],
            "raw_Cookie_value": leaked_values["cookie"],
            "clientSecret": leaked_values["secret"],
            "research_mode": "fast",
        },
    )

    visitor_response = admin_api.client.get(
        f"/api/admin/visitors/{visitor_id}", headers=admin_api.admin_headers
    )
    account_response = admin_api.client.get(
        f"/api/admin/accounts/{account.account_id}", headers=admin_api.admin_headers
    )

    assert visitor_response.status_code == account_response.status_code == 200
    for response in (visitor_response, account_response):
        serialized = response.text
        assert all(value not in serialized for value in leaked_values.values())
        metadata = (
            response.json()["usage_events"][0]["metadata"]
            if response is visitor_response
            else response.json()["linked_visitors"][0]["usage_events"][0]["metadata"]
        )
        assert metadata["research_mode"] == "fast"
        assert metadata["safe"]["nested"] == [{}, {"safe_note": "preserved"}]
    stored = admin_api.visitors.conn.execute(
        "SELECT metadata_json FROM usage_events WHERE visitor_id=?", (visitor_id,)
    ).fetchone()["metadata_json"]
    assert all(value in stored for value in leaked_values.values())


def test_conversation_view_is_capped_and_audited(admin_api):
    visitor_id = admin_api.visitors.ensure_visitor(
        None, fingerprint="fp_conversation", client_meta={"browser": "other"}
    )
    session_id = admin_api.visitors.ensure_session(
        None, visitor_id, client_meta={"browser": "other"}
    )
    conversation_id = "conversation_admin_view"
    assert admin_api.visitors.claim_or_verify_conversation(
        conversation_id=conversation_id,
        visitor_id=visitor_id,
        session_id=session_id,
        title="Audited conversation",
    )
    for index in range(502):
        admin_api.conversations.append_message(
            conversation_id, role="user", content=f"message {index}"
        )

    response = admin_api.client.get(
        f"/api/admin/visitors/{visitor_id}/conversations/{conversation_id}",
        headers=admin_api.admin_headers,
    )

    assert response.status_code == 200
    assert len(response.json()["messages"]) == 500
    assert response.json()["messages"][0]["content"] == "message 2"
    events = admin_api.client.get(
        "/api/admin/audit",
        params={"q": "conversation.view"},
        headers=admin_api.admin_headers,
    ).json()["items"]
    assert events[0]["target_id"] == conversation_id
    assert events[0]["outcome"] == "success"


def test_invitation_and_audit_lists_are_searchable_and_safe(admin_api):
    account, invitation, raw_token = admin_api.identity.create_account_with_invitation(
        email="invitee@example.com",
        display_name="Invitee",
        role="user",
        created_by=admin_api.admin.account_id,
    )
    response = admin_api.client.get(
        "/api/admin/invitations",
        params={"q": "invitee@example.com"},
        headers=admin_api.admin_headers,
    )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["invitation_id"] == invitation.invitation_id
    assert item["creator"]["account_id"] == admin_api.admin.account_id
    assert item["status"] == "pending"
    assert "token_hash" not in item
    assert raw_token not in response.text

    audit = admin_api.client.get(
        "/api/admin/audit",
        params={"q": account.account_id, "limit": 100, "offset": 0},
        headers=admin_api.owner_headers,
    )
    assert audit.status_code == 200
    assert audit.json()["limit"] == 100
    assert admin_api.client.get(
        "/api/admin/audit", params={"limit": 101}, headers=admin_api.owner_headers
    ).status_code == 422


def test_admin_identity_endpoints_require_authentication(admin_api):
    for path in (
        "/api/admin/accounts",
        "/api/admin/visitors",
        "/api/admin/invitations",
        "/api/admin/audit",
    ):
        assert admin_api.client.get(path).status_code == 401
