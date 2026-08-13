from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import io
import uuid

from .customers import ScsCustomerStore


MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5_000
MAX_COLUMNS = 100
MAX_CELL_CHARS = 32_768
ALLOWED_FIELDS = frozenset({"display_name", "customer_type", "legal_name", "contact_name", "email", "phone", "site_name", "service_address", "billing_address"})


@dataclass(frozen=True)
class ImportPreview:
    preview_id: str
    creates: tuple[dict[str, str], ...]
    matches: tuple[dict[str, object], ...]
    conflicts: tuple[dict[str, object], ...]
    rejections: tuple[dict[str, object], ...]
    expires_at: str


def _safe_cell(value: str) -> str:
    clean = value.strip()
    if clean.startswith(("=", "+", "-", "@")):
        return "'" + clean
    return clean


def preview_customer_csv(data: bytes, mapping: dict[str, str], store: ScsCustomerStore) -> ImportPreview:
    if len(data) > MAX_BYTES:
        raise ValueError("CSV exceeds 5 MiB limit")
    try:
        text = data.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        raise ValueError("CSV must be valid UTF-8") from None
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        headers = next(reader)
    except StopIteration:
        raise ValueError("CSV requires a header row") from None
    normalized_headers = [header.strip() for header in headers]
    if len(normalized_headers) > MAX_COLUMNS:
        raise ValueError("CSV exceeds 100 columns")
    if len(set(normalized_headers)) != len(normalized_headers):
        raise ValueError("CSV contains duplicate headers")
    if any(source not in normalized_headers for source in mapping):
        raise ValueError("mapping references an unknown header")
    if any(target not in ALLOWED_FIELDS for target in mapping.values()):
        raise ValueError("mapping contains an unsupported field")

    creates: list[dict[str, str]] = []
    matches: list[dict[str, object]] = []
    conflicts: list[dict[str, object]] = []
    rejections: list[dict[str, object]] = []
    index = {header: position for position, header in enumerate(normalized_headers)}
    for row_number, row in enumerate(reader, start=2):
        if row_number > MAX_ROWS + 1:
            raise ValueError("CSV exceeds 5,000 rows")
        if len(row) > MAX_COLUMNS:
            raise ValueError("CSV exceeds 100 columns")
        if any(len(value) > MAX_CELL_CHARS for value in row):
            raise ValueError("CSV cell exceeds size limit")
        values = {target: _safe_cell(row[index[source]] if index[source] < len(row) else "") for source, target in mapping.items()}
        display_name = values.get("display_name", "")
        customer_type = values.get("customer_type", "")
        if not display_name or customer_type not in {"residential", "commercial", "government", "internal"}:
            rejections.append({"row": row_number, "reason": "display_name and valid customer_type are required"})
            continue
        candidates = [item for item in store.search_customers(display_name, limit=20) if item.display_name.casefold() == display_name.casefold()]
        if len(candidates) == 1:
            matches.append({"row": row_number, "values": values, "customer_id": candidates[0].customer_id, "advisory": True})
        elif len(candidates) > 1:
            conflicts.append({"row": row_number, "values": values, "customer_ids": [item.customer_id for item in candidates]})
        else:
            creates.append(values)
    return ImportPreview("scs_imp_" + uuid.uuid4().hex, tuple(creates), tuple(matches), tuple(conflicts), tuple(rejections), (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat())
