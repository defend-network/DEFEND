from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from admin_auth import AdminPrincipal, require_admin
from api_setup_integrations_routes import build_setup_integrations_router
from defend_integrations.models import (
    AdapterProbe,
    HealthBadge,
)
from defend_integrations.service import SetupIntegrationsService
from defend_integrations.stores import ProviderConfigStore, SecretRegistry

from tests.test_setup_stores import MemStore


class FakeService:
    def __init__(self, service: SetupIntegrationsService):
        self._service = service

    def snapshot(self):
        return self._service.snapshot()

    def products(self):
        return self._service.products()

    def provider_view(self, provider_id):
        return self._service.provider_view(provider_id)

    def save_secret(self, provider_id, secret_name, value):
        return self._service.save_secret(provider_id, secret_name, value)

    def remove_secret(self, provider_id, secret_name):
        return self._service.remove_secret(provider_id, secret_name)

    def save_config(self, provider_id, *, enabled=None, config=None):
        return self._service.save_config(
            provider_id, enabled=enabled, config=config
        )

    def test(self, provider_id):
        return self._service.test(provider_id)

    def test_all_configured(self):
        return self._service.test_all_configured()

    def diagnostics(self):
        return self._service.diagnostics()


def make_client(service: SetupIntegrationsService | None):
    fake = FakeService(service) if service is not None else None
    app = FastAPI()
    app.include_router(build_setup_integrations_router(fake))
    app.dependency_overrides[require_admin] = lambda: AdminPrincipal(
        "acct_1", "owner", "owner", 9999999999
    )
    return TestClient(app), fake


def test_all_setup_routes_require_admin():
    app = FastAPI()
    app.include_router(build_setup_integrations_router(None))
    client = TestClient(app)
    assert client.get("/api/admin/setup/summary").status_code == 401
    assert client.get("/api/admin/setup/products").status_code == 401
    assert client.get("/api/admin/setup/providers/fred").status_code == 401
    assert (
        client.put(
            "/api/admin/setup/providers/fred/secret",
            json={"secret_name": "FRED_API_KEY", "value": "x"},
        ).status_code
        == 401
    )
    assert (
        client.delete(
            "/api/admin/setup/providers/fred/secret?secret_name=FRED_API_KEY"
        ).status_code
        == 401
    )
    assert (
        client.post("/api/admin/setup/providers/fred/test").status_code == 401
    )
    assert client.post("/api/admin/setup/test-all").status_code == 401
    assert client.get("/api/admin/setup/diagnostics").status_code == 401


def test_unavailable_service_returns_503():
    app = FastAPI()
    app.include_router(build_setup_integrations_router(None))
    app.dependency_overrides[require_admin] = lambda: AdminPrincipal(
        "acct_1", "owner", "owner", 9999999999
    )
    client = TestClient(app)
    assert client.get("/api/admin/setup/summary").status_code == 503
    assert client.post("/api/admin/setup/test-all").status_code == 503


def test_summary_returns_registry_data_without_leaking_secrets(tmp_path):
    service = _service_with_secrets(tmp_path)
    client, _ = make_client(service)
    response = client.get("/api/admin/setup/summary")
    assert response.status_code == 200
    body = response.json()
    assert len(body["categories"]) == 12
    assert "product_providers" in body
    for value in _SECRETS.values():
        assert value not in response.text


def test_provider_detail_404_and_200(tmp_path):
    service = _service_with_secrets(tmp_path)
    client, _ = make_client(service)
    assert (
        client.get("/api/admin/setup/providers/nope").status_code == 404
    )
    response = client.get("/api/admin/setup/providers/fred")
    assert response.status_code == 200
    body = response.json()
    assert body["credentials"][0]["name"] == "FRED_API_KEY"
    assert body["credentials"][0]["configured"] is True
    assert "****" in (body["credentials"][0]["masked"] or "")
    for value in _SECRETS.values():
        assert value not in response.text


