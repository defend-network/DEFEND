from __future__ import annotations

import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from typing import Any


STORE_ROOT = Path("artifacts/documents")
STORE_ROOT.mkdir(parents=True, exist_ok=True)


def _doc_dir(document_id: str) -> Path:
    d = STORE_ROOT / document_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_document(
    *,
    document_id: str,
    raw: bytes,
    metadata: dict[str, Any],
) -> str:
    d = _doc_dir(document_id)
    bin_path = d / "original.bin"
    meta_path = d / "meta.json"
    bin_path.write_bytes(raw)
    meta_path.write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")
    return str(bin_path)


def load_raw(document_id: str) -> bytes:
    path = _doc_dir(document_id) / "original.bin"
    if not path.exists():
        raise FileNotFoundError(f"Document not found: {document_id}")
    return path.read_bytes()


def load_meta(document_id: str) -> dict[str, Any]:
    path = _doc_dir(document_id) / "meta.json"
    if not path.exists():
        raise FileNotFoundError(f"Document metadata not found: {document_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def content_hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()