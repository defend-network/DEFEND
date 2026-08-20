"""Provider contract manifests: versioned, hashed records of the authoritative
API contracts each adapter is implemented against.

Manifest files live under ``docs/provider-contracts/`` (non-secret). Adapters
record which contract manifest version they were implemented against so a
provider contract change can be detected as CONTRACT_DRIFT instead of silently
treated as current.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


CONTRACT_DIR_NAME = "provider-contracts"


def contract_dir(worktree_root: Path) -> Path:
    return worktree_root / "docs" / CONTRACT_DIR_NAME


@dataclass(frozen=True)
class ContractManifest:
    """Versioned record of one authoritative provider contract."""

    provider_id: str
    contract_type: str  # openapi | schema | postman | official_docs | sdk | endpoint_catalog | empirical
    source_url_or_origin: str
    retrieved_at: str
    provider_version_if_known: str | None = None
    sha256: str | None = None
    endpoint_count: int | None = None
    schema_version: str | None = None
    auth_scheme: str = "unknown"
    rate_limit_notes: str | None = None
    capability_summary: str | None = None
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "contract_type": self.contract_type,
            "source_url_or_origin": self.source_url_or_origin,
            "retrieved_at": self.retrieved_at,
            "provider_version_if_known": self.provider_version_if_known,
            "sha256": self.sha256,
            "endpoint_count": self.endpoint_count,
            "schema_version": self.schema_version,
            "auth_scheme": self.auth_scheme,
            "rate_limit_notes": self.rate_limit_notes,
            "capability_summary": self.capability_summary,
            "notes": self.notes,
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"


def manifest_path(contract_dir_path: Path, provider_id: str) -> Path:
    return contract_dir_path / f"{provider_id}.contract.json"


def write_manifest(contract_dir_path: Path, manifest: ContractManifest) -> Path:
    contract_dir_path.mkdir(parents=True, exist_ok=True)
    path = manifest_path(contract_dir_path, manifest.provider_id)
    path.write_text(manifest.to_json(), encoding="utf-8")
    return path


def load_manifest(contract_dir_path: Path, provider_id: str) -> ContractManifest | None:
    path = manifest_path(contract_dir_path, provider_id)
    if not path.is_file():
        return None
    return manifest_from_dict(json.loads(path.read_text(encoding="utf-8")))


def manifest_from_dict(raw: dict[str, Any]) -> ContractManifest:
    return ContractManifest(
        provider_id=str(raw["provider_id"]),
        contract_type=str(raw["contract_type"]),
        source_url_or_origin=str(raw["source_url_or_origin"]),
        retrieved_at=str(raw["retrieved_at"]),
        provider_version_if_known=raw.get("provider_version_if_known"),
        sha256=raw.get("sha256"),
        endpoint_count=raw.get("endpoint_count"),
        schema_version=raw.get("schema_version"),
        auth_scheme=str(raw.get("auth_scheme", "unknown")),
        rate_limit_notes=raw.get("rate_limit_notes"),
        capability_summary=raw.get("capability_summary"),
        notes=raw.get("notes"),
    )


def record_contract_file(
    contract_dir_path: Path,
    *,
    provider_id: str,
    contract_type: str,
    source_url_or_origin: str,
    contract_file: Path,
    provider_version_if_known: str | None = None,
    endpoint_count: int | None = None,
    schema_version: str | None = None,
    auth_scheme: str = "unknown",
    rate_limit_notes: str | None = None,
    capability_summary: str | None = None,
    notes: str | None = None,
) -> tuple[ContractManifest, Path]:
    """Store a contract artifact alongside its manifest with a sha256 pin."""
    contract_dir_path.mkdir(parents=True, exist_ok=True)
    artifact_name = f"{provider_id}-{contract_type}.{contract_file.suffix.lstrip('.')}"
    if artifact_name == f"{provider_id}-{contract_type}":
        artifact_name = f"{provider_id}-{contract_type}.bin"
    artifact_path = contract_dir_path / artifact_name
    artifact_path.write_bytes(contract_file.read_bytes())
    manifest = ContractManifest(
        provider_id=provider_id,
        contract_type=contract_type,
        source_url_or_origin=source_url_or_origin,
        retrieved_at=utc_now_iso(),
        provider_version_if_known=provider_version_if_known,
        sha256=sha256_file(artifact_path),
        endpoint_count=endpoint_count,
        schema_version=schema_version,
        auth_scheme=auth_scheme,
        rate_limit_notes=rate_limit_notes,
        capability_summary=capability_summary,
        notes=notes,
    )
    manifest_path_ = write_manifest(contract_dir_path, manifest)
    return manifest, manifest_path_


def drift_status(
    contract_dir_path: Path,
    provider_id: str,
    current_file: Path | None = None,
    current_sha256: str | None = None,
) -> str:
    """Compare the recorded manifest pin against the current contract artifact.

    Returns YES when the pin no longer matches, NO when it matches, UNKNOWN
    when no manifest exists or no current artifact was provided.
    """
    manifest = load_manifest(contract_dir_path, provider_id)
    if manifest is None or manifest.sha256 is None:
        return "UNKNOWN"
    if current_sha256 is None and current_file is not None:
        current_sha256 = sha256_file(current_file)
    if current_sha256 is None:
        return "UNKNOWN"
    return "YES" if current_sha256 != manifest.sha256 else "NO"


def adapters_for_manifest(contract_dir_path: Path) -> dict[str, str]:
    """provider_id -> contract version recorded in each manifest."""
    if not contract_dir_path.is_dir():
        return {}
    result: dict[str, str] = {}
    for path in sorted(contract_dir_path.glob("*.contract.json")):
        manifest = load_manifest(contract_dir_path, path.stem.removesuffix(".contract"))
        if manifest is not None:
            result[manifest.provider_id] = manifest.provider_version_if_known or "unknown"
    return result