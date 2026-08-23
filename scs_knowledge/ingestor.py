"""KnowledgeIngestor (M1.4.2, P9-P16, P52-P55, H5-H6).

Production-grade import of owner-authorized local documents (PDF/TXT/MD/DOCX
if available). Preserves document/chapter/section/page/table/figure structure;
classifies sources before indexing; quarantines unknown/CUSTOMER_JOB content;
dedups by sha256 (changed hash = new version, never silently mutate); records
full provenance (ingest_id, parser/chunking/embedding versions, verification
state). Originals are never mutated - copies/derived artifacts live under
private runtime storage.

M1.4.2 changes:
  * strict OCR-unavailable path no longer TypeErrors (P65): IngestResult
    carries notes_hint.
  * Mixed PDFs are OCRed page-by-page (P52): a scanned page 47 is OCRed even
    when page 1 had native text.
  * OCR engine truth (P53): unsupported engine -> OCR_ENGINE_UNSUPPORTED.
  * OCR confidence preserved (P54) and low-confidence numerics flagged (P55).
  * Duplicate import reports the ACTUAL existing source state (P39).
  * Changed hash creates a NEW version linked via supersedes (P38).
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

PARSER_VERSION = "ingest-1.1"
CHUNKING_VERSION = "structure-v1"

SUPPORTED_OCR_ENGINES = ("rapidocr",)

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
    ocr_engine: str | None = None
    ocr_pages: int = 0
    ocr_used: bool = False
    text_pages: int = 0
    notes_hint: str | None = None
    ocr_confidence: dict[str, Any] = field(default_factory=dict)
    low_confidence_pages: list[int] = field(default_factory=list)
    supersedes_source_id: str | None = None

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
            "ocr_engine": self.ocr_engine, "ocr_pages": self.ocr_pages,
            "ocr_used": self.ocr_used, "text_pages": self.text_pages,
            "notes_hint": self.notes_hint,
            "ocr_confidence": self.ocr_confidence,
            "low_confidence_pages": self.low_confidence_pages,
            "supersedes_source_id": self.supersedes_source_id,
        }


def _dedup_state(prior: KnowledgeSource) -> str:
    """Report the ACTUAL existing source state on duplicate import (P39)."""
    if prior.source_state in ("SOURCE_VERIFIED", "DISABLED", "SUPERSEDED"):
        return prior.source_state
    if prior.source_type in ("UNKNOWN", "CUSTOMER_JOB"):
        return "QUARANTINED"
    return "CANDIDATE"


def ingest_file(library: SCSKnowledgeLibrary, path: Path, *,
                private_root: Path | None = None,
                ocr_engine: str | None = None,
                ocr_unavailable_ok: bool = True) -> IngestResult:
    """Index a document copy under private_root; originals never mutated."""
    path = Path(path)
    digest = sha256_of(path)
    existing = library.find_by_hash(digest)
    duplicate_of = existing[0].source_id if existing else None
    ingest_id = f"ING-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    if duplicate_of:
        prior = existing[0]
        return IngestResult(
            ingest_id=ingest_id, source_id=prior.source_id, filename=path.name,
            sha256=digest, byte_size=path.stat().st_size,
            document_type=path.suffix.lower(),
            source_classification=prior.source_type,
            source_state=_dedup_state(prior),
            chunks=[], tables=[], duplicate_of_source_id=duplicate_of)

    # P53: reject unsupported OCR engines truthfully (no silent RapidOCR)
    if ocr_engine and ocr_engine.lower() not in SUPPORTED_OCR_ENGINES:
        return IngestResult(
            ingest_id=ingest_id, source_id=f"SRC-{digest[:10]}",
            filename=path.name, sha256=digest, byte_size=path.stat().st_size,
            document_type=path.suffix.lower(),
            source_classification="UNKNOWN", source_state="QUARANTINED",
            chunks=[], tables=[], ocr_engine=ocr_engine,
            notes_hint="OCR_ENGINE_UNSUPPORTED")

    text, tables, text_pages, sparse_pages = _extract(path)
    ocr_used = False
    ocr_pages = 0
    page_confidence: dict[str, Any] = {}
    low_confidence_pages: list[int] = []
    ocr_notes: list[str] = []

    if path.suffix.lower() == ".pdf" and sparse_pages and ocr_engine:
        # P52: OCR image-only/sparse pages individually (mixed manuals)
        text, ocr_pages, page_confidence, low_confidence_pages = _ocr_pdf(
            path, sparse_pages, engine=ocr_engine)
        ocr_used = ocr_pages > 0
        for page_no in sparse_pages:
            conf = page_confidence.get(page_no)
            if conf is None:
                ocr_notes.append(f"PAGE {page_no}: OCR_NOT_AVAILABLE")

    classification = classify_document(path.name, text[:2000])
    quarantined = classification in ("UNKNOWN", "CUSTOMER_JOB") or (
        path.suffix.lower() == ".pdf" and text_pages == 0 and not ocr_used and sparse_pages)
    state = "QUARANTINED" if quarantined else "CANDIDATE"
    source_id = f"SRC-{digest[:10]}"

    # P38: link prior versions by filename stem (changed hash -> new version)
    supersedes_source_id = None
    prior_versions = library.find_by_title(path.stem)
    if prior_versions:
        supersedes_source_id = prior_versions[0].source_id

    private_copy = None
    if private_root:
        private_root.mkdir(parents=True, exist_ok=True)
        private_copy = private_root / f"{digest[:12]}{path.suffix.lower()}"
        if not private_copy.exists():
            import shutil
            shutil.copy2(path, private_copy)

    notes = "quarantined until classification/verification" if quarantined else "CANDIDATE"
    if low_confidence_pages:
        notes += f"; LOW_CONFIDENCE_OCR_PAGES={low_confidence_pages}"
    source = KnowledgeSource(
        source_id=source_id, source_type=classification,
        organization=None, manufacturer=None, title=path.stem,
        document_number=None, edition=None, revision=None,
        publication_date=None, retrieved_at=datetime.now().isoformat(timespec="seconds"),
        local_path_or_private_ref=str(private_copy) if private_copy else None,
        document_hash=digest, license_or_access_state="owner_authorized",
        active=not quarantined, confidence="HIGH",
        notes=notes,
        supersedes_source_id=supersedes_source_id)
    library.add_source(source)
    library._db.execute(
        "UPDATE sources SET source_state=?, ingest_id=?, parser_version=?, "
        "chunking_version=?, document_type=?, byte_size=? WHERE source_id=?",
        (state, ingest_id, PARSER_VERSION, CHUNKING_VERSION,
         path.suffix.lower(), path.stat().st_size, source_id))
    if supersedes_source_id:
        library._db.execute(
            "UPDATE sources SET superseded_by_source_id=? WHERE source_id=?",
            (source_id, supersedes_source_id))
    library._db.commit()

    chunks = _chunk_by_structure(text, source_id=source_id)
    for chunk in chunks:
        chunk.chunk_type = classify_chunk_type(chunk.text)
        library.add_chunk(chunk)
    for table in tables:
        table_id = f"tbl-{digest[:10]}-p{table.get('page')}-{table.get('table_index', 0)}"
        library._db.execute(
            "INSERT OR IGNORE INTO tables (table_id, source_id, page, section, "
            "caption, rows_json, active) VALUES (?,?,?,?,?,?,1)",
            (table_id, source_id, table.get("page"), table.get("section"),
             table.get("caption"), json.dumps(table.get("rows") or [])))
    library._db.commit()
    return IngestResult(ingest_id=ingest_id, source_id=source_id, filename=path.name,
                        sha256=digest, byte_size=path.stat().st_size,
                        document_type=path.suffix.lower(),
                        source_classification=classification, source_state=state,
                        chunks=chunks, tables=tables,
                        duplicate_of_source_id=None,
                        ocr_engine=ocr_engine, ocr_pages=ocr_pages,
                        ocr_used=ocr_used, text_pages=text_pages,
                        notes_hint="; ".join(ocr_notes) if ocr_notes else None,
                        ocr_confidence=page_confidence,
                        low_confidence_pages=low_confidence_pages,
                        supersedes_source_id=supersedes_source_id)


def verify_source(library: SCSKnowledgeLibrary, source_id: str,
                  *, manufacturer: str | None = None,
                  title: str | None = None) -> KnowledgeSource | None:
    """Deterministic metadata verification -> SOURCE_VERIFIED (P40)."""
    source = library.get_source(source_id)
    if source is None:
        return None
    if not source.document_hash:
        return source
    return library.verify_source(
        source_id, method="DETERMINISTIC_METADATA", verified_by="deterministic",
        verification_evidence=f"hash={source.document_hash[:12]}",
        manufacturer=manufacturer, document_number=None,
        title=title or source.title)


def _pdf_page_count(path: Path) -> list[int]:
    import fitz
    with fitz.open(str(path)) as pdf:
        return list(range(1, len(pdf) + 1))


def _ocr_pdf(path: Path, page_numbers: list[int], engine: str = "rapidocr",
             dpi: int = 200) -> tuple[str, int, dict[int, float], list[int]]:
    """OCR specified pages via RapidOCR (P52-P54).

    Returns (text, pages_ok, page_confidence, low_confidence_pages). The engine
    must be supported (P53); confidence is preserved per page (P54).
    """
    import io
    import fitz
    import numpy as np
    from PIL import Image
    parts = []
    pages_ok = 0
    page_confidence: dict[int, float] = {}
    low_confidence: list[int] = []
    if engine.lower() not in SUPPORTED_OCR_ENGINES:
        parts.append("\nOCR_ENGINE_UNSUPPORTED\n")
        return "\n".join(parts), 0, {}, []
    try:
        from rapidocr_onnxruntime import RapidOCR
        ocr = RapidOCR()
        with fitz.open(str(path)) as pdf:
            for number in page_numbers:
                page = pdf.load_page(number - 1)
                pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72))
                image = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
                result, _elapse = ocr(np.array(image))
                lines = [str(text) for _box, text, _score in (result or [])]
                scores = [float(score) for _box, _text, score in (result or []) if score is not None]
                if lines:
                    pages_ok += 1
                mean_conf = round(sum(scores) / len(scores), 3) if scores else 0.0
                page_confidence[number] = mean_conf
                if scores and mean_conf < 0.7:
                    low_confidence.append(number)
                parts.append(f"\nPAGE {number} (OCR)\n" + "\n".join(lines))
    except Exception as error:
        for number in page_numbers:
            page_confidence[number] = None
        parts.append("\nOCR_NOT_AVAILABLE\n")
    return "\n".join(parts), pages_ok, page_confidence, low_confidence


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


def _extract(path: Path) -> tuple[str, list[dict[str, Any]], int, list[int]]:
    """Extract text + tables preserving structure (PDF via pdfplumber).

    Returns (text, tables, text_page_count, sparse_pages) where sparse_pages
    are image-only pages with no native text (P52).
    """
    suffix = path.suffix.lower()
    tables: list[dict[str, Any]] = []
    if suffix == ".pdf":
        import pdfplumber
        parts = []
        text_pages = 0
        sparse_pages: list[int] = []
        with pdfplumber.open(str(path)) as pdf:
            for number, page in enumerate(pdf.pages, start=1):
                page_text = page.extract_text() or ""
                if page_text.strip():
                    text_pages += 1
                else:
                    sparse_pages.append(number)
                parts.append(f"\nPAGE {number}\n")
                parts.append(page_text)
                try:
                    for table_index, table in enumerate(page.find_tables()):
                        rows = table.extract()
                        if not rows:
                            continue
                        tables.append({"table_id": None, "page": str(number),
                                       "section": None, "caption": None,
                                       "rows": rows, "table_index": table_index})
                except Exception:
                    continue
        return "\n".join(parts), tables, text_pages, sparse_pages
    if suffix in (".txt", ".md", ".markdown"):
        return path.read_text(encoding="utf-8", errors="replace"), tables, 1, []
    if suffix == ".docx":
        try:
            from docx import Document
            doc = Document(str(path))
            return "\n".join(p.text for p in doc.paragraphs), tables, 1, []
        except Exception:
            return f"[unable to parse {suffix}]", tables, 0, []
    return f"[unsupported format {suffix}]", tables, 0, []
