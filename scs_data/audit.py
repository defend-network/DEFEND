from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
import sqlite3
import uuid
from typing import Any

from defend_data.sqlite_utils import json_dumps, json_loads


_SENSITIVE = re.compile(r"(?:password|pass|secret|token|cookie|authorization|api_key|hash)", re.I)


def _assert_safe(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if _SENSITIVE.search(str(key)):
                raise ValueError("audit metadata contains a sensitive key")
            _assert_safe(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _assert_safe(child)


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    actor_id: str | None
    event_type: str
    target_type: str
    target_id: str | None
    metadata: dict[str, Any]
    occurred_at: str


class ScsAuditStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def append(
        self,
        actor_id: str | None,
        event_type: str,
        target_type: str,
        target_id: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEvent:
        safe_metadata = dict(metadata or {})
        _assert_safe(safe_metadata)
        event = AuditEvent(
            "scs_aud_" + uuid.uuid4().hex,
            actor_id,
            event_type,
            target_type,
            target_id,
            safe_metadata,
            datetime.now(timezone.utc).isoformat(),
        )
        self.conn.execute(
            "INSERT INTO scs_audit_events VALUES (?,?,?,?,?,?,?)",
            (event.event_id, event.actor_id, event.event_type, event.target_type,
             event.target_id, json_dumps(event.metadata), event.occurred_at),
        )
        self.conn.commit()
        return event
