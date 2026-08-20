"""Setup & Integrations provider-surface tests (TT HISTORICAL ACTIVATION Phase 0).

Verifies the Odds-API.io setup card exists, credentials round-trip redacted,
the test action resolves keys through the SecretRegistry, provider cards
truthfully distinguish missing-key / missing-adapter / plan-required, and
health state never exposes a raw secret.
"""

from __future__ import annotations

import json

import pytest

import defend_integrations.service as service_module
from defend_integrations.models import AdapterProbe, HealthBadge
from defend_integrations.registry import (
    find_provider,
    providers_in_category,
)
from defend_integrations.service import SetupIntegrationsService
from defend_integrations.stores import ProviderConfigStore, SecretRegistry

from tests.test_setup_service import FakeAdapter, SECRET_VALUES
from tests.test_setup_stores import MemStore


def _make_service(tmp_path, probe: AdapterProbe | None = None):
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
            remaining_quota=98,
            quota_reset_at="2026-08-18T13:00:00Z",
        )
    )
    service_module.adapter_for = lambda definition: adapter
    return service, secret_registry, config_store, adapter


def _provider_view(service, provider_id: str) -> dict:
    return next(
        provider
        for category in service.snapshot()["categories"]
        for provider in category["providers"]
        if provider["provider_id"] == provider_id
    )


def test_odds_api_io_setup_card_registered(tmp_path):
    service, _, _, _ = _make_service(tmp_path)
    view = _provider_view(service, "odds_api_io")
    assert view["display_name"] == "Odds-API.io"
    assert view["category"] == "table_tennis"
    assert view["adapter_kind"] == "real"
    assert view["test_supported"] is True
    credential_names = [cred["name"] for cred in view["credentials"]]
    assert "ODDS_API_IO_API_KEY" in credential_names
    caps = view["capabilities"]
    assert caps["tt_results"] == "yes (verified)"
    assert caps["tt_historical_odds"] == "not_available"
    assert caps["adapter_status"] == "partial"


def test_odds_api_io_secret_round_trip_redacted(tmp_path):
    service, secret_registry, _, _ = _make_service(tmp_path)
    saved = service.save_secret(
        "odds_api_io", "ODDS_API_IO_API_KEY", "oaio-live-value-12345"
    )
    assert saved["configured"] is True
    assert saved["masked"] == "****2345"
    assert "oaio-live-value-12345" not in json.dumps(saved)
    view = _provider_view(service, "odds_api_io")
    assert view["credential_configured"] is True
    assert view["credentials_configured"] is True
    assert json.dumps(view).find("oaio-live-value-12345") == -1
    assert secret_registry.configured("ODDS_API_IO_API_KEY") is True
    removed = service.remove_secret("odds_api_io", "ODDS_API_IO_API_KEY")
    assert removed["configured"] is False
    assert _provider_view(service, "odds_api_io")["credential_configured"] is False


def test_odds_api_io_test_action_uses_secret_registry(tmp_path):
    service, secret_registry, _, adapter = _make_service(tmp_path)
    secret_registry.save({"ODDS_API_IO_API_KEY": "oaio-test-key-abc"})
    result = service.test("odds_api_io")
    assert result["ok"] is True
    assert result["badge"] == HealthBadge.HEALTHY.value
    assert adapter.calls, "adapter.probe must have been invoked"
    provider_id, secrets, config = adapter.calls[-1]
    assert provider_id == "odds_api_io"
    assert secrets.get("ODDS_API_IO_API_KEY") == "oaio-test-key-abc"
    assert "oaio-test-key-abc" not in json.dumps(result)
    assert result["remaining_quota"] == 98


def test_provider_card_distinguishes_missing_key_from_missing_adapter(tmp_path):
    service, _, _, _ = _make_service(tmp_path)
    odds = _provider_view(service, "odds_api_io")
    assert odds["state"] == "NOT_CONFIGURED"
    assert odds["health_badge"] == "NOT_CONFIGURED"
    betsapi = _provider_view(service, "betsapi_tt")
    assert betsapi["state"] == "ADAPTER_NOT_IMPLEMENTED"
    assert betsapi["test_supported"] is False
    assert betsapi["health_badge"] == "NOT_TESTED"
    service.save_secret("betsapi_tt", "BETSAPI_API_KEY", "betsapi-key-1")
    configured = _provider_view(service, "betsapi_tt")
    assert configured["state"] == "CREDENTIAL_PRESENT"
    assert configured["adapter_kind"] == "placeholder"


