from __future__ import annotations

import hashlib
import hmac
from types import SimpleNamespace

import pytest
from fastapi import Request, Response

from api_batch3_routes import ensure_visitor_session
from defend_data.visitor_store import client_ip


def test_connection_persists_full_observation_without_raw_cookie(visitor_store):
    connection_id = visitor_store.record_connection(
        visitor_id="vis_a",
        session_id="vsess_a",
        ip_address="203.0.113.8",
        user_agent="Browser/1 full user agent",
        client_meta={
            "browser": "other",
            "platform": "linux",
            "device": "desktop",
            "language": "en-us",
        },
        cookie_hash="cookie_hmac",
    )

    row = visitor_store.connection_detail(connection_id)

    assert row is not None
    assert row["connection_id"] == connection_id
    assert row["visitor_id"] == "vis_a"
    assert row["session_id"] == "vsess_a"
    assert row["ip_address"] == "203.0.113.8"
    assert row["user_agent"] == "Browser/1 full user agent"
    assert row["browser"] == "other"
    assert row["platform"] == "linux"
    assert row["device"] == "desktop"
    assert row["language"] == "en-us"
    assert row["fingerprint_hmac"].startswith("fp_")
    assert row["cookie_hash"] == "cookie_hmac"
    assert row["observed_at"]
    assert "raw_cookie" not in row


@pytest.mark.parametrize(
    ("trust_cloudflare", "expected"),
    [(False, "203.0.113.8"), (True, "198.51.100.99")],
)
def test_client_ip_uses_cloudflare_only_when_explicitly_trusted(
    trust_cloudflare,
    expected,
):
    assert client_ip(
        {"cf-connecting-ip": "198.51.100.99"},
        "203.0.113.8",
        trust_cloudflare=trust_cloudflare,
    ) == expected


def test_ensure_visitor_session_records_peer_ip_and_keyed_cookie_ids(
    visitor_store,
    monkeypatch,
):
    monkeypatch.setenv("DEFEND_TRUST_CLOUDFLARE", "false")
    raw_auth_cookie = "reusable-account-session-secret"
    app = SimpleNamespace(
        state=SimpleNamespace(
            defend_data=SimpleNamespace(visitors=visitor_store),
        )
    )
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/conversations",
        "headers": [
            (b"user-agent", b"Browser/1 full user agent"),
            (b"accept-language", b"en-US,en;q=0.9"),
            (b"cf-connecting-ip", b"198.51.100.99"),
            (b"cookie", f"defend_account_session={raw_auth_cookie}".encode()),
        ],
        "client": ("203.0.113.8", 43120),
        "app": app,
    }

    visitor_id, session_id = ensure_visitor_session(Request(scope), Response())

    row = dict(visitor_store.conn.execute("SELECT * FROM connection_events").fetchone())
    expected_payload = f"{visitor_id}|{session_id}".encode()
    expected_hash = hmac.new(
        b"test-key-with-at-least-thirty-two-characters",
        expected_payload,
        hashlib.sha256,
    ).hexdigest()
    assert row["ip_address"] == "203.0.113.8"
    assert row["user_agent"] == "Browser/1 full user agent"
    assert row["cookie_hash"] == f"cookie_{expected_hash}"
    assert raw_auth_cookie not in "|".join(str(value) for value in row.values())


def test_purge_connection_history_deletes_only_rows_before_cutoff(visitor_store):
    old_id = visitor_store.record_connection(
        visitor_id="vis_old",
        session_id="vsess_old",
        ip_address="203.0.113.8",
        user_agent="Browser/1",
        client_meta={"browser": "other"},
        cookie_hash="cookie_old",
        observed_at="2026-05-01T00:00:00+00:00",
    )
    cutoff_id = visitor_store.record_connection(
        visitor_id="vis_keep",
        session_id="vsess_keep",
        ip_address="203.0.113.9",
        user_agent="Browser/2",
        client_meta={"browser": "other"},
        cookie_hash="cookie_keep",
        observed_at="2026-05-02T00:00:00+00:00",
    )

    assert visitor_store.purge_connection_history(
        before="2026-05-02T00:00:00+00:00"
    ) == 1
    assert visitor_store.connection_detail(old_id) is None
    assert visitor_store.connection_detail(cutoff_id) is not None
