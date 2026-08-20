"""REPORT-DRIVEN FACT-EXTRACTION BENCHMARK over the real-photo corpus.

Measures how completely the AI/OCR pipeline captures the report-expected
fields (SCS_REPORT_FIELD_CATALOG_V1) per photo, using the owner's metrics:

    VISIBLE_SUPPORTED_FACTS  per-photo expected-by-report facts with photo
                             evidence (every extracted fact is photo-backed;
                             schema fields without evidence are absent)
    FACTS_EXTRACTED          total facts with values
    FACT_RECALL              expected facts extracted / expected-by-report fields
    FACT_PRECISION           expected facts extracted / all facts extracted
    CRITICAL_FACT_RECALL     critical identity fields / critical expected
    FALSE_FACT_RATE          flagged facts (known error class or unresolved
                             conflict) / facts extracted

Owner labels (real/labels.json) additionally contribute CONFIRMED / REJECTED
fact counts and owner rejection rate where present.

Usage:
    python tools/vision_benchmark_real.py [--data C:/SCS_DATA/vision-benchmark/real]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from vision_autofill import (
    EQUIPMENT_TYPES, _READING_TO_FIELD, _unit_to_field_id,
    detect_manufacturer_from_ocr, detect_tag_from_ocr, extract_nameplate_readings,
    is_model_token, is_manufacturer_or_type_token, is_serial_token, ocr_tokens,
    reconcile,
)
import vision_field_catalog as catalog
from vision_field_catalog import FIELD_CATALOG_V1, FIELD_SECTIONS, section_of

CRITICAL_FIELDS = ("photo_type", "manufacturer", "model", "serial",
                   "equipment_type", "equipment_tag")
EVIDENCE_FIELDS = ("manufacturer", "model", "serial", "equipment_type",
                   "equipment_tag")


def visible_evidence_ids(p: dict) -> set[str]:
    """Canonical field ids that carry ANY photo evidence (VLM fact or OCR),
    whether or not a value could be extracted."""
    ids: set[str] = set()
    if p.get("candidate_class"):
        ids.add("photo_type")
    et = ""
    for f in p.get("candidate_facts") or []:
        if str(f.get("field") or "") == "equipment_type":
            et = str(f.get("value") or "")
            break
    pt = catalog.canonical_photo_type(p.get("candidate_class"), et)
    for f in p.get("candidate_facts") or []:
        fname = str(f.get("field") or "")
        if fname in EVIDENCE_FIELDS:
            ids.add(fname)
        elif fname.startswith("reading_"):
            fid = _unit_to_field_id(f.get("unit"), pt)
            if fid:
                ids.add(fid)
        else:
            fid = fname.lower().replace(" ", "_")
            if fid in FIELD_CATALOG_V1:
                ids.add(fid)
    ocr = p.get("ocr_text") or []
    mfr, _ = detect_manufacturer_from_ocr(ocr)
    if mfr:
        ids.add("manufacturer")
    tag = detect_tag_from_ocr(ocr)
    if tag:
        ids.add("equipment_tag")
    for r in extract_nameplate_readings(ocr, None):
        fid = _READING_TO_FIELD.get(r["reading_type"])
        if fid:
            ids.add(fid)
    for t in ocr_tokens(ocr):
        if is_model_token(t) and not is_manufacturer_or_type_token(t):
            ids.add("model")
        if is_serial_token(t):
            ids.add("serial")
        if t in EQUIPMENT_TYPES:
            ids.add("equipment_type")
    return ids


def load_photos(data_dir: Path) -> list[dict]:
    inv = json.loads((data_dir / "inventory.json").read_text(encoding="utf-8"))
    if isinstance(inv, dict) and "inventory" in inv:
        return list(inv["inventory"])
    if isinstance(inv, dict):
        out = []
        for v in inv.values():
            if isinstance(v, list):
                out.extend(v)
            elif isinstance(v, dict):
                out.append(v)
        return out
    return list(inv)


def flag_fact(f: dict) -> bool:
    """A fact is FALSE_RATE-flagged when it carries a known error class or an
    unresolved conflict (needs confirmation without OCR+VLM corroboration)."""
    return bool(f.get("error_class")) or bool(
        f.get("needs_confirmation") and f.get("corroboration") != "OCR+VLM")


def fact_metrics(data_dir: Path) -> dict:
    photos = load_photos(data_dir)
    labels_path = data_dir / "labels.json"
    labels = {}
    if labels_path.exists():
        labels = json.loads(labels_path.read_text(encoding="utf-8-sig")) or {}

    per_photo: list[dict] = []
    totals = Counter()
    section_exp: dict[str, int] = defaultdict(int)
    section_ext: dict[str, int] = defaultdict(int)
    schema_exp: dict[str, int] = defaultdict(int)
    schema_ext: dict[str, int] = defaultdict(int)

    for p in photos:
        pid = p.get("photo_id") or "?"
        proposal = reconcile(p)
        expected = list(proposal["expected"] or [])
        facts = [f for f in (proposal["facts"] or []) if f.get("value")]
        extracted_ids = {f["field_type"] for f in facts}
        exp_extracted = [f for f in facts if f["field_type"] in expected]
        flagged = [f for f in facts if flag_fact(f)]
        crit_expected = [c for c in CRITICAL_FIELDS if c in expected]
        crit_extracted = [c for c in crit_expected if c in extracted_ids]
        visible_ids = visible_evidence_ids(p)
        visible_supported = [fid for fid in expected if fid in visible_ids]
        visible_unextracted = [fid for fid in visible_supported
                               if fid not in extracted_ids]
        label = labels.get(pid) or {}
        lab_facts = label.get("facts") or {}
        owner_confirmed = [f for f in lab_facts.values()
                           if f.get("value") and not f.get("rejected")]
        owner_rejected = [f for f in lab_facts.values() if f.get("rejected")]
        owner_rejected_fields = set(label.get("rejected_fields") or [])

        row = {
            "photo_id": pid,
            "photo_type_schema": proposal["photo_type_schema"],
            "verdict": proposal["verdict"],
            "label_status": (label.get("status") or "UNLABELED"),
            "VISIBLE_SUPPORTED_FACTS": len(visible_supported),
            "FACTS_EXTRACTED": len(facts),
            "EXPECTED_FIELDS": len(expected),
            "ABSENT_FIELDS": len(proposal["absent_fields"] or {}),
            "CRITICAL_EXPECTED": len(crit_expected),
            "CRITICAL_EXTRACTED": len(crit_extracted),
            "FLAGGED_FACTS": len(flagged),
            "FLAGGED_FACT_IDS": [f["field_type"] for f in flagged],
            "EXTRACTED_FACT_IDS": sorted(extracted_ids),
            "EXPECTED_EXTRACTED_FACT_IDS": sorted(f["field_type"] for f in exp_extracted),
            "VISIBLE_UNEXTRACTED_FACT_IDS": sorted(visible_unextracted),
            "OWNER_CONFIRMED_FACTS": len(owner_confirmed),
            "OWNER_REJECTED_FACTS": len(owner_rejected)
            + len(owner_rejected_fields - extracted_ids),
        }
        per_photo.append(row)

        totals["photos"] += 1
        totals["extracted"] += len(facts)
        totals["expected"] += len(expected)
        totals["expected_extracted"] += len(exp_extracted)
        totals["visible_supported"] += len(visible_supported)
        totals["flagged"] += len(flagged)
        totals["critical_expected"] += len(crit_expected)
        totals["critical_extracted"] += len(crit_extracted)
        totals["owner_confirmed"] += len(owner_confirmed)
        totals["owner_rejected"] += (len(owner_rejected)
                                     + len(owner_rejected_fields - extracted_ids))
        for fid in expected:
            section_exp[section_of(fid)] += 1
            schema_exp[proposal["photo_type_schema"]] += 1
        for f in exp_extracted:
            section_ext[section_of(f["field_type"])] += 1
            schema_ext[proposal["photo_type_schema"]] += 1

    def rate(num: int, den: int) -> float:
        return round(num / den, 4) if den else 0.0

    section_recall = {
        sec: {"EXPECTED": section_exp.get(sec, 0),
              "EXTRACTED": section_ext.get(sec, 0),
              "RECALL": rate(section_ext.get(sec, 0), section_exp.get(sec, 0))}
        for sec in FIELD_SECTIONS
        if section_exp.get(sec, 0)
    }
    schema_recall = {
        sc: {"EXPECTED": schema_exp.get(sc, 0),
             "EXTRACTED": schema_ext.get(sc, 0),
             "RECALL": rate(schema_ext.get(sc, 0), schema_exp.get(sc, 0))}
        for sc in sorted(schema_exp)
    }

    result = {
        "BENCHMARK": "SCS_REPORT_FIELD_CATALOG_V1",
        "CORPUS": "SCS_VISION_BENCH_V1_REAL",
        "DATA_DIR": str(data_dir),
        "MASTER_FIELDS_DISCOVERED": len(FIELD_CATALOG_V1),
        "PHOTOS_TOTAL": totals["photos"],
        "FACTS_EXTRACTED": totals["extracted"],
        "EXPECTED_FIELDS_TOTAL": totals["expected"],
        "VISIBLE_SUPPORTED_FACTS": totals["visible_supported"],
        "FACT_RECALL": rate(totals["expected_extracted"], totals["visible_supported"]),
        "FACT_PRECISION": rate(totals["expected_extracted"], totals["extracted"]),
        "FACT_COVERAGE_OF_REPORT": rate(totals["expected_extracted"], totals["expected"]),
        "CRITICAL_FACT_RECALL": rate(totals["critical_extracted"], totals["critical_expected"]),
        "FALSE_FACT_RATE": rate(totals["flagged"], totals["extracted"]),
        "FLAGGED_FACTS": totals["flagged"],
        "OWNER_CONFIRMED_FACTS": totals["owner_confirmed"],
        "OWNER_REJECTED_FACTS": totals["owner_rejected"],
        "OWNER_REJECTION_RATE": rate(totals["owner_rejected"],
                                     totals["owner_confirmed"] + totals["owner_rejected"]),
        "SECTION_RECALL": section_recall,
        "SCHEMA_RECALL": schema_recall,
        "PER_PHOTO": per_photo,
    }
    out_path = data_dir / "benchmark_facts.json"
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result, out_path


def print_report(result: dict) -> None:
    print(f"Benchmark: {result['BENCHMARK']} | Corpus: {result['CORPUS']}")
    print(f"Photos: {result['PHOTOS_TOTAL']} | Catalog fields: {result['MASTER_FIELDS_DISCOVERED']}")
    print(f"  FACTS_EXTRACTED          {result['FACTS_EXTRACTED']}")
    print(f"  EXPECTED_FIELDS_TOTAL    {result['EXPECTED_FIELDS_TOTAL']}")
    print(f"  VISIBLE_SUPPORTED_FACTS  {result['VISIBLE_SUPPORTED_FACTS']}")
    print(f"  FACT_RECALL              {result['FACT_RECALL']} (extracted / visible-supported)")
    print(f"  FACT_PRECISION           {result['FACT_PRECISION']}")
    print(f"  FACT_COVERAGE_OF_REPORT  {result['FACT_COVERAGE_OF_REPORT']}")
    print(f"  CRITICAL_FACT_RECALL     {result['CRITICAL_FACT_RECALL']}")
    print(f"  FALSE_FACT_RATE          {result['FALSE_FACT_RATE']} ({result['FLAGGED_FACTS']} flagged)")
    print(f"  OWNER_CONFIRMED_FACTS    {result['OWNER_CONFIRMED_FACTS']}")
    print(f"  OWNER_REJECTED_FACTS     {result['OWNER_REJECTED_FACTS']}")
    print(f"  OWNER_REJECTION_RATE     {result['OWNER_REJECTION_RATE']}")
    print("Section recall:")
    for sec, m in result["SECTION_RECALL"].items():
        print(f"  {sec:24s} {m['EXTRACTED']:4d}/{m['EXPECTED']:<4d} recall {m['RECALL']}")
    print("Schema recall:")
    for sc, m in result["SCHEMA_RECALL"].items():
        print(f"  {sc:28s} {m['EXTRACTED']:4d}/{m['EXPECTED']:<4d} recall {m['RECALL']}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=r"C:\SCS_DATA\vision-benchmark\real")
    args = parser.parse_args()
    data_dir = Path(args.data)
    if not (data_dir / "inventory.json").exists():
        print(f"[bench] inventory.json not found in {data_dir}", file=sys.stderr)
        return 2
    result, out_path = fact_metrics(data_dir)
    print_report(result)
    print(f"[bench] report written to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())