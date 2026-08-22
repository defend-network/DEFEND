"""PlanPacket: exactly what the owner supplied (M1.2).

Models full AND partial drawing sets, tracks received vs recognized vs
missing sheets, classifies packet completeness, extracts sheet references
(details/sections), and provides relevance-based selective indexing so large
mixed sets are deep-processed only where it matters. Missing sheets become
contextual uncertainty - never hallucinated facts, never a demand for the
whole set.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from . import plans

DETAIL_REF_RE = re.compile(r"(\d{1,2})\s*/\s*([MADEP]\d\.\d+|M-\d{3,4}|A-\d{3,4}|E-\d{3,4}|P-\d{3,4})")
SHEET_NUM_RE = re.compile(r"([MADEP]\d\.\d+|M-\d{3,4}|A-\d{3,4}|E-\d{3,4}|P-\d{3,4})")

MECHANICAL_TYPES = {
    "MECHANICAL_GENERAL_NOTES", "MECHANICAL_PLAN", "HVAC_PLAN", "DUCT_PLAN",
    "AIR_DEVICE_PLAN", "EQUIPMENT_SCHEDULE", "AIR_DEVICE_SCHEDULE",
    "VAV_SCHEDULE", "FAN_SCHEDULE", "RTU_SCHEDULE", "AHU_SCHEDULE",
    "DETAIL", "SECTION", "CONTROL_DIAGRAM", "MECHANICAL_ROOF_PLAN",
    "MECHANICAL_RISER", "MECHANICAL_DEMOLITION", "MECHANICAL_LEGEND",
    "MECHANICAL_EQUIPMENT_PLAN",
}
NON_MECHANICAL_TYPES = {"ELECTRICAL", "PLUMBING", "ARCHITECTURAL", "STRUCTURAL",
                        "COVER", "IRRELEVANT", "UNKNOWN"}


@dataclass
class SheetInfo:
    sheet_number: str | None
    sheet_title: str | None
    page_type: str
    confidence: float
    page_number: int
    source_document: str | None = None
    revision: str | None = None
    referenced_sheets: list[str] = field(default_factory=list)
    referenced_details: list[str] = field(default_factory=list)
    keynote_set: list[str] = field(default_factory=list)
    legend_presence: bool = False
    schedule_presence: bool = False
    notes_presence: bool = False

    @property
    def is_mechanical(self) -> bool:
        return self.page_type in MECHANICAL_TYPES

    def to_dict(self) -> dict[str, Any]:
        return {
            "sheet_number": self.sheet_number, "sheet_title": self.sheet_title,
            "page_type": self.page_type, "confidence": self.confidence,
            "page_number": self.page_number,
            "source_document": self.source_document, "revision": self.revision,
            "referenced_sheets": self.referenced_sheets,
            "referenced_details": self.referenced_details,
            "keynote_set": self.keynote_set,
            "legend_presence": self.legend_presence,
            "schedule_presence": self.schedule_presence,
            "notes_presence": self.notes_presence,
        }


@dataclass
class PlanPacket:
    packet_id: str
    document_hashes: list[str]
    documents: list[str]
    sheets: list[SheetInfo]
    received_sheet_ids: list[str]
    recognized_sheet_ids: list[str]
    mechanical_sheet_ids: list[str]
    nonmechanical_sheet_ids: list[str]
    referenced_but_missing_sheet_ids: list[str]
    packet_completeness: str  # FULL_SET / PARTIAL_SET / UNKNOWN_COMPLETENESS
    missing_context: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "packet_id": self.packet_id,
            "document_hashes": self.document_hashes,
            "documents": self.documents,
            "sheets": [s.to_dict() for s in self.sheets],
            "received_sheet_ids": self.received_sheet_ids,
            "recognized_sheet_ids": self.recognized_sheet_ids,
            "mechanical_sheet_ids": self.mechanical_sheet_ids,
            "nonmechanical_sheet_ids": self.nonmechanical_sheet_ids,
            "referenced_but_missing_sheet_ids": self.referenced_but_missing_sheet_ids,
            "packet_completeness": self.packet_completeness,
            "missing_context": self.missing_context,
        }


def _sheet_id(text: str) -> str:
    return re.sub(r"\s+", "", text.upper()).replace("-", "")


def extract_references(text: str) -> tuple[list[str], list[str]]:
    """Return (referenced_sheets, referenced_details like '3/M7.2')."""
    details = []
    for match in DETAIL_REF_RE.finditer(text):
        details.append(f"{match.group(1)}/{match.group(2).upper()}")
    sheet_nums = []
    for match in SHEET_NUM_RE.finditer(text):
        sheet_nums.append(match.group(1).upper())
    return sheet_nums, details


def build_packet(
    documents: list[plans.PlanDocument],
    *,
    packet_id: str | None = None,
) -> PlanPacket:
    sheets: list[SheetInfo] = []
    received_ids: set[str] = set()
    all_sheets_referenced: set[str] = set()
    index_sheet_numbers: set[str] = set()

    for doc in documents:
        for page in doc.pages:
            sheet_no = page.sheet_number
            if sheet_no:
                received_ids.add(_sheet_id(sheet_no))
            text = page.text
            ref_sheets, ref_details = extract_references(text)
            all_sheets_referenced.update(_sheet_id(s) for s in ref_sheets)
            # cover/index page lists other sheet numbers
            if page.page_type == "COVER" and sheet_no:
                index_sheet_numbers.update(_sheet_id(s) for s in ref_sheets)
            has_legend = any(k in text.upper() for k in ("LEGEND", "SYMBOL"))
            sheets.append(SheetInfo(
                sheet_number=sheet_no,
                sheet_title=page.sheet_title,
                page_type=page.page_type,
                confidence=page.confidence,
                page_number=page.page_number,
                source_document=doc.original_filename,
                revision=doc.revision,
                referenced_sheets=list(dict.fromkeys(ref_sheets)),
                referenced_details=list(dict.fromkeys(ref_details)),
                keynote_set=[],
                legend_presence=has_legend,
                schedule_presence="SCHEDULE" in page.page_type.upper(),
                notes_presence="NOTES" in page.page_type.upper(),
            ))

    recognized = {s.sheet_number for s in sheets if s.sheet_number}
    recognized_ids = {_sheet_id(s) for s in recognized}
    mechanical = [s.sheet_number for s in sheets if s.is_mechanical and s.sheet_number]
    nonmechanical = [s.sheet_number for s in sheets
                     if not s.is_mechanical and s.sheet_number]
    missing = sorted(
        {sid for sid in all_sheets_referenced if sid not in received_ids}
    )
    # packet completeness: index lists more than received -> partial
    if index_sheet_numbers and index_sheet_numbers > received_ids:
        completeness = "PARTIAL_SET"
    elif len(sheets) <= 3 and not index_sheet_numbers:
        completeness = "UNKNOWN_COMPLETENESS"
    else:
        completeness = "FULL_SET"

    packet = PlanPacket(
        packet_id=packet_id or f"PKT-{len(sheets)}",
        document_hashes=[d.sha256 for d in documents],
        documents=[d.original_filename for d in documents],
        sheets=sheets,
        received_sheet_ids=sorted(received_ids),
        recognized_sheet_ids=sorted(recognized_ids),
        mechanical_sheet_ids=sorted(dict.fromkeys(mechanical)),
        nonmechanical_sheet_ids=sorted(dict.fromkeys(nonmechanical)),
        referenced_but_missing_sheet_ids=missing,
        packet_completeness=completeness,
    )
    for sid in missing:
        packet.missing_context.append({
            "kind": "REFERENCE_MISSING",
            "sheet_id": sid,
            "classification": "IMPORTANT_FOR_SCOPE"
            if sid.startswith("M") else "OPTIONAL_FOR_SCOPE",
        })
    return packet


def classify_missing_context(packet: PlanPacket, scope_text: str = "") -> list[dict[str, Any]]:
    """P37: scope-aware missing-context classification (never blanket BLOCK)."""
    out: list[dict[str, Any]] = []
    low = scope_text.lower()
    scope_mech = any(k in low for k in ("airflow", "balance", "tab", "verify",
                                        "cfm", "static", "rpm", "damper"))
    for sid in packet.referenced_but_missing_sheet_ids:
        classification = "IMPORTANT_FOR_SCOPE" if sid.startswith("M") else \
            "OPTIONAL_FOR_SCOPE"
        out.append({"kind": "REFERENCE_MISSING", "sheet_id": sid,
                    "classification": classification,
                    "detail": f"{sid} referenced on supplied sheets but not received"})
    has_legend = any(s.legend_presence for s in packet.sheets)
    if not has_legend and any(s.is_mechanical for s in packet.sheets):
        out.append({"kind": "LEGEND_NOT_SUPPLIED",
                    "classification": "IMPORTANT_FOR_SCOPE" if scope_mech else "OPTIONAL_FOR_SCOPE",
                    "detail": "no legend sheet supplied; symbol semantics are generic inference"})
    has_schedule = any(s.schedule_presence for s in packet.sheets)
    if not has_schedule and scope_mech:
        out.append({"kind": "SCHEDULE_CONTEXT_NOT_SUPPLIED",
                    "classification": "BLOCKING_FOR_SCOPE",
                    "detail": "no equipment/air-device schedule supplied"})
    return out


# ---------------------------------------------------------------------------
# Selective indexing for large combined sets (P2/P3)
# ---------------------------------------------------------------------------


def page_inventory(doc: plans.PlanDocument) -> list[dict[str, Any]]:
    """Cheap per-page inventory: sheet no/title/type/confidence + word count."""
    return [
        {
            "page": p.page_number,
            "sheet_number": p.sheet_number,
            "title": p.sheet_title,
            "type": p.page_type,
            "confidence": p.confidence,
            "native_words": len(p.words),
        }
        for p in doc.pages
    ]


def mechanical_relevance_rank(
    inventory: list[dict[str, Any]],
    *,
    scope_keywords: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Rank pages by mechanical relevance for the given scope."""
    keywords = [k.upper() for k in (scope_keywords or [])]
    ranked = []
    for entry in inventory:
        ptype = entry["type"]
        base = 1.0 if ptype in MECHANICAL_TYPES else 0.0
        if ptype in ("ELECTRICAL", "PLUMBING", "ARCHITECTURAL", "IRRELEVANT"):
            base = 0.0
        text = f"{entry.get('title') or ''} {entry.get('sheet_number') or ''}".upper()
        score = base + sum(0.2 for k in keywords if k in text)
        ranked.append({**entry, "relevance": round(score, 3)})
    ranked.sort(key=lambda e: (-e["relevance"], e["page"]))
    return ranked


def select_deep_pages(
    inventory: list[dict[str, Any]],
    *,
    scope_keywords: list[str] | None = None,
    max_pages: int | None = None,
    relevance_threshold: float = 0.9,
) -> tuple[list[int], dict[str, int]]:
    """Pages to deep-process (OCR/VLM) vs skip. Returns (pages, stats)."""
    ranked = mechanical_relevance_rank(inventory, scope_keywords=scope_keywords)
    deep = [e["page"] for e in ranked if e["relevance"] >= relevance_threshold]
    if max_pages:
        deep = deep[:max_pages]
    skipped = [e["page"] for e in inventory if e["page"] not in deep]
    return deep, {
        "DOCUMENT_PAGES": len(inventory),
        "MECHANICAL_RELEVANT_PAGES": sum(1 for e in ranked if e["relevance"] >= relevance_threshold),
        "DEEP_PROCESSED_PAGES": len(deep),
        "SKIPPED_IRRELEVANT_PAGES": len(skipped),
    }
