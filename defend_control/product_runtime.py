"""Product-independent runtime records for the Control Center.

The Control Center is a lightweight, model-independent administration
surface. Each product runtime is independently started/stopped on demand and
records its state persistently so a Control Center restart does not lose the
retained-provider truth.

STOP preserves the provider instance (retained). DESTROY is an explicit,
separate, owner-confirmed action and never happens automatically.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

# Centralized reserved model-forward ports (product-scoped, collision-free).
PRODUCT_FORWARD_PORTS: dict[str, int] = {
    "defend-ai": 8402,
    "defendcoder": 8403,
    "defendmarkets": 8404,
    "scs-ai": 8405,
}

# Product inference API ports (product-scoped, separate from the admin API
# on :8000 and the shared web UI on :3000).
PRODUCT_API_PORTS: dict[str, int] = {
    "defend-ai": 8401,
    "defendcoder": 8301,
    "defendmarkets": 8300,
    "scs-ai": 8300,
}

PRODUCT_IDS = ("defend-ai", "defendcoder", "defendmarkets", "scs-ai")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ProductRuntimeRecord:
    product_id: str
    state: str = "stopped"
    provider: str | None = None
    model_alias: str | None = None
    model_repo: str | None = None
    model_revision: str | None = None
    adapter_repo: str | None = None
    adapter_revision: str | None = None
    instance_id: int | None = None
    provider_instance_state: str | None = None
    gpu: str | None = None
    gpu_count: int | None = None
    gpu_ram_mb: int | None = None
    hourly_compute_cost: str | None = None
    retained_storage_cost: str | None = None
    model_forward_port: int | None = None
    product_api_port: int | None = None
    product_web_port: int | None = None
    started_at: str | None = None
    last_activity_at: str | None = None
    last_error: str | None = None

    def mark_activity(self) -> None:
        self.last_activity_at = utc_now()

    def as_public_dict(self) -> dict[str, object]:
        return {k: v for k, v in asdict(self).items()}


class ProductRuntimeRegistry:
    """Persisted JSON registry of per-product runtime records."""

    def __init__(self, path: Path | None = None) -> None:
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) / "DEFEND" if local_app_data else Path.cwd()
        self._path = path or (base / "product-runtime.json")

    def load(self) -> dict[str, ProductRuntimeRecord]:
        if not self._path.exists():
            return {pid: ProductRuntimeRecord(product_id=pid) for pid in PRODUCT_IDS}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {pid: ProductRuntimeRecord(product_id=pid) for pid in PRODUCT_IDS}
        records: dict[str, ProductRuntimeRecord] = {}
        for pid in PRODUCT_IDS:
            entry = raw.get(pid) if isinstance(raw, dict) else None
            if isinstance(entry, dict):
                entry = dict(entry)
                entry.pop("product_id", None)
                records[pid] = ProductRuntimeRecord(product_id=pid, **entry)
            else:
                records[pid] = ProductRuntimeRecord(product_id=pid)
        return records

    def save(self, records: dict[str, ProductRuntimeRecord]) -> None:
        payload = {pid: asdict(record) for pid, record in records.items()}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = __import__("tempfile").mkstemp(
            dir=self._path.parent,
            prefix=f".{self._path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self._path)
        finally:
            temporary_path.unlink(missing_ok=True)

    def update(self, product_id: str, **values: Any) -> ProductRuntimeRecord:
        if product_id not in PRODUCT_IDS:
            raise ValueError(f"unknown product {product_id!r}")
        records = self.load()
        record = records[product_id]
        for name, value in values.items():
            if not hasattr(record, name):
                raise ValueError(f"unknown runtime field {name!r}")
            setattr(record, name, value)
        record.mark_activity()
        self.save(records)
        return record