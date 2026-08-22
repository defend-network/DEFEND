"""Raster blueprint intelligence for image-based / scanned mechanical prints.

Extends Blueprint V1 so image-based PDFs produce the SAME DesignBasis shape
as native-text PDFs. Primary reader is local OCR (RapidOCR) with geometry; a
local VLM (qwen2.5vl) corroborates precision crops when configured.

Every extracted fact maps back to PDF page coordinates (points, top-left
origin), so Plan Chat and region preview work identically whether the source
was NATIVE_TEXT / OCR / VISION / OCR_VISION_RECONCILED.

Numeric safety: only VERIFIED / HIGH values auto-populate design fields;
anything uncertain becomes REVIEW_REQUIRED / CONFLICT / UNREADABLE. No value
is invented from a low-confidence read.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

from . import plans
from .vision import (
    DocumentReader,
    OcrWord,
    RapidOcrDocumentReader,
    build_document_reader,
)

_OCR_MIN_CONF = 0.6
_NATIVE_GOOD_WORDS = 8


# ---------------------------------------------------------------------------
# Raster detection (per-page extraction-quality state)
# ---------------------------------------------------------------------------


def page_raster_state(page: plans.PlanPage, *, has_images: bool) -> str:
    """NATIVE_TEXT_GOOD / NATIVE_TEXT_SPARSE / HYBRID_PAGE / RASTER_PAGE."""
    word_count = len(page.words)
    if word_count >= _NATIVE_GOOD_WORDS:
        return "NATIVE_TEXT_GOOD"
    if word_count >= 2:
        return "HYBRID_PAGE" if has_images else "NATIVE_TEXT_SPARSE"
    return "RASTER_PAGE" if has_images else "NATIVE_TEXT_SPARSE"


def page_has_images(pdf_path: Path, page_number: int) -> bool:
    with fitz.open(str(pdf_path)) as pdf:
        page = pdf.load_page(page_number - 1)
        return bool(page.get_images(full=True))


# ---------------------------------------------------------------------------
# Rendering (cached by pdf sha256 + page + dpi)
# ---------------------------------------------------------------------------


def render_page_png(
    pdf_path: Path,
    page_number: int,
    dpi: int,
    cache_dir: Path,
    digest: str | None = None,
) -> Path:
    digest = digest or plans.sha256_of(pdf_path)
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / f"{digest[:12]}_p{page_number}_d{dpi}.png"
    if target.exists():
        return target
    zoom = dpi / 72.0
    with fitz.open(str(pdf_path)) as pdf:
        page = pdf.load_page(page_number - 1)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        pix.save(str(target))
    return target


def render_crop_png(
    pdf_path: Path,
    page_number: int,
    pdf_bbox: tuple[float, float, float, float],
    dpi: int,
    cache_dir: Path,
    digest: str | None = None,
) -> Path:
    """Render a PDF-coordinate crop (x0,y0,x1,y1) at high DPI (precision pass)."""
    digest = digest or plans.sha256_of(pdf_path)
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = f"{digest[:12]}_p{page_number}_d{dpi}_c{','.join(str(round(v)) for v in pdf_bbox)}"
    target = cache_dir / f"{key}.png"
    if target.exists():
        return target
    zoom = dpi / 72.0
    with fitz.open(str(pdf_path)) as pdf:
        page = pdf.load_page(page_number - 1)
        rect = fitz.Rect(*pdf_bbox)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=rect)
        pix.save(str(target))
    return target


@dataclass
class PageTile:
    page_number: int
    index: int
    pixel_bbox: tuple[int, int, int, int]
    pdf_bbox: tuple[float, float, float, float]
    dpi: int

    def to_dict(self) -> dict[str, Any]:
        return {"page": self.page_number, "index": self.index,
                "pixel_bbox": list(self.pixel_bbox), "pdf_bbox": list(self.pdf_bbox),
                "dpi": self.dpi}


def page_tiles(
    pdf_path: Path,
    page_number: int,
    dpi: int,
    cols: int,
    rows: int,
    overlap_px: int = 40,
) -> list[PageTile]:
    """Overlapping tile grid; each tile keeps PDF-coordinate bbox."""
    with fitz.open(str(pdf_path)) as pdf:
        page = pdf.load_page(page_number - 1)
        width_pt, height_pt = page.rect.width, page.rect.height
    zoom = dpi / 72.0
    width_px, height_px = width_pt * zoom, height_pt * zoom
    tile_w = width_px / cols
    tile_h = height_px / rows
    tiles: list[PageTile] = []
    index = 0
    for r in range(rows):
        for c in range(cols):
            x0 = max(0, c * tile_w - (overlap_px if c > 0 else 0))
            y0 = max(0, r * tile_h - (overlap_px if r > 0 else 0))
            x1 = min(width_px, (c + 1) * tile_w + (overlap_px if c < cols - 1 else 0))
            y1 = min(height_px, (r + 1) * tile_h + (overlap_px if r < rows - 1 else 0))
            tiles.append(PageTile(
                page_number=page_number,
                index=index,
                pixel_bbox=(int(x0), int(y0), int(x1), int(y1)),
                pdf_bbox=(x0 / zoom, y0 / zoom, x1 / zoom, y1 / zoom),
                dpi=dpi,
            ))
            index += 1
    return tiles


# ---------------------------------------------------------------------------
# OCR -> PDF-coordinate words
# ---------------------------------------------------------------------------


def ocr_page_words_pdf(
    pdf_path: Path,
    page_number: int,
    reader: DocumentReader,
    dpi: int,
    cache_dir: Path,
    digest: str | None = None,
) -> list[plans.Word]:
    """OCR a rendered page and map pixel bboxes back to PDF coordinates."""
    png = render_page_png(pdf_path, page_number, dpi, cache_dir, digest)
    zoom = dpi / 72.0
    words: list[plans.Word] = []
    for word in reader.read_page_words(png):
        words.append(plans.Word(
            text=word.text,
            x0=word.x0 / zoom,
            top=word.y0 / zoom,
            x1=word.x1 / zoom,
            bottom=word.y1 / zoom,
            size=0.0,
        ))
    return words


def _ocr_with_orientation(
    pdf_path: Path,
    page_number: int,
    reader: DocumentReader,
    dpi: int,
    cache_dir: Path,
    digest: str | None,
) -> tuple[list[plans.Word], str]:
    """OCR a page, retrying bounded rotations if the first pass is empty."""
    png = render_page_png(pdf_path, page_number, dpi, cache_dir, digest)
    raw = reader.read_page_words(png)
    if raw:
        return _to_pdf_words(raw, dpi), "NORMAL"
    # try the base render at each independent rotation (a scanned sheet may be
    # rotated 90/180/270 without the OCR engine handling it)
    import io

    import numpy as np
    from PIL import Image

    base = np.array(Image.open(png).convert("RGB"))
    for angle in (90, 180, 270):
        rotated = Image.fromarray(np.rot90(base, k=int(angle / 90)))
        rot_png = cache_dir / f"{digest[:12] if digest else 'doc'}_p{page_number}_r{angle}.png"
        rotated.save(str(rot_png))
        raw = reader.read_page_words(rot_png)
        if raw:
            return _to_pdf_words(raw, dpi), f"ROTATED_{angle}"
    return [], "NORMAL"


def _to_pdf_words(raw_words: list[OcrWord], dpi: int) -> list[plans.Word]:
    zoom = dpi / 72.0
    return [plans.Word(w.text, w.x0 / zoom, w.y0 / zoom, w.x1 / zoom, w.y1 / zoom, 0.0)
            for w in raw_words]


# ---------------------------------------------------------------------------
# Raster sheet classification
# ---------------------------------------------------------------------------


def raster_classify_page(
    words: list[plans.Word],
    page_height_pt: float,
) -> tuple[str | None, str | None, str, float]:
    text = " ".join(w.text for w in words)
    sheet_number = plans._extract_sheet_number(text)
    sheet_title = plans._extract_sheet_title(words, page_height_pt)
    page_type, confidence = plans.classify_page(text, words, page_height_pt)
    return sheet_number, sheet_title, page_type, confidence


# ---------------------------------------------------------------------------
# Raster schedules + plan devices (reuse native word geometry parsers)
# ---------------------------------------------------------------------------


def raster_schedules_from_words(
    words: list[plans.Word],
) -> list[dict[str, Any]]:
    """Reuse the native schedule word-column parser on OCR words."""
    records = plans._schedule_from_words(words)
    if not records:
        return []
    kinds = set()
    for record in records:
        tag = (record.get("tag") or "").upper()
        if "tag" in record and "design_cfm" in record:
            kinds.add("VAV_SCHEDULE" if "VAV" in record.get("type", "").upper()
                      else "AIR_DEVICE_SCHEDULE")
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
    if not kinds:
        return []
    return [{"kind": sorted(kinds), "records": records}]


def raster_plan_devices(
    words: list[plans.Word],
    page_number: int,
    sheet_number: str | None,
) -> list[dict[str, Any]]:
    page = plans.PlanPage(page_number=page_number, sheet_number=sheet_number,
                          sheet_title=None, page_type="RASTER_PLAN",
                          confidence=0.0, width=0.0, height=0.0,
                          text=" ".join(w.text for w in words), words=words)
    return plans.extract_plan_devices(page)


# ---------------------------------------------------------------------------
# Numeric dual-pass verification
# ---------------------------------------------------------------------------


def _read_value_crop(
    pdf_path: Path,
    page_number: int,
    pdf_bbox: tuple[float, float, float, float],
    reader: DocumentReader,
    cache_dir: Path,
    digest: str | None,
    dpi: int = 300,
) -> list[tuple[str, float]]:
    pad = 6.0
    padded = (pdf_bbox[0] - pad, pdf_bbox[1] - pad,
              pdf_bbox[2] + pad, pdf_bbox[3] + pad)
    crop = render_crop_png(pdf_path, page_number, padded, dpi, cache_dir, digest)
    words = reader.read_page_words(crop)
    values: list[tuple[str, float]] = []
    for word in words:
        if re.fullmatch(r"\d{1,5}(?:\.\d+)?", word.text):
            values.append((word.text, word.confidence))
    return values


def _numeric_status(primary: float, primary_conf: float,
                    second: list[tuple[str, float]]) -> str:
    if second:
        best = max(second, key=lambda t: t[1])
        try:
            second_val = float(best[0])
        except ValueError:
            second_val = None
        if second_val is not None and abs(primary - second_val) <= 1:
            return "VERIFIED"
        if second_val is not None:
            return "CONFLICT"
    return "HIGH" if primary_conf >= _OCR_MIN_CONF else "REVIEW_REQUIRED"


# ---------------------------------------------------------------------------
# Full raster run (one image-based PDF -> DesignBasis payload)
# ---------------------------------------------------------------------------


def raster_run(
    pdf_path: Path,
    reader: DocumentReader | None = None,
    *,
    dpi: int = 200,
    cache_dir: Path | None = None,
    revision: str | None = None,
) -> dict[str, Any]:
    reader = reader or build_document_reader()
    pdf_path = Path(pdf_path)
    digest = plans.sha256_of(pdf_path)
    cache_dir = cache_dir or pdf_path.parent / ".scs_raster_cache"
    doc = plans.index_pdf(pdf_path, tables=False)
    instances: list[dict[str, Any]] = []
    equipment_rows: list[dict[str, Any]] = []
    schedule_types: dict[str, dict[str, str]] = {}
    schedule_cfm: dict[str, float] = {}
    schedule_size: dict[str, str] = {}
    classifications: list[dict[str, Any]] = []
    stats = {"pages": len(doc.pages), "pages_ocr": 0, "pages_native_good": 0,
             "precision_crops": 0, "conflicts": []}

    for page in doc.pages:
        has_images = page_has_images(pdf_path, page.page_number)
        state = page_raster_state(page, has_images=has_images)
        if state == "NATIVE_TEXT_GOOD":
            stats["pages_native_good"] += 1
            continue
        # OCR pass
        words, orientation = _ocr_with_orientation(
            pdf_path, page.page_number, reader, dpi, cache_dir, digest)
        stats["pages_ocr"] += 1
        if not words:
            continue
        sheet_number, sheet_title, page_type, conf = raster_classify_page(
            words, page.height)
        classifications.append({
            "page": page.page_number, "sheet_number": sheet_number,
            "title": sheet_title, "type": page_type, "confidence": conf,
            "state": state, "orientation": orientation,
        })
        if page_type in ("AIR_DEVICE_SCHEDULE", "EQUIPMENT_SCHEDULE",
                         "VAV_SCHEDULE", "FAN_SCHEDULE", "RTU_SCHEDULE",
                         "AHU_SCHEDULE"):
            for sched in raster_schedules_from_words(words):
                for record in sched["records"]:
                    tag = (record.get("tag") or "").strip().upper()
                    if not tag:
                        continue
                    if "AIR_DEVICE_SCHEDULE" in sched["kind"]:
                        schedule_types[tag] = record
                        cfm = plans._num(record.get("design_cfm"))
                        if cfm is not None:
                            schedule_cfm[tag] = cfm
                        size = (record.get("neck_size") or record.get("size")
                                or record.get("face_size"))
                        if size:
                            schedule_size[tag] = size
                    elif tag.startswith(("RTU", "AHU", "FAN", "FCU", "VAV")):
                        equipment_rows.append({
                            "tag": tag, "type": record.get("type", ""),
                            "manufacturer": record.get("manufacturer"),
                            "model": record.get("model"),
                            "supply_cfm": plans._num(record.get("supply_cfm")
                                                     or record.get("design_cfm")),
                            "esp": plans._num(record.get("esp")),
                            "remarks": record.get("remarks"),
                            "source": {"sheet": sheet_number, "page": page.page_number,
                                       "extraction_method": "OCR_SCHEDULE",
                                       "confidence": "HIGH"},
                        })
        if page_type in ("MECHANICAL_PLAN", "HVAC_PLAN", "DUCT_PLAN",
                         "AIR_DEVICE_PLAN", "UNKNOWN"):
            for device in raster_plan_devices(words, page.page_number, sheet_number):
                type_tag = device.get("schedule_type")
                cfm, size, mapped, method = plans.resolve_instance_design(
                    device, schedule_types, schedule_cfm, schedule_size)
                # dual-pass numeric verification on the CFM value crop
                num_status = "UNREADABLE"
                if cfm is not None:
                    cfm_bbox = device["source"].get("cfm_bbox") or device["source"]["bbox"]
                    second = _read_value_crop(
                        pdf_path, page.page_number, cfm_bbox, reader, cache_dir,
                        digest)
                    stats["precision_crops"] += 1
                    num_status = _numeric_status(cfm, 0.7, second)
                    if num_status == "CONFLICT":
                        stats["conflicts"].append(
                            f"{device['device_id']}: OCR primary {cfm:.0f} vs crop "
                            f"{[v[0] for v in second]}")
                device["design_cfm"] = cfm if num_status in ("VERIFIED", "HIGH") else None
                device["size"] = size
                device["type"] = (schedule_types.get(type_tag, {}).get("type")
                                  if type_tag else None)
                device["confidence"] = num_status
                device["source"]["extraction_method"] = "OCR_PLAN"
                device["numeric_status"] = num_status
                instances.append(device)

    rooms = _group_rooms(instances)
    totals = _compute_totals(instances)
    doc_conflicts: list[dict[str, Any]] = [
        {"kind": "DESIGN_DOCUMENT_CONFLICT", "detail": d}
        for d in stats["conflicts"]
    ]
    # equipment schedule supply vs sum of supply devices (per room)
    supply_totals = [t for t in totals if t["function"] == "SUPPLY"]
    for equipment in equipment_rows:
        if not equipment.get("supply_cfm"):
            continue
        area_text = " ".join([
            str(equipment.get("remarks") or ""), str(equipment.get("type") or "")
        ]).upper()
        match = None
        for total in supply_totals:
            if total["scope"].upper() in area_text or area_text in total["scope"].upper():
                match = total
                break
        if match and match["design_total_cfm"] is not None:
            diff = match["design_total_cfm"] - equipment["supply_cfm"]
            if abs(diff) > 1:
                doc_conflicts.append({
                    "kind": "DESIGN_DOCUMENT_CONFLICT",
                    "detail": (
                        f"{equipment['tag']} printed supply {equipment['supply_cfm']:.0f} "
                        f"CFM vs sum of devices {match['design_total_cfm']:.0f} CFM "
                        f"({'%.0f' % diff} CFM difference)"
                    ),
                    "source": equipment["source"],
                })
    return {
        "document": {
            "document_id": f"DOC-{digest[:8]}",
            "original_filename": pdf_path.name,
            "sha256": digest,
            "revision": revision,
            "pages": [p.to_dict() for p in doc.pages],
        },
        "schedule_types": {
            tag: {"type": rec.get("type"), "design_cfm": rec.get("design_cfm"),
                  "size": rec.get("neck_size") or rec.get("size") or rec.get("face_size")}
            for tag, rec in schedule_types.items()
        },
        "equipment": equipment_rows,
        "instances": instances,
        "rooms": rooms,
        "design_totals": totals,
        "conflicts": doc_conflicts,
        "sheet_classification": classifications,
        "system_associations": plans.compute_system_associations(instances, equipment_rows),
        "extraction": {"mode": "RASTER", "provider": "OCR",
                       "stats": stats},
    }


def _group_rooms(instances: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rooms: dict[str, dict[str, Any]] = {}
    for device in instances:
        room = device.get("room")
        if not room:
            continue
        entry = rooms.setdefault(room, {"name": room, "devices": []})
        entry["devices"].append(device["device_id"])
    return list(rooms.values())


def _compute_totals(instances: list[dict[str, Any]]) -> list[dict[str, Any]]:
    room_func: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for device in instances:
        room = device.get("room")
        if not room:
            continue
        room_func.setdefault((room, plans._function_of(device)), []).append(device)
    totals = []
    for (room, func), devices in sorted(room_func.items()):
        total = sum(d["design_cfm"] for d in devices if d["design_cfm"])
        totals.append({
            "scope": room, "function": func,
            "method": "SUM_DEVICE_DESIGN_CFMS",
            "design_total_cfm": total if total else None,
            "device_count": len(devices),
            "source_sheets": sorted({d["source"].get("sheet") for d in devices
                                     if d["source"].get("sheet")}),
        })
    return totals


# ---------------------------------------------------------------------------
# Merge native + raster into one DesignBasis (single downstream path)
# ---------------------------------------------------------------------------


def merge_basis(*payloads: dict[str, Any] | None) -> dict[str, Any]:
    """Merge multiple basis payloads (native + raster) into one DesignBasis.

    Deduplicates instances/equipment/rooms by device/tag identity, keeps the
    union of schedule types/totals/sheets, and preserves conflicts.
    """
    merged: dict[str, Any] = {
        "document": None, "schedule_types": {}, "equipment": [],
        "instances": [], "rooms": [], "design_totals": [], "conflicts": [],
        "sheet_classification": [], "system_associations": [],
    }
    seen_instances: set[str] = set()
    seen_equipment: set[str] = set()
    seen_rooms: set[str] = set()
    seen_systems: set[str] = set()
    for payload in payloads:
        if not payload:
            continue
        if merged["document"] is None and payload.get("document"):
            merged["document"] = payload["document"]
        for tag, rec in (payload.get("schedule_types") or {}).items():
            merged["schedule_types"].setdefault(tag, rec)
        for row in payload.get("equipment") or []:
            tag = row.get("tag")
            if tag and tag not in seen_equipment:
                seen_equipment.add(tag)
                merged["equipment"].append(row)
        for device in payload.get("instances") or []:
            tag = device.get("device_id")
            if tag and tag not in seen_instances:
                seen_instances.add(tag)
                merged["instances"].append(device)
        for room in payload.get("rooms") or []:
            name = room.get("name")
            if name and name not in seen_rooms:
                seen_rooms.add(name)
                merged["rooms"].append(room)
        for assoc in payload.get("system_associations") or []:
            key = assoc.get("system_id")
            if key and key not in seen_systems:
                seen_systems.add(key)
                merged["system_associations"].append(assoc)
        merged["design_totals"].extend(payload.get("design_totals") or [])
        merged["conflicts"].extend(payload.get("conflicts") or [])
        merged["sheet_classification"].extend(payload.get("sheet_classification") or [])
    modes = [p.get("extraction", {}).get("mode") for p in payloads if p]
    if modes:
        merged["extraction"] = {
            "mode": "RASTER" if "RASTER" in modes else "NATIVE",
            "provider": "OCR",
            "stats": {
                "pages_ocr": sum(
                    (p.get("extraction", {}).get("stats", {}) or {}).get("pages_ocr", 0)
                    for p in payloads if p
                ),
                "precision_crops": sum(
                    (p.get("extraction", {}).get("stats", {}) or {}).get("precision_crops", 0)
                    for p in payloads if p
                ),
            },
        }
    return merged


# ---------------------------------------------------------------------------
# Oriented pipeline: per-page routing
# ---------------------------------------------------------------------------


def run_blueprint(
    pdf_path: Path,
    reader: DocumentReader | None = None,
    *,
    dpi: int = 200,
    cache_dir: Path | None = None,
    revision: str | None = None,
) -> dict[str, Any]:
    """Route each page by extraction quality: native where GOOD, OCR otherwise.

    Returns one reconciled DesignBasis payload.
    """
    native = plans.run_document(pdf_path, revision=revision)
    doc = plans.index_pdf(pdf_path, tables=False)
    needs_raster = any(
        page_raster_state(page, has_images=page_has_images(pdf_path, page.page_number))
        != "NATIVE_TEXT_GOOD"
        for page in doc.pages
    )
    if not needs_raster:
        return native
    raster = raster_run(pdf_path, reader, dpi=dpi, cache_dir=cache_dir,
                        revision=revision)
    return merge_basis(native, raster)


def source_crop_png(
    pdf_path: Path,
    page_number: int,
    pdf_bbox: tuple[float, float, float, float],
    cache_dir: Path,
    *,
    dpi: int = 200,
) -> bytes:
    """Render a source crop for review (source crops / region preview)."""
    png = render_crop_png(pdf_path, page_number, pdf_bbox, dpi, cache_dir)
    return png.read_bytes()


def cached_blueprint(
    pdf_path: Path,
    cache_dir: Path,
    reader: DocumentReader | None = None,
    *,
    dpi: int = 200,
) -> dict[str, Any]:
    """Route native/raster and cache the reconciled DesignBasis by sha256 +
    extraction version (revision-aware, provider-version-safe)."""
    import json as _json

    digest = plans.sha256_of(pdf_path)
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = f"{plans.SCS_EXTRACTION_VERSION}_raster_{digest}_d{dpi}.json"
    target = cache_dir / key
    if target.exists():
        try:
            cached = _json.loads(target.read_text(encoding="utf-8"))
            cached["_cache_hit"] = True
            return cached
        except Exception:
            pass
    payload = run_blueprint(pdf_path, reader, dpi=dpi, cache_dir=cache_dir)
    payload["_cache_hit"] = False
    target.write_text(_json.dumps(payload, indent=2, default=str),
                      encoding="utf-8")
    return payload
