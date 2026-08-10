from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from .config import DataPaths
from .sqlite_utils import connect_sqlite, json_dumps, json_loads, transaction


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_fingerprint(namespace: str, subject: str, predicate: str, value: Any) -> str:
    payload = json_dumps({"namespace": namespace, "subject": subject, "predicate": predicate, "value": value})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MemoryProposal:
    proposal_id: str
    namespace: str
    subject: str
    predicate: str
    value: Any
    value_text: str
    confidence: float
    sensitivity: str
    origin: str
    provenance: list[dict[str, Any]]
    status: str
    created_at: str
    fingerprint: str


@dataclass(frozen=True)
class MemoryRecord:
    memory_id: str
    namespace: str
    subject: str
    predicate: str
    value: Any
    value_text: str
    confidence: float
    sensitivity: str
    provenance: list[dict[str, Any]]
    status: str
    created_at: str
    updated_at: str
    valid_from: str | None
    valid_to: str | None
    source_proposal_id: str
    fingerprint: str


class MemoryStore:
    VALID_SENSITIVITY = {"public", "internal", "confidential", "restricted"}
    VALID_ORIGIN = {"model", "user", "system", "import", "admin"}

    def __init__(self, paths: DataPaths):
        self.paths = paths.ensure()
        self.db_path = self.paths.db / "memory.db"
        self.conn = connect_sqlite(self.db_path)
        self._migrate()

    def close(self) -> None:
        self.conn.close()

    def _migrate(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS memory_proposals (
                proposal_id TEXT PRIMARY KEY,
                namespace TEXT NOT NULL,
                subject TEXT NOT NULL,
                predicate TEXT NOT NULL,
                value_json TEXT NOT NULL,
                value_text TEXT NOT NULL,
                confidence REAL NOT NULL,
                sensitivity TEXT NOT NULL,
                origin TEXT NOT NULL,
                provenance_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                reviewed_at TEXT,
                reviewed_by TEXT,
                review_reason TEXT,
                fingerprint TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_memprop_status ON memory_proposals(status);
            CREATE INDEX IF NOT EXISTS idx_memprop_fingerprint ON memory_proposals(fingerprint);
            CREATE TABLE IF NOT EXISTS memories (
                memory_id TEXT PRIMARY KEY,
                namespace TEXT NOT NULL,
                subject TEXT NOT NULL,
                predicate TEXT NOT NULL,
                value_json TEXT NOT NULL,
                value_text TEXT NOT NULL,
                confidence REAL NOT NULL,
                sensitivity TEXT NOT NULL,
                provenance_json TEXT NOT NULL DEFAULT '[]',
                source_proposal_id TEXT NOT NULL REFERENCES memory_proposals(proposal_id),
                supersedes_memory_id TEXT REFERENCES memories(memory_id),
                valid_from TEXT,
                valid_to TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                fingerprint TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_memories_lookup ON memories(namespace,subject,predicate,status);
            CREATE INDEX IF NOT EXISTS idx_memories_fingerprint ON memories(fingerprint,status);
            """
        )
        self.conn.execute("INSERT OR REPLACE INTO schema_meta(key,value) VALUES('schema_version','1')")
        self.conn.commit()

    def create_proposal(self, *, namespace: str, subject: str, predicate: str, value: Any,
                        value_text: str, confidence: float, sensitivity: str, origin: str,
                        provenance: list[dict[str, Any]]) -> MemoryProposal:
        if sensitivity not in self.VALID_SENSITIVITY:
            raise ValueError(f"Invalid sensitivity: {sensitivity}")
        if origin not in self.VALID_ORIGIN:
            raise ValueError(f"Invalid origin: {origin}")
        fingerprint = canonical_fingerprint(namespace, subject, predicate, value)
        proposal_id = f"mprop_{uuid.uuid4().hex}"
        created_at = utc_now()
        self.conn.execute(
            """INSERT INTO memory_proposals(proposal_id,namespace,subject,predicate,value_json,value_text,confidence,sensitivity,origin,provenance_json,status,created_at,fingerprint)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (proposal_id, namespace, subject, predicate, json_dumps(value), value_text, float(confidence),
             sensitivity, origin, json_dumps(provenance), "pending", created_at, fingerprint),
        )
        self.conn.commit()
        return self.get_proposal(proposal_id)

    def get_proposal(self, proposal_id: str) -> MemoryProposal:
        r = self.conn.execute("SELECT * FROM memory_proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
        if r is None:
            raise KeyError(proposal_id)
        return MemoryProposal(r["proposal_id"], r["namespace"], r["subject"], r["predicate"],
                              json_loads(r["value_json"]), r["value_text"], float(r["confidence"]),
                              r["sensitivity"], r["origin"], json_loads(r["provenance_json"], []),
                              r["status"], r["created_at"], r["fingerprint"])

    def find_active_by_fingerprint(self, fingerprint: str) -> MemoryRecord | None:
        r = self.conn.execute(
            "SELECT * FROM memories WHERE fingerprint=? AND status='active' ORDER BY created_at DESC LIMIT 1",
            (fingerprint,),
        ).fetchone()
        return self._memory_from_row(r) if r else None

    def commit_proposal(self, proposal_id: str, *, reviewed_by: str, valid_from: str | None = None,
                        valid_to: str | None = None, supersedes_memory_id: str | None = None) -> MemoryRecord:
        if not reviewed_by.strip():
            raise ValueError("reviewed_by is required")
        with transaction(self.conn, immediate=True):
            p = self.conn.execute("SELECT * FROM memory_proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
            if p is None:
                raise KeyError(proposal_id)
            if p["status"] != "pending":
                raise ValueError(f"Proposal is not pending: {p['status']}")
            existing = self.conn.execute(
                "SELECT * FROM memories WHERE fingerprint=? AND status='active' ORDER BY created_at DESC LIMIT 1",
                (p["fingerprint"],),
            ).fetchone()
            now = utc_now()
            if existing is not None:
                self.conn.execute(
                    """UPDATE memory_proposals SET status='duplicate',reviewed_at=?,reviewed_by=?,review_reason='same committed fingerprint' WHERE proposal_id=?""",
                    (now, reviewed_by, proposal_id),
                )
                return self._memory_from_row(existing)

            memory_id = f"mem_{uuid.uuid4().hex}"
            self.conn.execute(
                """INSERT INTO memories(memory_id,namespace,subject,predicate,value_json,value_text,confidence,sensitivity,provenance_json,source_proposal_id,supersedes_memory_id,valid_from,valid_to,status,created_at,updated_at,fingerprint)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (memory_id, p["namespace"], p["subject"], p["predicate"], p["value_json"], p["value_text"],
                 p["confidence"], p["sensitivity"], p["provenance_json"], proposal_id, supersedes_memory_id,
                 valid_from, valid_to, "active", now, now, p["fingerprint"]),
            )
            self.conn.execute(
                """UPDATE memory_proposals SET status='committed',reviewed_at=?,reviewed_by=?,review_reason='approved' WHERE proposal_id=?""",
                (now, reviewed_by, proposal_id),
            )
            if supersedes_memory_id:
                self.conn.execute("UPDATE memories SET status='superseded',updated_at=? WHERE memory_id=?", (now, supersedes_memory_id))
            row = self.conn.execute("SELECT * FROM memories WHERE memory_id=?", (memory_id,)).fetchone()
            return self._memory_from_row(row)

    def reject_proposal(self, proposal_id: str, *, reviewed_by: str, reason: str) -> None:
        now = utc_now()
        cur = self.conn.execute(
            """UPDATE memory_proposals SET status='rejected',reviewed_at=?,reviewed_by=?,review_reason=? WHERE proposal_id=? AND status='pending'""",
            (now, reviewed_by, reason, proposal_id),
        )
        self.conn.commit()
        if cur.rowcount != 1:
            raise ValueError("Proposal not pending or not found")

    def search(self, query: str, *, namespaces: Iterable[str] | None = None,
               subject: str | None = None, limit: int = 8) -> list[MemoryRecord]:
        params: list[Any] = []
        clauses = ["status='active'"]
        if namespaces is not None:
            ns = list(namespaces)
            # Security invariant: an explicitly empty authorized namespace set
            # means "search nothing", never "search everything".
            if not ns:
                return []
            clauses.append(f"namespace IN ({','.join('?' for _ in ns)})")
            params.extend(ns)
        if subject:
            clauses.append("subject=?")
            params.append(subject)
        rows = self.conn.execute(f"SELECT * FROM memories WHERE {' AND '.join(clauses)}", params).fetchall()
        tokens = [t for t in re.findall(r"[a-z0-9_:\-]+", query.lower()) if len(t) > 1]
        scored: list[tuple[float, MemoryRecord]] = []
        for r in rows:
            mem = self._memory_from_row(r)
            hay = " ".join([mem.namespace, mem.subject, mem.predicate, mem.value_text]).lower()
            score = 0.0
            if query.strip() and query.lower().strip() in hay:
                score += 10.0
            score += sum(1.0 for t in tokens if t in hay)
            score += max(0.0, min(1.0, mem.confidence))
            if not tokens and not query.strip():
                score += 1.0
            if score > 0:
                scored.append((score, mem))
        scored.sort(key=lambda x: (x[0], x[1].updated_at), reverse=True)
        return [m for _, m in scored[:max(1, int(limit))]]


    def list_proposals(self, *, status: str = "pending", limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        allowed = {"pending", "committed", "rejected", "duplicate"}
        if status not in allowed:
            raise ValueError(f"Invalid proposal status: {status}")
        rows = self.conn.execute(
            """SELECT proposal_id,namespace,subject,predicate,value_text,confidence,sensitivity,
                      origin,provenance_json,status,created_at,reviewed_at,reviewed_by,review_reason
               FROM memory_proposals WHERE status=? ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            (status, max(1, min(int(limit), 500)), max(0, int(offset))),
        ).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            item["provenance"] = json_loads(item.pop("provenance_json"), [])
            out.append(item)
        return out

    def stats(self) -> dict[str, int]:
        pending = int(self.conn.execute("SELECT COUNT(*) FROM memory_proposals WHERE status='pending'").fetchone()[0])
        committed = int(self.conn.execute("SELECT COUNT(*) FROM memory_proposals WHERE status='committed'").fetchone()[0])
        rejected = int(self.conn.execute("SELECT COUNT(*) FROM memory_proposals WHERE status='rejected'").fetchone()[0])
        duplicate = int(self.conn.execute("SELECT COUNT(*) FROM memory_proposals WHERE status='duplicate'").fetchone()[0])
        active = int(self.conn.execute("SELECT COUNT(*) FROM memories WHERE status='active'").fetchone()[0])
        superseded = int(self.conn.execute("SELECT COUNT(*) FROM memories WHERE status='superseded'").fetchone()[0])
        return {
            "pending_proposals": pending,
            "committed_proposals": committed,
            "rejected_proposals": rejected,
            "duplicate_proposals": duplicate,
            "active_memories": active,
            "superseded_memories": superseded,
        }

    def _memory_from_row(self, r) -> MemoryRecord:
        return MemoryRecord(r["memory_id"], r["namespace"], r["subject"], r["predicate"],
                            json_loads(r["value_json"]), r["value_text"], float(r["confidence"]),
                            r["sensitivity"], json_loads(r["provenance_json"], []), r["status"],
                            r["created_at"], r["updated_at"], r["valid_from"], r["valid_to"],
                            r["source_proposal_id"], r["fingerprint"])
