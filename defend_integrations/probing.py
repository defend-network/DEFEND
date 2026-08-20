"""Phase C probe machinery: bounded probing, sanitized evidence capture,
error classification, quota capture, and the canonical normalization boundary.

Layering (P3):
  RAW PROVIDER EVIDENCE  -> :class:`RawEvidence` (sanitized, immutable, sha256)
  CANONICAL OBSERVATION  -> :class:`CanonicalObservation` (full provenance)
  DERIVED ARTIFACT       -> value matrix / research artifacts (elsewhere)

All outbound HTTP goes through :func:`defend_integrations.http.fetch` so
timeout/retry/sanitization policy stays centralized. Error bodies are captured
(sanitized) so structured business errors (OddsPapi NOT_FOUND /
TOO_MANY_BOOKMAKERS, ...) classify exactly instead of as generic failures.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from defend_control.redaction import redact_text

from .http import FetchResult, fetch

_PLAN_MARKERS = ("plan", "upgrade", "subscription", "tier")
_MAX_EVIDENCE_DIRS = 100_000
_DEFAULT_PROBE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; DEFEND/1.0)",
    "Accept": "application/json",
}


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def classify_error(status_code: int | None, body: str | None) -> str:
    """Map an HTTP outcome onto the Phase C error taxonomy.

    ``not_found`` covers both HTTP 404 and structured business 404s (e.g.
    OddsPapi's ``{"error":{"code":"NOT_FOUND",...}}`` for fixtures without
    historical data) - both are deterministic "data absent" signals.
    """
    if status_code is None:
        return "unavailable"
    if status_code == 429:
        return "rate_limited"
    if status_code in (401, 403):
        text = (body or "").lower()
        if any(marker in text for marker in _PLAN_MARKERS):
            return "plan_required"
        return "auth_failed"
    if 400 <= status_code < 500:
        text = (body or "").upper()
        if "NOT_FOUND" in text or "NO HISTORICAL" in text:
            return "not_found"
        if "TOO_MANY_BOOKMAKERS" in text or "TOO MANY" in text:
            return "validation"
        if status_code == 404:
            return "not_found"
        return "validation"
    return "unavailable"


@dataclass(frozen=True)
class RawEvidence:
    """One sanitized, immutable provider response (RAW PROVIDER EVIDENCE).

    ``body`` is redacted against the credentials used for the call and the
    URL is stored without any secret query values. Never write a raw secret
    into this record.
    """

    provider_id: str
    endpoint: str
    status_code: int | None
    latency_ms: int
    retrieved_at: str
    url_sanitized: str
    body: str | None
    body_sha256: str | None
    headers_kept: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "endpoint": self.endpoint,
            "status_code": self.status_code,
            "latency_ms": self.latency_ms,
            "retrieved_at": self.retrieved_at,
            "url_sanitized": self.url_sanitized,
            "body": self.body,
            "body_sha256": self.body_sha256,
            "headers_kept": dict(self.headers_kept),
        }

    def save(self, evidence_dir: Path) -> Path:
        """Write one immutable evidence file and return its path (the ref)."""
        evidence_dir.mkdir(parents=True, exist_ok=True)
        name = (
            f"{self.provider_id}-{self.endpoint}-{self.retrieved_at}"
            .replace(":", "").replace("+", "")
        )
        path = evidence_dir / f"{name}.json"
        if path.exists():
            return path
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path


@dataclass(frozen=True)
class CanonicalObservation:
    """A normalized market observation with full provenance (P3).

    Every observation retains enough provenance to recover provider,
    event, bookmaker, market, outcome, the raw evidence file, the
    observation timestamp (when the provider stamped it), the commence
    timestamp (when known), and the ingestion timestamp.
    """

    provider: str
    provider_event_id: str
    provider_bookmaker: str
    provider_market_id: str
    provider_outcome_id: str
    raw_evidence_ref: str
    observed_at: str | None
    commence_at: str | None
    ingested_at: str
    price: float | None = None
    active: bool | None = None
    participant_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "provider_event_id": self.provider_event_id,
            "provider_bookmaker": self.provider_bookmaker,
            "provider_market_id": self.provider_market_id,
            "provider_outcome_id": self.provider_outcome_id,
            "raw_evidence_ref": self.raw_evidence_ref,
            "observed_at": self.observed_at,
            "commence_at": self.commence_at,
            "ingested_at": self.ingested_at,
            "price": self.price,
            "active": self.active,
            "participant_key": self.participant_key,
        }


def capture_quota(
    headers: dict[str, str] | None,
    header_names: tuple[str, ...],
    body: Any = None,
    body_path: str | None = None,
) -> tuple[int | None, str | None]:
    """Best-effort quota capture from headers and/or a JSON body path."""
    remaining: int | None = None
    reset_at: str | None = None
    if headers:
        for name in header_names:
            raw = headers.get(name)
            if isinstance(raw, str) and raw.strip().lstrip("-").isdigit():
                remaining = int(raw.strip())
                break
    if remaining is None and body_path and isinstance(body, dict):
        node: Any = body
        for part in body_path.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if isinstance(node, dict):
            for key in ("remaining_quota", "remaining", "calls_left", "quota_left"):
                value = node.get(key)
                if isinstance(value, bool):
                    continue
                if isinstance(value, int):
                    remaining = value
                    break
                if isinstance(value, str) and value.strip().lstrip("-").isdigit():
                    remaining = int(value.strip())
                    break
            for key in ("quota_reset_at", "reset_at", "resets_at", "quota_reset"):
                value = node.get(key)
                if isinstance(value, str):
                    reset_at = value
                    break
    if headers and reset_at is None:
        reset_at = headers.get("x-ratelimit-reset") or headers.get(
            "ratelimit-reset"
        )
    return remaining, reset_at


class ProbeBudget:
    """Per-provider request budget (hard cap enforcement)."""

    def __init__(self, provider_id: str, cap: int) -> None:
        self.provider_id = provider_id
        self.cap = cap
        self.used = 0

    @property
    def remaining(self) -> int:
        return max(0, self.cap - self.used)

    def take(self, count: int = 1) -> bool:
        if self.used + count > self.cap:
            return False
        self.used += count
        return True


def probe_get(
    provider_id: str,
    endpoint: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    known_secrets: tuple[str, ...] = (),
    quota_headers: tuple[str, ...] = (),
    timeout_seconds: float = 25.0,
) -> tuple[FetchResult, RawEvidence, Any]:
    """One Phase C GET: fetch -> sanitized evidence -> parsed body (if JSON)."""
    request_headers = dict(_DEFAULT_PROBE_HEADERS)
    if headers:
        request_headers.update(headers)
    result = fetch(
        url,
        timeout_seconds=timeout_seconds,
        headers=request_headers,
        retries=1,
        backoff_seconds=1.0,
        known_secrets=known_secrets,
        capture_error_body=True,
    )
    body = result.body
    if body is not None:
        body = redact_text(body, known_secrets)
    parsed: Any = None
    if body:
        try:
            parsed = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            parsed = None
    kept_headers = {
        key: value
        for key, value in (result.headers or {}).items()
        if key.lower() in quota_headers
        or key.lower() in ("content-type", "etag", "cache-control")
    }
    evidence = RawEvidence(
        provider_id=provider_id,
        endpoint=endpoint,
        status_code=result.status_code,
        latency_ms=result.latency_ms,
        retrieved_at=utc_now_iso(),
        url_sanitized=redact_text(url, known_secrets),
        body=body,
        body_sha256=sha256_text(body) if body is not None else None,
        headers_kept=kept_headers,
    )
    return result, evidence, parsed