"""Phase A multi-provider setup behavior: shared RapidAPI credential
reference, honest card states, and secret non-disclosure.

Covers the consolidated multi-provider directive requirements:
- one RAPIDAPI_KEY shared across five provider entries (no duplicated secrets)
- saving/removing the shared key flips every dependent provider
- rotation invalidation touches every dependent provider
- placeholder cards show honest ADAPTER_NOT_IMPLEMENTED / CREDENTIAL_PRESENT
- credentials never leak through views
"""

from __future__ import annotations

from defend_integrations.adapters import REAL_ADAPTERS
from defend_integrations.models import AdapterKind, HealthBadge, ProviderState
from defend_integrations.registry import (
    PROVIDERS,
    find_provider,
    providers_in_category,
)
from defend_integrations.service import SetupIntegrationsService
from defend_integrations.stores import (
    ProviderConfigStore,
    SecretRegistry,
    apply_rotation_invalidation,
)
from defend_control.secrets import DpapiSecretStore

RAPIDAPI_PROVIDER_IDS = (
    "rapidapi_tabletennis",
    "rapidapi_tt_live",
    "rapidapi_tt_micro",
    "rapidapi_allsportsapi2",
    "rapidapi_allscores",
)


def _service(tmp_path):
    secret_path = tmp_path / "secrets.dpapi"
    config_path = tmp_path / "integrations-config.json"
    secrets = SecretRegistry(DpapiSecretStore(secret_path))
    config = ProviderConfigStore(config_path)
    return SetupIntegrationsService(secrets, config), secrets, config


def test_rapidapi_entries_share_single_secret_reference():
    for provider_id in RAPIDAPI_PROVIDER_IDS:
        provider = find_provider(provider_id)
        assert provider is not None
        assert provider.required_secrets == ("RAPIDAPI_KEY",)
        assert provider.host is not None
        assert provider.capabilities.adapter_status == "not_implemented"
    rapidapi_entries = [
        provider
        for provider in PROVIDERS
        if provider.provider_id in RAPIDAPI_PROVIDER_IDS
    ]
    assert len(rapidapi_entries) == 5
    assert {entry.required_secrets for entry in rapidapi_entries} == {
        ("RAPIDAPI_KEY",)
    }


def test_single_rapidapi_key_save_marks_all_dependents_configured(tmp_path):
    service, secrets, config = _service(tmp_path)
    service.save_secret("rapidapi_tabletennis", "RAPIDAPI_KEY", "rapid-secret-1234")
    for provider_id in RAPIDAPI_PROVIDER_IDS:
        view = service.provider_view(provider_id)
        assert view["credential_configured"] is True, provider_id
        assert view["state"] == ProviderState.CREDENTIAL_PRESENT.value, provider_id
        assert view["credentials"][0]["name"] == "RAPIDAPI_KEY"
        assert view["credentials"][0]["configured"] is True
        assert view["credentials"][0]["masked"] == "****1234"


def test_remove_shared_key_flips_all_dependents(tmp_path):
    service, secrets, config = _service(tmp_path)
    service.save_secret("rapidapi_tt_micro", "RAPIDAPI_KEY", "rapid-secret-1234")
    service.remove_secret("rapidapi_tt_micro", "RAPIDAPI_KEY")
    for provider_id in RAPIDAPI_PROVIDER_IDS:
        view = service.provider_view(provider_id)
        assert view["credential_configured"] is False, provider_id
        assert view["state"] == ProviderState.ADAPTER_NOT_IMPLEMENTED.value, provider_id


def test_rotation_invalidation_touches_every_rapidapi_dependent(tmp_path):
    service, secrets, config = _service(tmp_path)
    service.save_secret("rapidapi_allscores", "RAPIDAPI_KEY", "rapid-secret-1234")
    for provider_id in RAPIDAPI_PROVIDER_IDS:
        config.record_probe(
            provider_id,
            badge=HealthBadge.HEALTHY,
            tested_at="2026-08-18T00:00:00Z",
            detail="stale",
            status_code=200,
            latency_ms=1,
            last_success_at="2026-08-18T00:00:00Z",
            remaining_quota=None,
            quota_reset_at=None,
            default_enabled=True,
        )
    apply_rotation_invalidation(
        config, secrets, updates={"RAPIDAPI_KEY": "rotated-secret-99"}
    )
    for provider_id in RAPIDAPI_PROVIDER_IDS:
        assert config.get(provider_id).health_badge.value == "NOT_TESTED", provider_id
        assert config.get(provider_id).tested_at is None, provider_id


