"""P1 + P10 — first-pass inventory of the REAL corpus with the local stack.

For each image: candidate classification, confidence, candidate facts, OCR
text lines, needs_review flag. Also captures P10 performance (cold load,
mean/P50/P95 per image, VRAM/RAM peaks). Output is NOT ground truth; it only
pre-fills the labeling workflow.
"""
from __future__ import annotations

import json
import os
import statistics
import subprocess
import time
from pathlib import Path

import psutil

from scs_reports.vision import build_vision_router

DEST = Path(r"C:\SCS_DATA\vision-benchmark\real")
DECODED = DEST / "decoded"

_PEAK_VRAM = 0.0
_PEAK_RAM = 0.0
_GPU_MIN = float("inf")


def _gpu_used() -> float:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        ).stdout
        return float(out.strip().splitlines()[0])
    except Exception:
        return 0.0


def _sample() -> None:
    global _PEAK_VRAM, _PEAK_RAM, _GPU_MIN
    used = _gpu_used()
    _PEAK_VRAM = max(_PEAK_VRAM, used)
    _GPU_MIN = min(_GPU_MIN, used)
    try:
        for proc in psutil.process_iter(["name"]):
            try:
                if "ollama" in (proc.info["name"] or "").lower():
                    _PEAK_RAM = max(_PEAK_RAM, proc.memory_info().rss / (1024 ** 2))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass


def main() -> None:
    manifest = json.loads((DEST / "manifest.json").read_text(encoding="utf-8"))
    router = build_vision_router()
    inventory: list[dict] = []
    times: list[float] = []
    load_time: float | None = None

    for entry in manifest:
        if entry.get("decoded_status") != "OK":
            inventory.append({**entry, "import_status": "SKIPPED_DECODE"})
            continue
        path = Path(entry["decoded_path"])
        start = time.perf_counter()
        classification, confidence = router.classify_photo(path)
        nameplate_facts = router.candidate_nameplate_facts(path)
        display_facts = router.candidate_display_facts(path)
        elapsed = time.perf_counter() - start
        if load_time is None:
            load_time = elapsed
        times.append(elapsed)
        _sample()

        ocr = router._extractor if hasattr(router, "_extractor") else None
        ocr_text: list[dict] = []
        if ocr is not None and hasattr(ocr, "extract_nameplate"):
            try:
                ocr_lines = ocr.extract_nameplate(path)
                ocr_text = [{"text": f["value"], "confidence": f["confidence"]} for f in ocr_lines]
            except Exception:
                ocr_text = []

        facts = list(nameplate_facts) + list(display_facts)
        needs_review = bool(
            classification.value == "UNKNOWN"
            or confidence is None
            or confidence < 0.6
            or any(f.get("needs_confirmation") for f in facts)
        )
        inventory.append(
            {
                "benchmark_id": entry["benchmark_id"],
                "photo_id": entry["photo_id"],
                "original_filename": entry["original_filename"],
                "sha256": entry["sha256"],
                "candidate_class": classification.value,
                "candidate_confidence": confidence,
                "candidate_facts": facts,
                "ocr_text": ocr_text,
                "needs_review": needs_review,
                "seconds": round(elapsed, 3),
                "local_copy_path": entry["local_copy_path"],
                "decoded_path": entry["decoded_path"],
            }
        )
        print(
            f"{entry['photo_id']} {entry['original_filename']}: "
            f"{classification.value} conf={confidence} facts={len(facts)} "
            f"ocr={len(ocr_text)} {elapsed:.1f}s",
            flush=True,
        )

    times_sorted = sorted(times)
    perf = {
        "FIRST_MODEL_LOAD_TIME_SECONDS": round(load_time or 0.0, 2),
        "TOTAL_CORPUS_PROCESS_TIME_SECONDS": round(sum(times), 2),
        "MEAN_SEC_IMAGE": round(statistics.mean(times), 2),
        "P50_SEC_IMAGE": round(statistics.median(times), 2),
        "P95_SEC_IMAGE": round(times_sorted[max(0, round(len(times_sorted) * 0.95) - 1)], 2),
        "VRAM_PEAK_MIB": round(max(_PEAK_VRAM - _GPU_MIN, 0.0), 1),
        "RAM_PEAK_MIB": round(_PEAK_RAM, 1),
        "ESTIMATED_50_PHOTO_JOB_PROCESS_TIME_SECONDS": round(statistics.mean(times) * 50, 2),
        "provider": os.environ.get("SCS_VISION_PROVIDER", "LOCAL_QWEN_PLUS_OCR"),
    }
    out = DEST / "inventory.json"
    out.write_text(json.dumps({"inventory": inventory, "performance": perf}, indent=2), encoding="utf-8")
    print(json.dumps(perf, indent=2))


if __name__ == "__main__":
    main()