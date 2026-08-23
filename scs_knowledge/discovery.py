"""Deterministic owner knowledge discovery + approval (M1.5A, P0-P6).

A file's physical presence under SCS_KNOWLEDGE_ROOT grants DISCOVERED only —
never technical authority. Documents flow through an explicit, durable owner
workflow:

    DISCOVERED -> CLASSIFIED -> OWNER_APPROVED -> INDEXED -> BLOCKED
                                          `-> PARSE_FAILED / STALE_CHANGED

Discovery is idempotent by (relative_location, sha256). A changed file hash
invalidates the prior approval (STALE_CHANGED) and requires owner review again.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from .ingestor import PARSER_VERSION, classify_document, ingest_file, sha256_of

INGESTION_STATES = ("DISCOVERED", "CLASSIFIED", "OWNER_APPROVED", "INDEXED",
                    "BLOCKED", "STALE_CHANGED", "PARSE_FAILED")
_SUPPORTED_SUFFIXES = (".pdf", ".txt", ".md", ".markdown", ".docx")


def _page_count(path: Path) -> int | None:
    if path.suffix.lower() != ".pdf":
        return None
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            return len(pdf.pages)
    except Exception:
        return None


def _new_discovery_id(relative_location: str, digest: str) -> str:
    import hashlib
    h = hashlib.sha256(f"{relative_location}::{digest}".encode("utf-8")).hexdigest()
    return f"DSC-{h[:12]}"


class KnowledgeDiscoveryStore:
    """Durable discovery manifest (P0-P4). JSON-backed, atomic, thread-safe."""

    def __init__(self, store_path: Path, *, root: Path | None = None) -> None:
        self._path = Path(store_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._root = Path(root) if root else self._path.parent
        self._lock = threading.RLock()
        self._records = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self) -> None:
        with self._lock:
            tmp = self._path.with_name(self._path.name + ".tmp")
            tmp.write_text(json.dumps(self._records, indent=2, default=str),
                           encoding="utf-8")
            tmp.replace(self._path)

    def _by_location(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for did, rec in self._records.items():
            loc = rec.get("relative_location")
            if loc and rec.get("state") != "STALE_CHANGED":
                out[loc] = did
        return out

    def discover(self, root: Path | None = None) -> list[dict[str, Any]]:
        """Scan for owner documents and persist durable DISCOVERED records.

        Idempotent by (relative_location, sha256); changed sha marks the prior
        record STALE_CHANGED and creates a new version (P1)."""
        root = Path(root) if root else self._root
        self._root = root
        if not root.exists():
            return self.list()
        locations = self._by_location()
        with self._lock:
            for path in sorted(root.rglob("*")):
                if not path.is_file() or path.suffix.lower() not in _SUPPORTED_SUFFIXES:
                    continue
                if path.name == "library.db" or ".tmp" in path.suffixes:
                    continue
                try:
                    rel = str(path.relative_to(root))
                except ValueError:
                    rel = path.name
                digest = sha256_of(path)
                existing_id = locations.get(rel)
                if existing_id is not None:
                    existing = self._records[existing_id]
                    if existing.get("file_sha256") == digest:
                        existing["discovered_at"] = _now()
                        continue  # idempotent: same file, same bytes
                    # changed bytes: prior approval/index is now stale
                    existing["state"] = "STALE_CHANGED"
                    existing["stale_reason"] = "file content changed"
                    existing["stale_at"] = _now()
                first_text = ""
                if path.suffix.lower() in (".txt", ".md", ".markdown"):
                    try:
                        first_text = path.read_text(encoding="utf-8", errors="replace")[:2000]
                    except Exception:
                        first_text = ""
                did = _new_discovery_id(rel, digest)
                self._records[did] = {
                    "discovery_id": did,
                    "relative_location": rel,
                    "filename": path.name,
                    "file_sha256": digest,
                    "byte_size": path.stat().st_size,
                    "page_count": _page_count(path),
                    "candidate_source_type": classify_document(path.name, first_text),
                    "manufacturer": None, "model": None, "model_series": None,
                    "family_tags": [], "applicability": "UNKNOWN",
                    "edition": None,
                    "parser_version": PARSER_VERSION,
                    "discovered_at": _now(),
                    "state": "DISCOVERED",
                    "source_id": None,
                    "blocked_reason": None,
                }
                locations[rel] = did
            self._save()
        return self.list()

    def list(self) -> list[dict[str, Any]]:
        records = sorted(self._records.values(),
                         key=lambda r: (r.get("relative_location", "")))
        for r in records:
            r.setdefault("state", "DISCOVERED")
        return records

    def get(self, discovery_id: str) -> dict[str, Any] | None:
        return self._records.get(discovery_id)

    def classify(self, discovery_id: str, **metadata: Any) -> dict[str, Any] | None:
        record = self._records.get(discovery_id)
        if record is None:
            return None
        if record.get("state") in ("INDEXED", "BLOCKED"):
            return record
        for key in ("source_type", "manufacturer", "model", "model_series",
                    "family_tags", "applicability", "edition"):
            value = metadata.get(key)
            if value is not None:
                if key == "source_type":
                    record["candidate_source_type"] = value
                else:
                    record[key] = value
        record["state"] = "CLASSIFIED"
        self._save()
        return record

    def approve(self, discovery_id: str, *, verified_by: str = "owner",
                **metadata: Any) -> dict[str, Any] | None:
        record = self._records.get(discovery_id)
        if record is None:
            return None
        for key in ("source_type", "manufacturer", "model", "model_series",
                    "family_tags", "applicability", "edition"):
            value = metadata.get(key)
            if value is not None:
                if key == "source_type":
                    record["candidate_source_type"] = value
                else:
                    record[key] = value
        record["state"] = "OWNER_APPROVED"
        record["approved_by"] = verified_by
        record["approved_at"] = _now()
        self._save()
        return record

    def block(self, discovery_id: str, reason: str = "") -> dict[str, Any] | None:
        record = self._records.get(discovery_id)
        if record is None:
            return None
        record["state"] = "BLOCKED"
        record["blocked_reason"] = reason or "owner blocked"
        self._save()
        return record

    def mark_indexed(self, discovery_id: str, source_id: str) -> dict[str, Any] | None:
        record = self._records.get(discovery_id)
        if record is None:
            return None
        record["state"] = "INDEXED"
        record["source_id"] = source_id
        record["indexed_at"] = _now()
        self._save()
        return record

    def mark_parse_failed(self, discovery_id: str, reason: str = "") -> dict[str, Any] | None:
        record = self._records.get(discovery_id)
        if record is None:
            return None
        record["state"] = "PARSE_FAILED"
        record["blocked_reason"] = reason or "parse failed"
        self._save()
        return record

    def approve_and_index(self, discovery_id: str, library, *,
                          verified_by: str = "owner",
                          private_root: Path | None = None,
                          **metadata: Any) -> dict[str, Any] | None:
        """P3-P4: approve then run the canonical ingestor. Approval alone does
        not claim indexing success — INDEXED requires a successful parse, and
        the owner-approved source is then source-verified so it becomes
        retrievable authority."""
        record = self.approve(discovery_id, verified_by=verified_by, **metadata)
        if record is None:
            return None
        path = self._root / record["relative_location"]
        if not path.exists():
            self.mark_parse_failed(discovery_id, "source file missing")
            return self.get(discovery_id)
        try:
            result = ingest_file(library, path, private_root=private_root)
            if result.source_state == "QUARANTINED":
                self.mark_parse_failed(discovery_id, "ingestion quarantined")
            else:
                library.verify_source(
                    result.source_id, method="OWNER_APPROVED", verified_by=verified_by,
                    verification_evidence="owner-approved manual",
                    manufacturer=record.get("manufacturer"),
                    document_number=None, edition=record.get("edition"), revision=None)
                self.mark_indexed(discovery_id, result.source_id)
        except Exception as error:
            self.mark_parse_failed(discovery_id, f"{type(error).__name__}: {error}")
        return self.get(discovery_id)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# --- retained read-only helpers ---------------------------------------------


def discover_documents(root: Path) -> list[dict[str, Any]]:
    """Transient scan (kept for compatibility). Prefer KnowledgeDiscoveryStore."""
    store = KnowledgeDiscoveryStore(root / "discovery.json", root=root)
    return store.discover(root)


def inventory(library) -> dict[str, Any]:
    from .registry import SCSKnowledgeLibrary
    sources = library.list_sources()
    rows = []
    counts: dict[str, int] = {}
    for source in sources:
        counts[source.ingestion_state] = counts.get(source.ingestion_state, 0) + 1
        rows.append({
            "source_id": source.source_id,
            "source_type": source.source_type,
            "title": source.title,
            "filename": source.filename or source.title,
            "file_sha256": (source.document_hash or "")[:12],
            "manufacturer": source.manufacturer or "UNKNOWN",
            "model": source.model or "UNKNOWN",
            "model_series": source.model_series or "UNKNOWN",
            "equipment_family_tags": source.equipment_family_tags,
            "applicability": "UNKNOWN",
            "edition": source.edition or "UNKNOWN",
            "page_count": source.page_count,
            "ingestion_state": source.ingestion_state,
            "owner_approval_state": source.owner_approval_state,
            "source_state": source.source_state,
        })
    return {
        "documents": rows,
        "counts": counts,
        "discovered": counts.get("DISCOVERED", 0),
        "classified": counts.get("CLASSIFIED", 0),
        "owner_approved": counts.get("OWNER_APPROVED", 0),
        "indexed": counts.get("INDEXED", 0),
        "blocked": counts.get("BLOCKED", 0),
    }


def approve_source(library, source_id: str, *, source_type: str | None = None,
                   manufacturer: str | None = None, model: str | None = None,
                   model_series: str | None = None,
                   equipment_family_tags: list[str] | None = None,
                   applicability: str | None = None, edition: str | None = None,
                   verified_by: str = "owner") -> dict[str, Any] | None:
    source = library.get_source(source_id)
    if source is None:
        return None
    if source_type:
        library.reclassify_source(source_id, source_type, manufacturer=manufacturer,
                                  applicability=applicability)
    library.verify_source(source_id, method="OWNER_APPROVED", verified_by=verified_by,
                          verification_evidence="owner-approved manual",
                          manufacturer=manufacturer, document_number=None,
                          edition=edition, revision=None)
    library._db.execute(
        "UPDATE sources SET ingestion_state='OWNER_APPROVED', "
        "owner_approval_state='APPROVED', model=COALESCE(?, model), "
        "model_series=COALESCE(?, model_series), "
        "equipment_family_tags=COALESCE(?, equipment_family_tags) "
        "WHERE source_id=?",
        (model, model_series,
         json.dumps(equipment_family_tags) if equipment_family_tags else None, source_id))
    library._db.commit()
    updated = library.get_source(source_id)
    return updated.to_dict() if updated else None


def block_source(library, source_id: str) -> dict[str, Any] | None:
    source = library.get_source(source_id)
    if source is None:
        return None
    library._db.execute(
        "UPDATE sources SET ingestion_state='BLOCKED', owner_approval_state='BLOCKED' "
        "WHERE source_id=?", (source_id,))
    library._db.commit()
    updated = library.get_source(source_id)
    return updated.to_dict() if updated else None
