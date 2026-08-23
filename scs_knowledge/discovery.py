"""Deterministic owner knowledge discovery + approval (M1.5B).

A file's physical presence under SCS_KNOWLEDGE_ROOT grants DISCOVERED only —
never technical authority. Documents flow through an explicit, durable owner
workflow with an AUTHORITATIVE state machine and cryptographic byte binding:

    DISCOVERED -> CLASSIFIED -> OWNER_APPROVED -> INDEXED
                  `-> BLOCKED        `-> PARSE_FAILED / STALE_CHANGED

M1.5B hardening:
  * one authoritative transition validator (BLOCKED/STALE/INDEXED cannot be
    generically re-approved; PARSE_FAILED requires an explicit retry)
  * approval/indexing is cryptographically bound to the exact discovered bytes
    (pre-ingest rehash + post-ingest source hash verification)
  * the durable manifest is versioned and validated; corruption fails closed
    and is never silently treated as a fresh empty store
  * authority mutation fails closed without an explicit SCS_KNOWLEDGE_ROOT.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from .ingestor import PARSER_VERSION, classify_document, ingest_file, sha256_of

INGESTION_STATES = ("DISCOVERED", "CLASSIFIED", "OWNER_APPROVED", "INDEXED",
                    "BLOCKED", "STALE_CHANGED", "PARSE_FAILED")
_SUPPORTED_SUFFIXES = (".pdf", ".txt", ".md", ".markdown", ".docx")

MANIFEST_VERSION = 1

# Authoritative transition table (M1.5B 5.1). "* -> STALE_CHANGED" is applied
# by rediscovery only; BLOCKED and STALE_CHANGED are terminal w.r.t. generic
# owner actions.
_TRANSITIONS: dict[str, set[str]] = {
    "DISCOVERED": {"CLASSIFIED", "BLOCKED"},
    "CLASSIFIED": {"OWNER_APPROVED", "BLOCKED"},
    "OWNER_APPROVED": {"INDEXED", "PARSE_FAILED"},
    "INDEXED": set(),
    "PARSE_FAILED": {"CLASSIFIED"},  # explicit retry only
    "BLOCKED": set(),
    "STALE_CHANGED": set(),
}


class DiscoveryLedgerError(Exception):
    """Raised when a mutation is attempted against an invalid ledger."""


class KnowledgeRootNotConfigured(Exception):
    """Authority mutation attempted without an explicit canonical root."""


class ForbiddenTransition(ValueError):
    """Raised when an owner action violates the discovery state machine."""


def knowledge_root_configured() -> bool:
    return bool(os.environ.get("SCS_KNOWLEDGE_ROOT"))


def _page_count(path: Path) -> int | None:
    if path.suffix.lower() != ".pdf":
        return None
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            return len(pdf.pages)
    except Exception:
        return None


def _new_discovery_id(relative_location: str, digest: str) -> str:
    import hashlib
    h = hashlib.sha256(f"{relative_location}::{digest}".encode("utf-8")).hexdigest()
    return f"DSC-{h[:12]}"


class KnowledgeDiscoveryStore:
    """Durable, versioned, fail-closed discovery manifest (M1.5B)."""

    def __init__(self, store_path: Path, *, root: Path | None = None) -> None:
        self._path = Path(store_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._root = Path(root) if root else self._path.parent
        self._lock = threading.RLock()
        self._records, self.ledger_state = self._load()

    # ---- ledger durability ------------------------------------------------

    def _load(self) -> tuple[dict[str, dict[str, Any]], str]:
        if not self._path.exists():
            return {}, "EMPTY"
        try:
            raw = self._path.read_text(encoding="utf-8")
        except Exception:
            return {}, "CORRUPT"
        try:
            data = json.loads(raw)
        except Exception:
            return {}, "CORRUPT"
        if not isinstance(data, dict):
            return {}, "CORRUPT"
        version = data.get("version")
        if version != MANIFEST_VERSION:
            return {}, "INCOMPATIBLE"
        records = data.get("records")
        if not isinstance(records, dict):
            return {}, "CORRUPT"
        return records, "OK"

    def _save(self) -> None:
        with self._lock:
            payload = {"version": MANIFEST_VERSION, "records": self._records}
            tmp = self._path.with_name(self._path.name + ".tmp")
            tmp.write_text(json.dumps(payload, indent=2, default=str),
                           encoding="utf-8")
            tmp.replace(self._path)
            self.ledger_state = "OK"

    def _require_ok_ledger(self) -> None:
        if self.ledger_state in ("CORRUPT", "INCOMPATIBLE"):
            raise DiscoveryLedgerError(
                f"DISCOVERY_LEDGER_STATE={self.ledger_state}")

    def _require_root(self) -> None:
        if not knowledge_root_configured():
            raise KnowledgeRootNotConfigured(
                "KNOWLEDGE_AUTHORITY_BLOCKED_ROOT_NOT_CONFIGURED")

    def _set_state(self, record: dict[str, Any], new_state: str) -> None:
        current = record.get("state", "DISCOVERED")
        if new_state not in _TRANSITIONS.get(current, set()):
            raise ForbiddenTransition(
                f"forbidden transition {current} -> {new_state}")
        record["state"] = new_state

    # ---- discovery (read-only, idempotent, byte-aware) ---------------------

    def discover(self, root: Path | None = None) -> list[dict[str, Any]]:
        root = Path(root) if root else self._root
        self._root = root
        if not root.exists():
            return self.list()
        self._require_ok_ledger()
        locations: dict[str, str] = {}
        for did, rec in self._records.items():
            loc = rec.get("relative_location")
            if loc and rec.get("state") != "STALE_CHANGED":
                locations[loc] = did
        with self._lock:
            for path in sorted(root.rglob("*")):
                if not path.is_file() or path.suffix.lower() not in _SUPPORTED_SUFFIXES:
                    continue
                if path.name == "library.db" or ".tmp" in path.suffixes:
                    continue
                try:
                    rel = str(path.relative_to(root))
                except ValueError:
                    rel = path.name
                digest = sha256_of(path)
                existing_id = locations.get(rel)
                if existing_id is not None:
                    existing = self._records[existing_id]
                    if existing.get("file_sha256") == digest:
                        existing["discovered_at"] = _now()
                        continue
                    # bytes changed: reviewable/approved -> STALE_CHANGED;
                    # BLOCKED stays BLOCKED (historical) and the new bytes become
                    # a NEW candidate.
                    if existing.get("state") in ("DISCOVERED", "CLASSIFIED",
                                                 "OWNER_APPROVED", "INDEXED",
                                                 "PARSE_FAILED"):
                        existing["state"] = "STALE_CHANGED"
                        existing["stale_reason"] = "file content changed"
                        existing["stale_at"] = _now()
                        locations[rel] = None  # force a new record
                first_text = ""
                if path.suffix.lower() in (".txt", ".md", ".markdown"):
                    try:
                        first_text = path.read_text(encoding="utf-8", errors="replace")[:2000]
                    except Exception:
                        first_text = ""
                did = _new_discovery_id(rel, digest)
                self._records[did] = {
                    "discovery_id": did,
                    "relative_location": rel,
                    "filename": path.name,
                    "file_sha256": digest,
                    "byte_size": path.stat().st_size,
                    "page_count": _page_count(path),
                    "candidate_source_type": classify_document(path.name, first_text),
                    "manufacturer": None, "model": None, "model_series": None,
                    "family_tags": [], "applicability": "UNKNOWN",
                    "edition": None,
                    "parser_version": PARSER_VERSION,
                    "discovered_at": _now(),
                    "state": "DISCOVERED",
                    "source_id": None,
                    "blocked_reason": None,
                }
                locations[rel] = did
            self._save()
        return self.list()

    def list(self) -> list[dict[str, Any]]:
        records = sorted(self._records.values(),
                         key=lambda r: (r.get("relative_location", "")))
        for r in records:
            r.setdefault("state", "DISCOVERED")
        return records

    def get(self, discovery_id: str) -> dict[str, Any] | None:
        return self._records.get(discovery_id)

    # ---- owner mutations ---------------------------------------------------

    def classify(self, discovery_id: str, **metadata: Any) -> dict[str, Any] | None:
        self._require_ok_ledger()
        record = self._records.get(discovery_id)
        if record is None:
            return None
        self._set_state(record, "CLASSIFIED")  # raises ForbiddenTransition
        for key in ("source_type", "manufacturer", "model", "model_series",
                    "family_tags", "applicability", "edition"):
            value = metadata.get(key)
            if value is not None:
                if key == "source_type":
                    record["candidate_source_type"] = value
                else:
                    record[key] = value
        self._save()
        return record

    def approve(self, discovery_id: str, *, verified_by: str = "owner",
                **metadata: Any) -> dict[str, Any] | None:
        self._require_ok_ledger()
        self._require_root()
        record = self._records.get(discovery_id)
        if record is None:
            return None
        if record.get("state") != "CLASSIFIED":
            raise ForbiddenTransition(
                f"forbidden transition {record.get('state')} -> OWNER_APPROVED")
        # exact-byte gate: re-hash the current file before granting authority
        if not self._bytes_match(record):
            self._mark_stale(record)
            return record
        for key in ("source_type", "manufacturer", "model", "model_series",
                    "family_tags", "applicability", "edition"):
            value = metadata.get(key)
            if value is not None:
                if key == "source_type":
                    record["candidate_source_type"] = value
                else:
                    record[key] = value
        self._set_state(record, "OWNER_APPROVED")
        record["approved_by"] = verified_by
        record["approved_at"] = _now()
        self._save()
        return record

    def block(self, discovery_id: str, reason: str = "") -> dict[str, Any] | None:
        self._require_ok_ledger()
        record = self._records.get(discovery_id)
        if record is None:
            return None
        self._set_state(record, "BLOCKED")
        record["blocked_reason"] = reason or "owner blocked"
        self._save()
        return record

    def retry(self, discovery_id: str) -> dict[str, Any] | None:
        """Explicit PARSE_FAILED -> CLASSIFIED retry (never automatic)."""
        self._require_ok_ledger()
        record = self._records.get(discovery_id)
        if record is None:
            return None
        self._set_state(record, "CLASSIFIED")
        self._save()
        return record

    def _bytes_match(self, record: dict[str, Any]) -> bool:
        path = self._root / record.get("relative_location", "")
        if not path.exists():
            return False
        return sha256_of(path) == record.get("file_sha256")

    def _mark_stale(self, record: dict[str, Any]) -> None:
        record["state"] = "STALE_CHANGED"
        record["stale_reason"] = "file content changed before approval/indexing"
        record["stale_at"] = _now()
        self._save()

    def mark_indexed(self, discovery_id: str, source_id: str) -> dict[str, Any] | None:
        self._require_ok_ledger()
        record = self._records.get(discovery_id)
        if record is None:
            return None
        self._set_state(record, "INDEXED")
        record["source_id"] = source_id
        record["indexed_at"] = _now()
        self._save()
        return record

    def mark_parse_failed(self, discovery_id: str, reason: str = "") -> dict[str, Any] | None:
        self._require_ok_ledger()
        record = self._records.get(discovery_id)
        if record is None:
            return None
        self._set_state(record, "PARSE_FAILED")
        record["blocked_reason"] = reason or "parse failed"
        self._save()
        return record

    def approve_and_index(self, discovery_id: str, library, *,
                          verified_by: str = "owner",
                          private_root: Path | None = None,
                          **metadata: Any) -> dict[str, Any] | None:
        """Approve then index, cryptographically bound to an immutable snapshot.

        The source is staged into a private immutable snapshot whose SHA must
        equal the discovery SHA; parsing/indexing consumes ONLY the snapshot.
        Any byte disagreement fails closed (STALE_CHANGED, no authority)."""
        self._require_ok_ledger()
        self._require_root()
        record = self._records.get(discovery_id)
        if record is None:
            return None
        if record.get("state") not in ("CLASSIFIED", "OWNER_APPROVED"):
            raise ForbiddenTransition(
                f"forbidden transition {record.get('state')} -> INDEXED")
        path = self._root / record["relative_location"]
        if not path.exists():
            self._mark_stale(record)
            return record
        # Deterministic source identity: ingest derives SRC-{sha[:10]} from the
        # snapshot bytes, and the snapshot SHA == discovery SHA, so cleanup can
        # always locate any partially-created source even if ingest throws
        # before returning a result (defect A2).
        expected_source_id = f"SRC-{record['file_sha256'][:10]}"
        # Phase 1: stage an immutable private snapshot (auto-removed on exit).
        import shutil
        from tempfile import TemporaryDirectory
        with TemporaryDirectory(prefix="scs_stage_") as staging:
            snapshot = Path(staging) / record["filename"]
            shutil.copy2(path, snapshot)
            if sha256_of(snapshot) != record["file_sha256"]:
                self._mark_stale(record)
                return record
            try:
                if record.get("state") == "CLASSIFIED":
                    record["approved_by"] = verified_by
                    record["approved_at"] = _now()
                    self._set_state(record, "OWNER_APPROVED")
                    for key in ("source_type", "manufacturer", "model", "model_series",
                                "family_tags", "applicability", "edition"):
                        value = metadata.get(key)
                        if value is not None:
                            if key == "source_type":
                                record["candidate_source_type"] = value
                            else:
                                record[key] = value
                    self._save()
                result = ingest_file(library, snapshot, private_root=private_root)
                if result.sha256 != record["file_sha256"]:
                    _cleanup_quarantine(library, expected_source_id, result.source_id)
                    self._mark_stale(record)
                    return record
                if result.source_state == "QUARANTINED":
                    _cleanup_quarantine(library, expected_source_id, result.source_id)
                    self.mark_parse_failed(discovery_id, "ingestion quarantined")
                    return self.get(discovery_id)
                library.verify_source(
                    result.source_id, method="OWNER_APPROVED", verified_by=verified_by,
                    verification_evidence=f"sha={record['file_sha256'][:16]} owner-approved",
                    manufacturer=record.get("manufacturer"),
                    document_number=None, edition=record.get("edition"), revision=None)
                library.mark_discovery_managed(result.source_id)
                self.mark_indexed(discovery_id, result.source_id)
            except (DiscoveryLedgerError, KnowledgeRootNotConfigured, ForbiddenTransition):
                raise
            except Exception as error:
                try:
                    _cleanup_quarantine(library, expected_source_id)
                except Exception as cleanup_error:
                    raise DiscoveryLedgerError(
                        f"KNOWLEDGE_CLEANUP_FAILED: {type(cleanup_error).__name__}"
                        f": {cleanup_error}") from error
                self.mark_parse_failed(discovery_id, f"{type(error).__name__}: {error}")
            return self.get(discovery_id)


def _cleanup_quarantine(library, *source_ids: str | None) -> None:
    """Quarantine every candidate source id; raises on any failure (no swallow)."""
    for source_id in source_ids:
        if source_id:
            library.quarantine_source(source_id)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# --- retained helpers --------------------------------------------------------


def discover_documents(root: Path) -> list[dict[str, Any]]:
    store = KnowledgeDiscoveryStore(root / "discovery.json", root=root)
    return store.discover(root)


def inventory(library) -> dict[str, Any]:
    sources = library.list_sources()
    rows = []
    counts: dict[str, int] = {}
    for source in sources:
        counts[source.ingestion_state] = counts.get(source.ingestion_state, 0) + 1
        rows.append({
            "source_id": source.source_id,
            "source_type": source.source_type,
            "title": source.title,
            "filename": source.filename or source.title,
            "file_sha256": (source.document_hash or "")[:12],
            "manufacturer": source.manufacturer or "UNKNOWN",
            "model": source.model or "UNKNOWN",
            "model_series": source.model_series or "UNKNOWN",
            "equipment_family_tags": source.equipment_family_tags,
            "edition": source.edition or "UNKNOWN",
            "page_count": source.page_count,
            "ingestion_state": source.ingestion_state,
            "owner_approval_state": source.owner_approval_state,
            "source_state": source.source_state,
        })
    return {
        "documents": rows,
        "counts": counts,
        "discovered": counts.get("DISCOVERED", 0),
        "classified": counts.get("CLASSIFIED", 0),
        "owner_approved": counts.get("OWNER_APPROVED", 0),
        "indexed": counts.get("INDEXED", 0),
        "blocked": counts.get("BLOCKED", 0),
    }


def approve_source(library, source_id: str, *, source_type: str | None = None,
                   manufacturer: str | None = None, model: str | None = None,
                   model_series: str | None = None,
                   equipment_family_tags: list[str] | None = None,
                   applicability: str | None = None, edition: str | None = None,
                   verified_by: str = "owner") -> dict[str, Any] | None:
    source = library.get_source(source_id)
    if source is None:
        return None
    # AUDIT-B2-03: discovery-managed sources may ONLY be promoted through their
    # discovery ID (with the hash/state gates). Legacy source-ID approval is
    # forbidden for them.
    if source.source_origin == "DISCOVERY_MANAGED":
        raise ForbiddenTransition(
            "DISCOVERY_MANAGED source cannot use legacy source-ID approval")
    if source_type:
        library.reclassify_source(source_id, source_type, manufacturer=manufacturer,
                                  applicability=applicability)
    library.verify_source(source_id, method="OWNER_APPROVED", verified_by=verified_by,
                          verification_evidence="owner-approved manual",
                          manufacturer=manufacturer, document_number=None,
                          edition=edition, revision=None)
    library._db.execute(
        "UPDATE sources SET ingestion_state='OWNER_APPROVED', "
        "owner_approval_state='APPROVED', model=COALESCE(?, model), "
        "model_series=COALESCE(?, model_series), "
        "equipment_family_tags=COALESCE(?, equipment_family_tags) "
        "WHERE source_id=?",
        (model, model_series,
         json.dumps(equipment_family_tags) if equipment_family_tags else None, source_id))
    library._db.commit()
    updated = library.get_source(source_id)
    return updated.to_dict() if updated else None


def block_source(library, source_id: str) -> dict[str, Any] | None:
    source = library.get_source(source_id)
    if source is None:
        return None
    library._db.execute(
        "UPDATE sources SET ingestion_state='BLOCKED', owner_approval_state='BLOCKED' "
        "WHERE source_id=?", (source_id,))
    library._db.commit()
    updated = library.get_source(source_id)
    return updated.to_dict() if updated else None
