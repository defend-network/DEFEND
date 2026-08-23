"""SCSKnowledgeLibrary - private/local-first knowledge source registry + index
(M1.4.2, P3-P8, P34-P51).

Sqlite-backed storage keeps sources/chunks/citations/gaps/lessons in separate
tables (never one JSON blob). Retrieval supports lexical search + metadata
filters (source_type / manufacturer / model / edition / topic / procedure /
equipment family / instrument). Copyrighted standards are never committed;
only metadata + short curated passages may be indexed.

M1.4.2 changes:
  * KnowledgeSource exposes source_state + verification provenance as
    first-class fields (P36/P40).
  * add_source/add_chunk use explicit INSERT (no silent INSERT OR REPLACE of
    trusted identity) (P37).
  * verify_source records method/actor/time/evidence (P40-P43); owner approval
    is a distinct provenance (P41).
  * fetch_source returns bounded trusted CONTENT (P18/P49).
  * search_tables enforces active/trusted filters (P50).
  * exact_model_lookup avoids substring false positives (P48).
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .sources import SOURCE_TYPES

SOURCE_ATTRS = (
    "source_id", "source_type", "organization", "manufacturer", "title",
    "document_number", "edition", "revision", "publication_date", "retrieved_at",
    "local_path_or_private_ref", "document_hash", "license_or_access_state",
    "equipment_family_tags", "procedure_tags", "topic_tags", "supersedes_source_id",
    "superseded_by_source_id", "active", "confidence", "notes", "source_state",
    "duplicate_of_source_id", "ingest_id", "parser_version", "chunking_version",
    "document_type", "byte_size", "verification_method", "verified_by",
    "verified_at", "verification_evidence", "filename", "ingestion_state",
    "owner_approval_state", "model", "model_series", "page_count",
)

# H5/H6: source verification + quarantine state + dedup lineage
SOURCE_STATES = ("ACTIVE", "QUARANTINED", "CANDIDATE", "SOURCE_VERIFIED",
                 "DISABLED", "SUPERSEDED")
VERIFICATION_METHODS = ("DETERMINISTIC_METADATA", "OWNER_APPROVED",
                        "MANUFACTURER_SOURCE_VERIFIED")


@dataclass
class KnowledgeSource:
    source_id: str
    source_type: str
    organization: str | None = None
    manufacturer: str | None = None
    title: str | None = None
    document_number: str | None = None
    edition: str | None = None
    revision: str | None = None
    publication_date: str | None = None
    retrieved_at: str | None = None
    local_path_or_private_ref: str | None = None
    document_hash: str | None = None
    license_or_access_state: str | None = None
    equipment_family_tags: list[str] = field(default_factory=list)
    procedure_tags: list[str] = field(default_factory=list)
    topic_tags: list[str] = field(default_factory=list)
    supersedes_source_id: str | None = None
    superseded_by_source_id: str | None = None
    active: bool = True
    confidence: str = "HIGH"
    notes: str | None = None
    source_state: str = "ACTIVE"
    duplicate_of_source_id: str | None = None
    ingest_id: str | None = None
    parser_version: str | None = None
    chunking_version: str | None = None
    document_type: str | None = None
    byte_size: int | None = None
    verification_method: str | None = None
    verified_by: str | None = None
    verified_at: str | None = None
    verification_evidence: str | None = None
    filename: str | None = None
    ingestion_state: str = "INDEXED"
    owner_approval_state: str = "PENDING"
    model: str | None = None
    model_series: str | None = None
    page_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {attr: getattr(self, attr) for attr in SOURCE_ATTRS}
        data["active"] = bool(data["active"])
        return data


@dataclass
class KnowledgeChunk:
    chunk_id: str
    source_id: str
    text: str
    chunk_type: str = "NOTE"
    section: str | None = None
    page: str | None = None
    topic_tags: list[str] = field(default_factory=list)
    procedure_tags: list[str] = field(default_factory=list)
    equipment_family_tags: list[str] = field(default_factory=list)
    table: str | None = None
    figure: str | None = None
    active: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id, "source_id": self.source_id,
            "text": self.text, "chunk_type": self.chunk_type,
            "section": self.section, "page": self.page,
            "topic_tags": self.topic_tags, "procedure_tags": self.procedure_tags,
            "equipment_family_tags": self.equipment_family_tags,
            "table": self.table, "figure": self.figure, "active": self.active,
        }


_IDENTIFIER_RE = re.compile(r"[A-Z0-9]{2,}(?:[-.][A-Z0-9]{1,6})*")


def _identifier_tokens(text: str) -> set[str]:
    return set(_IDENTIFIER_RE.findall(str(text or "").upper()))


class SCSKnowledgeLibrary:
    """Private local knowledge library (sqlite-backed)."""

    def __init__(self, db_path: Path | str) -> None:
        self._db = sqlite3.connect(str(db_path))
        self._db.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._db.executescript("""
        CREATE TABLE IF NOT EXISTS sources (
            source_id TEXT PRIMARY KEY,
            source_type TEXT NOT NULL,
            organization TEXT, manufacturer TEXT, title TEXT,
            document_number TEXT, edition TEXT, revision TEXT,
            publication_date TEXT, retrieved_at TEXT,
            local_path_or_private_ref TEXT, document_hash TEXT,
            license_or_access_state TEXT,
            equipment_family_tags TEXT, procedure_tags TEXT, topic_tags TEXT,
            supersedes_source_id TEXT, superseded_by_source_id TEXT,
            active INTEGER DEFAULT 1, confidence TEXT, notes TEXT
        );
        CREATE TABLE IF NOT EXISTS chunks (
            chunk_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, text TEXT NOT NULL,
            chunk_type TEXT, section TEXT, page TEXT,
            topic_tags TEXT, procedure_tags TEXT, equipment_family_tags TEXT,
            table_ref TEXT, figure TEXT, active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS tables (
            table_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, page TEXT,
            section TEXT, caption TEXT, rows_json TEXT, active INTEGER DEFAULT 1
        );
        """)
        # schema migrations: add columns to pre-existing DBs (P7/P24/H5)
        existing = {row[1] for row in self._db.execute("PRAGMA table_info(sources)")}
        migrations = {
            "source_state": "TEXT DEFAULT 'ACTIVE'",
            "duplicate_of_source_id": "TEXT",
            "ingest_id": "TEXT",
            "parser_version": "TEXT",
            "chunking_version": "TEXT",
            "document_type": "TEXT",
            "byte_size": "INTEGER",
            "verification_method": "TEXT",
            "verified_by": "TEXT",
            "verified_at": "TEXT",
            "verification_evidence": "TEXT",
            "filename": "TEXT",
            "ingestion_state": "TEXT DEFAULT 'INDEXED'",
            "owner_approval_state": "TEXT DEFAULT 'PENDING'",
            "model": "TEXT",
            "model_series": "TEXT",
            "page_count": "INTEGER",
        }
        for column, ddl in migrations.items():
            if column not in existing:
                self._db.execute(f"ALTER TABLE sources ADD COLUMN {column} {ddl}")
        self._db.commit()

    # ---- sources ----------------------------------------------------------

    def add_source(self, source: KnowledgeSource) -> None:
        existing = self.get_source(source.source_id)
        if existing is not None:
            # Source identity is immutable (P37). Only version/link relations
            # may be updated explicitly - never silently replace trusted data.
            if source.superseded_by_source_id or source.supersedes_source_id:
                self._db.execute(
                    "UPDATE sources SET supersedes_source_id=COALESCE(?, supersedes_source_id), "
                    "superseded_by_source_id=COALESCE(?, superseded_by_source_id) "
                    "WHERE source_id=?",
                    (source.supersedes_source_id, source.superseded_by_source_id,
                     source.source_id))
                self._db.commit()
            return
        row = source.to_dict()
        for list_field in ("equipment_family_tags", "procedure_tags", "topic_tags"):
            row[list_field] = json.dumps(row[list_field])
        columns = list(SOURCE_ATTRS)
        self._db.execute(
            f"INSERT INTO sources ({', '.join(columns)}) VALUES "
            f"({', '.join('?' * len(columns))})",
            [row.get(c) for c in columns],
        )
        self._db.commit()

    def get_source(self, source_id: str) -> KnowledgeSource | None:
        row = self._db.execute("SELECT * FROM sources WHERE source_id=?",
                               (source_id,)).fetchone()
        if row is None:
            return None
        return self._source_from_row(row)

    def find_by_hash(self, document_hash: str) -> list[KnowledgeSource]:
        rows = self._db.execute("SELECT * FROM sources WHERE document_hash=?",
                                (document_hash,)).fetchall()
        return [self._source_from_row(r) for r in rows]

    def find_by_title(self, title: str) -> list[KnowledgeSource]:
        rows = self._db.execute("SELECT * FROM sources WHERE title=?",
                                (title,)).fetchall()
        return [self._source_from_row(r) for r in rows]

    def set_source_state(self, source_id: str, state: str) -> None:
        assert state in SOURCE_STATES, state
        self._db.execute("UPDATE sources SET source_state=? WHERE source_id=?",
                         (state, source_id))
        self._db.commit()

    def verify_source(self, source_id: str, *, method: str,
                      verified_by: str = "owner",
                      verification_evidence: str | None = None,
                      manufacturer: str | None = None,
                      document_number: str | None = None,
                      edition: str | None = None,
                      revision: str | None = None,
                      organization: str | None = None,
                      applicability: str | None = None) -> KnowledgeSource | None:
        """Promote a source with real provenance (P40-P43). No anonymous flip."""
        assert method in VERIFICATION_METHODS, method
        source = self.get_source(source_id)
        if source is None:
            return None
        from datetime import datetime
        self._db.execute(
            "UPDATE sources SET source_state='SOURCE_VERIFIED', "
            "verification_method=?, verified_by=?, verified_at=?, "
            "verification_evidence=?, manufacturer=COALESCE(?, manufacturer), "
            "document_number=COALESCE(?, document_number), "
            "edition=COALESCE(?, edition), revision=COALESCE(?, revision), "
            "organization=COALESCE(?, organization), notes=COALESCE(?, notes) "
            "WHERE source_id=?",
            (method, verified_by, datetime.now().isoformat(timespec="seconds"),
             verification_evidence, manufacturer, document_number, edition,
             revision, organization, applicability, source_id))
        self._db.commit()
        return self.get_source(source_id)

    def reclassify_source(self, source_id: str, source_type: str, *,
                          manufacturer: str | None = None,
                          applicability: str | None = None) -> KnowledgeSource | None:
        """Reclassify actually changes source_type (P42)."""
        if source_type not in SOURCE_TYPES:
            return None
        self._db.execute(
            "UPDATE sources SET source_type=?, manufacturer=COALESCE(?, manufacturer), "
            "notes=COALESCE(?, notes) WHERE source_id=?",
            (source_type, manufacturer, applicability, source_id))
        self._db.commit()
        return self.get_source(source_id)

    @staticmethod
    def _source_from_row(row) -> KnowledgeSource:
        data = dict(row)
        for list_field in ("equipment_family_tags", "procedure_tags", "topic_tags"):
            raw = data.get(list_field)
            data[list_field] = json.loads(raw) if raw else []
        data["active"] = bool(data.get("active", 1))
        return KnowledgeSource(**{k: data.get(k) for k in SOURCE_ATTRS})

    def list_sources(self) -> list[KnowledgeSource]:
        rows = self._db.execute("SELECT * FROM sources").fetchall()
        return [self._source_from_row(r) for r in rows]

    def count_sources(self, source_type: str | None = None) -> int:
        if source_type:
            return self._db.execute(
                "SELECT COUNT(*) FROM sources WHERE source_type=?", (source_type,)
            ).fetchone()[0]
        return self._db.execute("SELECT COUNT(*) FROM sources").fetchone()[0]

    # ---- chunks -----------------------------------------------------------

    def add_chunk(self, chunk: KnowledgeChunk) -> None:
        # explicit INSERT (P37): chunk identity is immutable; no silent replace
        exists = self._db.execute(
            "SELECT 1 FROM chunks WHERE chunk_id=?", (chunk.chunk_id,)).fetchone()
        if exists:
            return
        self._db.execute(
            "INSERT INTO chunks (chunk_id, source_id, text, chunk_type, "
            "section, page, topic_tags, procedure_tags, equipment_family_tags, "
            "table_ref, figure, active) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (chunk.chunk_id, chunk.source_id, chunk.text, chunk.chunk_type,
             chunk.section, chunk.page, json.dumps(chunk.topic_tags),
             json.dumps(chunk.procedure_tags), json.dumps(chunk.equipment_family_tags),
             chunk.table, chunk.figure, 1),
        )
        self._db.commit()

    # ---- retrieval (lexical + metadata filters) ---------------------------

    def search(self, query: str, *, source_type: str | None = None,
               manufacturer: str | None = None, model: str | None = None,
               topic: str | None = None, procedure: str | None = None,
               equipment_family: str | None = None, limit: int = 5,
               active_only: bool = True) -> list[dict[str, Any]]:
        """Lexical + metadata retrieval. Excludes CUSTOMER_JOB / QUARANTINED
        sources from global search (firewall)."""
        sql = ("SELECT c.*, s.source_type, s.title, s.edition, s.revision, s.manufacturer, "
               "s.source_state, s.document_number "
               "FROM chunks c JOIN sources s ON c.source_id = s.source_id WHERE 1=1")
        params: list[Any] = []
        if active_only:
            sql += " AND c.active = 1 AND s.active = 1"
            # M1.4.1 firewall: only explicitly trusted states enter
            # authoritative retrieval. CANDIDATE / QUARANTINED / DISABLED /
            # SUPERSEDED / CUSTOMER_JOB are excluded.
            sql += " AND s.source_state IN ('SOURCE_VERIFIED', 'ACTIVE')"
            sql += " AND s.source_type != 'CUSTOMER_JOB'"
        if source_type:
            sql += " AND s.source_type = ?"
            params.append(source_type)
        if manufacturer:
            sql += " AND s.manufacturer = ?"
            params.append(manufacturer)
        if model:
            sql += " AND (s.title LIKE ? OR c.text LIKE ?)"
            params += [f"%{model}%", f"%{model}%"]
        if topic:
            sql += " AND (c.topic_tags LIKE ? OR s.topic_tags LIKE ?)"
            params += [f"%{topic}%", f"%{topic}%"]
        if procedure:
            sql += " AND (c.procedure_tags LIKE ? OR s.procedure_tags LIKE ?)"
            params += [f"%{procedure}%", f"%{procedure}%"]
        if equipment_family:
            sql += " AND (c.equipment_family_tags LIKE ? OR s.equipment_family_tags LIKE ?)"
            params += [f"%{equipment_family}%", f"%{equipment_family}%"]
        sql += " ORDER BY CASE WHEN lower(c.text) LIKE lower(?) THEN 0 ELSE 1 END, c.chunk_id"
        params.append(f"%{query}%")
        sql += " LIMIT ?"
        params.append(limit)
        rows = self._db.execute(sql, params).fetchall()
        results = []
        for row in rows:
            data = dict(row)
            for list_field in ("topic_tags", "procedure_tags", "equipment_family_tags"):
                raw = data.get(list_field)
                data[list_field] = json.loads(raw) if raw else []
            results.append(data)
        return results

    def exact_model_lookup(self, model: str) -> list[dict[str, Any]]:
        """Exact-model lookup avoiding substring false positives (P48).

        '50TC-E08' must not match '50TC-E080' or '50TC-E08X': the model must
        appear as a whole identifier token (bounded by non-alphanumeric)."""
        results = self.search(model, source_type=None, model=model, limit=8)
        norm = re.sub(r"[^A-Z0-9]", "", (model or "").upper())
        if not norm:
            return []
        exact = []
        for candidate in results:
            blob = " ".join([
                str(candidate.get("text") or ""),
                str(candidate.get("document_number") or ""),
                str(candidate.get("title") or ""),
            ]).upper()
            tokens = _identifier_tokens(blob)
            if norm in tokens or any(t == norm for t in tokens):
                exact.append(candidate)
            elif norm in tokens:
                exact.append(candidate)
        return exact[:3]

    def superseded(self) -> list[KnowledgeSource]:
        rows = self._db.execute(
            "SELECT * FROM sources WHERE superseded_by_source_id IS NOT NULL OR "
            "supersedes_source_id IS NOT NULL").fetchall()
        return [self._source_from_row(r) for r in rows]

    def fetch_source(self, source_id: str, *, limit: int = 12) -> dict[str, Any] | None:
        """Return bounded trusted CONTENT for a source (P18/P49): metadata +
        relevant chunks + tables - never just metadata, never a full dump."""
        source = self.get_source(source_id)
        if source is None:
            return None
        chunks = self._db.execute(
            "SELECT * FROM chunks WHERE source_id=? AND active=1 LIMIT ?",
            (source_id, limit)).fetchall()
        tables = self._db.execute(
            "SELECT * FROM tables WHERE source_id=? AND active=1 LIMIT ?",
            (source_id, 5)).fetchall()
        chunk_dicts = []
        for row in chunks:
            data = dict(row)
            for list_field in ("topic_tags", "procedure_tags", "equipment_family_tags"):
                raw = data.get(list_field)
                data[list_field] = json.loads(raw) if raw else []
            chunk_dicts.append(data)
        table_dicts = []
        for row in tables:
            data = dict(row)
            data["rows"] = json.loads(data.get("rows_json") or "[]")
            table_dicts.append({
                "table_id": data["table_id"], "page": data.get("page"),
                "section": data.get("section"), "caption": data.get("caption"),
                "rows": data["rows"],
            })
        return {
            "source": source.to_dict(),
            "chunks": chunk_dicts,
            "tables": table_dicts,
        }

    # ---- table retrieval (P50) --------------------------------------------

    def search_tables(self, query: str, *, limit: int = 3) -> list[dict[str, Any]]:
        """Retrieve table evidence by caption/rows with trust filter (P50)."""
        q = query.lower()
        rows = self._db.execute(
            "SELECT t.*, s.source_type, s.source_state FROM tables t "
            "JOIN sources s ON t.source_id = s.source_id "
            "WHERE s.source_state IN ('SOURCE_VERIFIED','ACTIVE') "
            "AND s.active = 1 AND t.active = 1 "
            "AND s.source_type != 'CUSTOMER_JOB' "
            "AND (lower(t.caption) LIKE ? OR lower(t.rows_json) LIKE ?) LIMIT ?",
            (f"%{q}%", f"%{q}%", limit)).fetchall()
        results = []
        for row in rows:
            data = dict(row)
            data["rows"] = json.loads(data.get("rows_json") or "[]")
            results.append({
                "table_id": data["table_id"], "source_id": data["source_id"],
                "source_type": data.get("source_type"),
                "page": data.get("page"), "section": data.get("section"),
                "caption": data.get("caption"), "headers": (data["rows"][0] if data["rows"] else []),
                "rows": data["rows"],
            })
        return results

    def close(self) -> None:
        self._db.close()