def test_save_secret_returns_masked_only(tmp_path):
    service = _service_with_secrets(tmp_path)
    client, _ = make_client(service)
    response = client.put(
        "/api/admin/setup/providers/fred/secret",
        json={"secret_name": "FRED_API_KEY", "value": "route-secret-value-99"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True
    assert body["masked"] == "****e-99"
    assert "route-secret-value-99" not in response.text


def test_save_secret_validates_provider_and_name(tmp_path):
    service = _service_with_secrets(tmp_path)
    client, _ = make_client(service)
    assert (
        client.put(
            "/api/admin/setup/providers/nope/secret",
            json={"secret_name": "FRED_API_KEY", "value": "x"},
        ).status_code
        == 404
    )
    assert (
        client.put(
            "/api/admin/setup/providers/fred/secret",
            json={"secret_name": "VAST_API_KEY", "value": "x"},
        ).status_code
        == 400
    )
    assert (
        client.put(
            "/api/admin/setup/providers/fred/secret",
            json={"secret_name": "FRED_API_KEY", "value": ""},
        ).status_code
        == 422
    )


def test_remove_secret_route(tmp_path):
    service = _service_with_secrets(tmp_path)
    client, _ = make_client(service)
    response = client.delete(
        "/api/admin/setup/providers/fred/secret?secret_name=FRED_API_KEY"
    )
    assert response.status_code == 200
    assert response.json()["configured"] is False
    view = client.get("/api/admin/setup/providers/fred").json()
    assert view["health_badge"] == "NOT_CONFIGURED"


def test_config_update_routes(tmp_path):
    service = _service_with_secrets(tmp_path)
    client, _ = make_client(service)
    response = client.put(
        "/api/admin/setup/providers/gpu_policy/config",
        json={"config": {"allowed_families": "A100"}},
    )
    assert response.status_code == 200
    assert response.json()["config"]["allowed_families"] == "A100"
    assert (
        client.put(
            "/api/admin/setup/providers/gpu_policy/config",
            json={},
        ).status_code
        == 400
    )
    assert (
        client.put(
            "/api/admin/setup/providers/gpu_policy/config",
            json={"config": {"bogus": "x"}},
        ).status_code
        == 400
    )


def test_test_and_test_all_routes(tmp_path):
    service, _, config_store, adapter = _make_service_with_adapter(tmp_path)
    for name, value in _SECRETS.items():
        service._secrets.save({name: value})
    client, _ = make_client(service)
    response = client.post("/api/admin/setup/providers/fred/test")
    assert response.status_code == 200
    assert response.json()["badge"] == "HEALTHY"
    assert config_store.get("fred").health_badge is HealthBadge.HEALTHY

    response = client.post("/api/admin/setup/test-all")
    assert response.status_code == 200
    body = response.json()
    assert body["tested"] == 8
    assert body["summary"]["tested"] == 8
    assert body["summary"]["healthy"] == 8
    assert body["summary"]["planned"] >= 1
    assert body["skipped"]

    assert (
        client.post("/api/admin/setup/providers/nope/test").status_code == 404
    )
    config_store.set_enabled("fred", False)
    assert (
        client.post("/api/admin/setup/providers/fred/test").status_code == 400
    )


def test_diagnostics_route(tmp_path):
    service = _service_with_secrets(tmp_path)
    client, _ = make_client(service)
    response = client.get("/api/admin/setup/diagnostics")
    assert response.status_code == 200
    rows = response.json()["rows"]
    assert rows
    assert {"implemented", "credentials_configured", "enabled", "tested"} <= set(
        rows[0]
    )
    for value in _SECRETS.values():
        assert value not in response.text


_SECRETS = {
    "VAST_API_KEY": "route-super-secret-vast-value-abc123",
    "HF_TOKEN": "route-super-secret-hf-value-abc123",
    "FRED_API_KEY": "route-super-secret-fred-value-abc123",
    "CONGRESS_API_KEY": "route-super-secret-congress-value-abc123",
    "THE_ODDS_API_KEY": "route-super-secret-odds-value-abc123",
}


def _service_with_secrets(tmp_path):
    service, _, _, _ = _make_service_with_adapter(tmp_path)
    for name, value in _SECRETS.items():
        service._secrets.save({name: value})
    return service


def _make_service_with_adapter(tmp_path):
    import defend_integrations.service as service_module

    secret_registry = SecretRegistry(MemStore())
    config_store = ProviderConfigStore(tmp_path / "config.json")
    service = SetupIntegrationsService(secret_registry, config_store)
    adapter = _FakeAdapter(
        AdapterProbe(
            ok=True,
            status_code=200,
            latency_ms=25,
            detail="reachable",
            authenticated=True,
        )
    )
    service_module.adapter_for = lambda definition: adapter
    return service, secret_registry, config_store, adapter


class _FakeAdapter:
    def __init__(self, probe):
        self._probe = probe

    def probe(self, definition, secrets, config):
        return self._probe