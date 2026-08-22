"""SCSKnowledgeLibrary - private/local-first knowledge source registry + index
(M1.3, P3-P8, P58, P88-P89).

Sqlite-backed storage keeps sources/chunks/citations/gaps/lessons in separate
tables (never one JSON blob). Retrieval supports lexical search + metadata
filters (source_type / manufacturer / model / edition / topic / procedure /
equipment family / instrument). Copyrighted standards are never committed;
only metadata + short curated passages may be indexed.
"""
from __future__ import annotations

import json
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
    "superseded_by_source_id", "active", "confidence", "notes",
)


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

    def to_dict(self) -> dict[str, Any]:
        return {attr: getattr(self, attr) for attr in SOURCE_ATTRS}


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
        """)
        self._db.commit()

    # ---- sources ----------------------------------------------------------

    def add_source(self, source: KnowledgeSource) -> None:
        row = source.to_dict()
        for list_field in ("equipment_family_tags", "procedure_tags", "topic_tags"):
            row[list_field] = json.dumps(row[list_field])
        self._db.execute(
            f"INSERT OR REPLACE INTO sources ({', '.join(SOURCE_ATTRS)}) VALUES "
            f"({', '.join('?' * len(SOURCE_ATTRS))})",
            [row.get(a) for a in SOURCE_ATTRS],
        )
        self._db.commit()

    def get_source(self, source_id: str) -> KnowledgeSource | None:
        row = self._db.execute("SELECT * FROM sources WHERE source_id=?",
                               (source_id,)).fetchone()
        if row is None:
            return None
        return self._source_from_row(row)

    @staticmethod
    def _source_from_row(row) -> KnowledgeSource:
        data = dict(row)
        for list_field in ("equipment_family_tags", "procedure_tags", "topic_tags"):
            raw = data.get(list_field)
            data[list_field] = json.loads(raw) if raw else []
        data["active"] = bool(data.get("active", 1))
        return KnowledgeSource(**{k: data[k] for k in SOURCE_ATTRS})

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
        self._db.execute(
            "INSERT OR REPLACE INTO chunks (chunk_id, source_id, text, chunk_type, "
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
        """Hybrid-ish retrieval: lexical match on chunk text + filters."""
        sql = ("SELECT c.*, s.source_type, s.title, s.edition, s.revision, s.manufacturer "
               "FROM chunks c JOIN sources s ON c.source_id = s.source_id WHERE 1=1")
        params: list[Any] = []
        if active_only:
            sql += " AND c.active = 1 AND s.active = 1"
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
        return self.search(model, source_type=None, model=model, limit=3)

    def superseded(self) -> list[KnowledgeSource]:
        rows = self._db.execute(
            "SELECT * FROM sources WHERE superseded_by_source_id IS NOT NULL OR "
            "supersedes_source_id IS NOT NULL").fetchall()
        return [self._source_from_row(r) for r in rows]

    def close(self) -> None:
        self._db.close()
