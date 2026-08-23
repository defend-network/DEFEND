from __future__ import annotations

from defend_integrations.adapters import REAL_ADAPTERS
from defend_integrations.models import AdapterKind
from defend_integrations.registry import (
    CATEGORIES,
    LEGACY_SECRET_MAP,
    PRODUCTS,
    PROVIDERS,
    REGISTRY_SECRET_NAMES,
    find_provider,
    providers_for_product,
    providers_in_category,
)

REAL_PROVIDER_IDS = {
    "vast",
    "huggingface",
    "fred",
    "congress_gov",
    "the_odds_api",
    "odds_api_io",
    "oddspapi",
    "sec_edgar",
    "world_bank",
    "polymarket",
}


def test_twelve_categories_match_specification_order():
    assert [category.category_id for category in CATEGORIES] == [
        "core",
        "ai_models",
        "vast_compute",
        "sports",
        "table_tennis",
        "markets",
        "macro",
        "government_events",
        "prediction_markets",
        "crypto",
        "integrations",
        "diagnostics",
    ]


def test_four_products_match_specification():
    assert [product.product_id for product in PRODUCTS] == [
        "defend_ai",
        "defendcoder",
        "defendmarkets",
        "scs",
    ]


def test_provider_ids_are_unique_and_categories_exist():
    ids = [provider.provider_id for provider in PROVIDERS]
    assert len(ids) == len(set(ids))
    category_ids = {category.category_id for category in CATEGORIES}
    for provider in PROVIDERS:
        assert provider.category in category_ids, provider.provider_id
        assert provider.display_name
        assert provider.purpose
        assert provider.adapter_kind in (AdapterKind.REAL, AdapterKind.PLACEHOLDER)


def test_secret_names_are_non_empty_and_registered():
    for provider in PROVIDERS:
        for name in (*provider.required_secrets, *provider.optional_secrets):
            assert isinstance(name, str) and name, provider.provider_id
            assert name in REGISTRY_SECRET_NAMES, name


def test_products_referenced_by_providers_exist():
    product_ids = {product.product_id for product in PRODUCTS}
    for provider in PROVIDERS:
        for product in provider.products:
            assert product in product_ids, provider.provider_id


def test_real_adapters_have_matching_real_definitions():
    assert set(REAL_ADAPTERS) == REAL_PROVIDER_IDS
    for provider in PROVIDERS:
        if provider.provider_id in REAL_PROVIDER_IDS:
            assert provider.adapter_kind is AdapterKind.REAL, provider.provider_id
        elif provider.adapter_kind is AdapterKind.REAL:
            assert provider.provider_id in REAL_ADAPTERS, provider.provider_id


def test_placeholder_providers_are_explicitly_placeholder():
    for provider in PROVIDERS:
        if provider.provider_id in REAL_PROVIDER_IDS:
            continue
        assert provider.adapter_kind is AdapterKind.PLACEHOLDER, provider.provider_id


def test_no_key_providers_are_first_class():
    for provider_id in ("sec_edgar", "world_bank", "polymarket"):
        provider = find_provider(provider_id)
        assert provider is not None
        assert provider.auth_type.value in ("none", "user_agent")
        assert not provider.required_secrets


def test_legacy_secret_map_targets_existing_providers():
    for secret_name, provider_id in LEGACY_SECRET_MAP.items():
        assert secret_name in REGISTRY_SECRET_NAMES or secret_name in LEGACY_SECRET_MAP
        assert find_provider(provider_id) is not None, provider_id
    # Every initially required secret id is covered by the compatibility map.
    for required in (
        "VAST_API_KEY",
        "HF_TOKEN",
        "THE_ODDS_API_KEY",
        "FRED_API_KEY",
        "CONGRESS_API_KEY",
    ):
        assert required in LEGACY_SECRET_MAP


def test_provider_category_grouping():
    sports = [p.provider_id for p in providers_in_category("sports")]
    assert "the_odds_api" in sports
    assert "sports_odds_secondary" in sports
    macro = [p.provider_id for p in providers_in_category("macro")]
    assert "fred" in macro and "world_bank" in macro


def test_product_mapping_is_backend_data():
    markets = {p.provider_id for p in providers_for_product("defendmarkets")}
    assert "fred" in markets
    assert "the_odds_api" in markets
    assert "sec_edgar" in markets
    assert "polymarket" in markets
    coder = {p.provider_id for p in providers_for_product("defendcoder")}
    assert "vast" in coder and "huggingface" in coder
    scs = {p.provider_id for p in providers_for_product("scs")}
    assert "world_bank" in scs and "fred" in scs


def test_rate_limit_and_license_metadata_present_on_real_providers():
    for provider_id in ("fred", "the_odds_api", "congress_gov", "sec_edgar"):
        provider = find_provider(provider_id)
        assert provider is not None
        assert provider.rate_limits.to_dict() is not None
        assert provider.license.commercial_use_status in (
            "allowed",
            "restricted",
            "unknown",
        )
        assert provider.license.redistribution_status in (
            "allowed",
            "restricted",
            "unknown",
        )


