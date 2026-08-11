from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import threading
import time
from urllib.error import HTTPError
from urllib.parse import SplitResult, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


_MAX_RESPONSE_BYTES = 64 * 1024
_MAX_TIMEOUT_SECONDS = 60.0
_PROBE_CAPACITY = threading.BoundedSemaphore(8)


@dataclass(frozen=True)
class HealthResult:
    ok: bool
    status_code: int | None
    latency_ms: int
    error_type: str | None


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        request,
        file_pointer,
        code,
        message,
        headers,
        new_url,
    ):
        return None


def _safe_error_type(error: BaseException) -> str:
    name = type(error).__name__
    return name if name.isidentifier() and len(name) <= 64 else "Error"


def _origin(parsed: SplitResult) -> tuple[str, str, int]:
    hostname = parsed.hostname
    if hostname is None:
        raise ValueError("hostname required")
    scheme = parsed.scheme.casefold()
    if scheme not in {"http", "https"}:
        raise ValueError("unsupported scheme")
    port = parsed.port
    if port is None:
        port = 443 if scheme == "https" else 80
    return scheme, hostname.rstrip(".").casefold(), port


def _is_loopback(hostname: str) -> bool:
    if hostname.rstrip(".").casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _url_allowed(url: str, public_origin: str | None) -> bool:
    try:
        parsed = urlsplit(url)
        candidate_origin = _origin(parsed)
    except (TypeError, ValueError):
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    if parsed.fragment:
        return False
    scheme, hostname, _port = candidate_origin
    if _is_loopback(hostname):
        return scheme in {"http", "https"}
    if scheme != "https" or public_origin is None:
        return False
    try:
        configured = urlsplit(public_origin)
        if (
            configured.username is not None
            or configured.password is not None
            or configured.path not in ("", "/")
            or configured.query
            or configured.fragment
        ):
            return False
        return _origin(configured) == candidate_origin and configured.scheme.casefold() == "https"
    except (TypeError, ValueError):
        return False


def probe_http(
    url: str,
    timeout_seconds: float,
    *,
    public_origin: str | None = None,
) -> HealthResult:
    started = time.monotonic()
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not 0 < float(timeout_seconds) <= _MAX_TIMEOUT_SECONDS
    ):
        return HealthResult(False, None, 0, "InvalidTimeout")
    if not _url_allowed(url, public_origin):
        return HealthResult(False, None, 0, "UnsafeUrl")

    if not _PROBE_CAPACITY.acquire(blocking=False):
        return HealthResult(False, None, 0, "ProbeCapacityExceeded")

    completed = threading.Event()
    outcome: list[tuple[bool, int | None, str | None]] = []

    def run_probe() -> None:
        status_code: int | None = None
        try:
            request = Request(
                url, method="GET", headers={"Accept": "application/json"}
            )
            opener = build_opener(_NoRedirectHandler())
            with opener.open(
                request, timeout=float(timeout_seconds)
            ) as response:
                raw_status = getattr(response, "status", None)
                status_code = int(raw_status) if raw_status is not None else None
                response.read(_MAX_RESPONSE_BYTES)
            ok = status_code is not None and 200 <= status_code < 300
            error_type = None
        except HTTPError as error:
            status_code = error.code if isinstance(error.code, int) else None
            ok = False
            error_type = "HTTPError"
        except Exception as error:
            ok = False
            error_type = _safe_error_type(error)
        finally:
            if "ok" in locals():
                outcome.append((ok, status_code, error_type))
            _PROBE_CAPACITY.release()
            completed.set()

    try:
        threading.Thread(
            target=run_probe,
            daemon=True,
            name="defend-health-probe",
        ).start()
    except Exception as error:
        _PROBE_CAPACITY.release()
        return HealthResult(False, None, 0, _safe_error_type(error))

    elapsed = time.monotonic() - started
    remaining = max(0.0, float(timeout_seconds) - elapsed)
    if not completed.wait(remaining):
        latency_ms = max(0, int((time.monotonic() - started) * 1000))
        return HealthResult(False, None, latency_ms, "TimeoutError")

    ok, status_code, error_type = outcome[0]

    latency_ms = max(0, int((time.monotonic() - started) * 1000))
    return HealthResult(ok, status_code, latency_ms, error_type)
