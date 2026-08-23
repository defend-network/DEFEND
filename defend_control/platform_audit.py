"""Neutral, redacted platform audit log (Section 27).

Owner-facing audit for neutral/platform events only: product process launched,
product stopped, credential configured, credential verification attempted,
manifest collision, health transition, platform setting changed. Secrets,
model private reasoning, customer content and member conversations are NEVER
recorded here.

Persistence is best-effort JSON under %LOCALAPPDATA%\\DEFEND; failures degrade
to in-memory only. All recorded text is redacted against known secrets using
the shared :mod:`defend_control.redaction` primitive.
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Any

from shared_platform.redaction import redact_text

_DEFAULT_MAX_ENTRIES = 2000
_MAX_LINE_CHARS = 512


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


# Canonical neutral event vocabulary.
EVENT_PRODUCT_LAUNCHED = "product_launched"
EVENT_PRODUCT_STOPPED = "product_stopped"
EVENT_CREDENTIAL_CONFIGURED = "credential_configured"
EVENT_CREDENTIAL_VERIFY_ATTEMPTED = "credential_verification_attempted"
EVENT_MANIFEST_COLLISION = "manifest_collision"
EVENT_HEALTH_TRANSITION = "health_transition"
EVENT_PLATFORM_SETTING_CHANGED = "platform_setting_changed"

EVENT_TYPES = frozenset(
    {
        EVENT_PRODUCT_LAUNCHED,
        EVENT_PRODUCT_STOPPED,
        EVENT_CREDENTIAL_CONFIGURED,
        EVENT_CREDENTIAL_VERIFY_ATTEMPTED,
        EVENT_MANIFEST_COLLISION,
        EVENT_HEALTH_TRANSITION,
        EVENT_PLATFORM_SETTING_CHANGED,
    }
)


@dataclass(frozen=True)
class PlatformAuditEntry:
    event_type: str
    occurred_at: str
    product_id: str | None = None
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PlatformAuditLog:
    """Thread-safe, redacted, bounded audit log with best-effort persistence."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        max_entries: int = _DEFAULT_MAX_ENTRIES,
        known_secrets: tuple[str, ...] = (),
        clock=_utc_now_iso,
    ) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self._path = path or default_audit_path()
        self._known_secrets = {
            value for value in known_secrets if isinstance(value, str) and value
        }
        self._clock = clock
        self._entries: deque[PlatformAuditEntry] = deque(maxlen=int(max_entries))
        self._lock = threading.Lock()
        self._restore()

    @staticmethod
    def _safe_detail(value: str) -> str:
        return str(value).replace("\r", "\\r").replace("\n", "\\n")

    def add_known_secrets(self, values: tuple[str, ...]) -> None:
        with self._lock:
            self._known_secrets.update(
                value for value in values if isinstance(value, str) and value
            )

    def record(
        self,
        event_type: str,
        *,
        product_id: str | None = None,
        detail: str | None = None,
    ) -> PlatformAuditEntry:
        if event_type not in EVENT_TYPES:
            raise ValueError(f"unknown platform audit event: {event_type}")
        safe = self._safe_detail(detail) if detail is not None else None
        with self._lock:
            cleaned = redact_text(safe, tuple(self._known_secrets)) if safe else None
            if cleaned is not None and len(cleaned) > _MAX_LINE_CHARS:
                cleaned = cleaned[:_MAX_LINE_CHARS]
            entry = PlatformAuditEntry(
                event_type=event_type,
                occurred_at=self._clock(),
                product_id=product_id,
                detail=cleaned,
            )
            self._entries.append(entry)
            try:
                self._persist(entry)
            except Exception:
                pass
            return entry

    def snapshot(self) -> tuple[PlatformAuditEntry, ...]:
        with self._lock:
            return tuple(self._entries)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entries": [entry.to_dict() for entry in self.snapshot()],
        }

    # ------------------------------------------------------------- persistence

    def _persist(self, entry: PlatformAuditEntry) -> None:
        existing: list[dict[str, Any]] = []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("entries"), list):
                existing = [
                    item for item in raw["entries"] if isinstance(item, dict)
                ]
        except (OSError, ValueError):
            existing = []
        existing.append(entry.to_dict())
        self._path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self._path.parent,
            prefix=f".{self._path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(
                    {"entries": existing}, handle, indent=2, sort_keys=True
                )
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self._path)
        finally:
            temporary_path.unlink(missing_ok=True)

    def _restore(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict) or not isinstance(raw.get("entries"), list):
            return
        for item in raw["entries"]:
            if not isinstance(item, dict):
                continue
            event_type = item.get("event_type")
            if event_type not in EVENT_TYPES:
                continue
            detail = (
                str(item["detail"]) if item.get("detail") is not None else None
            )
            if detail is not None:
                detail = redact_text(detail, tuple(self._known_secrets))
            self._entries.append(
                PlatformAuditEntry(
                    event_type=event_type,
                    occurred_at=str(item.get("occurred_at") or ""),
                    product_id=(
                        str(item["product_id"])
                        if item.get("product_id") is not None
                        else None
                    ),
                    detail=detail,
                )
            )


def default_audit_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) / "DEFEND" if local_app_data else Path.cwd()
    return base / "platform-audit.json"
