"""Owls Insight Setup & Integrations card tests.

Verifies the Owls Insight provider card (Table Tennis category) exists for the
DEFENDmarkets product with the OWLS_INSIGHT_API_KEY credential slot, secrets
round-trip redacted through the SecretRegistry / DPAPI store path, the Test
action performs a real (mocked) Hard Rock Florida TABLE_TENNIS coverage probe
plus a ladder structure check, coverage classification distinguishes
AVAILABLE / EMPTY / auth / plan failure, and no probe path ever exposes the
raw secret (header, URL, detail, snapshot, exceptions, config JSON).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import defend_integrations.adapters as adapters_module
import defend_integrations.service as service_module
from defend_integrations.adapters import OwlsInsightAdapter, REAL_ADAPTERS
from defend_integrations.http import FetchResult
from defend_integrations.models import (
    AdapterKind,
    AdapterProbe,
    HealthBadge,
    ProviderState,
    badge_from_probe,
)
from defend_integrations.registry import (
    REGISTRY_SECRET_NAMES,
    find_provider,
    providers_for_product,
    providers_in_category,
)
from defend_integrations.service import SetupIntegrationsService
from defend_integrations.stores import ProviderConfigStore, SecretRegistry

from tests.test_setup_service import FakeAdapter
from tests.test_setup_stores import MemStore

SECRET_VALUE = "owls-live-key-123456"
SECRET_NAME = "OWLS_INSIGHT_API_KEY"

BASE = "https://api.owlsinsight.com/api/v2/hardrock"
TT_ENDPOINT = f"{BASE}/fl/TABLE_TENNIS"
LADDER_ENDPOINT = f"{BASE}/ladder"

# ------------------------------------------------------------------ fixtures

TT_BODY_EMPTY = {"sport": "TABLE_TENNIS", "state": "fl", "events": []}

TT_BODY_AVAILABLE = {
    "sport": "TABLE_TENNIS",
    "state": "fl",
    "events": [
        {
            "id": "evt-1",
            "sport": "table_tennis",
            "start": "2026-08-22T20:00:00Z",
            "inplay": False,
            "participants": ["PLAYER_ALPHA", "PLAYER_BETA"],
            "markets": [
                {
                    "market_id": "m1",
                    "name": "moneyline",
                    "outcomes": [
                        {"selection_id": "s1", "name": "PLAYER_ALPHA", "rootIdx": 42},
                        {"selection_id": "s2", "name": "PLAYER_BETA", "rootIdx": 43},
                    ],
                }
            ],
        },
        {
            "id": "evt-2",
            "sport": "table_tennis",
            "start": "2026-08-22T21:00:00Z",
            "inplay": True,
            "participants": ["PLAYER_GAMMA", "PLAYER_DELTA"],
            "markets": [
                {
                    "market_id": "m2",
                    "name": "total_points",
                    "outcomes": [
                        {"selection_id": "s3", "rootIdx": 44},
                        {"selection_id": "s4", "rootIdx": 45},
                    ],
                }
            ],
        },
    ],
}

TT_BODY_NO_MARKETS = {
    "sport": "TABLE_TENNIS",
    "state": "fl",
    "events": [
        {
            "id": "evt-1",
            "sport": "table_tennis",
            "start": "2026-08-22T20:00:00Z",
            "participants": ["PLAYER_ALPHA", "PLAYER_BETA"],
            "markets": [],
        }
    ],
}

TT_BODY_NO_ROOTIDX = {
    "sport": "TABLE_TENNIS",
    "state": "fl",
    "events": [
        {
            "id": "evt-1",
            "sport": "table_tennis",
            "start": "2026-08-22T20:00:00Z",
            "participants": ["PLAYER_ALPHA", "PLAYER_BETA"],
            "markets": [
                {
                    "market_id": "m1",
                    "name": "moneyline",
                    "outcomes": [{"selection_id": "s1", "price": 1.9}],
                }
            ],
        }
    ],
}

LADDER_BODY = {
    "ladder": [
        {"rootIdx": 1, "american": 120},
        {"rootIdx": 2, "american": -140},
        {"rootIdx": 42, "american": 150},
        {"rootIdx": 43, "american": -110},
    ]
}

PLAN_ERROR_BODY = {"error": "upgrade your plan to access this endpoint"}


class _Result(FetchResult):
    def __init__(self, status_code, body, headers=None, error_type=None):
        ok = status_code is not None and 200 <= status_code < 300
        super().__init__(
            ok=ok,
            status_code=status_code,
            latency_ms=31,
            error_type=error_type,
            body=json.dumps(body) if body is not None else None,
            retries=0,
            headers=headers,
        )


def make_fake_fetch(
    tt_status=200,
    tt_body=None,
    ladder_status=200,
    ladder_body=LADDER_BODY,
):
    tt_body = LADDER_BODY if tt_body is None else tt_body
    captured: list[dict] = []

    def _fake(url, **kwargs):
        captured.append(
            {
                "url": url,
                "headers": dict(kwargs.get("headers") or {}),
                "known": tuple(kwargs.get("known_secrets") or ()),
            }
        )
        if url.endswith("/ladder"):
            return _Result(ladder_status, ladder_body)
        return _Result(tt_status, tt_body)

    return _fake, captured


def _adapter_probe(
    tt_status=200,
    tt_body=None,
    ladder_status=200,
    ladder_body=LADDER_BODY,
    secret=SECRET_VALUE,
    monkeypatch=None,
):
    fake, captured = make_fake_fetch(
        tt_status=tt_status,
        tt_body=tt_body,
        ladder_status=ladder_status,
        ladder_body=ladder_body,
    )
    if monkeypatch is None:
        adapters_module.fetch = fake
    else:
        monkeypatch.setattr(adapters_module, "fetch", fake)
    definition = find_provider("owls_insight")
    assert definition is not None
    probe = REAL_ADAPTERS["owls_insight"].probe(
        definition, {SECRET_NAME: secret}, {}
    )
    return probe, captured


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
            detail="authenticated; state=fl; sport=TABLE_TENNIS; events=1",
            authenticated=True,
            coverage_state="AVAILABLE",
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


# ------------------------------------------------------------- registry/card


def test_owls_provider_registered():
    provider = find_provider("owls_insight")
    assert provider is not None
    assert provider.display_name == "Owls Insight"
    assert provider.category == "table_tennis"
    assert provider.adapter_kind is AdapterKind.REAL
    assert SECRET_NAME in provider.required_secrets
    assert provider.host == "https://api.owlsinsight.com"
    assert provider in providers_in_category("table_tennis")
    assert "owls_insight" in REAL_ADAPTERS


def test_owls_assigned_to_defendmarkets():
    provider = find_provider("owls_insight")
    assert provider is not None
    assert "defendmarkets" in provider.products
    assert provider in providers_for_product("defendmarkets")


def test_owls_secret_is_a_recognized_registry_secret():
    assert SECRET_NAME in REGISTRY_SECRET_NAMES


def test_owls_card_visible_in_table_tennis_category(tmp_path):
    service, _, _, _ = _make_service(tmp_path)
    view = _provider_view(service, "owls_insight")
    assert view["provider_id"] == "owls_insight"
    assert view["display_name"] == "Owls Insight"
    assert view["category"] == "table_tennis"
    assert view["adapter_kind"] == "real"
    assert view["test_supported"] is True
    assert "defendmarkets" in view["products"]
    assert view["host"] == "https://api.owlsinsight.com"
    assert view["docs_url"] == "https://www.owlsinsight.com/docs"
    assert view["auth_type"] in ("api_key", "bearer")
    credential_names = [cred["name"] for cred in view["credentials"]]
    assert SECRET_NAME in credential_names


def test_owls_missing_key_is_not_configured(tmp_path):
    service, _, _, _ = _make_service(tmp_path)
    view = _provider_view(service, "owls_insight")
    assert view["state"] == ProviderState.NOT_CONFIGURED.value
    assert view["credential_configured"] is False
    assert view["health_badge"] == HealthBadge.NOT_CONFIGURED.value
    with pytest.raises(ValueError, match="missing required credentials"):
        service.test("owls_insight")


def test_owls_save_key_becomes_configured(tmp_path):
    service, secret_registry, _, _ = _make_service(tmp_path)
    saved = service.save_secret("owls_insight", SECRET_NAME, SECRET_VALUE)
    assert saved["configured"] is True
    assert saved["masked"] == "****3456"
    assert SECRET_VALUE not in json.dumps(saved)
    view = _provider_view(service, "owls_insight")
    assert view["credential_configured"] is True
    assert view["credentials_configured"] is True
    assert view["state"] == ProviderState.READY_TO_TEST.value
    assert secret_registry.configured(SECRET_NAME) is True
    assert secret_registry.get(SECRET_NAME) == SECRET_VALUE


def test_owls_raw_secret_never_appears_in_snapshot(tmp_path):
    service, secret_registry, _, _ = _make_service(tmp_path)
    secret_registry.save({SECRET_NAME: SECRET_VALUE})
    serialized = json.dumps(service.snapshot())
    assert SECRET_VALUE not in serialized
    assert "masked" in serialized  # masked view only
    view = _provider_view(service, "owls_insight")
    assert SECRET_VALUE not in json.dumps(view)
    assert view["credentials"][0]["configured"] is True
    assert view["credentials"][0]["masked"] == "****3456"
    assert view["credentials"][0]["masked"] != SECRET_VALUE


def test_owls_rotation_invalidates_cached_health(tmp_path):
    service, _, _, adapter = _make_service(tmp_path)
    service._secrets.save({SECRET_NAME: "first-owls-key-0001"})
    result = service.test("owls_insight")
    assert result["badge"] == HealthBadge.HEALTHY.value
    assert adapter.calls
    view = _provider_view(service, "owls_insight")
    assert view["health_badge"] == HealthBadge.HEALTHY.value
    service.save_secret("owls_insight", SECRET_NAME, "second-owls-key-0002")
    view = _provider_view(service, "owls_insight")
    assert view["health_badge"] == HealthBadge.NOT_TESTED.value
    assert view["state"] == ProviderState.READY_TO_TEST.value
    assert view["last_test_detail"] is None
    assert view["coverage_state"] == "UNKNOWN"


def test_owls_remove_supported(tmp_path):
    service, _, _, _ = _make_service(tmp_path)
    service.save_secret("owls_insight", SECRET_NAME, SECRET_VALUE)
    removed = service.remove_secret("owls_insight", SECRET_NAME)
    assert removed["configured"] is False
    assert removed["masked"] is None
    view = _provider_view(service, "owls_insight")
    assert view["credential_configured"] is False
    assert view["state"] == ProviderState.NOT_CONFIGURED.value


def test_owls_test_action_resolves_key_through_secret_registry(tmp_path):
    service, secret_registry, _, adapter = _make_service(tmp_path)
    secret_registry.save({SECRET_NAME: "owls-test-key-abc"})
    result = service.test("owls_insight")
    assert result["ok"] is True
    assert result["badge"] == HealthBadge.HEALTHY.value
    assert adapter.calls, "adapter.probe must have been invoked"
    provider_id, secrets, _config = adapter.calls[-1]
    assert provider_id == "owls_insight"
    assert secrets.get(SECRET_NAME) == "owls-test-key-abc"
    assert "owls-test-key-abc" not in json.dumps(result)


def test_owls_probe_result_never_exposes_secret(tmp_path):
    service, secret_registry, _, _ = _make_service(tmp_path)
    secret_registry.save({SECRET_NAME: SECRET_VALUE})
    result = service.test("owls_insight")
    diagnostics = service.diagnostics()
    serialized = json.dumps({"result": result, "diagnostics": diagnostics})
    assert SECRET_VALUE not in serialized
    view = _provider_view(service, "owls_insight")
    assert SECRET_VALUE not in json.dumps(view)


# ------------------------------------------------------------------- adapter


def test_owls_missing_key_never_touches_network(monkeypatch):
    called = []

    def _fake(url, **kwargs):
        called.append(url)
        return _Result(200, TT_BODY_AVAILABLE)

    monkeypatch.setattr(adapters_module, "fetch", _fake)
    definition = find_provider("owls_insight")
    probe = REAL_ADAPTERS["owls_insight"].probe(definition, {SECRET_NAME: ""}, {})
    assert probe.ok is False
    assert probe.detail == "missing OWLS_INSIGHT_API_KEY"
    assert not called


def test_owls_probe_sends_bearer_and_never_puts_key_in_url(monkeypatch):
    probe, captured = _adapter_probe(tt_body=TT_BODY_AVAILABLE, monkeypatch=monkeypatch)
    assert len(captured) == 2
    for call in captured:
        assert call["headers"].get("Authorization") == f"Bearer {SECRET_VALUE}"
        assert SECRET_VALUE in call["known"]
        assert SECRET_VALUE not in call["url"]
        assert "apiKey" not in call["url"]
        assert call["url"].startswith("https://api.owlsinsight.com/api/v2/hardrock")
    assert captured[0]["url"] == TT_ENDPOINT
    assert captured[1]["url"] == LADDER_ENDPOINT
    assert probe.ok is True


def test_owls_endpoint_paths_exactly_match_contract(monkeypatch):
    _probe, captured = _adapter_probe(tt_body=TT_BODY_AVAILABLE, monkeypatch=monkeypatch)
    assert captured[0]["url"] == "https://api.owlsinsight.com/api/v2/hardrock/fl/TABLE_TENNIS"
    assert captured[1]["url"] == "https://api.owlsinsight.com/api/v2/hardrock/ladder"
    assert TT_ENDPOINT.endswith("/api/v2/hardrock/fl/TABLE_TENNIS")
    assert LADDER_ENDPOINT.endswith("/api/v2/hardrock/ladder")


def test_owls_401_maps_to_auth_failed(monkeypatch):
    probe, _ = _adapter_probe(
        tt_status=401, tt_body={"error": "invalid token"}, monkeypatch=monkeypatch
    )
    assert probe.ok is False
    assert probe.error_class == "auth_failed"
    assert badge_from_probe(probe) is HealthBadge.AUTH_FAILED
    assert SECRET_VALUE not in probe.detail


def test_owls_403_plan_body_maps_to_plan_required_not_healthy(monkeypatch):
    probe, _ = _adapter_probe(
        tt_status=403, tt_body=PLAN_ERROR_BODY, monkeypatch=monkeypatch
    )
    assert probe.ok is False
    assert probe.error_class == "plan_required"
    assert badge_from_probe(probe) is HealthBadge.PLAN_REQUIRED
    assert probe.coverage_state == "LIMITED"
    assert SECRET_VALUE not in probe.detail


def test_owls_403_plain_maps_to_auth_failed_not_healthy(monkeypatch):
    probe, _ = _adapter_probe(
        tt_status=403, tt_body={"message": "forbidden"}, monkeypatch=monkeypatch
    )
    assert probe.ok is False
    assert probe.error_class == "auth_failed"
    assert badge_from_probe(probe) is HealthBadge.AUTH_FAILED


def test_owls_429_maps_to_rate_limited(monkeypatch):
    probe, _ = _adapter_probe(
        tt_status=429, tt_body={"error": "too many requests"}, monkeypatch=monkeypatch
    )
    assert probe.ok is False
    assert probe.error_class == "rate_limited"
    assert badge_from_probe(probe) is HealthBadge.RATE_LIMITED
    assert "rate limited" in probe.detail


def test_owls_500_maps_to_unavailable(monkeypatch):
    probe, _ = _adapter_probe(
        tt_status=500, tt_body={"error": "boom"}, monkeypatch=monkeypatch
    )
    assert probe.ok is False
    assert badge_from_probe(probe) is HealthBadge.UNAVAILABLE


def test_owls_timeout_maps_to_unavailable(monkeypatch):
    probe, _ = _adapter_probe(
        tt_status=None, tt_body=None, monkeypatch=monkeypatch
    )
    assert probe.ok is False
    assert badge_from_probe(probe) is HealthBadge.UNAVAILABLE


def test_owls_malformed_json_maps_to_schema_error(monkeypatch):
    def _fake(url, **kwargs):
        if url.endswith("/ladder"):
            return _Result(200, LADDER_BODY)
        return FetchResult(ok=True, status_code=200, latency_ms=10, error_type=None, body="{not-json")

    monkeypatch.setattr(adapters_module, "fetch", _fake)
    definition = find_provider("owls_insight")
    probe = REAL_ADAPTERS["owls_insight"].probe(definition, {SECRET_NAME: SECRET_VALUE}, {})
    assert probe.ok is False
    assert "SCHEMA/PROTOCOL ERROR" in probe.detail
    assert probe.coverage_state == "UNKNOWN"
    assert badge_from_probe(probe) is HealthBadge.UNAVAILABLE


def test_owls_empty_slate_classifies_emppty(monkeypatch):
    probe, captured = _adapter_probe(tt_body=TT_BODY_EMPTY, monkeypatch=monkeypatch)
    assert probe.ok is True
    assert probe.authenticated is True
    assert probe.coverage_state == "EMPTY"
    assert badge_from_probe(probe) is HealthBadge.HEALTHY
    assert "events=0" in probe.coverage_detail
    assert len(captured) == 2


def test_owls_events_without_markets_not_falsely_available(monkeypatch):
    probe, _ = _adapter_probe(tt_body=TT_BODY_NO_MARKETS, monkeypatch=monkeypatch)
    assert probe.ok is False
    assert probe.coverage_state == "UNKNOWN"
    assert probe.coverage_state != "AVAILABLE"
    assert badge_from_probe(probe) is HealthBadge.UNAVAILABLE


def test_owls_markets_without_rootidx_not_available(monkeypatch):
    probe, _ = _adapter_probe(tt_body=TT_BODY_NO_ROOTIDX, monkeypatch=monkeypatch)
    assert probe.ok is False
    assert probe.coverage_state == "UNKNOWN"
    assert probe.coverage_state != "AVAILABLE"


def test_owls_event_market_rootidx_classifies_available(monkeypatch):
    probe, captured = _adapter_probe(tt_body=TT_BODY_AVAILABLE, monkeypatch=monkeypatch)
    assert probe.ok is True
    assert probe.authenticated is True
    assert probe.coverage_state == "AVAILABLE"
    assert badge_from_probe(probe) is HealthBadge.HEALTHY
    assert "events=2" in probe.coverage_detail
    assert "inplay_events=1" in probe.coverage_detail
    assert "markets=2" in probe.coverage_detail
    assert "priced_selections=4" in probe.coverage_detail
    assert "rootidx_values=4" in probe.coverage_detail
    assert len(captured) == 2


def test_owls_ladder_structure_validated(monkeypatch):
    probe, _ = _adapter_probe(tt_body=TT_BODY_AVAILABLE, monkeypatch=monkeypatch)
    assert probe.ok is True
    assert "ladder=reachable" in probe.coverage_detail
    assert "ladder_entries=4" in probe.coverage_detail


def test_owls_ladder_failure_reported_in_detail(monkeypatch):
    probe, _ = _adapter_probe(
        tt_body=TT_BODY_AVAILABLE,
        ladder_status=503,
        ladder_body={"error": "unavailable"},
        monkeypatch=monkeypatch,
    )
    assert probe.ok is True  # primary TT data still present
    assert "ladder=status 503" in probe.coverage_detail
    assert "ladder_entries=0" in probe.coverage_detail


def test_owls_ladder_schema_error_reported(monkeypatch):
    def _fake(url, **kwargs):
        if url.endswith("/ladder"):
            return FetchResult(ok=True, status_code=200, latency_ms=10, error_type=None, body="<html>")
        return _Result(200, TT_BODY_AVAILABLE)

    monkeypatch.setattr(adapters_module, "fetch", _fake)
    definition = find_provider("owls_insight")
    probe = REAL_ADAPTERS["owls_insight"].probe(definition, {SECRET_NAME: SECRET_VALUE}, {})
    assert probe.coverage_state == "AVAILABLE"
    assert "ladder=schema_error" in probe.coverage_detail


def test_owls_coverage_detail_is_aggregate_counts_only(monkeypatch):
    probe, _ = _adapter_probe(tt_body=TT_BODY_AVAILABLE, monkeypatch=monkeypatch)
    assert probe.coverage_detail.startswith("state=fl; sport=TABLE_TENNIS")
    assert "PLAYER_ALPHA" not in probe.coverage_detail
    assert "evt-1" not in probe.coverage_detail
    assert "selection_id" not in probe.coverage_detail
    assert "rootIdx" not in probe.detail.replace("rootidx", "")  # only sanitized keys
    assert SECRET_VALUE not in probe.coverage_detail


def test_owls_probe_makes_at_most_two_http_calls(monkeypatch):
    _probe, captured = _adapter_probe(tt_body=TT_BODY_AVAILABLE, monkeypatch=monkeypatch)
    assert len(captured) == 2
    _probe, captured = _adapter_probe(
        tt_status=401, tt_body={"error": "no"}, monkeypatch=monkeypatch
    )
    assert len(captured) == 1  # auth failure short-circuits the ladder call


def test_owls_probe_errors_never_leak_secret(monkeypatch):
    for status, body in (
        (401, {"error": "invalid token"}),
        (403, PLAN_ERROR_BODY),
        (429, {"error": "too many requests"}),
        (500, {"error": "boom"}),
    ):
        probe, captured = _adapter_probe(
            tt_status=status, tt_body=body, monkeypatch=monkeypatch
        )
        serialized = json.dumps(probe.to_dict())
        assert SECRET_VALUE not in serialized, status
        assert "Bearer" not in serialized, status
        for call in captured:
            assert SECRET_VALUE not in call["url"], status
            # The key travels only inside the transport Authorization header
            # and is registered as a known secret for redaction; it must never
            # surface in the probe output or URLs.
            assert call["headers"].get("Authorization") == f"Bearer {SECRET_VALUE}", status
            assert SECRET_VALUE in call["known"], status


def test_owls_no_raw_odds_ingestion_started():
    # This bounded setup task must not touch the Markets ingestion pipeline.
    import defend_markets

    assert "OwlsInsight" not in dir(defend_markets)
    for module_name in ("defend_markets.arb", "defend_markets.quant"):
        import importlib

        module = importlib.import_module(module_name)
        assert "owls" not in module.__dict__, module_name


def test_generic_setup_ui_renders_owls_without_special_case():
    # The Setup UI is registry-driven: the provider card, credential field,
    # Save/Remove and Test actions are rendered generically from the backend
    # snapshot. No frontend special-casing for this provider may exist.
    panel = (
        Path(__file__).resolve().parents[1]
        / "defend-ui-v2"
        / "components"
        / "setup"
        / "SetupIntegrationsPanel.tsx"
    )
    card = (
        Path(__file__).resolve().parents[1]
        / "defend-ui-v2"
        / "components"
        / "setup"
        / "ProviderCard.tsx"
    )
    for path in (panel, card):
        source = path.read_text(encoding="utf-8")
        assert "owls" not in source.casefold(), path.name
