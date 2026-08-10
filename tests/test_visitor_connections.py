from __future__ import annotations

import hashlib
import hmac
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi import Request, Response

from api_batch3_routes import ensure_visitor_session
from defend_data.visitor_store import VisitorStore, client_ip


def test_shared_visitor_store_serializes_parallel_observation_writes(visitor_store):
    worker_count = 16
    start = threading.Barrier(worker_count)

    def observe(index: int) -> None:
        meta = {
            "browser": "other",
            "platform": "linux",
            "device": "desktop",
            "language": "en-us",
        }
        start.wait()
        visitor_id = visitor_store.ensure_visitor(
            None,
            fingerprint=f"fp_parallel_{index}",
            client_meta=meta,
        )
        session_id = visitor_store.ensure_session(
            None,
            visitor_id,
            client_meta=meta,
        )
        visitor_store.record_connection(
            visitor_id=visitor_id,
            session_id=session_id,
            ip_address=f"203.0.113.{index + 1}",
            user_agent=f"ParallelBrowser/{index}",
            client_meta=meta,
            cookie_hash=f"cookie_parallel_{index}",
        )
        visitor_store.record_event(
            event_type="parallel_observation",
            visitor_id=visitor_id,
            metadata={"worker": index},
        )

    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = [pool.submit(observe, index) for index in range(worker_count)]
        for future in futures:
            future.result()

    overview = visitor_store.overview()
    assert overview["visitors"] == worker_count
    assert overview["sessions"] == worker_count
    assert overview["usage_events"] == worker_count
    assert visitor_store.conn.execute(
        "SELECT COUNT(*) FROM connection_events"
    ).fetchone()[0] == worker_count


def test_conversation_existence_is_checked_through_the_serialized_store(visitor_store):
    visitor_id = visitor_store.ensure_visitor(
        None,
        fingerprint="fp_conversation_exists",
        client_meta={"browser": "other"},
    )
    session_id = visitor_store.ensure_session(
        None, visitor_id, client_meta={"browser": "other"}
    )
    assert visitor_store.claim_or_verify_conversation(
        conversation_id="conversation_exists",
        visitor_id=visitor_id,
        session_id=session_id,
    )

    assert visitor_store.conversation_exists("conversation_exists")
    assert not visitor_store.conversation_exists("conversation_missing")


def test_newer_visitor_schema_is_rejected(data_paths):
    with sqlite3.connect(data_paths.db / "visitors.db") as conn:
        conn.executescript(
            """
            CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO schema_meta(key,value) VALUES('schema_version','99');
            """
        )

    with pytest.raises(RuntimeError, match="newer visitor schema version 99"):
        VisitorStore(data_paths)


def test_current_visitor_schema_is_not_rewritten(data_paths, monkeypatch):
    monkeypatch.setenv(
        "DEFEND_VISITOR_HMAC_KEY",
        "test-key-with-at-least-thirty-two-characters",
    )
    VisitorStore(data_paths).close()
    with sqlite3.connect(data_paths.db / "visitors.db") as conn:
        conn.executescript(
            """
            CREATE TRIGGER schema_meta_no_insert
            BEFORE INSERT ON schema_meta
            BEGIN SELECT RAISE(ABORT, 'schema version is immutable'); END;
            CREATE TRIGGER schema_meta_no_update
            BEFORE UPDATE ON schema_meta
            BEGIN SELECT RAISE(ABORT, 'schema version is immutable'); END;
            CREATE TRIGGER schema_meta_no_delete
            BEFORE DELETE ON schema_meta
            BEGIN SELECT RAISE(ABORT, 'schema version is immutable'); END;
            """
        )

    VisitorStore(data_paths).close()


def test_failed_visitor_v1_migration_rolls_back_schema_changes(data_paths, monkeypatch):
    monkeypatch.setenv(
        "DEFEND_VISITOR_HMAC_KEY",
        "test-key-with-at-least-thirty-two-characters",
    )
    VisitorStore(data_paths).close()
    with sqlite3.connect(data_paths.db / "visitors.db") as conn:
        conn.executescript(
            """
            DROP INDEX idx_connection_events_visitor;
            DROP INDEX idx_connection_events_session;
            DROP INDEX idx_connection_events_ip;
            DROP INDEX idx_connection_events_observed;
            DROP TABLE connection_events;
            UPDATE schema_meta SET value='1' WHERE key='schema_version';
            CREATE TRIGGER schema_meta_block_insert
            BEFORE INSERT ON schema_meta
            BEGIN SELECT RAISE(ABORT, 'migration failure'); END;
            CREATE TRIGGER schema_meta_block_update
            BEFORE UPDATE ON schema_meta
            BEGIN SELECT RAISE(ABORT, 'migration failure'); END;
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="migration failure"):
        VisitorStore(data_paths)

    with sqlite3.connect(data_paths.db / "visitors.db") as conn:
        version = conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()[0]
        connection_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='connection_events'"
        ).fetchone()
    assert version == "1"
    assert connection_table is None


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


@pytest.mark.parametrize(
    ("configured_value", "expected_ip"),
    [
        ("true", "198.51.100.99"),
        ("TRUE", "198.51.100.99"),
        ("1", "203.0.113.8"),
        ("yes", "203.0.113.8"),
        ("on", "203.0.113.8"),
    ],
)
def test_request_path_trusts_cloudflare_only_for_literal_true(
    visitor_store,
    monkeypatch,
    configured_value,
    expected_ip,
):
    monkeypatch.setenv("DEFEND_TRUST_CLOUDFLARE", configured_value)
    app = SimpleNamespace(
        state=SimpleNamespace(
            defend_data=SimpleNamespace(visitors=visitor_store),
        )
    )
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/conversations",
        "headers": [(b"cf-connecting-ip", b"198.51.100.99")],
        "client": ("203.0.113.8", 43120),
        "app": app,
    }

    ensure_visitor_session(Request(scope), Response())

    row = visitor_store.conn.execute(
        "SELECT ip_address FROM connection_events"
    ).fetchone()
    assert row["ip_address"] == expected_ip


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
