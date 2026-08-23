"""Platform credential entitlement tests (Section 15, 16).

Verifies the neutral entitlement view: credential_key / provider /
configured / authorized_products / verification_state, no raw secret value ever
survives into a view, and verification state only follows a real passing probe.
"""

from __future__ import annotations

import json

import pytest

from defend_control.platform_credentials import (
    PlatformCredentialRegistry,
    verification_state,
)
from defend_integrations.models import HealthBadge
from defend_integrations.service import SetupIntegrationsService
from defend_integrations.stores import ProviderConfigStore, SecretRegistry

from tests.test_setup_stores import MemStore


def _service(tmp_path):
    secret_registry = SecretRegistry(MemStore())
    config_store = ProviderConfigStore(tmp_path / "config.json")
    service = SetupIntegrationsService(secret_registry, config_store)
    return service, secret_registry, config_store


def _provider_by_id(view, provider_id: str) -> dict:
    return next(
        provider
        for category in view["categories"]
        for provider in category["providers"]
        if provider["provider_id"] == provider_id
    )


def test_verification_state_vocabulary():
    assert (
        verification_state(
            configured=False,
            tested_at=None,
            health_badge=HealthBadge.NOT_CONFIGURED.value,
        )
        == "NOT_CONFIGURED"
    )
    assert (
        verification_state(
            configured=True,
            tested_at="2026-08-23T00:00:00Z",
            health_badge=HealthBadge.HEALTHY.value,
        )
        == "VERIFIED"
    )
    assert (
        verification_state(
            configured=True,
            tested_at=None,
            health_badge=HealthBadge.NOT_TESTED.value,
        )
        == "UNKNOWN"
    )
    assert (
        verification_state(
            configured=True,
            tested_at="2026-08-23T00:00:00Z",
            health_badge=HealthBadge.AUTH_FAILED.value,
        )
        == "FAILED"
    )


def test_entitlement_rows_include_intended_products(tmp_path):
    service, _, _ = _service(tmp_path)
    registry = PlatformCredentialRegistry(service)
    rows = {row["credential_key"]: row for row in registry.entitlement_rows()}
    assert "FRED_API_KEY" in rows
    fred = rows["FRED_API_KEY"]
    assert fred["provider"] == "fred"
    assert set(fred["intended_products"]) == {"defendmarkets", "scs"}
    assert fred["configured"] is False
    assert fred["verification_state"] == "NOT_CONFIGURED"
    assert fred["masked"] is None


def test_product_metadata_is_not_enforced_authorization(tmp_path):
    service, _, _ = _service(tmp_path)
    registry = PlatformCredentialRegistry(service)
    assert registry.product_use_enforcement() == "NOT_IMPLEMENTED"
    assert registry.to_dict()["product_use_enforcement"] == "NOT_IMPLEMENTED"


def test_configured_secret_masked_only_never_raw(tmp_path):
    service, secret_registry, config_store = _service(tmp_path)
    secret_registry.save({"FRED_API_KEY": "fred-super-secret-value"})
    config_store.record_probe(
        "fred",
        badge=HealthBadge.HEALTHY,
        tested_at="2026-08-23T00:00:00Z",
        detail="reachable",
        status_code=200,
        latency_ms=10,
        last_success_at="2026-08-23T00:00:00Z",
        remaining_quota=None,
        quota_reset_at=None,
    )
    registry = PlatformCredentialRegistry(service)
    data = registry.to_dict()
    assert data["configured"] == 1
    assert data["verified"] >= 1
    serialized = json.dumps(data)
    assert "fred-super-secret-value" not in serialized
    row = next(
        row
        for row in data["credentials"]
        if row["credential_key"] == "FRED_API_KEY"
    )
    assert row["masked"] == "****alue"
    assert row["verification_state"] == "VERIFIED"


def test_configured_never_verified_is_unknown(tmp_path):
    service, secret_registry, _ = _service(tmp_path)
    secret_registry.save({"FRED_API_KEY": "fred-other-secret"})
    registry = PlatformCredentialRegistry(service)
    row = next(
        row
        for row in registry.entitlement_rows()
        if row["credential_key"] == "FRED_API_KEY"
    )
    assert row["configured"] is True
    assert row["verification_state"] == "UNKNOWN"


def test_entitlement_rows_never_contain_raw_values(tmp_path):
    service, secret_registry, _ = _service(tmp_path)
    secret_registry.save(
        {
            "VAST_API_KEY": "vast-raw-value-1",
            "HF_TOKEN": "hf-raw-value-2",
        }
    )
    registry = PlatformCredentialRegistry(service)
    serialized = json.dumps(registry.to_dict())
    assert "vast-raw-value-1" not in serialized
    assert "hf-raw-value-2" not in serialized
    assert "masked" in serialized


def test_registry_rejects_wrong_service_type(tmp_path):
    with pytest.raises(TypeError):
        PlatformCredentialRegistry(object())  # type: ignore[arg-type]
