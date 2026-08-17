from __future__ import annotations

import io
import time
from urllib.error import HTTPError

import pytest

import defend_integrations.http as http_module
from defend_integrations.http import fetch


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200, headers=None):
        self.body = body
        self.status = status
        self.headers = headers or {"content-type": "application/json"}

    def read(self, limit: int = -1) -> bytes:
        if limit == -1:
            return self.body
        return self.body[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class FakeOpener:
    def __init__(self, outcome):
        self._outcome = outcome
        self.calls = 0

    def open(self, request, timeout=None):
        self.calls += 1
        outcome = self._outcome
        if callable(outcome):
            outcome = outcome(self.calls)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make_opener(outcome):
    opener = FakeOpener(outcome)
    http_module.build_opener = lambda *args, **kwargs: opener
    return opener


def test_fetch_success_parses_and_sanitizes(monkeypatch):
    body = b'{"status": "ok", "token": "hf_super-secret-value"}'
    opener = make_opener(FakeResponse(body))
    result = fetch(
        "https://api.example.test/v1/status",
        known_secrets=("hf_super-secret-value",),
    )
    assert result.ok is True
    assert result.status_code == 200
    assert result.retries == 0
    assert "hf_super-secret-value" not in (result.body or "")
    assert '"ok"' in (result.body or "")
    assert opener.calls == 1


def test_fetch_retries_transient_five_hundred_then_succeeds(monkeypatch):
    calls = {"count": 0}

    def flaky(_call):
        calls["count"] += 1
        if calls["count"] <= 2:
            return HTTPError(
                "https://api.example.test/", 500, "boom", {}, io.BytesIO(b"")
            )
        return FakeResponse(b'{"ok": true}')

    make_opener(flaky)
    result = fetch(
        "https://api.example.test/v1/x",
        retries=3,
        backoff_seconds=0.01,
    )
    assert result.ok is True
    assert result.retries == 2


def test_fetch_does_not_retry_429_401_or_403(monkeypatch):
    for status in (429, 401, 403):
        opener = make_opener(
            HTTPError(
                "https://api.example.test/", status, "denied", {}, io.BytesIO(b"")
            )
        )
        result = fetch("https://api.example.test/v1/x", retries=3)
        assert result.ok is False
        assert result.status_code == status
        assert result.retries == 0
        assert opener.calls == 1


def test_fetch_returns_error_type_when_unreachable(monkeypatch):
    def error(_call):
        raise TimeoutError("read timed out")

    make_opener(error)
    result = fetch("https://api.example.test/v1/x", timeout_seconds=5)
    assert result.ok is False
    assert result.status_code is None
    assert result.error_type == "TimeoutError"


def test_fetch_rejects_unsafe_urls(monkeypatch):
    for url in (
        "http://example.test/x",  # plain http to a public host
        "https://127.0.0.1/x",  # loopback/private
        "https://localhost/x",
        "https://user:pass@example.test/x",
        "https://example.test/x#fragment",
    ):
        result = fetch(url)
        assert result.ok is False
        assert result.error_type == "UnsafeUrl"


def test_fetch_timeout_bounds_latency(monkeypatch):
    def slow(_call):
        time.sleep(3)
        return FakeResponse(b"{}")

    make_opener(slow)
    started = time.monotonic()
    result = fetch("https://api.example.test/v1/x", timeout_seconds=0.5)
    elapsed = time.monotonic() - started
    assert result.ok is False
    assert result.error_type == "TimeoutError"
    assert elapsed < 2.0
    assert 0 <= result.latency_ms < 2000


def test_fetch_captures_quota_headers(monkeypatch):
    make_opener(
        FakeResponse(
            b'[]',
            headers={
                "x-requests-remaining": "87",
                "x-requests-last": "2026-08-18T00:00:00Z",
            },
        )
    )
    result = fetch("https://api.the-odds-api.test/v4/sports/")
    assert result.ok is True
    assert result.headers["x-requests-remaining"] == "87"


def test_fetch_rejects_invalid_timeout():
    result = fetch("https://api.example.test/", timeout_seconds=0)
    assert result.ok is False
    assert result.error_type == "InvalidTimeout"


def test_fetch_never_retries_more_than_cap(monkeypatch):
    def always_error(_call):
        return HTTPError(
            "https://api.example.test/", 500, "boom", {}, io.BytesIO(b"")
        )

    opener = make_opener(always_error)
    result = fetch(
        "https://api.example.test/v1/x",
        retries=99,
        backoff_seconds=0.001,
    )
    assert result.ok is False
    assert opener.calls == 1 + 3  # capped at three retries
    assert result.retries == 3


def test_http_module_redaction_is_utf8_bounded():
    from defend_control.redaction import redact_text

    cleaned = redact_text("secret a+b? " + "é" * 70_000, ["a+b?"])
    assert "a+b?" not in cleaned
    assert len(cleaned.encode("utf-8")) <= 16 * 1024


def test_fetch_default_timeout_is_bounded(monkeypatch):
    from defend_integrations.http import _MAX_TIMEOUT_SECONDS

    assert _MAX_TIMEOUT_SECONDS <= 60.0
    result = fetch("https://api.example.test/", timeout_seconds=9999)
    assert result.ok is False
    assert result.error_type == "InvalidTimeout"


@pytest.mark.parametrize("bad_retries", [True, -1, "2", 3.5])
def test_fetch_normalizes_bad_retry_values(monkeypatch, bad_retries):
    opener = make_opener(FakeResponse(b'{}'))
    result = fetch("https://api.example.test/", retries=bad_retries)
    assert result.ok is True
    assert opener.calls >= 1