"""Contract manifest behavior: versioning, hashing, and drift detection.

Locks the failure mode where an adapter silently goes stale against a changed
provider contract (P3 / P28 of the multi-provider directive).
"""

from __future__ import annotations

from defend_integrations.contracts import (
    ContractManifest,
    contract_dir,
    drift_status,
    load_manifest,
    manifest_from_dict,
    manifest_path,
    record_contract_file,
    sha256_bytes,
    sha256_file,
    write_manifest,
)


def test_sha256_is_stable_and_content_sensitive(tmp_path):
    first = tmp_path / "a.bin"
    second = tmp_path / "b.bin"
    first.write_bytes(b"payload-one")
    second.write_bytes(b"payload-one")
    assert sha256_file(first) == sha256_file(second) == sha256_bytes(b"payload-one")
    second.write_bytes(b"payload-two")
    assert sha256_file(second) != sha256_file(first)


def test_manifest_round_trip(tmp_path):
    root = tmp_path / "contracts"
    manifest = ContractManifest(
        provider_id="sportradar_tt",
        contract_type="official_docs",
        source_url_or_origin="https://developer.sportradar.com",
        retrieved_at="2026-08-20T00:00:00Z",
        provider_version_if_known="v2",
        sha256="abc123",
        endpoint_count=42,
        auth_scheme="api_key",
        rate_limit_notes="trial limited",
        capability_summary="tt results/fixtures/rankings",
    )
    path = write_manifest(root, manifest)
    assert path == manifest_path(root, "sportradar_tt")
    loaded = load_manifest(root, "sportradar_tt")
    assert loaded is not None
    assert loaded.to_dict() == manifest.to_dict()
    assert manifest_from_dict(manifest.to_dict()).provider_id == "sportradar_tt"


def test_manifest_round_trip_is_idempotent(tmp_path):
    root = tmp_path / "contracts"
    manifest = ContractManifest(
        provider_id="sports_game_odds",
        contract_type="sdk",
        source_url_or_origin="https://github.com/SportsGameOdds",
        retrieved_at="2026-08-20T00:00:00Z",
        auth_scheme="header",
    )
    write_manifest(root, manifest)
    write_manifest(root, manifest)
    loaded = load_manifest(root, "sports_game_odds")
    assert loaded is not None
    assert loaded.to_dict() == manifest.to_dict()


def test_record_contract_file_pins_sha256(tmp_path):
    root = tmp_path / "contracts"
    artifact = tmp_path / "spec.json"
    artifact.write_text('{"openapi":"3.0.0"}', encoding="utf-8")
    manifest, manifest_path_ = record_contract_file(
        root,
        provider_id="rapidapi_tt_micro",
        contract_type="openapi",
        source_url_or_origin="https://rapidapi.com",
        contract_file=artifact,
        endpoint_count=12,
        auth_scheme="header",
    )
    assert manifest_path_.is_file()
    stored_artifact = root / "rapidapi_tt_micro-openapi.json"
    assert stored_artifact.is_file()
    assert manifest.sha256 == sha256_file(stored_artifact)
    assert manifest.endpoint_count == 12


def test_drift_detection_yes_no_unknown(tmp_path):
    root = tmp_path / "contracts"
    artifact = tmp_path / "spec.json"
    artifact.write_text('{"openapi":"3.0.0"}', encoding="utf-8")
    record_contract_file(
        root,
        provider_id="rapidapi_tabletennis",
        contract_type="openapi",
        source_url_or_origin="https://rapidapi.com",
        contract_file=artifact,
    )
    stored = root / "rapidapi_tabletennis-openapi.json"
    assert drift_status(root, "rapidapi_tabletennis", current_file=stored) == "NO"
    stored.write_text('{"openapi":"3.0.1","changed":true}', encoding="utf-8")
    assert drift_status(root, "rapidapi_tabletennis", current_file=stored) == "YES"
    assert drift_status(root, "rapidapi_tabletennis", current_file=None, current_sha256=None) == "UNKNOWN"
    assert drift_status(root, "never_recorded", current_file=stored) == "UNKNOWN"


def test_contract_dir_location():
    from pathlib import Path

    root = Path("C:/worktree")
    assert contract_dir(root) == Path("C:/worktree/docs/provider-contracts")