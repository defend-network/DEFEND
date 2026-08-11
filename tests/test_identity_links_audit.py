from __future__ import annotations

from datetime import datetime

import pytest


def _pending_account(identity, owner):
    return identity.create_account(
        email="linked-user@example.com",
        display_name="Linked User",
        role="user",
        created_by=owner.account_id,
    )


def test_link_is_idempotent_and_preserves_the_original_link_time(identity, owner):
    account = _pending_account(identity, owner)

    identity.link_visitor(
        account_id=account.account_id,
        visitor_id="vis_123",
        linked_at="2026-08-10T12:00:00+00:00",
    )
    identity.link_visitor(
        account_id=account.account_id,
        visitor_id="vis_123",
        linked_at="2026-08-10T13:00:00+00:00",
    )

    assert identity.list_linked_visitors(account.account_id) == ["vis_123"]
    row = identity.conn.execute(
        "SELECT linked_at,last_seen_at FROM account_visitor_links"
    ).fetchone()
    assert dict(row) == {
        "linked_at": "2026-08-10T12:00:00+00:00",
        "last_seen_at": "2026-08-10T12:00:00+00:00",
    }


@pytest.mark.parametrize(
    ("field", "payload"),
    [
        ("metadata", {"token": "invite-value"}),
        ("metadata", {"safe": [{"Password": "not-for-audit"}]}),
        ("client_context", {"headers": {"authorization": "test-value"}}),
        ("client_context", {"raw_cookie": "session-value"}),
    ],
)
def test_audit_rejects_secret_keys_recursively(identity, owner, field, payload):
    kwargs = {field: payload}

    with pytest.raises(ValueError, match="sensitive key"):
        identity.record_audit(
            actor_account_id=owner.account_id,
            action="conversation.view",
            target_type="conversation",
            target_id="c1",
            outcome="success",
            **kwargs,
        )

    assert identity.list_audit_events() == []


def test_audit_round_trips_context_and_supports_bounded_search(identity, owner):
    first = identity.record_audit(
        actor_account_id=owner.account_id,
        action="conversation.view",
        target_type="conversation",
        target_id="conversation-47",
        outcome="success",
        request_id="request-47",
        client_context={"ip_address": "203.0.113.8", "browser": "other"},
        metadata={"message_count": 12},
    )
    identity.record_audit(
        actor_account_id=owner.account_id,
        action="account.disable",
        target_type="account",
        target_id="acct_target",
        outcome="failure",
    )

    rows = identity.list_audit_events(query="conversation-47", limit=1, offset=0)
    assert len(rows) == 1
    created_at = rows[0].pop("created_at")
    assert datetime.fromisoformat(created_at).tzinfo is not None
    assert rows == [
        {
            "event_id": first,
            "actor_account_id": owner.account_id,
            "action": "conversation.view",
            "target_type": "conversation",
            "target_id": "conversation-47",
            "outcome": "success",
            "request_id": "request-47",
            "client_context": {
                "ip_address": "203.0.113.8",
                "browser": "other",
            },
            "metadata": {"message_count": 12},
        }
    ]

    with pytest.raises(ValueError, match="limit"):
        identity.list_audit_events(limit=101)
    with pytest.raises(ValueError, match="offset"):
        identity.list_audit_events(offset=-1)


def test_audit_rejects_an_unreasonably_large_payload(identity, owner):
    with pytest.raises(ValueError, match="too large"):
        identity.record_audit(
            actor_account_id=owner.account_id,
            action="visitor.view",
            target_type="visitor",
            target_id="vis_123",
            outcome="success",
            metadata={"notes": "x" * 20_000},
        )

    assert identity.list_audit_events() == []
