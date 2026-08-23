"""P0 — import the real owner field-photo corpus (SCS_VISION_BENCH_V1_REAL).

Provenance rules:
- Drive originals are NEVER altered; downloads are read-only copies.
- Original filenames and bytes are preserved under real/imported/.
- Decoded PNG working copies go under real/decoded/ (HEIC -> PNG via
  pillow-heif; PNG/JPG copied as-is) for the LOCAL vision stack only.
- Every image gets a SHA-256; the manifest carries source provenance.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from PIL import Image
import pillow_heif  # noqa: F401  (registers HEIF with Pillow)

pillow_heif.register_heif_opener()

SOURCE_FOLDER = "https://drive.google.com/drive/folders/1CR5KSgDV6eOU5K_IfXGgJvGr2JLJH1BP?usp=drive_link"
BENCH_ID = "SCS_VISION_BENCH_V1_REAL"
STAGING = Path(r"C:\Users\thoma\AppData\Local\Temp\opencode\drive-scs-vision")
DEST = Path(r"C:\SCS_DATA\vision-benchmark\real")
IMPORTED = DEST / "imported"
DECODED = DEST / "decoded"

MAX_WORKING_DIMENSION = 1600

ORIGINAL_DATETIME = 36867
DATETIME = 306

IMAGE_EXTENSIONS = {".heic", ".heif", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def capture_timestamp(image: Image.Image) -> str | None:
    exif = image.getexif()
    for tag in (ORIGINAL_DATETIME, DATETIME):
        raw = exif.get(tag)
        if raw:
            try:
                return str(datetime.strptime(str(raw), "%Y:%m:%d %H:%M:%S"))
            except ValueError:
                return str(raw)
    return None


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    IMPORTED.mkdir(parents=True, exist_ok=True)
    DECODED.mkdir(parents=True, exist_ok=True)

    manifest: list[dict] = []
    seen_hashes: dict[str, str] = {}
    duplicates = 0
    skipped = 0
    total_bytes = 0

    files = sorted(
        (p for p in STAGING.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS),
        key=lambda p: p.name,
    )
    for index, source in enumerate(files, start=1):
        photo_id = f"PHOTO-{index:03d}"
        digest = sha256_of(source)
        total_bytes += source.stat().st_size
        if digest in seen_hashes:
            duplicates += 1
            manifest.append(
                {
                    "benchmark_id": BENCH_ID,
                    "source_folder": SOURCE_FOLDER,
                    "photo_id": photo_id,
                    "original_filename": source.name,
                    "sha256": digest,
                    "duplicate_of": seen_hashes[digest],
                    "import_status": "DUPLICATE",
                }
            )
            continue
        seen_hashes[digest] = photo_id

        local_copy = IMPORTED / source.name
        if not local_copy.exists():
            local_copy.write_bytes(source.read_bytes())

        entry: dict = {
            "benchmark_id": BENCH_ID,
            "source_folder": SOURCE_FOLDER,
            "photo_id": photo_id,
            "original_filename": source.name,
            "sha256": digest,
            "file_type": source.suffix.lower().lstrip("."),
            "local_copy_path": str(local_copy),
            "import_status": "IMPORTED",
        }
        try:
            image = Image.open(source)
            entry["dimensions"] = f"{image.width}x{image.height}"
            entry["capture_timestamp"] = capture_timestamp(image)
            if image.mode != "RGB":
                image = image.convert("RGB")
            if max(image.width, image.height) > MAX_WORKING_DIMENSION:
                scale = MAX_WORKING_DIMENSION / max(image.width, image.height)
                image = image.resize(
                    (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                    Image.LANCZOS,
                )
                entry["working_dimensions"] = f"{image.width}x{image.height}"
            working = DECODED / f"{photo_id}_{Path(source.stem).name}.png"
            image.save(working, format="PNG")
            entry["decoded_path"] = str(working)
            entry["decoded_status"] = "OK"
        except Exception as exc:  # noqa: BLE001
            skipped += 1
            entry["decoded_status"] = "FAILED"
            entry["decode_error"] = str(exc)[:200]
        manifest.append(entry)

    out = DEST / "manifest.json"
    out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    summary = {
        "DRIVE_FOLDER_ACCESS": "OK",
        "FILES_DISCOVERED": len(files),
        "IMAGES_IMPORTED": len(manifest) - duplicates,
        "IMAGES_SKIPPED": skipped,
        "DUPLICATES": duplicates,
        "TOTAL_BYTES": total_bytes,
        "manifest": str(out),
        "imported_dir": str(IMPORTED),
        "decoded_dir": str(DECODED),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()