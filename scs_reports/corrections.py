"""Owner corrections become job knowledge (never overwrite provenance).

A correction stores the original extracted value, the corrected value, the
document hash, sheet/page/bbox, extraction method, corrected_by, timestamp and
optional reason. Re-uploading the same PDF hash can reapply known corrections
with an audit trail. Original extraction is never deleted.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def correction_key(sha256: str, sheet: str | None, device: str) -> str:
    return f"{sha256[:12]}::{sheet or '?'}::{device}"


def save_correction(
    store_path: Path,
    *,
    sha256: str,
    device: str,
    original_value: Any,
    corrected_value: Any,
    sheet: str | None = None,
    page: int | None = None,
    bbox: list[float] | None = None,
    extraction_method: str | None = None,
    corrected_by: str = "owner",
    reason: str | None = None,
) -> dict[str, Any]:
    """Record a correction, preserving the original extraction."""
    store_path = Path(store_path)
    store_path.parent.mkdir(parents=True, exist_ok=True)
    records = load_corrections(store_path)
    key = correction_key(sha256, sheet, device)
    record = {
        "key": key,
        "sha256": sha256,
        "device": device,
        "sheet": sheet,
        "page": page,
        "bbox": bbox,
        "original_value": original_value,
        "corrected_value": corrected_value,
        "extraction_method": extraction_method,
        "corrected_by": corrected_by,
        "reason": reason,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
    records[key] = record
    store_path.write_text(json.dumps(records, indent=2, default=str),
                          encoding="utf-8")
    return record


def load_corrections(store_path: Path) -> dict[str, dict[str, Any]]:
    store_path = Path(store_path)
    if not store_path.exists():
        return {}
    try:
        return json.loads(store_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def lookup_correction(store_path: Path, sha256: str, device: str,
                      sheet: str | None = None) -> dict[str, Any] | None:
    key = correction_key(sha256, sheet, device)
    return load_corrections(store_path).get(key)


def apply_known_correction(store_path: Path, sha256: str, device: str,
                           sheet: str | None = None) -> Any | None:
    """Return a known corrected value for a device, or None."""
    record = lookup_correction(store_path, sha256, device, sheet)
    if record is None:
        return None
    return record["corrected_value"]
