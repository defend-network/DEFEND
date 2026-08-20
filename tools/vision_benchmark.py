"""Local vision stack benchmark for SCS TAB.

Runs QWEN_ONLY / MINICPM_ONLY / PADDLE_OCR / QWEN_PLUS_PADDLEOCR /
MINICPM_PLUS_PADDLEOCR over the synthetic ground-truth set under
C:\\SCS_DATA\\vision-benchmark and reports the owner's metrics.

Uses nvidia-smi for VRAM and psutil for RAM. Ollama models are expected to be
pulled already (qwen2.5vl:3b, minicpm-v). Photos stay on this machine.
"""
from __future__ import annotations

import json
import os
import statistics
import subprocess
import time
from pathlib import Path

import psutil

from scs_reports.vision import (
    CombinedProvider,
    ModelRouter,
    OllamaVisionProvider,
    PaddleOcrProvider,
)

BENCH_ROOT = Path(r"C:\SCS_DATA\vision-benchmark")
IMAGES = BENCH_ROOT / "images"
GT = json.loads((BENCH_ROOT / "ground_truth.json").read_text(encoding="utf-8"))

_PEAK_VRAM = 0.0
_PEAK_RAM = 0.0
_GPU_MIN = float("inf")


def _unload_models() -> None:
    ollama = r"C:\Users\thoma\AppData\Local\Programs\Ollama\ollama.exe"
    for model in ("qwen2.5vl:3b", "minicpm-v"):
        try:
            subprocess.run([ollama, "stop", model], capture_output=True, text=True, timeout=30)
        except Exception:
            pass
    time.sleep(3)


def _gpu_used() -> float:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        ).stdout
        return float(out.strip().splitlines()[0])
    except Exception:
        return 0.0


def _sample_ollama_vram() -> None:
    global _PEAK_VRAM, _GPU_MIN
    used = _gpu_used()
    _PEAK_VRAM = max(_PEAK_VRAM, used)
    _GPU_MIN = min(_GPU_MIN, used)


def _sample_ollama_ram() -> None:
    global _PEAK_RAM
    try:
        for proc in psutil.process_iter(["name"]):
            try:
                name = (proc.info["name"] or "").lower()
                if "ollama" in name:
                    _PEAK_RAM = max(_PEAK_RAM, proc.memory_info().rss / (1024 ** 2))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass


def _classify_facts(router, path: Path):
    classification, confidence = router.classify_photo(path)
    facts = list(router.candidate_nameplate_facts(path) or [])
    facts += list(router.candidate_display_facts(path) or [])
    return classification, confidence, facts


def _norm(value: str) -> str:
    return "".join(ch for ch in str(value).upper() if ch.isalnum() or ch in ".-")


