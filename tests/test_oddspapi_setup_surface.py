"""OddsPapi Setup & Integrations card tests.

Verifies the OddsPapi provider card (Table Tennis category) exists with the
ODDSPAPI_API_KEY credential slot, credentials round-trip redacted through the
SecretRegistry / DPAPI store path, the test action resolves the key through
the SecretRegistry, missing keys never claim configured/healthy, capability
cells stay UNKNOWN until empirically verified, and no probe path ever exposes
the raw secret.
"""

from __future__ import annotations

import json

import pytest

import defend_integrations.adapters as adapters_module
import defend_integrations.service as service_module
from defend_integrations.adapters import OddsPapiAdapter, REAL_ADAPTERS
from defend_integrations.http import FetchResult
from defend_integrations.models import (
    AdapterKind,
    AdapterProbe,
    HealthBadge,
    ProviderState,
    badge_from_probe,
)
from defend_integrations.registry import (
    find_provider,
    providers_in_category,
)
from defend_integrations.service import SetupIntegrationsService
from defend_integrations.stores import ProviderConfigStore, SecretRegistry

from tests.test_setup_service import FakeAdapter
from tests.test_setup_stores import MemStore

SECRET_VALUE = "oddspapi-live-key-123456"
SECRET_NAME = "ODDSPAPI_API_KEY"


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
            detail="reachable; table tennis sport present=True",
            authenticated=True,
            remaining_quota=240,
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


def test_oddspapi_provider_registered():
    provider = find_provider("oddspapi")
    assert provider is not None
    assert provider.display_name == "OddsPapi"
    assert provider.category == "table_tennis"
    assert provider.adapter_kind is AdapterKind.REAL
    assert SECRET_NAME in provider.required_secrets
    assert provider in providers_in_category("table_tennis")
    assert "oddspapi" in REAL_ADAPTERS


def test_oddspapi_card_visible_in_table_tennis_category(tmp_path):
    service, _, _, _ = _make_service(tmp_path)
    view = _provider_view(service, "oddspapi")
    assert view["provider_id"] == "oddspapi"
    assert view["display_name"] == "OddsPapi"
    assert view["category"] == "table_tennis"
    assert view["adapter_kind"] == "real"
    assert view["test_supported"] is True
    credential_names = [cred["name"] for cred in view["credentials"]]
    assert SECRET_NAME in credential_names
    assert view["auth_type"] == "api_key"


def test_oddspapi_secret_round_trip_redacted(tmp_path):
    service, secret_registry, _, _ = _make_service(tmp_path)
    saved = service.save_secret("oddspapi", SECRET_NAME, SECRET_VALUE)
    assert saved["configured"] is True
    assert saved["masked"] == "****3456"
    assert SECRET_VALUE not in json.dumps(saved)
    view = _provider_view(service, "oddspapi")
    assert view["credential_configured"] is True
    assert view["credentials_configured"] is True
    assert SECRET_VALUE not in json.dumps(view)
    assert secret_registry.configured(SECRET_NAME) is True
    assert secret_registry.get(SECRET_NAME) == SECRET_VALUE
    removed = service.remove_secret("oddspapi", SECRET_NAME)
    assert removed["configured"] is False
    assert _provider_view(service, "oddspapi")["credential_configured"] is False


def test_oddspapi_test_action_uses_secret_registry(tmp_path):
    service, secret_registry, _, adapter = _make_service(tmp_path)
    secret_registry.save({SECRET_NAME: "oddspapi-test-key-abc"})
    result = service.test("oddspapi")
    assert result["ok"] is True
    assert result["badge"] == HealthBadge.HEALTHY.value
    assert adapter.calls, "adapter.probe must have been invoked"
    provider_id, secrets, config = adapter.calls[-1]
    assert provider_id == "oddspapi"
    assert secrets.get(SECRET_NAME) == "oddspapi-test-key-abc"
    assert "oddspapi-test-key-abc" not in json.dumps(result)
    assert result["remaining_quota"] == 240


def test_oddspapi_missing_key_is_not_configured(tmp_path):
    service, _, _, _ = _make_service(tmp_path)
    view = _provider_view(service, "oddspapi")
    assert view["state"] == ProviderState.NOT_CONFIGURED.value
    assert view["credential_configured"] is False
    with pytest.raises(ValueError, match="missing required credentials"):
        service.test("oddspapi")


def test_oddspapi_credential_present_does_not_imply_healthy(tmp_path):
    service, secret_registry, _, _ = _make_service(tmp_path)
    secret_registry.save({SECRET_NAME: "oddspapi-saved-1"})
    view = _provider_view(service, "oddspapi")
    assert view["credential_configured"] is True
    assert view["state"] == ProviderState.READY_TO_TEST.value
    assert view["health_badge"] == HealthBadge.NOT_TESTED.value
    assert view["state"] != ProviderState.HEALTHY.value
    service_module.adapter_for = lambda definition: FakeAdapter(
        AdapterProbe(
            ok=False,
            status_code=401,
            latency_ms=12,
            detail="authentication failed",
            authenticated=False,
            error_class="auth_failed",
        )
    )
    result = service.test("oddspapi")
    assert result["ok"] is False
    assert result["badge"] == HealthBadge.AUTH_FAILED.value
    assert _provider_view(service, "oddspapi")["state"] == "AUTH_FAILED"


def test_oddspapi_probe_never_exposes_secret(tmp_path):
    service, secret_registry, _, _ = _make_service(tmp_path)
    secret_registry.save({SECRET_NAME: SECRET_VALUE})
    result = service.test("oddspapi")
    diagnostics = service.diagnostics()
    serialized = json.dumps({"result": result, "diagnostics": diagnostics})
    assert SECRET_VALUE not in serialized
    view = _provider_view(service, "oddspapi")
    assert SECRET_VALUE not in json.dumps(view)
    assert "masked" not in view  # no raw key field on the view at all


