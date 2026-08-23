"""Deterministic owner knowledge discovery + approval (M1.5, P2-P6).

A file's physical presence under SCS_KNOWLEDGE_ROOT does NOT grant it
authority. Documents flow through an explicit owner workflow:

    DISCOVERED -> CLASSIFIED -> OWNER_APPROVED -> INDEXED -> BLOCKED

Automatic discovery infers CANDIDATE metadata only; it never silently grants
OEM/STANDARD authority. Owner-approved metadata is the authority input.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .ingestor import PARSER_VERSION, classify_document, sha256_of
from .registry import SCSKnowledgeLibrary

INGESTION_STATES = ("DISCOVERED", "CLASSIFIED", "OWNER_APPROVED", "INDEXED", "BLOCKED")
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


def discover_documents(root: Path) -> list[dict[str, Any]]:
    """Scan a knowledge root for owner documents. Returns DISCOVERED metadata
    only (no indexing, no authority). Never crawls outside the root."""
    root = Path(root)
    if not root.exists():
        return []
    found: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _SUPPORTED_SUFFIXES:
            continue
        # skip the runtime library/derived artifacts
        if path.name == "library.db" or ".tmp" in path.suffixes:
            continue
        digest = sha256_of(path)
        try:
            rel = str(path.relative_to(root))
        except ValueError:
            rel = path.name
        first_text = ""
        if path.suffix.lower() in (".txt", ".md", ".markdown"):
            try:
                first_text = path.read_text(encoding="utf-8", errors="replace")[:2000]
            except Exception:
                first_text = ""
        found.append({
            "filename": path.name,
            "relative_location": rel,
            "file_sha256": digest,
            "source_type": classify_document(path.name, first_text),
            "byte_size": path.stat().st_size,
            "page_count": _page_count(path),
            "ingestion_state": "DISCOVERED",
            "owner_approval_state": "PENDING",
            "manufacturer": None, "model": None, "model_series": None,
            "equipment_family_tags": [], "applicability": "UNKNOWN",
            "edition": None, "parser_version": PARSER_VERSION,
        })
    return found


def inventory(library: SCSKnowledgeLibrary) -> dict[str, Any]:
    """Deterministic knowledge inventory (P2). Unknown metadata stays UNKNOWN."""
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


def approve_source(library: SCSKnowledgeLibrary, source_id: str, *,
                   source_type: str | None = None,
                   manufacturer: str | None = None,
                   model: str | None = None,
                   model_series: str | None = None,
                   equipment_family_tags: list[str] | None = None,
                   applicability: str | None = None,
                   edition: str | None = None,
                   verified_by: str = "owner") -> dict[str, Any] | None:
    """Owner approval boundary (P3): promotes a source to OWNER_APPROVED with
    durable owner metadata, and marks it source-verified with OWNER_APPROVED
    provenance. Never grants authority from physical presence alone."""
    source = library.get_source(source_id)
    if source is None:
        return None
    if source_type:
        library.reclassify_source(source_id, source_type, manufacturer=manufacturer,
                                  applicability=applicability)
    library.verify_source(source_id, method="OWNER_APPROVED",
                          verified_by=verified_by,
                          verification_evidence="owner-approved manual",
                          manufacturer=manufacturer,
                          document_number=None, edition=edition,
                          revision=None)
    library._db.execute(
        "UPDATE sources SET ingestion_state='OWNER_APPROVED', "
        "owner_approval_state='APPROVED', model=COALESCE(?, model), "
        "model_series=COALESCE(?, model_series), "
        "equipment_family_tags=COALESCE(?, equipment_family_tags) "
        "WHERE source_id=?",
        (model, model_series,
         __import__("json").dumps(equipment_family_tags) if equipment_family_tags else None,
         source_id))
    library._db.commit()
    updated = library.get_source(source_id)
    return updated.to_dict() if updated else None


def block_source(library: SCSKnowledgeLibrary, source_id: str) -> dict[str, Any] | None:
    source = library.get_source(source_id)
    if source is None:
        return None
    library._db.execute(
        "UPDATE sources SET ingestion_state='BLOCKED', owner_approval_state='BLOCKED' "
        "WHERE source_id=?", (source_id,))
    library._db.commit()
    updated = library.get_source(source_id)
    return updated.to_dict() if updated else None
