from __future__ import annotations

import json

import pytest

import defend_integrations.service as service_module
from defend_integrations.adapters import PLACEHOLDER_ADAPTER
from defend_integrations.models import (
    AdapterProbe,
    HealthBadge,
)
from defend_integrations.registry import find_provider
from defend_integrations.service import SetupIntegrationsService
from defend_integrations.stores import ProviderConfigStore, SecretRegistry

from tests.test_setup_stores import MemStore


class FakeAdapter:
    def __init__(self, probe: AdapterProbe):
        self._probe = probe
        self.calls = []

    def probe(self, definition, secrets, config):
        self.calls.append((definition.provider_id, secrets, config))
        return self._probe


def make_service(tmp_path, probe: AdapterProbe | None = None):
    secret_registry = SecretRegistry(MemStore())
    config_store = ProviderConfigStore(tmp_path / "config.json")
    service = SetupIntegrationsService(secret_registry, config_store)
    adapter = FakeAdapter(
        probe
        or AdapterProbe(
            ok=True,
            status_code=200,
            latency_ms=25,
            detail="reachable",
            authenticated=True,
        )
    )
    service_module.adapter_for = lambda definition: adapter
    return service, secret_registry, config_store, adapter


SECRET_VALUES = {
    "VAST_API_KEY": "super-secret-vast-value-abc123",
    "HF_TOKEN": "super-secret-hf-value-abc123",
    "FRED_API_KEY": "super-secret-fred-value-abc123",
    "CONGRESS_API_KEY": "super-secret-congress-value-abc123",
    "THE_ODDS_API_KEY": "super-secret-odds-value-abc123",
    "DEFEND_OWNER_USER": "super-secret-owner-user-abc123",
}


def dump_payloads(*payloads) -> str:
    return json.dumps(payloads)


def test_snapshot_has_twelve_categories_and_never_leaks_secrets(tmp_path):
    service, _, _, _ = make_service(tmp_path)
    for name, value in SECRET_VALUES.items():
        service._secrets.save({name: value})
    snapshot = service.snapshot()
    assert len(snapshot["categories"]) == 12
    assert set(snapshot["product_providers"]) == {
        "defend_ai",
        "defendcoder",
        "defendmarkets",
        "scs",
    }
    serialized = dump_payloads(snapshot)
    for value in SECRET_VALUES.values():
        assert value not in serialized
    # Masked views still show the credential is configured.
    fred = next(
        provider
        for category in snapshot["categories"]
        for provider in category["providers"]
        if provider["provider_id"] == "fred"
    )
    assert fred["credentials"][0]["configured"] is True
    assert fred["credentials"][0]["masked"].startswith("****")


def test_save_secret_masks_and_updates(tmp_path):
    service, secret_registry, _, _ = make_service(tmp_path)
    result = service.save_secret("fred", "FRED_API_KEY", "brand-new-fred-key")
    assert result["configured"] is True
    assert result["masked"] == "****-key"
    assert "brand-new-fred-key" not in dump_payloads(result)
    assert secret_registry.configured("FRED_API_KEY") is True


def test_save_secret_rejects_unknown_provider_and_name(tmp_path):
    service, _, _, _ = make_service(tmp_path)
    with pytest.raises(KeyError):
        service.save_secret("nope", "FRED_API_KEY", "x")
    with pytest.raises(ValueError, match="not accepted"):
        service.save_secret("fred", "VAST_API_KEY", "x")
    with pytest.raises(ValueError, match="non-empty"):
        service.save_secret("fred", "FRED_API_KEY", "")
    with pytest.raises(ValueError, match="4096"):
        service.save_secret("fred", "FRED_API_KEY", "x" * 5000)


def test_legacy_secret_ids_are_accepted_per_provider(tmp_path):
    service, _, _, _ = make_service(tmp_path)
    result = service.save_secret("vast", "VAST_API_KEY", "legacy-vast-value")
    assert result["ok"] is True
    result = service.save_secret("admin_identity", "DEFEND_OWNER_USER", "owner")
    assert result["ok"] is True


def test_remove_secret_flips_configured_state(tmp_path):
    service, _, _, _ = make_service(tmp_path)
    service.save_secret("fred", "FRED_API_KEY", "remove-me-value")
    result = service.remove_secret("fred", "FRED_API_KEY")
    assert result["configured"] is False
    assert result["masked"] is None
    view = service.provider_view("fred")
    assert view["state"] == "AVAILABLE"
    assert view["health_badge"] == "NOT_CONFIGURED"


def test_save_and_remove_rotate_cached_health(tmp_path):
    service, _, config_store, _ = make_service(tmp_path)
    service.save_secret("fred", "FRED_API_KEY", "rotating-key-value")
    result = service.test("fred")
    assert result["badge"] == "HEALTHY"
    assert config_store.get("fred").health_badge is HealthBadge.HEALTHY
    service.save_secret("fred", "FRED_API_KEY", "rotated-key-value-2")
    assert config_store.get("fred").health_badge is HealthBadge.NOT_TESTED
    service.test("fred")
    service.remove_secret("fred", "FRED_API_KEY")
    assert config_store.get("fred").health_badge is HealthBadge.NOT_TESTED