def test_oddspapi_capabilities_reflect_verified_findings():
    provider = find_provider("oddspapi")
    assert provider is not None
    caps = provider.capabilities.to_dict()
    assert caps["tt_live_odds"] == "yes (2026-08-18 verified)"
    assert caps["tt_historical_odds"].startswith("unresolved")
    assert caps["tt_results"] == "yes (2026-08-18 verified)"
    assert caps["tt_live_scores"] == "unknown (not verified)"
    assert caps["adapter_status"] == "partial"
    assert provider.capabilities.earliest_history is None
    assert caps["multi_snapshot"].startswith("no (verified")
    assert caps["timestamped_odds"].startswith("yes (2026-08-18 verified")
    assert caps["historical_odds_plan_requirement"]


# ------------------------------------------------------------------ adapter


class _Success(FetchResult):
    def __init__(self, body: object, headers=None):
        super().__init__(
            ok=True,
            status_code=200,
            latency_ms=31,
            error_type=None,
            body=json.dumps(body),
            retries=0,
            headers=headers,
        )


class _Failure(FetchResult):
    def __init__(self, status_code=None, body=None, error_type="TimeoutError"):
        super().__init__(
            ok=False,
            status_code=status_code,
            latency_ms=20,
            error_type=error_type,
            body=body,
        )


def _adapter_probe(result, secret=SECRET_VALUE):
    definition = find_provider("oddspapi")
    adapter = REAL_ADAPTERS["oddspapi"]
    return adapter.probe(definition, {SECRET_NAME: secret}, {})


def test_oddspapi_adapter_missing_key_never_touches_network(monkeypatch):
    called = []

    def _fake(url, **kwargs):
        called.append(url)
        return _Success([])

    monkeypatch.setattr(adapters_module, "fetch", _fake)
    probe = _adapter_probe(None, secret="")
    assert probe.ok is False
    assert probe.detail == "missing ODDSPAPI_API_KEY"
    assert not called


def test_oddspapi_adapter_reports_tt_presence_in_detail(monkeypatch):
    def _fake(url, **kwargs):
        if "sports" in url:
            return _Success(
                [
                    {"id": 25, "name": "Table Tennis", "slug": "table-tennis"},
                    {"id": 1, "name": "Football", "slug": "football"},
                ],
                headers={"x-ratelimit-remaining": "230"},
            )
        return _Success({"odds": []})

    monkeypatch.setattr(adapters_module, "fetch", _fake)
    probe = _adapter_probe(None)
    assert probe.ok is True
    assert probe.authenticated is True
    assert "table tennis sport present=True" in probe.detail
    assert "historical odds endpoint reachable" in probe.detail
    assert probe.remaining_quota == 230
    assert SECRET_VALUE not in json.dumps(probe.to_dict())
    assert badge_from_probe(probe) is HealthBadge.HEALTHY


def test_oddspapi_adapter_tt_absent_is_recorded_honestly(monkeypatch):
    def _fake(url, **kwargs):
        return _Success([{"id": 1, "name": "Football", "slug": "football"}])

    monkeypatch.setattr(adapters_module, "fetch", _fake)
    probe = _adapter_probe(None)
    assert probe.ok is True
    assert "table tennis sport present=False" in probe.detail


def test_oddspapi_adapter_403_plan_body_maps_to_plan_required(monkeypatch):
    def _fake(url, **kwargs):
        return _Failure(
            status_code=403,
            body='{"error": "upgrade your plan to access this endpoint"}',
        )

    monkeypatch.setattr(adapters_module, "fetch", _fake)
    probe = _adapter_probe(None)
    assert probe.ok is False
    assert probe.error_class == "plan_required"
    assert badge_from_probe(probe) is HealthBadge.PLAN_REQUIRED
    assert SECRET_VALUE not in probe.detail


def test_oddspapi_adapter_401_maps_to_auth_failed(monkeypatch):
    def _fake(url, **kwargs):
        return _Failure(status_code=401, body="invalid apiKey")

    monkeypatch.setattr(adapters_module, "fetch", _fake)
    probe = _adapter_probe(None)
    assert probe.ok is False
    assert probe.error_class == "auth_failed"
    assert badge_from_probe(probe) is HealthBadge.AUTH_FAILED
    assert probe.detail == "authentication failed"


def test_oddspapi_adapter_429_maps_to_rate_limited(monkeypatch):
    def _fake(url, **kwargs):
        return _Failure(status_code=429, body="too many requests")

    monkeypatch.setattr(adapters_module, "fetch", _fake)
    probe = _adapter_probe(None)
    assert probe.ok is False
    assert probe.error_class == "rate_limited"
    assert badge_from_probe(probe) is HealthBadge.RATE_LIMITED


def test_oddspapi_adapter_urls_embed_key_only_as_query(monkeypatch):
    captured: list[str] = []

    def _fake(url, **kwargs):
        captured.append(url)
        if "sports" in url:
            return _Success([], headers={})
        return _Success({})

    monkeypatch.setattr(adapters_module, "fetch", _fake)
    probe = _adapter_probe(None)
    assert probe.ok is True
    assert len(captured) == 2
    assert SECRET_VALUE in captured[0]
    assert captured[0].startswith("https://api.oddspapi.io/v4/sports?apiKey=")
    assert captured[1].startswith(
        "https://api.oddspapi.io/v4/odds?apiKey="
    )