def test_provider_card_distinguishes_plan_required(tmp_path):
    service, _, _, _ = _make_service(tmp_path)
    odds = _provider_view(service, "odds_api_io")
    assert odds["capabilities"]["tt_historical_odds"] == "not_available"
    assert odds["capabilities"]["historical_odds_plan_requirement"]
    assert odds["capabilities"]["tt_results"] == "yes (verified)"


def test_provider_health_never_exposes_secret(tmp_path):
    service, secret_registry, _, _ = _make_service(tmp_path)
    secret_registry.save({"ODDS_API_IO_API_KEY": "oaio-secret-777"})
    result = service.test("odds_api_io")
    diagnostics = service.diagnostics()
    serialized = json.dumps({"result": result, "diagnostics": diagnostics})
    assert "oaio-secret-777" not in serialized
    view = _provider_view(service, "odds_api_io")
    assert "masked" not in view  # no raw key field on the view at all
    assert json.dumps(view).find("oaio-secret-777") == -1


def test_provider_health_records_error_class(tmp_path):
    service, secret_registry, _, _ = _make_service(tmp_path)
    secret_registry.save({"ODDS_API_IO_API_KEY": "oaio-bad-key-1"})
    service_module.adapter_for = lambda definition: FakeAdapter(
        AdapterProbe(
            ok=False,
            status_code=401,
            latency_ms=12,
            detail="invalid api key",
            authenticated=False,
        )
    )
    result = service.test("odds_api_io")
    assert result["ok"] is False
    assert result["badge"] == HealthBadge.AUTH_FAILED.value
    view = _provider_view(service, "odds_api_io")
    assert view["last_error_class"] == "AUTH_FAILED"
    assert view["state"] == "AUTH_FAILED"


def test_placeholder_provider_does_not_claim_ready(tmp_path):
    service, _, _, _ = _make_service(tmp_path)
    for provider_id in (
        "betsapi_tt",
        "sportsapi_pro",
        "sportmicro_tt",
        "rapidapi_tabletennis",
        "rapidapi_tt_live",
    ):
        view = _provider_view(service, provider_id)
        assert view["adapter_kind"] == "placeholder", provider_id
        assert view["test_supported"] is False, provider_id
        assert view["state"] in (
            "ADAPTER_NOT_IMPLEMENTED",
            "CREDENTIAL_PRESENT",
        ), provider_id
        with pytest.raises(ValueError, match="planned"):
            service.test(provider_id)


def test_setup_provider_capabilities_are_truthful(tmp_path):
    service, _, _, _ = _make_service(tmp_path)
    tt_providers = providers_in_category("table_tennis")
    assert {p.provider_id for p in tt_providers} >= {
        "odds_api_io",
        "betsapi_tt",
        "sportsapi_pro",
        "sportmicro_tt",
        "rapidapi_tabletennis",
        "rapidapi_tt_live",
    }
    for provider in tt_providers:
        caps = provider.capabilities
        if provider.adapter_kind.value == "placeholder":
            assert caps.adapter_status == "not_implemented", provider.provider_id
            assert "(verified)" not in caps.tt_results, provider.provider_id
            assert "(verified)" not in caps.tt_live_odds, provider.provider_id
        else:
            assert caps.adapter_status == "partial", provider.provider_id
    odds = _provider_view(service, "odds_api_io")
    assert odds["capabilities"]["tt_historical_odds"] == "not_available"
    assert odds["capabilities"]["tt_live_odds"].startswith("no")


def test_health_badge_reaction_to_rate_limit(tmp_path):
    service, secret_registry, _, _ = _make_service(tmp_path)
    secret_registry.save({"ODDS_API_IO_API_KEY": "oaio-quota-key-1"})
    service_module.adapter_for = lambda definition: FakeAdapter(
        AdapterProbe(
            ok=False,
            status_code=429,
            latency_ms=8,
            detail="rate limited",
            authenticated=True,
            remaining_quota=0,
            quota_reset_at="2026-08-18T14:00:00Z",
        )
    )
    result = service.test("odds_api_io")
    assert result["badge"] == HealthBadge.RATE_LIMITED.value
    view = _provider_view(service, "odds_api_io")
    assert view["last_error_class"] == "RATE_LIMITED"
    assert view["remaining_quota"] == 0
