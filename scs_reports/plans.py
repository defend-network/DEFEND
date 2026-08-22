"""SCS Blueprint / Plan Intelligence V1.

Deterministic, local-first plan extraction for mechanical construction
drawings. Layered pipeline per product spec:

    PASS 1  native PDF structure (text, words with bboxes, page size)
    PASS 2  sheet classification (sheet number + title + keyword scoring)
    PASS 3  schedule/table extraction (air-device + equipment schedules)
    PASS 4  plan device/tag + room + CFM-callout extraction (word bboxes)
    PASS 5  reconciliation (schedule mapping, plan-callout priority,
            design totals, document conflicts)

Never infers CFM from grille size; never invents duct dimensions; every
extracted value carries provenance (source_document, sheet, page, bbox,
extraction_method, confidence).

Design vs measured is never confused: this module only produces DESIGN basis.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pdfplumber

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass
class Word:
    text: str
    x0: float
    top: float
    x1: float
    bottom: float
    size: float = 0.0

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x0 + self.x1) / 2, (self.top + self.bottom) / 2)

    def bbox(self) -> tuple[float, float, float, float]:
        return (self.x0, self.top, self.x1, self.bottom)

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "x0": self.x0, "top": self.top,
                "x1": self.x1, "bottom": self.bottom, "size": self.size}


@dataclass
class PlanRegion:
    bbox: tuple[float, float, float, float]
    region_type: str
    text: str
    extraction_method: str
    confidence: str = "HIGH"

    def to_dict(self) -> dict[str, Any]:
        return {"bbox": list(self.bbox), "region_type": self.region_type,
                "text": self.text, "extraction_method": self.extraction_method,
                "confidence": self.confidence}


@dataclass
class PlanPage:
    page_number: int
    sheet_number: str | None
    sheet_title: str | None
    page_type: str
    confidence: float
    width: float
    height: float
    text: str
    words: list[Word] = field(default_factory=list)
    regions: list[PlanRegion] = field(default_factory=list)
    tables: list[list[list[str | None]]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_number": self.page_number,
            "sheet_number": self.sheet_number,
            "sheet_title": self.sheet_title,
            "page_type": self.page_type,
            "confidence": self.confidence,
            "width": self.width,
            "height": self.height,
            "text": self.text,
            "regions": [r.to_dict() for r in self.regions],
            "tables": self.tables,
        }


@dataclass
class PlanDocument:
    document_id: str
    original_filename: str
    sha256: str
    revision: str | None = None
    pages: list[PlanPage] = field(default_factory=list)

    def page(self, number: int) -> PlanPage | None:
        return next((p for p in self.pages if p.page_number == number), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "original_filename": self.original_filename,
            "sha256": self.sha256,
            "revision": self.revision,
            "pages": [p.to_dict() for p in self.pages],
        }


# ---------------------------------------------------------------------------
# Sheet / page classification
# ---------------------------------------------------------------------------

SHEET_TYPES = (
    "COVER", "INDEX", "MECHANICAL_GENERAL_NOTES", "MECHANICAL_PLAN",
    "HVAC_PLAN", "DUCT_PLAN", "AIR_DEVICE_PLAN", "EQUIPMENT_SCHEDULE",
    "AIR_DEVICE_SCHEDULE", "VAV_SCHEDULE", "FAN_SCHEDULE", "RTU_SCHEDULE",
    "AHU_SCHEDULE", "DETAIL", "SECTION", "CONTROL_DIAGRAM", "PLUMBING",
    "ELECTRICAL", "ARCHITECTURAL", "IRRELEVANT", "UNKNOWN",
)

_SHEET_NO_RE = re.compile(
    r"(?:^|\s)([MADEP][0-9]{1,2}(?:\.[0-9]+)?|[MADEP]-[0-9]{2,4}|[MADEP]\s*[0-9]{2,4})\b",
    re.IGNORECASE,
)
_TITLE_BLOCK_RE = re.compile(r"(MECHANICAL|HVAC|AIR DEVICE|EQUIPMENT|DETAIL|SECTION|DIAGRAM|PLAN|SCHEDULE|GENERAL NOTES|DUCT|VAV|RTU|AHU|FAN|PUMP|PIPE|PLUMBING|ELECTRICAL|ARCHITECTURAL)", re.IGNORECASE)

_TYPE_KEYWORDS: list[tuple[str, float, list[str]]] = [
    ("AIR_DEVICE_SCHEDULE", 0.9, ["AIR DEVICE SCHEDULE", "DIFFUSER SCHEDULE", "GRILLE SCHEDULE", "OUTLET SCHEDULE", "AIR DEVICE & GRILLE"]),
    ("EQUIPMENT_SCHEDULE", 0.9, ["EQUIPMENT SCHEDULE", "SCHEDULE OF EQUIPMENT", "UNIT SCHEDULE"]),
    ("VAV_SCHEDULE", 0.9, ["VAV SCHEDULE", "VARIABLE AIR VOLUME SCHEDULE", "TERMINAL UNIT SCHEDULE"]),
    ("FAN_SCHEDULE", 0.9, ["FAN SCHEDULE"]),
    ("RTU_SCHEDULE", 0.9, ["RTU SCHEDULE", "ROOFTOP SCHEDULE", "ROOFTOP UNIT SCHEDULE"]),
    ("AHU_SCHEDULE", 0.9, ["AHU SCHEDULE", "AIR HANDLER SCHEDULE", "AIR HANDLING UNIT SCHEDULE"]),
    ("MECHANICAL_GENERAL_NOTES", 0.85, ["GENERAL NOTES", "MECHANICAL NOTES", "GENERAL NOTES -", "NOTES AND LEGEND"]),
    ("MECHANICAL_PLAN", 0.7, ["MECHANICAL PLAN", "MECHANICAL FLOOR PLAN", "MECH SITE PLAN", "HVAC PLAN", "HVAC FLOOR PLAN"]),
    ("DUCT_PLAN", 0.7, ["DUCT PLAN", "DUCTWORK PLAN", "SUPPLY DUCT", "RETURN DUCT", "DUCT LAYOUT"]),
    ("AIR_DEVICE_PLAN", 0.6, ["AIR DEVICE", "OUTLET", "DIFFUSER", "GRILLE", "REGISTER", "TERMINAL PLAN"]),
    ("HVAC_PLAN", 0.7, ["HVAC PLAN", "HVAC LAYOUT", "HVAC FIRST", "HVAC SECOND"]),
    ("DETAIL", 0.75, ["DETAIL", "DETAILS", "TYPICAL DETAIL"]),
    ("SECTION", 0.75, ["SECTION", "SECTIONS", "BUILDING SECTION"]),
    ("CONTROL_DIAGRAM", 0.8, ["CONTROL DIAGRAM", "CONTROL SCHEMATIC", "DCC DIAGRAM", "SEQUENCE OF OPERATION"]),
    ("PLUMBING", 0.8, ["PLUMBING", "PIPING", "SANITARY", "WATER SUPPLY"]),
    ("ELECTRICAL", 0.8, ["ELECTRICAL", "POWER PLAN", "LIGHTING PLAN", "ONE-LINE", "RISER DIAGRAM"]),
    ("ARCHITECTURAL", 0.8, ["ARCHITECTURAL", "ARCH FLOOR", "FINISH PLAN", "RCP", "REFLECTED"]),
    ("COVER", 0.8, ["COVER SHEET", "TITLE SHEET", "DRAWING LIST", "SHEET INDEX"]),
]

_SHEET_NUMBER_TYPE_HINTS = {
    "MECHANICAL_PLAN": ("M",),
    "AIR_DEVICE_SCHEDULE": ("M",),
    "EQUIPMENT_SCHEDULE": ("M",),
    "DETAIL": ("M", "A"),
    "ELECTRICAL": ("E",),
    "PLUMBING": ("P",),
    "ARCHITECTURAL": ("A",),
}


def _extract_sheet_number(page_text: str) -> str | None:
    lines = [ln.strip() for ln in page_text.splitlines() if ln.strip()]
    for line in reversed(lines):
        match = re.search(r"([MADEP][0-9]{1,2}\.[0-9]+|[MADEP]-[0-9]{2,4})\b", line, re.IGNORECASE)
        if match:
            return match.group(1).upper()
    match = _SHEET_NO_RE.search(page_text)
    return match.group(1).upper() if match else None


def _extract_sheet_title(words: list[Word], page_height: float) -> str | None:
    """Heuristic title from large-font words or title-block lower region."""
    if not words:
        return None
    by_size = sorted(words, key=lambda w: w.size, reverse=True)
    large = [w.text for w in by_size[:40] if w.size >= max(6.0, by_size[0].size - 2)]
    candidate = " ".join(large)
    if _TITLE_BLOCK_RE.search(candidate):
        return candidate[:80]
    bottom = [w.text for w in words if w.top > page_height * 0.75]
    if bottom:
        joined = " ".join(bottom)
        if _TITLE_BLOCK_RE.search(joined):
            return joined[:80]
    return None


def classify_page(page_text: str, words: list[Word], page_height: float) -> tuple[str, float]:
    upper = page_text.upper()
    # Cover / index first: these list other sheet titles and would otherwise
    # match schedule keywords.
    if ("COVER" in upper or "SHEET INDEX" in upper or "DRAWING LIST" in upper
            or "TITLE SHEET" in upper):
        return "COVER", 0.9
    best_type = "UNKNOWN"
    best_score = 0.0
    for sheet_type, weight, keywords in _TYPE_KEYWORDS:
        hits = sum(1 for k in keywords if k.upper() in upper)
        if hits:
            score = weight * (1 - 0.25 * (len(keywords) - hits) / max(1, len(keywords)))
            if score > best_score:
                best_score = score
                best_type = sheet_type
    sheet_number = _extract_sheet_number(page_text)
    if sheet_number and best_type == "UNKNOWN":
        prefix = sheet_number[0]
        for sheet_type, prefixes in _SHEET_NUMBER_TYPE_HINTS.items():
            if prefix in prefixes:
                best_type = sheet_type
                best_score = 0.5
                break
    if best_type == "UNKNOWN" and words:
        title = _extract_sheet_title(words, page_height)
        if title and _TITLE_BLOCK_RE.search(title.upper()):
            best_type = "MECHANICAL_PLAN"
            best_score = 0.4
    return best_type, round(best_score, 2)


# ---------------------------------------------------------------------------
# Schedule extraction
# ---------------------------------------------------------------------------

_SCHEDULE_HEADER_ALIASES = {
    "tag": ("tag", "mark", "no.", "no", "device", "device tag", "equip no", "qty"),
    "type": ("type", "description", "unit type", "device type", "schedule type"),
    "manufacturer": ("manufacturer", "mfr", "mfgr", "make"),
    "model": ("model", "model no", "model number"),
    "service": ("service", "service/room", "room", "location", "serves", "served by"),
    "neck_size": ("neck size", "neck", "neck opening"),
    "face_size": ("face size", "face", "face dim", "overall size"),
    "size": ("size", "grille size", "diffuser size", "dimensions"),
    "design_cfm": ("design cfm", "cfm", "airflow", "air flow", "air quantity", "supply cfm", "capacity cfm"),
    "outside_air_cfm": ("outside air cfm", "oa cfm", "outside air"),
    "supply_cfm": ("supply cfm", "supply air cfm"),
    "exhaust_cfm": ("exhaust cfm", "return cfm", "relief cfm"),
    "esp": ("esp", "external static", "static pressure"),
    "voltage": ("voltage", "volt", "volts"),
    "phase": ("phase", "ph"),
    "capacity": ("capacity", "tons", "nominal capacity", "cooling capacity"),
    "model2": ("model no.", "model number"),
    "remarks": ("remarks", "note", "notes", "comments"),
}


def _norm_header(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^a-z0-9 ]", "", value.strip().lower())


def _header_role(cell: str | None) -> str | None:
    norm = _norm_header(cell)
    if not norm:
        return None
    best_role: str | None = None
    best_len = 0
    for role, aliases in _SCHEDULE_HEADER_ALIASES.items():
        for alias in aliases:
            a = _norm_header(alias)
            if norm == a or (len(a) > 3 and norm.startswith(a[:6])):
                if len(a) > best_len:
                    best_role = role
                    best_len = len(a)
    return best_role


def _table_to_records(table: list[list[str | None]]) -> list[dict[str, str]]:
    if not table:
        return []
    header_row = 0
    header_roles: list[str | None] = []
    for idx, row in enumerate(table[:4]):
        roles = [_header_role(cell) for cell in row]
        if sum(1 for r in roles if r) >= 2:
            header_row = idx
            header_roles = roles
            break
    if not header_roles or not any(header_roles):
        return []
    records: list[dict[str, str]] = []
    for row in table[header_row + 1:]:
        cells = ["" if c is None else str(c).strip() for c in row]
        if not any(cells):
            continue
        record: dict[str, str] = {}
        for col, role in enumerate(header_roles):
            if role and col < len(cells) and cells[col]:
                record.setdefault(role, cells[col])
        if record.get("tag") or any(v for v in record.values()):
            records.append(record)
    return records


def _words_to_rows(words: list[Word], y_tol: float = 6) -> list[list[Word]]:
    lines: list[list[Word]] = []
    for w in sorted(words, key=lambda x: (x.top, x.x0)):
        placed = False
        for line in lines:
            if abs(line[0].top - w.top) <= y_tol:
                line.append(w)
                placed = True
                break
        if not placed:
            lines.append([w])
    lines.sort(key=lambda ln: ln[0].top)
    return lines


_MERGE_HEADER_PAIRS = {
    "NECK SIZE", "DESIGN CFM", "SUPPLY CFM", "SUPPLY AIR CFM", "FACE SIZE",
    "MODEL NO", "MODEL NUMBER", "OUTSIDE AIR CFM", "EXHAUST CFM",
    "RETURN CFM", "GRILLE SIZE", "DIFFUSER SIZE", "NOMINAL CAPACITY",
    "COOLING CAPACITY", "UNIT TYPE", "DEVICE TYPE", "DESIGN AIRFLOW",
    "SUPPLY AIRFLOW", "AIRFLOW", "AIR FLOW",
}
_TAG_VALUE_RE = re.compile(
    r"^(?:SD|SA|RA|EA|EF|EG|RG|RF|SF|LI|CR|VAV|AD|SUP|RET|EXH|OA|RTU|AHU|"
    r"FCU|FAN|D|SI|RD)-?\d{1,3}$", re.IGNORECASE
)


def _schedule_from_words(words: list[Word]) -> list[dict[str, str]]:
    """Fallback schedule parse using word x/y alignment (gridless CAD text)."""
    lines = _words_to_rows(words)
    if not lines:
        return []
    # locate the header line (first line with >=2 role words)
    header_idx = -1
    header_phrases: list[tuple[int, str, float, float]] = []  # (x0, phrase, x1, role)
    for idx, line in enumerate(lines[:5]):
        role_words = sorted(
            ((w, _header_role(w.text)) for w in line),
            key=lambda t: t[0].x0,
        )
        roles = [(w, role) for w, role in role_words if role]
        if len(roles) < 3 or not any(r == "tag" for _w, r in roles):
            continue
        header_idx = idx
        phrases: list[tuple[float, str, float]] = []  # (x0, phrase, x1)
        for w, role in roles:
            if phrases and _MERGE_HEADER_PAIRS & {
                phrases[-1][1] + " " + w.text.upper()
            }:
                x0, phrase, _x1 = phrases[-1]
                phrases[-1] = (x0, phrase + " " + w.text.upper(), w.x1)
            else:
                phrases.append((w.x0, w.text.upper(), w.x1))
        header_phrases = [
            (x0, phrase, x1, _header_role(phrase)) for x0, phrase, x1 in phrases
        ]
        break
    if not header_phrases:
        return []
    # column x-ranges
    columns: list[tuple[float, float, str, str]] = []
    for i, (x0, phrase, x1, role) in enumerate(header_phrases):
        right = header_phrases[i + 1][0] if i + 1 < len(header_phrases) else 1e9
        columns.append((x0, right, phrase, role or ""))

    def column_of(word: Word) -> str | None:
        for x0, right, _phrase, role in columns:
            if x0 <= word.x0 < right:
                return role if role else None
        return None

    records: list[dict[str, str]] = []
    for line in lines[header_idx + 1:]:
        cells: list[str] = [""] * len(columns)
        for w in sorted(line, key=lambda x: x.x0):
            role = column_of(w)
            if role is None:
                continue
            idx = next(i for i, (_a, _b, _p, r) in enumerate(columns) if r == role)
            cells[idx] = (cells[idx] + " " if cells[idx] else "") + w.text
        record = {
            columns[i][3]: text.strip()
            for i, text in enumerate(cells)
            if text.strip()
        }
        tag = (record.get("tag") or "").strip()
        if tag and _TAG_VALUE_RE.match(tag):
            records.append(record)
    return records


def extract_schedules(page: PlanPage) -> list[dict[str, Any]]:
    """Return [{kind, records[], bbox, confidence}] from a page.

    Prefers the word/x-y alignment parser (robust for CAD-exported PDFs and
    gridless schedules), then falls back to pdfplumber table extraction.
    """
    out: list[dict[str, Any]] = []
    table_records = _schedule_from_words(page.words) if page.words else []
    if not table_records:
        for table in page.tables:
            table_records.extend(_table_to_records(table))
    if not table_records:
        return out
    kinds = set()
    for record in table_records:
        if "tag" in record and "design_cfm" in record:
            if any(k in record.get("type", "").upper()
                   for k in ("VAV", "TERMINAL")):
                kinds.add("VAV_SCHEDULE")
            else:
                kinds.add("AIR_DEVICE_SCHEDULE")
        elif "tag" in record and ("manufacturer" in record or "model" in record):
            if any(k in record.get("type", "").upper() for k in ("RTU", "ROOFTOP")):
                kinds.add("RTU_SCHEDULE")
            elif any(k in record.get("type", "").upper() for k in ("AHU", "AIR HANDLER")):
                kinds.add("AHU_SCHEDULE")
            elif any(k in record.get("type", "").upper() for k in ("FAN", "BLOWER")):
                kinds.add("FAN_SCHEDULE")
            else:
                kinds.add("EQUIPMENT_SCHEDULE")
        elif "tag" in record:
            kinds.add("EQUIPMENT_SCHEDULE")
    if kinds:
        out.append({"kind": sorted(kinds), "records": table_records})
    return out


# ---------------------------------------------------------------------------
# Plan device / room / CFM extraction
# ---------------------------------------------------------------------------

_DEVICE_TAG_RE = re.compile(
    r"^(?P<prefix>[A-Z]{1,3})(?:[- ]?)(?P<num>[0-9]{1,3})$"
)
_ROOM_RE = re.compile(
    r"^(WORKOUT STUDIO|SPIN STUDIO|STUDIO|OFFICE|LOCKER ROOM|MECHANICAL ROOM|"
    r"MECH ROOM|CORRIDOR|GYM|FITNESS|CLASSROOM|LOBBY|STORAGE|BATHROOM|RESTROOM|"
    r"BREAK ROOM|CONFERENCE|SUITE|SHOP|WAREHOUSE)( [A-Z0-9].*)?$"
)
_CFM_WORD_RE = re.compile(r"^\d{1,5}(?:\.\d+)?$")
_SIZE_RE = re.compile(
    r"^(\d{1,3}(?:\.\d+)?)[xX\u00d7](\d{1,3}(?:\.\d+)?)$|^(\d{1,3}(?:\.\d+)?)\s*(?:IN|\\\"|\\\")$"
)


def _is_device_tag(text: str) -> str | None:
    text = text.strip().upper()
    match = _DEVICE_TAG_RE.match(text)
    if not match:
        return None
    prefix, num = match.group("prefix"), match.group("num")
    if prefix in ("SD", "LD"):  # schedule TYPE references, not instances
        return None
    if prefix in ("SA", "RA", "EA", "EF", "EG", "RG", "RF", "SF", "LI", "CR",
                  "VAV", "AD", "SUP", "RET", "EXH", "OA", "D", "SI", "RD"):
        return f"{prefix}-{int(num):d}"
    return None


def _is_type_ref(text: str) -> str | None:
    text = text.strip().upper()
    match = _DEVICE_TAG_RE.match(text)
    if match and match.group("prefix") in ("SD", "LD"):
        return f"{match.group('prefix')}-{int(match.group('num')):d}"
    return None


def _line_words(words: list[Word], target: Word, y_tol: float = 8) -> list[Word]:
    return [w for w in words if abs(w.top - target.top) <= y_tol]


_ROOM_EXCLUDE = ("PLAN", "SCHEDULE", "DETAIL", "SECTION", "DIAGRAM", "NOTES",
                 "INDEX", "COVER", "GENERAL", "LEGEND", "DRAWING SET")


def _find_room(words: list[Word], tag: Word) -> tuple[str | None, float]:
    """Reconstruct a room label from line words; prefer strong room patterns
    over generic keyword hits and ignore sheet-title lines."""
    strong: list[tuple[str, float]] = []
    weak: list[tuple[str, float]] = []
    for w in words:
        line = _line_words(words, w)
        if not line:
            continue
        joined = " ".join(x.text for x in sorted(line, key=lambda x: x.x0))
        upper = joined.strip().upper()
        if not upper:
            continue
        if any(token in upper for token in _ROOM_EXCLUDE):
            continue
        if _ROOM_RE.match(upper):
            dist = ((w.x0 - tag.x0) ** 2 + (w.top - tag.top) ** 2) ** 0.5
            strong.append((upper, dist))
        elif len(upper) <= 40 and any(
            k in upper for k in ("GYM", "FITNESS", "OFFICE", "LOCKER",
                                 "CORRIDOR", "CLASSROOM", "LOBBY", "SUITE")
        ):
            dist = ((w.x0 - tag.x0) ** 2 + (w.top - tag.top) ** 2) ** 0.5
            weak.append((upper, dist))
    pool = strong or weak
    if not pool:
        return (None, 0.0)
    best = min(pool, key=lambda t: t[1])
    return (best[0], round(best[1], 1))


def _function_of(device: dict[str, Any]) -> str:
    prefix = device.get("device_id", "").upper().split("-")[0]
    if prefix in ("EF", "EA", "EXH"):
        return "EXHAUST"
    if prefix in ("RA", "RG", "RET", "RF"):
        return "RETURN"
    if prefix in ("OA",):
        return "OUTSIDE AIR"
    return "SUPPLY"


def extract_plan_devices(page: PlanPage) -> list[dict[str, Any]]:
    """Find device instances on a plan page; associate same-line CFM callouts,
    schedule-type references and the nearest room label."""
    devices: list[dict[str, Any]] = []
    tags = [w for w in page.words if _is_device_tag(w.text)]
    for tag in tags:
        tag_id = _is_device_tag(tag.text)
        line = _line_words(page.words, tag)
        type_ref: str | None = None
        cfm: float | None = None
        for w in sorted(line, key=lambda x: x.x0):
            if w is tag or w.x1 < tag.x1:
                continue
            ref = _is_type_ref(w.text)
            if ref:
                type_ref = ref
                continue
            if _CFM_WORD_RE.match(w.text):
                cfm = float(w.text.replace(",", ""))
                continue
            if "CFM" in w.text.upper():
                match = re.search(r"(\d{1,5})", w.text)
                if match:
                    cfm = float(match.group(1))
        room, room_dist = _find_room(page.words, tag)
        devices.append({
            "device_id": tag_id,
            "room": room,
            "design_cfm": cfm,
            "size": None,
            "schedule_type": type_ref,
            "source": {
                "sheet": page.sheet_number,
                "page": page.page_number,
                "bbox": tag.bbox(),
                "extraction_method": "NATIVE_TEXT",
            },
            "confidence": "HIGH" if cfm is not None else "MEDIUM",
        })
    return devices


# ---------------------------------------------------------------------------
# Reconciliation: schedule mapping + design totals + conflicts
# ---------------------------------------------------------------------------

def _num(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").strip()
    match = re.search(r"\d+(?:\.\d+)?", text)
    return float(match.group(0)) if match else None


def resolve_instance_design(
    device: dict[str, Any],
    schedule_types: dict[str, dict[str, str]],
    schedule_cfm: dict[str, float],
    schedule_size: dict[str, str],
) -> tuple[float | None, str | None, str | None, str]:
    """Priority: explicit plan CFM > device's own schedule row > type mapping.

    Size and type are always enriched from the schedule where available.
    """
    tag = device["device_id"]
    type_tag = device.get("schedule_type")
    own_size = schedule_size.get(tag)
    type_size = schedule_size.get(type_tag or "")
    size = own_size or type_size or device.get("size")
    plan_cfm = device.get("design_cfm")
    if plan_cfm is not None:
        return (plan_cfm, size, type_tag, "PLAN_CALLOUT")
    own_cfm = schedule_cfm.get(tag)
    if own_cfm is not None:
        return (own_cfm, size, tag, "SCHEDULE_MAPPING")
    if type_tag:
        cfm = schedule_cfm.get(type_tag)
        if cfm is not None:
            return (cfm, size, type_tag, "SCHEDULE_MAPPING")
    return (None, size, type_tag, "UNKNOWN")


def _schedule_index(records: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    for record in records:
        tag = (record.get("tag") or "").strip().upper()
        if tag:
            index.setdefault(tag, record)
    return index


# ---------------------------------------------------------------------------
# Pipeline / indexing / caching
# ---------------------------------------------------------------------------


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def index_pdf(
    path: Path,
    document_id: str | None = None,
    *,
    revision: str | None = None,
    tables: bool = True,
) -> PlanDocument:
    """Index a PDF into a PlanDocument (native text + words + bboxes)."""
    path = Path(path)
    digest = sha256_of(path)
    doc = PlanDocument(
        document_id=document_id or f"DOC-{digest[:8]}",
        original_filename=path.name,
        sha256=digest,
        revision=revision,
    )
    with pdfplumber.open(str(path)) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            words = [
                Word(w["text"], w["x0"], w["top"], w["x1"], w["bottom"],
                     float(w.get("size") or 0.0))
                for w in page.extract_words(keep_blank_chars=False,
                                            extra_attrs=["size"])
                if w.get("text")
            ]
            sheet_number = _extract_sheet_number(text)
            sheet_title = _extract_sheet_title(words, page.height)
            page_type, confidence = classify_page(text, words, page.height)
            tables_raw: list[list[list[str | None]]] = []
            if tables and page_type in (
                "AIR_DEVICE_SCHEDULE", "EQUIPMENT_SCHEDULE", "VAV_SCHEDULE",
                "FAN_SCHEDULE", "RTU_SCHEDULE", "AHU_SCHEDULE",
            ):
                try:
                    tables_raw = [t.extract() for t in page.find_tables()]
                except Exception:
                    tables_raw = []
            doc.pages.append(PlanPage(
                page_number=number,
                sheet_number=sheet_number,
                sheet_title=sheet_title,
                page_type=page_type,
                confidence=confidence,
                width=page.width,
                height=page.height,
                text=text,
                words=words,
                tables=tables_raw,
            ))
    return doc


def run_document(
    path: Path,
    document_id: str | None = None,
    *,
    revision: str | None = None,
) -> dict[str, Any]:
    """Full plan pipeline for one PDF -> DesignBasis payload."""
    doc = index_pdf(path, document_id, revision=revision)
    schedules_by_page: dict[int, list[dict[str, Any]]] = {}
    for page in doc.pages:
        if page.page_type in ("AIR_DEVICE_SCHEDULE", "EQUIPMENT_SCHEDULE",
                              "VAV_SCHEDULE", "FAN_SCHEDULE", "RTU_SCHEDULE",
                              "AHU_SCHEDULE"):
            schedules_by_page[page.page_number] = extract_schedules(page)

    schedule_types: dict[str, dict[str, str]] = {}
    schedule_cfm: dict[str, float] = {}
    schedule_size: dict[str, str] = {}
    equipment_rows: list[dict[str, Any]] = []
    for page_no, scheds in schedules_by_page.items():
        page = doc.page(page_no)
        for sched in scheds:
            for record in sched["records"]:
                tag = (record.get("tag") or "").strip().upper()
                if not tag:
                    continue
                if "AIR_DEVICE_SCHEDULE" in sched["kind"]:
                    schedule_types[tag] = record
                    cfm = _num(record.get("design_cfm"))
                    if cfm is not None:
                        schedule_cfm[tag] = cfm
                    size = (record.get("neck_size") or record.get("size")
                            or record.get("face_size"))
                    if size:
                        schedule_size[tag] = size
                elif tag.startswith(("RTU", "AHU", "FAN", "FCU", "VAV")):
                    equipment_rows.append({
                        "tag": tag,
                        "type": record.get("type", ""),
                        "manufacturer": record.get("manufacturer"),
                        "model": record.get("model"),
                        "supply_cfm": _num(record.get("supply_cfm")
                                           or record.get("design_cfm")),
                        "esp": _num(record.get("esp")),
                        "voltage": record.get("voltage"),
                        "phase": record.get("phase"),
                        "remarks": record.get("remarks"),
                        "source": {
                            "sheet": page.sheet_number if page else None,
                            "page": page_no,
                            "extraction_method": "SCHEDULE_TABLE",
                            "confidence": "HIGH",
                        },
                    })

    instances: list[dict[str, Any]] = []
    for page in doc.pages:
        if page.page_type not in (
            "MECHANICAL_PLAN", "HVAC_PLAN", "DUCT_PLAN", "AIR_DEVICE_PLAN",
            "UNKNOWN",
        ):
            continue
        for device in extract_plan_devices(page):
            type_tag = device.get("schedule_type")
            device["schedule_type"] = type_tag
            cfm, size, mapped_type, method = resolve_instance_design(
                device, schedule_types, schedule_cfm, schedule_size
            )
            device["design_cfm"] = cfm
            device["size"] = size
            type_record = schedule_types.get(type_tag) if type_tag else None
            device["type"] = type_record.get("type") if type_record else None
            device["source"]["extraction_method"] = method
            device["confidence"] = (
                "VERIFIED" if (cfm is not None and method != "UNKNOWN") else
                "HIGH" if cfm is not None else "LOW"
            )
            instances.append(device)

    rooms: dict[str, dict[str, Any]] = {}
    for device in instances:
        room = device.get("room")
        if not room:
            continue
        entry = rooms.setdefault(room, {"name": room, "devices": []})
        entry["devices"].append(device["device_id"])

    totals: list[dict[str, Any]] = []
    room_func: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for device in instances:
        room = device.get("room")
        if not room:
            continue
        func = _function_of(device)
        room_func.setdefault((room, func), []).append(device)
    for (room, func), devices in sorted(room_func.items()):
        total = sum(d["design_cfm"] for d in devices if d["design_cfm"])
        totals.append({
            "scope": room,
            "function": func,
            "method": "SUM_DEVICE_DESIGN_CFMS",
            "design_total_cfm": total if total else None,
            "device_count": len(devices),
            "source_sheets": sorted({d["source"]["sheet"] for d in devices
                                     if d["source"].get("sheet")}),
        })

    conflicts: list[dict[str, Any]] = []
    for equipment in equipment_rows:
        if not equipment.get("supply_cfm"):
            continue
        area_text = " ".join([
            str(equipment.get("remarks") or ""), str(equipment.get("type") or "")
        ])
        match = None
        for total in totals:
            if total["function"] != "SUPPLY":
                continue
            if total["scope"].upper() in area_text.upper() or \
                    area_text.upper() in total["scope"].upper():
                match = total
                break
        if match and match["design_total_cfm"] is not None:
            diff = match["design_total_cfm"] - equipment["supply_cfm"]
            if abs(diff) > 1:
                conflicts.append({
                    "kind": "DESIGN_DOCUMENT_CONFLICT",
                    "detail": (
                        f"{equipment['tag']} printed supply {equipment['supply_cfm']:.0f} CFM "
                        f"vs sum of devices {match['design_total_cfm']:.0f} CFM "
                        f"({'%.0f' % diff} CFM difference)"
                    ),
                    "source": equipment["source"],
                })

    return {
        "document": doc.to_dict(),
        "schedule_types": {
            tag: {
                "type": rec.get("type"),
                "design_cfm": rec.get("design_cfm"),
                "size": rec.get("neck_size") or rec.get("size") or rec.get("face_size"),
                "source": {"sheet": next(
                    (doc.page(pn).sheet_number for pn, s in schedules_by_page.items()
                     for sch in s if tag.upper() in
                     {(r.get("tag") or "").upper() for r in sch["records"]}
                     if doc.page(pn)),
                    None)}
            }
            for tag, rec in schedule_types.items()
        },
        "equipment": equipment_rows,
        "instances": instances,
        "rooms": list(rooms.values()),
        "design_totals": totals,
        "conflicts": conflicts,
        "sheet_classification": [
            {
                "page": p.page_number,
                "sheet_number": p.sheet_number,
                "title": p.sheet_title,
                "type": p.page_type,
                "confidence": p.confidence,
            }
            for p in doc.pages
        ],
    }


# ---------------------------------------------------------------------------
# JSON serialization / cache
# ---------------------------------------------------------------------------


def save_basis_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str),
                    encoding="utf-8")


def load_basis_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def cached_basis(path: Path, cache_dir: Path) -> dict[str, Any]:
    """Reuse extraction for the same PDF sha256 (never re-charge AI)."""
    digest = sha256_of(path)
    cache_file = cache_dir / f"{digest}.json"
    cached = load_basis_json(cache_file)
    if cached is not None:
        cached["_cache_hit"] = True
        return cached
    payload = run_document(path)
    payload["_cache_hit"] = False
    save_basis_json(payload, cache_file)
    return payload