def test_test_records_health_and_quota(tmp_path):
    service, _, config_store, adapter = make_service(tmp_path)
    service.save_secret("fred", "FRED_API_KEY", "quota-key-value")
    adapter._probe = AdapterProbe(
        ok=True,
        status_code=200,
        latency_ms=33,
        detail="reachable",
        authenticated=True,
        remaining_quota=77,
        quota_reset_at="2026-08-18T00:00:00Z",
    )
    result = service.test("fred")
    assert result["badge"] == "HEALTHY"
    assert result["remaining_quota"] == 77
    assert result["latency_ms"] == 33
    assert result["tested_at"] is not None
    stored = config_store.get("fred")
    assert stored.last_success_at is not None
    assert stored.remaining_quota == 77
    assert stored.health_badge is HealthBadge.HEALTHY
    assert "quota-key-value" not in dump_payloads(result)


def test_test_auth_failure_records_auth_failed(tmp_path):
    service, _, config_store, adapter = make_service(tmp_path)
    service.save_secret("fred", "FRED_API_KEY", "bad-key-value")
    adapter._probe = AdapterProbe(
        ok=False,
        status_code=401,
        latency_ms=12,
        detail="authentication failed",
        authenticated=False,
    )
    result = service.test("fred")
    assert result["badge"] == "AUTH_FAILED"
    stored = config_store.get("fred")
    assert stored.last_success_at is None
    assert stored.health_badge is HealthBadge.AUTH_FAILED


def test_test_placeholder_provider_never_goes_healthy(tmp_path):
    service, _, config_store, _ = make_service(tmp_path)
    service_module.adapter_for = lambda definition: PLACEHOLDER_ADAPTER
    service.save_secret("api_sports", "API_SPORTS_API_KEY", "placeholder-key")
    result = service.test("api_sports")
    assert result["badge"] == "NOT_TESTED"
    assert result["detail"] == "ADAPTER NOT IMPLEMENTED"
    assert config_store.get("api_sports").health_badge is HealthBadge.NOT_TESTED


def test_test_disabled_provider_raises(tmp_path):
    service, _, config_store, _ = make_service(tmp_path)
    config_store.set_enabled("fred", False)
    with pytest.raises(ValueError, match="disabled"):
        service.test("fred")


def test_test_all_configured_skips_placeholders_and_disabled(tmp_path):
    service, _, config_store, _ = make_service(tmp_path)
    for name, value in SECRET_VALUES.items():
        service._secrets.save({name: value})
    config_store.set_enabled("world_bank", False)
    result = service.test_all_configured()
    assert result["tested"] == 7  # eight real adapters minus disabled world_bank
    assert len(result["results"]) == 7
    assert all(item["badge"] == "HEALTHY" for item in result["results"])
    reasons = {item["provider_id"]: item["reason"] for item in result["skipped"]}
    assert reasons["api_sports"] == "adapter not implemented"
    assert reasons["world_bank"] == "disabled"
    assert "fred" not in reasons
    for item in result["results"]:
        assert "super-secret" not in dump_payloads(item)


def test_test_all_configured_skips_missing_credentials(tmp_path):
    service, _, _, _ = make_service(tmp_path)
    result = service.test_all_configured()
    tested = {item["provider_id"] for item in result["results"]}
    assert "fred" not in tested
    reasons = {item["provider_id"]: item["reason"] for item in result["skipped"]}
    assert reasons["fred"] == "missing credentials"


def test_diagnostics_matrix_never_leaks_secrets(tmp_path):
    service, _, _, _ = make_service(tmp_path)
    for name, value in SECRET_VALUES.items():
        service._secrets.save({name: value})
    diagnostics = service.diagnostics()
    from defend_integrations.registry import PROVIDERS

    assert len(diagnostics["rows"]) == len(PROVIDERS)
    serialized = dump_payloads(diagnostics)
    for value in SECRET_VALUES.values():
        assert value not in serialized
    rows = {row["provider_id"]: row for row in diagnostics["rows"]}
    assert rows["fred"]["configured"] is True
    assert rows["the_odds_api"]["products"] == ["defendmarkets"]


def test_product_mapping_endpoint_data(tmp_path):
    service, _, _, _ = make_service(tmp_path)
    products = service.products()
    assert len(products["products"]) == 4
    assert "fred" in products["product_providers"]["defendmarkets"]
    assert "vast" in products["product_providers"]["defendcoder"]


def test_save_config_validates_keys_and_round_trips(tmp_path):
    service, _, config_store, _ = make_service(tmp_path)
    view = service.save_config(
        "gpu_policy", config={"allowed_families": "A100,H100"}
    )
    assert view["config"]["allowed_families"] == "A100,H100"
    with pytest.raises(ValueError, match="not accepted"):
        service.save_config("gpu_policy", config={"bogus": "x"})
    view = service.save_config("gpu_policy", enabled=False)
    assert view["enabled"] is False
    assert view["state"] == "DISABLED"
    view = service.save_config("gpu_policy", enabled=True)
    assert view["enabled"] is True


def test_provider_view_masks_secret_shaped_config(tmp_path):
    from defend_integrations.models import mask_config_value

    assert mask_config_value("very-secret-value").startswith("****")
    assert mask_config_value("bearer auth token-abc").startswith("****")
    assert mask_config_value("plain-value") == "plain-value"
    service, _, _, _ = make_service(tmp_path)
    view = service.save_config(
        "gpu_policy", config={"allowed_families": "A100,H100"}
    )
    assert view["config"]["allowed_families"] == "A100,H100"


def test_unknown_provider_view_raises_key_error(tmp_path):
    service, _, _, _ = make_service(tmp_path)
    with pytest.raises(KeyError):
        service.provider_view("nope")