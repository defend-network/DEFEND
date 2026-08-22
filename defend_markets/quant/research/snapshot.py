"""Immutable research dataset snapshots with point-in-time safety.

A snapshot is a content-addressed, immutable view over a deterministic set of
training rows. Experiments reference a snapshot id and never train against
"whatever is in the DB today". Snapshot creation rejects future rows relative
to its cutoff.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class DatasetSnapshot:
    snapshot_id: str
    created_at: str
    cutoff: str
    target_definition: str
    source_query_version: int
    feature_schema_version: int
    row_count: int
    event_count: int
    player_count: int
    date_min: str
    date_max: str
    content_hash: str
    excluded_row_counts: Mapping[str, int] = field(default_factory=dict)
    leakage_checks: Mapping[str, Any] = field(default_factory=dict)
    provenance: Mapping[str, Any] = field(default_factory=dict)
    rows: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)

    def to_dict(self, *, include_rows: bool = False) -> dict[str, Any]:
        document = {
            "snapshot_id": self.snapshot_id,
            "created_at": self.created_at,
            "cutoff": self.cutoff,
            "target_definition": self.target_definition,
            "source_query_version": self.source_query_version,
            "feature_schema_version": self.feature_schema_version,
            "row_count": self.row_count,
            "event_count": self.event_count,
            "player_count": self.player_count,
            "date_min": self.date_min,
            "date_max": self.date_max,
            "content_hash": self.content_hash,
            "excluded_row_counts": dict(self.excluded_row_counts),
            "leakage_checks": dict(self.leakage_checks),
            "provenance": dict(self.provenance),
        }
        if include_rows:
            document["rows"] = list(self.rows)
        return document


def _row_signature(row: Mapping[str, Any]) -> str:
    return json.dumps(
        {
            "event_key": str(row.get("event_key") or ""),
            "home_key": str(row.get("home_key") or ""),
            "away_key": str(row.get("away_key") or ""),
            "ts": str(row.get("ts") or ""),
            "actual": float(row.get("actual") or 0.0),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def build_snapshot(
    rows: Iterable[Mapping[str, Any]],
    *,
    cutoff: str,
    target_definition: str,
    source_query_version: int = 1,
    feature_schema_version: int = 1,
    provenance: Mapping[str, Any] | None = None,
    created_at: str | None = None,
) -> DatasetSnapshot:
    cutoff_dt = datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
    rows = [dict(row) for row in rows]
    for row in rows:
        ts = row.get("ts")
        if isinstance(ts, datetime):
            row["ts"] = ts.isoformat()
        elif not isinstance(ts, str):
            raise ValueError("snapshot rows require an ISO ts string")

    excluded = {"after_cutoff": 0, "draw": 0, "missing_participant": 0}
    accepted: list[Mapping[str, Any]] = []
    players: set[str] = set()
    for row in rows:
        row_ts = datetime.fromisoformat(str(row["ts"]).replace("Z", "+00:00"))
        if row_ts >= cutoff_dt:
            excluded["after_cutoff"] += 1
            continue
        home = str(row.get("home_key") or "")
        away = str(row.get("away_key") or "")
        actual = row.get("actual")
        if not home or not away:
            excluded["missing_participant"] += 1
            continue
        if actual is None:
            excluded["draw"] += 1
            continue
        players.update((home, away))
        accepted.append(row)

    accepted.sort(key=lambda row: (row["ts"], row["event_key"]))
    signatures = "".join(_row_signature(row) for row in accepted)
    content_hash = _sha256_text(signatures)
    snapshot_id = _sha256_text(
        json.dumps(
            {
                "cutoff": cutoff,
                "target_definition": target_definition,
                "source_query_version": source_query_version,
                "feature_schema_version": feature_schema_version,
                "content_hash": content_hash,
            },
            sort_keys=True,
        )
    )
    timestamps = [datetime.fromisoformat(str(row["ts"]).replace("Z", "+00:00")) for row in accepted]
    leakage_checks = {
        "accepted_rows_after_cutoff": 0,
        "excluded_rows_after_cutoff": excluded["after_cutoff"],
        "leakage_detected": False,
    }
    return DatasetSnapshot(
        snapshot_id=snapshot_id,
        created_at=created_at or utc_now_iso(),
        cutoff=cutoff,
        target_definition=target_definition,
        source_query_version=source_query_version,
        feature_schema_version=feature_schema_version,
        row_count=len(accepted),
        event_count=len({row["event_key"] for row in accepted}),
        player_count=len(players),
        date_min=min(timestamps).isoformat() if timestamps else "",
        date_max=max(timestamps).isoformat() if timestamps else "",
        content_hash=content_hash,
        excluded_row_counts=excluded,
        leakage_checks=leakage_checks,
        provenance=dict(provenance or {}),
        rows=tuple(accepted),
    )