def evaluate(router, config_name: str) -> dict:
    global _PEAK_VRAM, _PEAK_RAM, _GPU_MIN
    _PEAK_VRAM = _PEAK_RAM = 0.0
    _GPU_MIN = float("inf")

    times: list[float] = []
    class_hits = 0
    model_hits = serial_hits = equip_hits = reading_hits = unit_hits = 0
    model_total = serial_total = equip_total = reading_total = unit_total = 0
    false_facts = 0
    abstention_honest = 0
    abstention_total = 0
    per_image: list[dict] = []
    load_time: float | None = None
    _sample_ollama_vram()

    for ground in GT:
        path = IMAGES / ground["file"]
        start = time.perf_counter()
        classification, confidence, facts = _classify_facts(router, path)
        elapsed = time.perf_counter() - start
        if load_time is None:
            load_time = elapsed
        times.append(elapsed)
        _sample_ollama_vram()
        _sample_ollama_ram()

        expected_class = ground.get("classification", "UNKNOWN")
        class_hit = str(classification.value) == expected_class
        if class_hit:
            class_hits += 1

        values = {f["field"]: _norm(f["value"]) for f in facts}
        fields_present = {f["field"] for f in facts}
        all_text = [_norm(f["value"]) for f in facts] + [
            _norm(f["unit"]) for f in facts if f.get("unit")
        ]

        if ground.get("model"):
            model_total += 1
            if _norm(ground["model"]) in values.values():
                model_hits += 1
        if ground.get("serial"):
            serial_total += 1
            if _norm(ground["serial"]) in values.values():
                serial_hits += 1
        if ground.get("equipment_type"):
            equip_total += 1
            if _norm(ground["equipment_type"]) in values.values():
                equip_hits += 1
        for expected in ground.get("readings", []):
            reading_total += 1
            exp = _norm(expected["value"])
            if exp in values.values():
                reading_hits += 1
            if expected.get("unit"):
                unit_total += 1
                if _norm(expected["unit"]) in all_text:
                    unit_hits += 1

        invented = False
        if ground.get("model") is None and any(f["field"] == "model" for f in facts):
            invented = True
        if ground.get("serial") is None and any(f["field"] == "serial" for f in facts):
            invented = True
        if not ground.get("readings") and any(f["field"].startswith("reading_") for f in facts):
            invented = True
        if invented:
            false_facts += 1

        expected_readings = [r["value"] for r in ground.get("readings", [])]
        degraded = ground.get("degraded") or not expected_readings
        if degraded:
            abstention_total += 1
            if not facts or any(f.get("needs_confirmation") or f.get("confidence", 0) < 0.6 for f in facts):
                abstention_honest += 1

        per_image.append({
            "file": ground["file"],
            "expected": expected_class,
            "actual": str(classification.value),
            "class_hit": class_hit,
            "confidence": confidence,
            "facts": facts,
            "seconds": round(elapsed, 3),
        })

    n = len(GT)
    steady = times[1:] if len(times) > 1 else times
    summary = {
        "CONFIG": config_name,
        "PHOTO_CLASSIFICATION_ACCURACY": round(class_hits / n, 3),
        "MODEL_NUMBER_EXACT_MATCH": round(model_hits / model_total, 3) if model_total else None,
        "SERIAL_NUMBER_EXACT_MATCH": round(serial_hits / serial_total, 3) if serial_total else None,
        "EQUIPMENT_TYPE_ACCURACY": round(equip_hits / equip_total, 3) if equip_total else None,
        "NUMERIC_READING_EXACT_MATCH": round(reading_hits / reading_total, 3) if reading_total else None,
        "UNIT_EXACT_MATCH": round(unit_hits / unit_total, 3) if unit_total else None,
        "FALSE_FACT_RATE": round(false_facts / n, 3),
        "ABSTENTION_QUALITY": round(abstention_honest / abstention_total, 3) if abstention_total else None,
        "LOAD_TIME_SECONDS": round(load_time or 0.0, 3),
        "MEAN_SECONDS_PER_IMAGE": round(statistics.mean(steady), 3),
        "VRAM_USAGE_MIB": round(max(_PEAK_VRAM - _GPU_MIN, 0.0), 1),
        "RAM_USAGE_MIB": round(_PEAK_RAM, 1),
    }
    return {"summary": summary, "per_image": per_image}


def main(only: str | None = None) -> None:
    out = BENCH_ROOT / "benchmark_results.json"
    results: dict[str, dict] = {}
    if out.exists():
        results = json.loads(out.read_text(encoding="utf-8"))
    providers = {
        "QWEN_ONLY": OllamaVisionProvider("qwen2.5vl:3b"),
        "MINICPM_ONLY": OllamaVisionProvider("minicpm-v"),
        "PADDLE_OCR": PaddleOcrProvider(),
    }
    qwen = providers["QWEN_ONLY"]
    minicpm = providers["MINICPM_ONLY"]
    ocr = providers["PADDLE_OCR"]
    providers["QWEN_PLUS_PADDLEOCR"] = CombinedProvider(qwen, ocr)
    providers["MINICPM_PLUS_PADDLEOCR"] = CombinedProvider(minicpm, ocr)

    for name, provider in providers.items():
        if name in results:
            print(f"\n=== {name} === (already done, skipping)", flush=True)
            continue
        if only and name != only:
            continue
        print(f"\n=== {name} ===", flush=True)
        _unload_models()
        router = ModelRouter(extractor=provider) if isinstance(provider, PaddleOcrProvider) else ModelRouter(provider, provider)
        results[name] = evaluate(router, name)
        print(json.dumps(results[name]["summary"], indent=2), flush=True)
        out.write_text(json.dumps(results, indent=2), encoding="utf-8")
        if only:
            break
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    import sys
    main(only=sys.argv[1] if len(sys.argv) > 1 else None)