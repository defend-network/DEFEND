"""SCS Blueprint Intelligence benchmark.

Evaluates the plan pipeline against a ground-truth drawing set and reports the
owner metrics:

    SHEET_CLASSIFICATION_ACCURACY
    SCHEDULE_ROW_EXTRACTION_ACCURACY
    DEVICE_TAG_EXACT_MATCH
    CFM_EXACT_MATCH
    SIZE_EXACT_MATCH
    ROOM_ASSOCIATION_ACCURACY
    SYSTEM_ASSOCIATION_ACCURACY
    DEVICE_COUNT_ACCURACY
    DESIGN_TOTAL_EXACTNESS
    FALSE_FACT_RATE
    UNSUPPORTED_AUTOFILL_RATE

CFM_EXACT_MATCH and FALSE_FACT_RATE are the highest-priority metrics.

Usage:
    python tools/blueprint_benchmark.py [--fixture PATH] [--out PATH]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scs_reports.plans import run_document  # noqa: E402


def evaluate(basis: dict, ground_truth: dict) -> dict:
    # sheet classification
    expected_sheets = ground_truth["EXPECTED_SHEETS"]
    actual_by_page = {
        p["page"]: p["type"]
        for p in basis["sheet_classification"]
    }
    sheet_hits = sum(
        1 for page, (sheet, ptype) in expected_sheets.items()
        if actual_by_page.get(page) == ptype
    )
    sheet_accuracy = sheet_hits / len(expected_sheets) if expected_sheets else 0.0

    # equipment
    expected_equip = ground_truth.get("EXPECTED_EQUIPMENT", {})
    equip_hits = 0
    for tag, attrs in expected_equip.items():
        row = next((e for e in basis["equipment"] if e["tag"] == tag), None)
        if row and row.get("manufacturer") == attrs["manufacturer"] \
                and row.get("supply_cfm") == attrs["supply_cfm"]:
            equip_hits += 1
    equipment_accuracy = equip_hits / len(expected_equip) if expected_equip else 0.0

    # devices
    expected_devices = ground_truth.get("EXPECTED_DEVICES", {})
    actual = {d["device_id"]: d for d in basis["instances"]}
    tags_hit = sum(1 for tag in expected_devices if tag in actual)
    tag_exact = tags_hit / len(expected_devices) if expected_devices else 0.0

    cfm_hit = sum(
        1 for tag, attrs in expected_devices.items()
        if tag in actual and actual[tag].get("design_cfm") == attrs["cfm"]
    )
    cfm_exact = cfm_hit / len(expected_devices) if expected_devices else 0.0

    size_hit = sum(
        1 for tag, attrs in expected_devices.items()
        if tag in actual and actual[tag].get("size") == attrs.get("size")
    )
    size_exact = size_hit / len(expected_devices) if expected_devices else 0.0

    room_hit = sum(
        1 for tag, attrs in expected_devices.items()
        if tag in actual and (actual[tag].get("room") or "").upper() == attrs["room"].upper()
    )
    room_accuracy = room_hit / len(expected_devices) if expected_devices else 0.0

    device_count = len(expected_devices)
    found_count = len(actual)
    extra = found_count - device_count
    # extra instances are false positives (count against, but not double-punish)
    false_facts = extra + sum(
        1 for d in actual.values()
        if d.get("design_cfm") is not None and d["device_id"] not in expected_devices
    )
    false_fact_rate = false_facts / max(1, found_count)

    # design totals (supply per room)
    expected_totals = ground_truth.get("EXPECTED_SUPPLY_TOTALS", {})
    total_exact = 0
    for room, attrs in expected_totals.items():
        match = next(
            (t for t in basis["design_totals"]
             if t["scope"].upper() == room.upper() and t["function"] == "SUPPLY"),
            None,
        )
        if match and match["design_total_cfm"] == attrs["cfm"] \
                and match["device_count"] == attrs["count"]:
            total_exact += 1
    total_exactness = total_exact / len(expected_totals) if expected_totals else 0.0

    unsupported = sum(
        1 for tag in expected_devices
        if tag in actual and actual[tag].get("design_cfm") is None
    )
    unsupported_autofill = unsupported / len(expected_devices) if expected_devices else 0.0

    return {
        "DEVICES_EXPECTED": device_count,
        "DEVICES_FOUND": found_count,
        "SHEET_CLASSIFICATION_ACCURACY": round(sheet_accuracy, 4),
        "SCHEDULE_ROW_EXTRACTION_ACCURACY": round(equipment_accuracy, 4),
        "DEVICE_TAG_EXACT_MATCH": round(tag_exact, 4),
        "CFM_EXACT_MATCH": round(cfm_exact, 4),
        "SIZE_EXACT_MATCH": round(size_exact, 4),
        "ROOM_ASSOCIATION_ACCURACY": round(room_accuracy, 4),
        "DESIGN_TOTAL_EXACTNESS": round(total_exactness, 4),
        "FALSE_FACT_RATE": round(false_fact_rate, 4),
        "UNSUPPORTED_AUTOFILL_RATE": round(unsupported_autofill, 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture",
                        default=r"C:\SCS_DATA\corpus\fixtures\blueprint_fixture.pdf")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    fixture = Path(args.fixture)
    if not fixture.exists():
        print(f"[bench] fixture not found: {fixture}", file=sys.stderr)
        return 2
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests" / "fixtures"))
    from blueprint_ground_truth import (  # type: ignore
        EXPECTED_DEVICES,
        EXPECTED_EQUIPMENT,
        EXPECTED_SHEETS,
        EXPECTED_SUPPLY_TOTALS,
    )
    ground_truth = {
        "EXPECTED_SHEETS": EXPECTED_SHEETS,
        "EXPECTED_EQUIPMENT": EXPECTED_EQUIPMENT,
        "EXPECTED_DEVICES": EXPECTED_DEVICES,
        "EXPECTED_SUPPLY_TOTALS": EXPECTED_SUPPLY_TOTALS,
    }
    basis = run_document(fixture)
    metrics = evaluate(basis, ground_truth)
    print("Blueprint benchmark")
    for key, value in metrics.items():
        print(f"  {key:36s} {value}")
    if args.out:
        Path(args.out).write_text(
            json.dumps(metrics, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())