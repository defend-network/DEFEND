"""SCS_AI_TRAIN corpus inventory -> CORPUS_MANIFEST.json in SCS-managed storage.

READ-ONLY over the owner corpus (C:\\Users\\thoma\\OneDrive\\Documents\\
SunshineClimateSolutions\\SCS_AI_TRAIN). Never mutates the source directory.

Per file the manifest records:
    relative_path, filename, extension, size, sha256, modified_time,
    media_type, probable_category, tags[], category_confidence, parse_status

Duplicate groups (by sha256) and category counts are also emitted. The
manifest lives in SCS-managed storage (default C:\\SCS_DATA\\corpus\\), never
inside the source directory.

Usage:
    python tools/corpus_inventory.py [--corpus PATH] [--out PATH]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import sys
import time
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

CATEGORIES = [
    "COMPLETED_REPORT", "PARTIAL_REPORT", "MASTER_TEMPLATE",
    "FIELD_PHOTO", "NAMEPLATE_PHOTO", "INSTRUMENT_PHOTO", "DUCTWORK_PHOTO",
    "DEFICIENCY_PHOTO", "DRAWING", "SCHEDULE", "MANUFACTURER_DOC",
    "TAB_REFERENCE", "HVAC_REFERENCE", "INSTRUMENT_MANUAL", "CALIBRATION_DOC",
    "UNKNOWN",
]

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".gif", ".bmp", ".tif", ".tiff", ".webp"}
XLSX_EXTS = {".xlsx", ".xlsm"}
PDF_EXT = ".pdf"

# Keyword -> tags, applied to filenames (uppercased). Confidence per group.
PHOTO_KEYWORDS = [
    ("DUCTWORK_PHOTO", 0.8, ["DUCT", "PLENUM", "SHEETMETAL", "MASTIC", "SADDLE"]),
    ("DEFICIENCY_PHOTO", 0.75, ["POOR", "LEAK", "DIRTY", "BROKEN", "CRACKED", "DAMAGE", "BREAKING"]),
    ("INSTRUMENT_PHOTO", 0.8, ["RECOVERY", "MICRON", "SCALE", "TARE", "MANIFOLD", "GAUGE"]),
    ("NAMEPLATE_PHOTO", 0.7, ["NAMEPLATE", "LABEL", "SERIAL", "TAG"]),
    ("DUCTWORK_PHOTO", 0.6, ["DUCTWORK", "FILTER"]),
]
# Filenames that clearly indicate install / quality documentation photos
INSTALL_MARKERS = ("INSTALL", "BEND", "BRAZING", "COPPER", "LINE HIDE",
                   "DISCONNECT", "GAS PIPE", "CONDENSER", "MINISPLIT",
                   "PACKAGE UNIT", "FURNACE", "TRUCK", "MOBILE HOME",
                   "EXAMPLE", "QUALITY", "DEMO", "PERFECT", "PROPER",
                   "SHARP", "CUSTOM", "NEW", "HANGING", "HORIZONTAL",
                   "INSTALLED", "FIXED")

DOC_KEYWORDS = [
    ("DRAWING", 0.9, ["DWG", "LAYOUT", "COMBINED SET", "DRAWN"]),
    ("MANUFACTURER_DOC", 0.8, ["SUBMITTAL", "MANUAL", "DATA SHEET", "CATALOG", "NOMENCLATURE", "BROCHURE"]),
    ("COMPLETED_REPORT", 0.8, ["REPORT", "AIRFLOW", "VERIFICATION", "TAB REPORT", "FITNESS", "CRUNCH"]),
    ("PARTIAL_REPORT", 0.6, ["NOTES", "NOTES (", "FIELD NOTES"]),
    ("TAB_REFERENCE", 0.8, ["TAB MASTER", "BALANCE", "NEBB", "SMACNA"]),
    ("INSTRUMENT_MANUAL", 0.85, ["INSTRUMENT", "ANEMOMETER", "VELOCITY", "MANOMETER"]),
    ("CALIBRATION_DOC", 0.85, ["CALIBRATION", "CERT"]),
    ("SCHEDULE", 0.7, ["SCHEDULE", "SERIES"]),
    ("MASTER_TEMPLATE", 0.9, ["MASTER TEMPLATE", "MASTER"]),
]


def _tokens(upper: str) -> set[str]:
    return set(re.findall(r"[A-Z0-9]+", upper))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sniff(path: Path) -> dict:
    """Lightweight parse-status / structure check. Reads only file headers."""
    ext = path.suffix.lower()
    try:
        with open(path, "rb") as fh:
            head = fh.read(512)
    except OSError:
        return {"parse_status": "UNREADABLE", "format_detail": None}
    if ext in IMAGE_EXTS:
        return {"parse_status": "IMAGE", "format_detail": "magic-checked"}
    if ext == PDF_EXT:
        return {"parse_status": "PDF_OK" if head.startswith(b"%PDF") else "PDF_UNREADABLE",
                "format_detail": None}
    if ext in XLSX_EXTS:
        try:
            with zipfile.ZipFile(path) as zf:
                names = zf.namelist()
                has_workbook = any(n.endswith("workbook.xml") for n in names)
                has_vba = any("vbaProject.bin" in n for n in names)
                sheet_count = sum(1 for n in names if n.startswith("xl/worksheets/"))
            status = "XLSX_VALID" if has_workbook else "XLSX_STRUCTURE_UNEXPECTED"
            return {"parse_status": status,
                    "format_detail": {"sheet_files": sheet_count, "has_vba": has_vba}}
        except zipfile.BadZipFile:
            return {"parse_status": "XLSX_BAD_ZIP", "format_detail": None}
    return {"parse_status": "UNVERIFIED", "format_detail": None}


def classify(path: Path) -> dict:
    """Heuristic category assignment with confidence and multi-tags."""
    ext = path.suffix.lower()
    name = path.name
    upper = name.upper()
    if name.startswith("~$") or name.startswith("~"):
        return {"probable_category": "UNKNOWN", "tags": ["TRANSIENT_LOCK_FILE"],
                "category_confidence": 0.95, "note": "Office owner lock file"}
    tags: list[str] = []
    confidences: list[float] = []
    if ext in IMAGE_EXTS:
        for cat, conf, keys in PHOTO_KEYWORDS:
            if any(k in upper for k in keys):
                tags.append(cat)
                confidences.append(conf)
        if not tags:
            if any(m in upper for m in INSTALL_MARKERS):
                tags = ["FIELD_PHOTO"]
                confidences = [0.5]
                tags.append("INSTALL_QUALITY_PHOTO")
                confidences.append(0.5)
            else:
                tags = ["FIELD_PHOTO"]
                confidences = [0.35]
                tags.append("UNCLASSIFIED_CONTENT")
                confidences.append(0.35)
        elif "DEFICIENCY_PHOTO" in tags or "INSTRUMENT_PHOTO" in tags:
            # deficiency / instrument photos are also field photos
            tags.append("FIELD_PHOTO")
            confidences.append(0.7)
        else:
            tags.append("FIELD_PHOTO")
            confidences.append(0.6)
    else:
        for cat, conf, keys in DOC_KEYWORDS:
            if any(k in upper for k in keys):
                tags.append(cat)
                confidences.append(conf)
        if "PLANS" in upper:
            tags.append("DRAWING")
            confidences.append(0.9)
        if "COMPLETED_REPORT" in tags and "AIRFLOW" in upper and "VERIFICATION" in upper:
            tags.append("AIRFLOW_VERIFICATION_REPORT")
            confidences.append(0.9)
        if "INVOICE" in upper:
            tags.append("INVOICE")
            confidences.append(0.95)
        if "ESTIMATE" in upper:
            tags.append("ESTIMATE")
            confidences.append(0.95)
        if not tags:
            tags = ["UNKNOWN"]
            confidences = [0.3]
    canonical = [(t, c) for t, c in zip(tags, confidences) if t in CATEGORIES]
    if canonical:
        best = max(canonical, key=lambda x: x[1])
    else:
        best = ("UNKNOWN", max(confidences) if confidences else 0.3)
    return {"probable_category": best[0], "tags": tags,
            "category_confidence": best[1]}


def inventory(corpus_root: Path, out_path: Path) -> dict:
    files: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(corpus_root, followlinks=False):
        dirnames.sort()
        for fname in sorted(filenames):
            full = Path(dirpath) / fname
            rel = str(full.relative_to(corpus_root)).replace("\\", "/")
            try:
                st = full.stat()
            except OSError:
                continue
            if not os.path.isfile(full):
                continue
            hashed = sha256_file(full)
            media_type = mimetypes.guess_type(fname)[0] or "application/octet-stream"
            cls = classify(full)
            sniffed = sniff(full)
            files.append({
                "relative_path": rel,
                "filename": fname,
                "extension": full.suffix.lower(),
                "size": st.st_size,
                "sha256": hashed,
                "modified_time": time.strftime("%Y-%m-%dT%H:%M:%S",
                                               time.localtime(st.st_mtime)),
                "media_type": media_type,
                "probable_category": cls["probable_category"],
                "tags": cls["tags"],
                "category_confidence": cls["category_confidence"],
                "parse_status": sniffed["parse_status"],
                "format_detail": sniffed["format_detail"],
            })

    dup_groups: dict[str, list[str]] = defaultdict(list)
    for f in files:
        dup_groups[f["sha256"]].append(f["relative_path"])
    duplicates = {h: paths for h, paths in dup_groups.items() if len(paths) > 1}

    category_counts = Counter(f["probable_category"] for f in files)
    total_size = sum(f["size"] for f in files)

    manifest = {
        "manifest": {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "corpus_root": str(corpus_root),
            "source_read_only": True,
            "files_total": len(files),
            "size_bytes": total_size,
            "size_gb": round(total_size / (1024 ** 3), 4),
            "duplicate_groups": len(duplicates),
        },
        "files": files,
        "duplicates": duplicates,
        "category_counts": dict(category_counts),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus",
                        default=r"C:\Users\thoma\OneDrive\Documents\SunshineClimateSolutions\SCS_AI_TRAIN")
    parser.add_argument("--out", default=r"C:\SCS_DATA\corpus\CORPUS_MANIFEST.json")
    args = parser.parse_args()
    corpus_root = Path(args.corpus)
    if not corpus_root.is_dir():
        print(f"[corpus] source directory not found: {corpus_root}", file=sys.stderr)
        return 2
    manifest = inventory(corpus_root, Path(args.out))
    m = manifest["manifest"]
    print(f"CORPUS_MANIFEST -> {args.out}")
    print(f"  files={m['files_total']} size_GB={m['size_gb']} dup_groups={m['duplicate_groups']}")
    for cat, n in sorted(manifest["category_counts"].items(), key=lambda x: -x[1]):
        print(f"  {cat:20s} {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())