def test_tt_provider_cards_and_capability_matrix():
    for provider_id, secret in (
        ("odds_api_io", "ODDS_API_IO_API_KEY"),
        ("betsapi_tt", "BETSAPI_API_KEY"),
        ("sportsapi_pro", "SPORTSAPI_PRO_API_KEY"),
        ("sportmicro_tt", "SPORTMICRO_API_KEY"),
        ("rapidapi_tabletennis", "RAPIDAPI_KEY"),
        ("rapidapi_tt_live", "RAPIDAPI_KEY"),
        ("rapidapi_tt_micro", "RAPIDAPI_KEY"),
        ("sportradar_tt", "SPORTRADAR_API_KEY"),
        ("sports_game_odds", "SPORTS_GAME_ODDS_API_KEY"),
    ):
        provider = find_provider(provider_id)
        assert provider is not None, provider_id
        assert provider.category == "table_tennis", provider_id
        assert secret in provider.required_secrets, provider_id
        assert secret in REGISTRY_SECRET_NAMES, secret
        capabilities = provider.capabilities.to_dict()
        for column in (
            "live_odds",
            "historical_odds",
            "completed_results",
            "historical_results",
            "live_scores",
            "player_ids",
            "event_ids",
            "bookmaker_detail",
            "odds_movements",
            "pagination",
            "rate_limit",
            "cost_quota",
            "adapter_status",
            "tt_live_odds",
            "tt_historical_odds",
            "tt_results",
            "tt_live_scores",
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
            "historical_odds_plan_requirement",
        ):
            assert column in capabilities, provider_id

    odds_api_io = find_provider("odds_api_io")
    assert odds_api_io is not None
    assert odds_api_io.adapter_kind is AdapterKind.REAL
    assert odds_api_io.capabilities.earliest_history == "2025-12"
    assert odds_api_io.capabilities.adapter_status == "partial"
    assert "SPORTS_ODDS_PRIMARY_API_KEY" not in odds_api_io.required_secrets
    for provider_id in (
        "betsapi_tt", "sportsapi_pro", "sportmicro_tt",
        "rapidapi_tabletennis", "rapidapi_tt_live", "rapidapi_tt_micro",
        "sportradar_tt", "sports_game_odds",
    ):
        provider = find_provider(provider_id)
        assert provider is not None
        assert provider.adapter_kind is AdapterKind.PLACEHOLDER, provider_id
        assert provider.capabilities.adapter_status == "not_implemented", provider_id


def test_rapidapi_providers_share_one_credential_with_hosts():
    rapidapi_ids = (
        "rapidapi_tabletennis",
        "rapidapi_tt_live",
        "rapidapi_tt_micro",
        "rapidapi_allsportsapi2",
        "rapidapi_allscores",
    )
    expected_hosts = {
        "rapidapi_tabletennis": "https://tabletennisapi.p.rapidapi.com",
        "rapidapi_tt_live": "https://table-tennis-api-live-scores-stats-odds-predictions.p.rapidapi.com",
        "rapidapi_tt_micro": "https://table-tennis-micro.p.rapidapi.com",
        "rapidapi_allsportsapi2": "https://allsportsapi2.p.rapidapi.com",
        "rapidapi_allscores": "https://allscores.p.rapidapi.com",
    }
    for provider_id in rapidapi_ids:
        provider = find_provider(provider_id)
        assert provider is not None, provider_id
        assert provider.required_secrets == ("RAPIDAPI_KEY",), provider_id
        assert provider.host == expected_hosts[provider_id], provider_id
    assert REGISTRY_SECRET_NAMES == frozenset(
        name
        for provider in PROVIDERS
        for name in (*provider.required_secrets, *provider.optional_secrets)
    )
    assert "RAPIDAPI_KEY" in REGISTRY_SECRET_NAMES
    assert "SPORTS_GAME_ODDS_API_KEY" in REGISTRY_SECRET_NAMES


def test_tt_capabilities_are_truthful_verified_values():
    odds_api_io = find_provider("odds_api_io")
    assert odds_api_io is not None
    caps = odds_api_io.capabilities
    assert caps.tt_results == "yes (verified)"
    assert caps.tt_historical_odds == "not_available"
    assert caps.tt_live_odds == "no (verified: empty bookmakers on free tier)"
    assert caps.historical_odds_plan_requirement is not None
    assert "not_available" not in {
        "live_odds": caps.live_odds,
        "historical_odds": caps.historical_odds,
    }
    for provider_id in (
        "betsapi_tt",
        "sportsapi_pro",
        "sportmicro_tt",
        "rapidapi_tabletennis",
        "rapidapi_tt_live",
        "rapidapi_tt_micro",
        "sportradar_tt",
        "sports_game_odds",
        "sportdevs_tt",
        "tabt",
    ):
        provider = find_provider(provider_id)
        assert provider is not None
        # Placeholders must never claim a verified TT capability.
        for column in ("tt_results", "tt_live_odds", "tt_historical_odds", "tt_live_scores"):
            value = getattr(provider.capabilities, column)
            assert "(verified)" not in value, (provider_id, column)