def test_rapidapi_key_never_leaks_through_views(tmp_path):
    service, secrets, config = _service(tmp_path)
    service.save_secret("rapidapi_tt_live", "RAPIDAPI_KEY", "super-secret-value-xyz")
    for provider_id in RAPIDAPI_PROVIDER_IDS:
        view = service.provider_view(provider_id)
        assert "super-secret-value-xyz" not in str(view)
    snapshot = service.snapshot()
    assert "super-secret-value-xyz" not in str(snapshot)
    assert "rapid-secret" not in str(snapshot)


def test_sports_game_odds_card_honest_states(tmp_path):
    service, secrets, config = _service(tmp_path)
    provider = find_provider("sports_game_odds")
    assert provider is not None
    assert provider.required_secrets == ("SPORTS_GAME_ODDS_API_KEY",)
    assert provider.adapter_kind is AdapterKind.PLACEHOLDER
    view = service.provider_view("sports_game_odds")
    assert view["state"] == ProviderState.ADAPTER_NOT_IMPLEMENTED.value
    assert view["credentials"][0]["configured"] is False
    service.save_secret(
        "sports_game_odds", "SPORTS_GAME_ODDS_API_KEY", "sgo-key-4321"
    )
    view = service.provider_view("sports_game_odds")
    assert view["state"] == ProviderState.CREDENTIAL_PRESENT.value
    assert view["credentials"][0]["masked"] == "****4321"
    with_existing = {p for p in REAL_ADAPTERS}
    assert "sports_game_odds" not in with_existing
    assert view["test_supported"] is False


def test_sportradar_card_is_placeholder_until_adapter_exists(tmp_path):
    service, secrets, config = _service(tmp_path)
    provider = find_provider("sportradar_tt")
    assert provider is not None
    assert provider.host == "https://api.sportradar.com/tabletennis/v2"
    assert provider.contract_version == "v2"
    view = service.provider_view("sportradar_tt")
    assert view["state"] == ProviderState.ADAPTER_NOT_IMPLEMENTED.value
    assert view["host"] == "https://api.sportradar.com/tabletennis/v2"
    assert view["contract_version"] == "v2"
    assert view["test_supported"] is False


def test_new_tt_capability_cells_default_to_unknown():
    documented = {
        ("sports_game_odds", "tt_live_odds"),
        ("sports_game_odds", "tt_historical_odds"),
        ("sports_game_odds", "tt_results"),
        ("sports_game_odds", "tt_live_scores"),
        ("sports_game_odds", "tt_fixtures"),
        ("sports_game_odds", "tt_player_data"),
        ("sports_game_odds", "tt_bookmakers"),
        ("sports_game_odds", "tt_probabilities"),
        ("rapidapi_tabletennis", "tt_results"),
        ("rapidapi_tt_live", "tt_live_scores"),
    }
    columns = (
        "tt_fixtures",
        "tt_player_data",
        "tt_rankings",
        "tt_stats",
        "tt_form_h2h",
        "tt_live_state",
        "tt_bookmakers",
        "tt_probabilities",
        "tt_opening_line",
        "tt_closing_line",
        "contract_drift",
    )
    for provider_id in (
        "sports_game_odds",
        "rapidapi_tt_micro",
        "rapidapi_tt_live",
        "rapidapi_tabletennis",
    ):
        provider = find_provider(provider_id)
        assert provider is not None
        caps = provider.capabilities
        for column in columns:
            if (provider_id, column) in documented:
                assert getattr(caps, column) != "unknown", (provider_id, column)
            else:
                value = getattr(caps, column)
                assert value == "unknown" or value.startswith("unknown"), (
                    provider_id,
                    column,
                )


def test_allsportsapi2_and_allscores_live_in_sports_category():
    for provider_id in ("rapidapi_allsportsapi2", "rapidapi_allscores"):
        provider = find_provider(provider_id)
        assert provider is not None
        assert provider.category == "sports"
        assert provider.capabilities.adapter_status == "not_implemented"
        assert "RAPIDAPI_KEY" in provider.required_secrets


def test_shared_secret_not_duplicated_in_config_store(tmp_path):
    _, secrets, config = _service(tmp_path)
    secrets.save({"RAPIDAPI_KEY": "shared-value-1"})
    assert config.get("rapidapi_tt_micro").config == {}
    assert config.get("rapidapi_allscores").config == {}