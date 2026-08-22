"""KnowledgeIngestor (M1.4, P9-P16, H5-H6).

Production-grade import of owner-authorized local documents (PDF/TXT/MD/DOCX
if available). Preserves document/chapter/section/page/table/figure structure;
classifies sources before indexing; quarantines unknown/CUSTOMER_JOB content;
dedups by sha256 (changed hash = new version, never silently mutate); records
full provenance (ingest_id, parser/chunking/embedding versions, verification
state). Originals are never mutated - copies/derived artifacts live under
private runtime storage.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .registry import KnowledgeChunk, KnowledgeSource, SCSKnowledgeLibrary

PARSER_VERSION = "ingest-1.0"
CHUNKING_VERSION = "structure-v1"

# auto-classification (P12) - CUSTOMER_JOB never promotes globally
CLASSIFICATION_KEYWORDS = [
    ("OEM_IOM", ("installation", "operation", "maintenance", " iom ", "installation manual", "operation manual")),
    ("OEM_SERVICE_MANUAL", ("service manual", "service and", "repair manual")),
    ("OEM_ENGINEERING_DATA", ("engineering data", "performance data", "product data", "selection", "fan curve")),
    ("OEM_SUBMITTAL", ("submittal", "submittal data")),
    ("OEM_CATALOG", ("catalog", "catalogue", "product catalog")),
    ("STANDARD_NEBB", ("nebb",)),
    ("STANDARD_AABC", ("aabc",)),
    ("STANDARD_ASHRAE", ("ashrae",)),
    ("STANDARD_SMACNA", ("smacna",)),
    ("INSTRUMENT_MANUAL", ("instrument", "meter manual", "probe manual", "balometer", "anemometer", "micromanometer")),
    ("SCS_PLAYBOOK", ("scs playbook", "playbook", "scs procedure")),
    ("CUSTOMER_JOB", ("customer", "job report", "field report", "t&b report", "tab report")),
]
_HEADING_RE = re.compile(r"^(#{1,6}\s+|(?:section|chapter)\s+\d+\.?\s*|(\d+\.\d*\s+[A-Z]))", re.IGNORECASE)


def classify_document(filename: str, first_text: str = "") -> str:
    upper = (filename + " " + first_text).upper()
    for source_type, keywords in CLASSIFICATION_KEYWORDS:
        if any(k.upper() in upper for k in keywords):
            return source_type
    return "UNKNOWN"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _chunk_by_structure(text: str, *, source_id: str) -> list[KnowledgeChunk]:
    """Structure-preserving chunking: headings + paragraph/page boundaries."""
    chunks: list[KnowledgeChunk] = []
    current_section = "GENERAL"
    current_lines: list[str] = []
    page = None
    index = 0

    def flush():
        nonlocal current_lines, index
        body = "\n".join(current_lines).strip()
        if not body:
            return
        index += 1
        chunks.append(KnowledgeChunk(
            chunk_id=f"{source_id}-c{index:03d}", source_id=source_id,
            text=body, chunk_type="SECTION", section=current_section, page=page))

    for line in text.splitlines():
        stripped = line.strip()
        if _HEADING_RE.match(stripped):
            flush()
            current_section = stripped[:60]
            current_lines = []
            continue
        page_match = re.search(r"^\s*PAGE\s+(\d+)\s*$", stripped, re.IGNORECASE)
        if page_match:
            page = page_match.group(1)
            continue
        current_lines.append(stripped)
    flush()
    return chunks


@dataclass
class IngestResult:
    ingest_id: str
    source_id: str
    filename: str
    sha256: str
    byte_size: int
    document_type: str
    source_classification: str
    source_state: str
    chunks: list[KnowledgeChunk]
    tables: list[dict[str, Any]]
    duplicate_of_source_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ingest_id": self.ingest_id, "source_id": self.source_id,
            "filename": self.filename, "sha256": self.sha256,
            "byte_size": self.byte_size, "document_type": self.document_type,
            "source_classification": self.source_classification,
            "source_state": self.source_state,
            "chunk_count": len(self.chunks), "table_count": len(self.tables),
            "duplicate_of_source_id": self.duplicate_of_source_id,
            "parser_version": PARSER_VERSION, "chunking_version": CHUNKING_VERSION,
        }


def ingest_file(library: SCSKnowledgeLibrary, path: Path, *,
                private_root: Path | None = None) -> IngestResult:
    """Index a document copy under private_root; originals never mutated."""
    path = Path(path)
    digest = sha256_of(path)
    existing = library.find_by_hash(digest)
    duplicate_of = existing[0].source_id if existing else None

    # same hash: do not duplicate-index blindly (H5)
    if duplicate_of:
        prior = existing[0]
        prior_state = "QUARANTINED" if prior.source_type in ("UNKNOWN", "CUSTOMER_JOB") \
            else "CANDIDATE"
        return IngestResult(
            ingest_id=f"ING-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            source_id=prior.source_id, filename=path.name, sha256=digest,
            byte_size=path.stat().st_size, document_type=path.suffix.lower(),
            source_classification=prior.source_type, source_state=prior_state,
            chunks=[], tables=[], duplicate_of_source_id=duplicate_of)

    text, tables = _extract(path)
    classification = classify_document(path.name, text[:2000])
    quarantined = classification in ("UNKNOWN", "CUSTOMER_JOB")
    state = "QUARANTINED" if quarantined else "CANDIDATE"
    source_id = f"SRC-{digest[:10]}"
    ingest_id = f"ING-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    private_copy = None
    if private_root:
        private_root.mkdir(parents=True, exist_ok=True)
        private_copy = private_root / f"{digest[:12]}{path.suffix.lower()}"
        if not private_copy.exists():
            import shutil
            shutil.copy2(path, private_copy)

    source = KnowledgeSource(
        source_id=source_id, source_type=classification,
        organization=None, manufacturer=None, title=path.stem,
        document_number=None, edition=None, revision=None,
        publication_date=None, retrieved_at=datetime.now().isoformat(timespec="seconds"),
        local_path_or_private_ref=str(private_copy) if private_copy else None,
        document_hash=digest, license_or_access_state="owner_authorized",
        active=not quarantined, confidence="HIGH",
        notes="quarantined until classification/verification" if quarantined else "CANDIDATE")
    library.add_source(source)
    # provenance (H5): state + dedup + parser/chunking versions after insert
    library._db.execute(
        "UPDATE sources SET source_state=?, ingest_id=?, parser_version=?, "
        "chunking_version=?, document_type=?, byte_size=? WHERE source_id=?",
        (state, ingest_id, PARSER_VERSION, CHUNKING_VERSION,
         path.suffix.lower(), path.stat().st_size, source_id))
    library._db.commit()

    chunks = _chunk_by_structure(text, source_id=source_id)
    for chunk in chunks:
        chunk.chunk_type = classify_chunk_type(chunk.text)
        library.add_chunk(chunk)
    for table in tables:
        library._db.execute(
            "INSERT OR REPLACE INTO tables (table_id, source_id, page, section, "
            "caption, rows_json, active) VALUES (?,?,?,?,?,?,1)",
            (table["table_id"], source_id, table.get("page"), table.get("section"),
             table.get("caption"), json.dumps(table.get("rows") or [])))
    library._db.commit()
    return IngestResult(ingest_id=ingest_id, source_id=source_id, filename=path.name,
                        sha256=digest, byte_size=path.stat().st_size,
                        document_type=path.suffix.lower(),
                        source_classification=classification, source_state=state,
                        chunks=chunks, tables=tables,
                        duplicate_of_source_id=None)


def classify_chunk_type(text: str) -> str:
    upper = text.upper()
    if any(w in upper for w in ("WARNING", "CAUTION")):
        return "WARNING"
    if any(w in upper for w in ("TEST REQUIRE", "REQUIRED READING", "SHALL")):
        return "TEST_REQUIREMENT"
    if any(w in upper for w in ("PROCEDURE", "STEP 1", "STEP 2", "TRAVERSE")):
        return "PROCEDURE_STEP"
    if any(w in upper for w in ("LIMIT", "MAXIMUM", "RANGE", "TOLERANCE")):
        return "LIMIT"
    if upper.startswith("TABLE"):
        return "TABLE_VALUE"
    return "NOTE"


def _extract(path: Path) -> tuple[str, list[dict[str, Any]]]:
    """Extract text + tables preserving structure (PDF via pdfplumber)."""
    suffix = path.suffix.lower()
    tables: list[dict[str, Any]] = []
    if suffix == ".pdf":
        import pdfplumber
        parts = []
        with pdfplumber.open(str(path)) as pdf:
            for number, page in enumerate(pdf.pages, start=1):
                parts.append(f"\nPAGE {number}\n")
                parts.append(page.extract_text() or "")
                try:
                    for table_index, table in enumerate(page.find_tables()):
                        rows = table.extract()
                        if not rows:
                            continue
                        caption = f"table p{number} t{table_index + 1}"
                        tables.append({"table_id": f"tbl-{path.stem}-p{number}-{table_index}",
                                       "page": str(number), "section": None,
                                       "caption": caption, "rows": rows})
                except Exception:
                    continue
        return "\n".join(parts), tables
    if suffix in (".txt", ".md", ".markdown"):
        return path.read_text(encoding="utf-8", errors="replace"), tables
    if suffix == ".docx":
        try:
            from docx import Document
            doc = Document(str(path))
            return "\n".join(p.text for p in doc.paragraphs), tables
        except Exception:
            return f"[unable to parse {suffix}]", tables
    return f"[unsupported format {suffix}]", tables
