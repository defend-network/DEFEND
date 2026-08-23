"""DEFENDCODER_BENCH_V1 freeze guard (P0).

DEFENDCODER_BENCH_V1 is frozen: the 10 task definitions (classes A-J),
the fixture payloads, and the scoring rules may not change without a
V2. ``v1_manifest.json`` is the single snapshot of V1 (task fixtures,
expected outcomes, forbidden files, inspect requirements, scripts,
scoring rules). ``MANIFEST_SHA256`` pins that snapshot; tests assert
that both the manifest file and the live task sources still match, so
any accidental edit to V1 breaks loudly.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

MANIFEST_PATH = Path(__file__).with_name("v1_manifest.json")

#: SHA-256 of the canonical V1 manifest payload (sort_keys + indent=2).
MANIFEST_SHA256 = (
    "312186636649c553b42af9c26d0290cdbf5ef753d98cc1d03db199a0d4083563"
)


def manifest_payload() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def manifest_sha256(payload: dict | None = None) -> str:
    payload = payload if payload is not None else manifest_payload()
    canonical = dict(payload)
    canonical.pop("manifest_sha256", None)
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, default=str, indent=2).encode(
            "utf-8"
        )
    ).hexdigest()


def verify_manifest() -> dict[str, bool]:
    payload = manifest_payload()
    return {
        "file_present": MANIFEST_PATH.is_file(),
        "sha256_matches": manifest_sha256(payload) == MANIFEST_SHA256,
        "name_matches": payload.get("name") == "DEFENDCODER_BENCH_V1",
        "task_count_matches": len(payload.get("tasks", [])) == 10,
    }