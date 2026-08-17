"""Centralized outbound HTTP for provider health probes.

All timeout, retry/backoff, size and sanitization behavior lives here so
individual adapters never invent their own retry loops. Requests are
read-only GETs against well-known provider endpoints; loops are HTTPS-only,
follow no redirects, and cap response sizes.
"""

from __future__ import annotations

import ipaddress
import threading
import time
from dataclasses import dataclass
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from defend_control.redaction import redact_text

_MAX_RESPONSE_BYTES = 64 * 1024
_MAX_TIMEOUT_SECONDS = 60.0
_MAX_RETRIES = 3
_DEFAULT_BACKOFF_SECONDS = 1.0
_CAPACITY = threading.BoundedSemaphore(8)


@dataclass(frozen=True)
class FetchResult:
    ok: bool
    status_code: int | None
    latency_ms: int
    error_type: str | None
    body: str | None = None
    retries: int = 0
    headers: dict[str, str] | None = None


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def _safe_error_type(error: BaseException) -> str:
    name = type(error).__name__
    return name if name.isidentifier() and len(name) <= 64 else "Error"


def _validate_url(url: str) -> None:
    parsed = urlsplit(url)
    scheme = parsed.scheme.casefold()
    if scheme not in {"http", "https"}:
        raise ValueError("unsupported scheme")
    hostname = parsed.hostname
    if hostname is None:
        raise ValueError("hostname required")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("userinfo not allowed")
    if parsed.fragment:
        raise ValueError("fragment not allowed")
    if scheme != "https" and not (
        hostname.rstrip(".").casefold() == "localhost"
        or _is_loopback(hostname)
    ):
        raise ValueError("non-loopback requests must use HTTPS")
    if _is_private(hostname):
        raise ValueError("private network hosts not allowed")


def _is_loopback(hostname: str) -> bool:
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _is_private(hostname: str) -> bool:
    lowered = hostname.rstrip(".").casefold()
    if lowered == "localhost":
        return True
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return (
        address.is_loopback
        or address.is_private
        or address.is_reserved
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
    )


def _request_once(
    url: str,
    headers: dict[str, str] | None,
    timeout_seconds: float,
) -> tuple[int | None, str | None, str, dict[str, str]]:
    """Perform one bounded GET inside the caller's thread."""
    request = Request(url, method="GET", headers=headers or {})
    opener = build_opener(_NoRedirectHandler())
    with opener.open(request, timeout=float(timeout_seconds)) as response:
        raw_status = getattr(response, "status", None)
        status_code = int(raw_status) if raw_status is not None else None
        body = response.read(_MAX_RESPONSE_BYTES).decode("utf-8", errors="replace")
        response_headers = {
            key: value
            for key, value in response.headers.items()
            if key.isascii()
        }
    return status_code, None, body, response_headers


def fetch(
    url: str,
    *,
    timeout_seconds: float = 10.0,
    headers: dict[str, str] | None = None,
    retries: int = 2,
    backoff_seconds: float = _DEFAULT_BACKOFF_SECONDS,
    known_secrets: tuple[str, ...] = (),
) -> FetchResult:
    """Bounded GET with centralized retry/backoff and sanitized errors.

    Retries only on transient network failures (429 and 5xx are not retried
    beyond the single documented policy: 429 maps to RATE_LIMITED by the
    service layer). Error strings are redacted against ``known_secrets``.
    """
    started = time.monotonic()
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not 0 < float(timeout_seconds) <= _MAX_TIMEOUT_SECONDS
    ):
        return FetchResult(False, None, 0, "InvalidTimeout")
    if isinstance(retries, bool) or not isinstance(retries, int) or retries < 0:
        retries = 0
    if retries > _MAX_RETRIES:
        retries = _MAX_RETRIES
    try:
        _validate_url(url)
    except ValueError:
        return FetchResult(False, None, 0, "UnsafeUrl")

    if not _CAPACITY.acquire(blocking=False):
        return FetchResult(False, None, 0, "ProbeCapacityExceeded")

    completed = threading.Event()
    outcome: list[tuple[int | None, str | None, str | None, int, dict[str, str]]] = []

    def run() -> None:
        attempts = retries + 1
        try:
            for attempt in range(attempts):
                try:
                    status_code, error_type, body, response_headers = _request_once(
                        url, headers, timeout_seconds
                    )
                    ok = status_code is not None and 200 <= status_code < 300
                    outcome.append((status_code, None if ok else error_type, body if ok else None, attempt, response_headers))
                    return
                except HTTPError as error:
                    status_code = error.code if isinstance(error.code, int) else None
                    if status_code in (429, 401, 403, 404) or attempt + 1 >= attempts:
                        outcome.append((status_code, None, None, attempt, {}))
                        return
                except Exception as error:
                    error_type = _safe_error_type(error)
                    if attempt + 1 >= attempts:
                        outcome.append((None, error_type, None, attempt, {}))
                        return
                if attempt + 1 < attempts:
                    time.sleep(backoff_seconds * (2**attempt))
            outcome.append((None, "Failed", None, attempts - 1, {}))
        finally:
            completed.set()

    try:
        threading.Thread(
            target=run, daemon=True, name="defend-provider-probe"
        ).start()
    except Exception as error:
        _CAPACITY.release()
        return FetchResult(False, None, 0, _safe_error_type(error))

    elapsed = time.monotonic() - started
    remaining = max(0.0, float(timeout_seconds) - elapsed)
    if not completed.wait(remaining):
        latency_ms = max(0, int((time.monotonic() - started) * 1000))
        _CAPACITY.release()
        return FetchResult(False, None, latency_ms, "TimeoutError")

    _CAPACITY.release()
    status_code, error_type, body, attempts, response_headers = outcome[0]
    latency_ms = max(0, int((time.monotonic() - started) * 1000))
    sanitized = None
    if body is not None:
        sanitized = redact_text(body, known_secrets)
    return FetchResult(
        ok=status_code is not None and 200 <= status_code < 300,
        status_code=status_code,
        latency_ms=latency_ms,
        error_type=error_type,
        body=sanitized,
        retries=attempts,
        headers=response_headers,
    )


def json_body(result: FetchResult):
    """Best-effort JSON parse of a successful fetch body (sanitized)."""
    if not result.ok or not result.body:
        return None
    import json

    try:
        return json.loads(result.body)
    except (ValueError, UnicodeDecodeError):
        return None