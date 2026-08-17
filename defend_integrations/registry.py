"""Declarative provider registry for the Setup / Integrations control plane.

All provider metadata lives here (and in the config store for mutable state).
The web UI renders cards from the data the backend returns; no provider
business logic is duplicated in the frontend.
"""

from __future__ import annotations

from .models import (
    AdapterKind,
    AuthType,
    Category,
    Product,
    ProviderDefinition,
    ProviderLicense,
    ProviderRateLimits,
)


CATEGORIES: tuple[Category, ...] = (
    Category("core", "Core", "PostgreSQL, tunnel, product origins and identity"),
    Category(
        "ai_models",
        "AI / Models",
        "Hugging Face, local model serving, aliases and provider slots",
    ),
    Category(
        "vast_compute",
        "Vast / Compute",
        "Vast.ai GPU compute, GPU policy and runtime budgets",
    ),
    Category(
        "sports",
        "Sports",
        "Odds and sports data feeds used by sports and markets desks",
    ),
    Category(
        "table_tennis",
        "Table Tennis",
        "Table tennis event and fixture data providers",
    ),
    Category(
        "markets",
        "Markets",
        "Market data: SEC filings, equities, fundamentals and licensed slots",
    ),
    Category(
        "macro",
        "Macro",
        "Macroeconomic and climate series: FRED, World Bank, BLS and more",
    ),
    Category(
        "government_events",
        "Government / Events",
        "Congress.gov, FEC, Federal Register and disclosure feeds",
    ),
    Category(
        "prediction_markets",
        "Prediction Markets",
        "Polymarket, Kalshi and event-contract feeds",
    ),
    Category("crypto", "Crypto", "CoinGecko, Binance public data and exchange slots"),
    Category("integrations", "Integrations", "Webhooks, Slack and e-mail delivery"),
    Category("diagnostics", "Diagnostics", "Cross-provider health and quota matrix"),
)


PRODUCTS: tuple[Product, ...] = (
    Product("defend_ai", "DEFEND AI", "Core chat + research product"),
    Product("defendcoder", "DEFENDcoder", "Autonomous coding agent"),
    Product("defendmarkets", "DEFENDmarkets", "Markets, macro and sports data desks"),
    Product("scs", "SCS", "Sunshine Climate Solutions AI"),
)


def _no_key() -> ProviderLicense:
    return ProviderLicense(
        commercial_use_status="allowed",
        redistribution_status="restricted",
        attribution_requirement="Source attribution required where mandated",
    )


PROVIDERS: tuple[ProviderDefinition, ...] = (
    # ------------------------------------------------------------------ Core
    ProviderDefinition(
        provider_id="admin_identity",
        display_name="Admin identity",
        purpose="Owner/admin credentials used by the identity store",
        category="core",
        auth_type=AuthType.ACCOUNT,
        adapter_kind=AdapterKind.PLACEHOLDER,
        required_secrets=("DEFEND_OWNER_USER", "DEFEND_OWNER_EMAIL"),
        optional_secrets=("DEFEND_OWNER_PASS",),
        notes="Managed from Users & Roles; shown here for credential visibility.",
    ),
    ProviderDefinition(
        provider_id="postgres_per_product",
        display_name="PostgreSQL (per product)",
        purpose="Each product's relational database (DEFEND AI, Sports, SCS, markets)",
        category="core",
        auth_type=AuthType.NONE,
        adapter_kind=AdapterKind.PLACEHOLDER,
        optional_config=("database_url_configured", "schema_version"),
        notes="Database URLs are set via per-product environment variables.",
    ),
    ProviderDefinition(
        provider_id="cloudflare_tunnel",
        display_name="Cloudflare tunnel",
        purpose="Public HTTPS routes for product origins",
        category="core",
        auth_type=AuthType.NONE,
        adapter_kind=AdapterKind.PLACEHOLDER,
        optional_config=("tunnel", "config"),
        notes="Managed by the Control Center runtime; health is observed locally.",
    ),
    ProviderDefinition(
        provider_id="origin_defend_ai",
        display_name="DEFEND AI origin",
        purpose="Public origin and local ports for the DEFEND AI product",
        category="core",
        auth_type=AuthType.NONE,
        adapter_kind=AdapterKind.PLACEHOLDER,
        optional_config=("public_origin", "api_port", "web_port"),
    ),
    ProviderDefinition(
        provider_id="origin_defendcoder",
        display_name="DEFENDcoder origin",
        purpose="Public origin for the DEFENDcoder product",
        category="core",
        auth_type=AuthType.NONE,
        adapter_kind=AdapterKind.PLACEHOLDER,
        optional_config=("public_origin",),
    ),
    ProviderDefinition(
        provider_id="origin_defendmarkets",
        display_name="DEFENDmarkets origin",
        purpose="Public origin and local ports for the DEFENDmarkets product",
        category="core",
        auth_type=AuthType.NONE,
        adapter_kind=AdapterKind.PLACEHOLDER,
        optional_config=("public_origin", "api_port", "web_port"),
    ),
    ProviderDefinition(
        provider_id="origin_scs",
        display_name="SCS origin",
        purpose="Public origin and local ports for the SCS product",
        category="core",
        auth_type=AuthType.NONE,
        adapter_kind=AdapterKind.PLACEHOLDER,
        optional_config=("public_origin", "api_port", "web_port"),
    ),
    # ------------------------------------------------------------- AI / Models
    ProviderDefinition(
        provider_id="huggingface",
        display_name="Hugging Face",
        purpose="Model hubs, adapters and tokens for DEFEND AI and SCS AI",
        category="ai_models",
        auth_type=AuthType.BEARER,
        adapter_kind=AdapterKind.REAL,
        required_secrets=("HF_TOKEN",),
        docs_url="https://huggingface.co/docs/api-inference",
        products=("defend_ai", "defendcoder", "scs"),
        rate_limits=ProviderRateLimits(requests_per_second=50),
        license=_no_key(),
    ),
    ProviderDefinition(
        provider_id="local_model",
        display_name="Local model (vLLM / Ollama)",
        purpose="Local model serving paths, images and revision pins",
        category="ai_models",
        auth_type=AuthType.BEARER,
        adapter_kind=AdapterKind.PLACEHOLDER,
        optional_secrets=("VLLM_API_KEY",),
        optional_config=("image", "max_model_len", "gpu_ram_mb"),
        products=("defend_ai", "defendcoder", "scs"),
        notes="Legacy VLLM_API_KEY maps here for compatibility.",
    ),
    ProviderDefinition(
        provider_id="model_aliases",
        display_name="Model aliases",
        purpose="Stable aliases mapping to provider model names",
        category="ai_models",
        auth_type=AuthType.NONE,
        adapter_kind=AdapterKind.PLACEHOLDER,
        optional_config=("aliases",),
        products=("defend_ai", "defendcoder", "scs"),
    ),
    ProviderDefinition(
        provider_id="model_provider_slots",
        display_name="Model provider slots",
        purpose="Reserved slots for future hosted model providers",
        category="ai_models",
        auth_type=AuthType.API_KEY,
        adapter_kind=AdapterKind.PLACEHOLDER,
        optional_secrets=("MODEL_PROVIDER_API_KEY",),
        products=("defend_ai", "defendcoder", "scs"),
    ),
    # --------------------------------------------------------- Vast / Compute
    ProviderDefinition(
        provider_id="vast",
        display_name="Vast.ai",
        purpose="GPU compute marketplace used to host models",
        category="vast_compute",
        auth_type=AuthType.BEARER,
        adapter_kind=AdapterKind.REAL,
        required_secrets=("VAST_API_KEY",),
        docs_url="https://docs.vast.ai",
        products=("defend_ai", "defendcoder", "scs"),
        rate_limits=ProviderRateLimits(requests_per_minute=60),
        license=ProviderLicense(
            commercial_use_status="allowed",
            redistribution_status="restricted",
        ),
    ),
    ProviderDefinition(
        provider_id="gpu_policy",
        display_name="GPU policy",
        purpose="Allowed GPU families and minimum RAM floor for compute",
        category="vast_compute",
        auth_type=AuthType.NONE,
        adapter_kind=AdapterKind.PLACEHOLDER,
        optional_config=("allowed_families", "min_ram_mb", "max_hourly"),
        products=("defend_ai", "defendcoder", "scs"),
    ),
    ProviderDefinition(
        provider_id="coder_budget",
        display_name="DEFENDcoder budget",
        purpose="Session and hourly budget policy for coder compute",
        category="vast_compute",
        auth_type=AuthType.NONE,
        adapter_kind=AdapterKind.PLACEHOLDER,
        optional_config=("session_budget_usd", "max_hourly"),
        products=("defendcoder",),
    ),
    ProviderDefinition(
        provider_id="deployment_runtime_policy",
        display_name="Deployment / runtime policy",
        purpose="Image pins, disk and runtime constraints for deployments",
        category="vast_compute",
        auth_type=AuthType.NONE,
        adapter_kind=AdapterKind.PLACEHOLDER,
        optional_config=("image", "disk_gb"),
        products=("defend_ai", "defendcoder", "scs"),
    ),
    # ----------------------------------------------------------------- Sports
    ProviderDefinition(
        provider_id="the_odds_api",
        display_name="The Odds API",
        purpose="Sports odds and scores feed",
        category="sports",
        auth_type=AuthType.API_KEY,
        adapter_kind=AdapterKind.REAL,
        required_secrets=("THE_ODDS_API_KEY",),
        docs_url="https://the-odds-api.com",
        products=("defendmarkets",),
        rate_limits=ProviderRateLimits(requests_per_second=1, monthly_credits=500),
        license=_no_key(),
    ),
    ProviderDefinition(
        provider_id="api_sports",
        display_name="API-Sports",
        purpose="Sports schedules, results and statistics",
        category="sports",
        auth_type=AuthType.API_KEY,
        adapter_kind=AdapterKind.PLACEHOLDER,
        required_secrets=("API_SPORTS_API_KEY",),
        products=("defendmarkets",),
        license=_no_key(),
    ),
    ProviderDefinition(
        provider_id="sportsdatario",
        display_name="SportsDataIO",
        purpose="Sports data endpoints per sport",
        category="sports",
        auth_type=AuthType.API_KEY,
        adapter_kind=AdapterKind.PLACEHOLDER,
        required_secrets=("SPORTSDATAIO_API_KEY",),
        products=("defendmarkets",),
        license=_no_key(),
    ),
    ProviderDefinition(
        provider_id="odds_api_io",
        display_name="Odds-API.io",
        purpose="Alternative odds feed",
        category="sports",
        auth_type=AuthType.API_KEY,
        adapter_kind=AdapterKind.PLACEHOLDER,
        required_secrets=("SPORTS_ODDS_PRIMARY_API_KEY",),
        products=("defendmarkets",),
        license=_no_key(),
    ),
    ProviderDefinition(
        provider_id="sports_odds_primary",
        display_name="Sports odds slot (primary)",
        purpose="Generic primary odds slot; the_odds_api or api_sports may fill it",
        category="sports",
        auth_type=AuthType.API_KEY,
        adapter_kind=AdapterKind.PLACEHOLDER,
        required_secrets=("SPORTS_ODDS_PRIMARY_API_KEY",),
        products=("defendmarkets",),
        license=_no_key(),
    ),
    ProviderDefinition(
        provider_id="sports_odds_secondary",
        display_name="Sports odds slot (secondary)",
        purpose="Generic secondary odds slot for fallback feeds",
        category="sports",
        auth_type=AuthType.API_KEY,
        adapter_kind=AdapterKind.PLACEHOLDER,
        required_secrets=("SPORTS_ODDS_SECONDARY_API_KEY",),
        products=("defendmarkets",),
        license=_no_key(),
    ),
    # ------------------------------------------------------------ Table Tennis
    ProviderDefinition(
        provider_id="sportradar_tt",
        display_name="Sportradar Table Tennis",
        purpose="Official table tennis results and rankings",
        category="table_tennis",
        auth_type=AuthType.API_KEY,
        adapter_kind=AdapterKind.PLACEHOLDER,
        required_secrets=("SPORTRADAR_API_KEY",),
        products=("defendmarkets",),
        license=_no_key(),
    ),
    ProviderDefinition(
        provider_id="sportdevs_tt",
        display_name="SportDevs Table Tennis",
        purpose="Table tennis fixture and score feeds",
        category="table_tennis",
        auth_type=AuthType.API_KEY,
        adapter_kind=AdapterKind.PLACEHOLDER,
        required_secrets=("SPORTDEVS_API_KEY",),
        products=("defendmarkets",),
        license=_no_key(),
    ),
    ProviderDefinition(
        provider_id="tabt",
        display_name="TabT",
        purpose="Table tennis platform data (association-managed)",
        category="table_tennis",
        auth_type=AuthType.NONE,
        adapter_kind=AdapterKind.PLACEHOLDER,
        products=("defendmarkets",),
        license=_no_key(),
    ),
    ProviderDefinition(
        provider_id="fixture_sports_provider",
        display_name="FixtureSports provider (internal)",
        purpose="Existing internal table tennis fixture source",
        category="table_tennis",
        auth_type=AuthType.NONE,
        adapter_kind=AdapterKind.PLACEHOLDER,
        products=("defendmarkets",),
    ),
    ProviderDefinition(
        provider_id="legacy_tt_engine",
        display_name="Legacy TT engine",
        purpose="Legacy table tennis engine status and data source",
        category="table_tennis",
        auth_type=AuthType.NONE,
        adapter_kind=AdapterKind.PLACEHOLDER,
        products=("defendmarkets",),
    ),
    # ---------------------------------------------------------------- Markets
    ProviderDefinition(
        provider_id="sec_edgar",
        display_name="SEC EDGAR",
        purpose="Company filings and financial disclosures",
        category="markets",
        auth_type=AuthType.USER_AGENT,
        adapter_kind=AdapterKind.REAL,
        docs_url="https://www.sec.gov/edgar/searchedgar",
        products=("defendmarkets",),
        rate_limits=ProviderRateLimits(requests_per_second=10),
        license=ProviderLicense(
            terms_url="https://www.sec.gov/os/accessing-edgar-data",
            commercial_use_status="allowed",
            redistribution_status="restricted",
            attribution_requirement="Attribution to SEC EDGAR required",
        ),
        notes="Requires a User-Agent identifying the application; no key.",
    ),
    ProviderDefinition(
        provider_id="alpha_vantage",
        display_name="Alpha Vantage",
        purpose="Equities and fundamentals time series",
        category="markets",
        auth_type=AuthType.API_KEY,
        adapter_kind=AdapterKind.PLACEHOLDER,
        required_secrets=("ALPHA_VANTAGE_API_KEY",),
        products=("defendmarkets",),
        license=_no_key(),
    ),
    ProviderDefinition(
        provider_id="finnhub",
        display_name="Finnhub",
        purpose="Market data and company fundamentals",
        category="markets",
        auth_type=AuthType.API_KEY,
        adapter_kind=AdapterKind.PLACEHOLDER,
        required_secrets=("FINNHUB_API_KEY",),
        products=("defendmarkets",),
        license=_no_key(),
    ),
    ProviderDefinition(
        provider_id="twelve_data",
        display_name="Twelve Data",
        purpose="OHLCV, quotes and forex feeds",
        category="markets",
        auth_type=AuthType.API_KEY,
        adapter_kind=AdapterKind.PLACEHOLDER,
        required_secrets=("TWELVE_DATA_API_KEY",),
        products=("defendmarkets",),
        license=_no_key(),
    ),
    ProviderDefinition(
        provider_id="licensed_market_data",
        display_name="Licensed market data slot",
        purpose="Future licensed exchange feed (reserved)",
        category="markets",
        auth_type=AuthType.API_KEY,
        adapter_kind=AdapterKind.PLACEHOLDER,
        optional_secrets=("LICENSED_MARKET_API_KEY",),
        products=("defendmarkets",),
        license=_no_key(),
    ),
    # ------------------------------------------------------------------ Macro
    ProviderDefinition(
        provider_id="fred",
        display_name="FRED",
        purpose="Federal Reserve economic data series",
        category="macro",
        auth_type=AuthType.API_KEY,
        adapter_kind=AdapterKind.REAL,
        required_secrets=("FRED_API_KEY",),
        docs_url="https://fred.stlouisfed.org/docs/api",
        products=("defendmarkets", "scs"),
        rate_limits=ProviderRateLimits(requests_per_second=1, requests_per_day=120),
        license=ProviderLicense(
            commercial_use_status="allowed",
            redistribution_status="restricted",
            attribution_requirement="Attribution to FRED required",
        ),
    ),
    ProviderDefinition(
        provider_id="alfred_vintages",
        display_name="ALFRED vintages",
        purpose="Historical data vintages for macro series",
        category="macro",
        auth_type=AuthType.API_KEY,
        adapter_kind=AdapterKind.PLACEHOLDER,
        required_secrets=("FRED_API_KEY",),
        products=("defendmarkets", "scs"),
        license=ProviderLicense(
            commercial_use_status="allowed",
            redistribution_status="restricted",
            attribution_requirement="Attribution to ALFRED required",
        ),
    ),
    ProviderDefinition(
        provider_id="bls",
        display_name="BLS",
        purpose="Bureau of Labor Statistics series",
        category="macro",
        auth_type=AuthType.API_KEY,
        adapter_kind=AdapterKind.PLACEHOLDER,
        optional_secrets=("BLS_API_KEY",),
        products=("defendmarkets", "scs"),
        license=_no_key(),
    ),
    ProviderDefinition(
        provider_id="world_bank",
        display_name="World Bank",
        purpose="Global development and climate indicators",
        category="macro",
        auth_type=AuthType.NONE,
        adapter_kind=AdapterKind.REAL,
        docs_url="https://datahelpdesk.worldbank.org/knowledgebase/articles/889392",
        products=("defendmarkets", "scs"),
        rate_limits=ProviderRateLimits(requests_per_second=5),
        license=ProviderLicense(
            commercial_use_status="allowed",
            redistribution_status="allowed",
            attribution_requirement="Attribution to World Bank data required",
        ),
    ),
    ProviderDefinition(
        provider_id="bea",
        display_name="BEA",
        purpose="Bureau of Economic Analysis (reserved)",
        category="macro",
        auth_type=AuthType.API_KEY,
        adapter_kind=AdapterKind.PLACEHOLDER,
        optional_secrets=("BEA_API_KEY",),
        products=("defendmarkets", "scs"),
        license=_no_key(),
    ),
    ProviderDefinition(
        provider_id="eia",
        display_name="EIA",
        purpose="Energy Information Administration (reserved)",
        category="macro",
        auth_type=AuthType.API_KEY,
        adapter_kind=AdapterKind.PLACEHOLDER,
        optional_secrets=("EIA_API_KEY",),
        products=("defendmarkets", "scs"),
        license=_no_key(),
    ),
    ProviderDefinition(
        provider_id="us_treasury",
        display_name="US Treasury",
        purpose="Treasury rates and fiscal data (reserved)",
        category="macro",
        auth_type=AuthType.NONE,
        adapter_kind=AdapterKind.PLACEHOLDER,
        products=("defendmarkets", "scs"),
        license=_no_key(),
    ),
    ProviderDefinition(
        provider_id="federal_reserve",
        display_name="Federal Reserve",
        purpose="Fed policy and H.4.1 data (reserved)",
        category="macro",
        auth_type=AuthType.NONE,
        adapter_kind=AdapterKind.PLACEHOLDER,
        products=("defendmarkets", "scs"),
        license=_no_key(),
    ),
    # ------------------------------------------------------ Government / Events
    ProviderDefinition(
        provider_id="congress_gov",
        display_name="Congress.gov",
        purpose="Federal legislation, members and hearings",
        category="government_events",
        auth_type=AuthType.API_KEY,
        adapter_kind=AdapterKind.REAL,
        required_secrets=("CONGRESS_API_KEY",),
        docs_url="https://api.congress.gov",
        products=("defend_ai", "defendmarkets"),
        rate_limits=ProviderRateLimits(requests_per_second=5, requests_per_day=5000),
        license=ProviderLicense(
            commercial_use_status="allowed",
            redistribution_status="restricted",
        ),
        notes="Also requires a descriptive User-Agent header.",
    ),
    ProviderDefinition(
        provider_id="openfec",
        display_name="OpenFEC",
        purpose="Campaign finance disclosure data",
        category="government_events",
        auth_type=AuthType.API_KEY,
        adapter_kind=AdapterKind.PLACEHOLDER,
        required_secrets=("FEC_API_KEY",),
        products=("defend_ai", "defendmarkets"),
        license=_no_key(),
    ),
    ProviderDefinition(
        provider_id="federal_register",
        display_name="Federal Register",
        purpose="Daily federal rules and notices",
        category="government_events",
        auth_type=AuthType.NONE,
        adapter_kind=AdapterKind.PLACEHOLDER,
        products=("defend_ai", "defendmarkets"),
        license=_no_key(),
    ),
    ProviderDefinition(
        provider_id="govinfo",
        display_name="GovInfo",
        purpose="GPO official publications (reserved)",
        category="government_events",
        auth_type=AuthType.API_KEY,
        adapter_kind=AdapterKind.PLACEHOLDER,
        optional_secrets=("GOVINFO_API_KEY",),
        products=("defend_ai", "defendmarkets"),
        license=_no_key(),
    ),
    ProviderDefinition(
        provider_id="regulations_gov",
        display_name="Regulations.gov",
        purpose="Rulemaking comments and documents (reserved)",
        category="government_events",
        auth_type=AuthType.API_KEY,
        adapter_kind=AdapterKind.PLACEHOLDER,
        optional_secrets=("REGULATIONS_GOV_API_KEY",),
        products=("defend_ai", "defendmarkets"),
        license=_no_key(),
    ),
    ProviderDefinition(
        provider_id="sec_disclosures",
        display_name="SEC disclosures",
        purpose="Insider trading and ownership disclosures",
        category="government_events",
        auth_type=AuthType.NONE,
        adapter_kind=AdapterKind.PLACEHOLDER,
        products=("defendmarkets",),
        license=_no_key(),
    ),
    ProviderDefinition(
        provider_id="public_official_disclosures",
        display_name="Public official disclosures",
        purpose="Financial disclosure forms of public officials (reserved)",
        category="government_events",
        auth_type=AuthType.NONE,
        adapter_kind=AdapterKind.PLACEHOLDER,
        products=("defend_ai", "defendmarkets"),
        license=_no_key(),
    ),
    # ------------------------------------------------------ Prediction Markets
    ProviderDefinition(
        provider_id="polymarket",
        display_name="Polymarket",
        purpose="Event-contract prices and market data",
        category="prediction_markets",
        auth_type=AuthType.NONE,
        adapter_kind=AdapterKind.REAL,
        docs_url="https://docs.polymarket.com",
        products=("defendmarkets",),
        rate_limits=ProviderRateLimits(requests_per_second=2),
        license=ProviderLicense(
            commercial_use_status="restricted",
            redistribution_status="restricted",
        ),
    ),
    ProviderDefinition(
        provider_id="kalshi",
        display_name="Kalshi",
        purpose="Event-contract markets (reserved; no public health probe)",
        category="prediction_markets",
        auth_type=AuthType.NONE,
        adapter_kind=AdapterKind.PLACEHOLDER,
        products=("defendmarkets",),
        license=ProviderLicense(
            commercial_use_status="restricted",
            redistribution_status="restricted",
        ),
    ),
    # ------------------------------------------------------------------ Crypto
    ProviderDefinition(
        provider_id="coingecko",
        display_name="CoinGecko",
        purpose="Cryptocurrency market data",
        category="crypto",
        auth_type=AuthType.API_KEY,
        adapter_kind=AdapterKind.PLACEHOLDER,
        optional_secrets=("COINGECKO_API_KEY",),
        products=("defendmarkets", "scs"),
        rate_limits=ProviderRateLimits(requests_per_minute=30),
        license=ProviderLicense(
            commercial_use_status="restricted",
            redistribution_status="restricted",
        ),
        notes="Key optional on the free tier.",
    ),
    ProviderDefinition(
        provider_id="binance_public",
        display_name="Binance public data",
        purpose="Public exchange market data (no trading)",
        category="crypto",
        auth_type=AuthType.NONE,
        adapter_kind=AdapterKind.PLACEHOLDER,
        products=("defendmarkets",),
        license=ProviderLicense(
            commercial_use_status="restricted",
            redistribution_status="restricted",
        ),
    ),
    ProviderDefinition(
        provider_id="exchange_slots",
        display_name="Exchange slots",
        purpose="Generic exchange feed slots (reserved)",
        category="crypto",
        auth_type=AuthType.API_KEY,
        adapter_kind=AdapterKind.PLACEHOLDER,
        optional_secrets=("EXCHANGE_API_KEY",),
        products=("defendmarkets",),
        license=ProviderLicense(
            commercial_use_status="restricted",
            redistribution_status="restricted",
        ),
    ),
    # ------------------------------------------------------------ Integrations
    ProviderDefinition(
        provider_id="webhooks",
        display_name="Webhooks",
        purpose="Outbound event delivery to configured endpoints",
        category="integrations",
        auth_type=AuthType.NONE,
        adapter_kind=AdapterKind.PLACEHOLDER,
        optional_config=("endpoints",),
        products=("defend_ai", "defendcoder", "defendmarkets", "scs"),
    ),
    ProviderDefinition(
        provider_id="slack",
        display_name="Slack",
        purpose="Notification delivery via webhook",
        category="integrations",
        auth_type=AuthType.BEARER,
        adapter_kind=AdapterKind.PLACEHOLDER,
        optional_secrets=("SLACK_WEBHOOK_URL",),
        products=("defend_ai", "defendcoder", "defendmarkets", "scs"),
    ),
    ProviderDefinition(
        provider_id="email_smtp",
        display_name="E-mail (SMTP)",
        purpose="Transactional e-mail delivery",
        category="integrations",
        auth_type=AuthType.ACCOUNT,
        adapter_kind=AdapterKind.PLACEHOLDER,
        required_secrets=("SMTP_USER",),
        optional_secrets=("SMTP_PASSWORD",),
        optional_config=("host", "port", "from_address"),
        products=("defend_ai", "defendcoder", "defendmarkets", "scs"),
    ),
)


# Migration compatibility: legacy secret IDs saved by the previous Setup dialog
# map onto provider registry entries so existing credentials keep working
# without re-entry. Values are read from the same DPAPI store as before.
LEGACY_SECRET_MAP: dict[str, str] = {
    "VAST_API_KEY": "vast",
    "HF_TOKEN": "huggingface",
    "VLLM_API_KEY": "local_model",
    "DEFEND_OWNER_USER": "admin_identity",
    "DEFEND_OWNER_EMAIL": "admin_identity",
    "DEFEND_OWNER_PASS": "admin_identity",
    "THE_ODDS_API_KEY": "the_odds_api",
    "FRED_API_KEY": "fred",
    "CONGRESS_API_KEY": "congress_gov",
    "FEC_API_KEY": "openfec",
    "API_SPORTS_API_KEY": "api_sports",
    "SPORTRADAR_API_KEY": "sportradar_tt",
    "SPORTDEVS_API_KEY": "sportdevs_tt",
    "ALPHA_VANTAGE_API_KEY": "alpha_vantage",
    "FINNHUB_API_KEY": "finnhub",
    "TWELVE_DATA_API_KEY": "twelve_data",
    "COINGECKO_API_KEY": "coingecko",
}

# Every secret name the registry understands (used to partition the DPAPI map).
REGISTRY_SECRET_NAMES: frozenset[str] = frozenset(
    name
    for provider in PROVIDERS
    for name in (*provider.required_secrets, *provider.optional_secrets)
)

# Product -> provider assignments (backend source of truth for mapping).
PRODUCT_PROVIDERS: dict[str, tuple[str, ...]] = {
    "defend_ai": tuple(
        provider.provider_id
        for provider in PROVIDERS
        if "defend_ai" in provider.products
    ),
    "defendcoder": tuple(
        provider.provider_id
        for provider in PROVIDERS
        if "defendcoder" in provider.products
    ),
    "defendmarkets": tuple(
        provider.provider_id
        for provider in PROVIDERS
        if "defendmarkets" in provider.products
    ),
    "scs": tuple(
        provider.provider_id
        for provider in PROVIDERS
        if "scs" in provider.products
    ),
}


def find_provider(provider_id: str) -> ProviderDefinition | None:
    for provider in PROVIDERS:
        if provider.provider_id == provider_id:
            return provider
    return None


def find_category(category_id: str) -> Category | None:
    for category in CATEGORIES:
        if category.category_id == category_id:
            return category
    return None


def providers_in_category(category_id: str) -> tuple[ProviderDefinition, ...]:
    return tuple(
        provider
        for provider in PROVIDERS
        if provider.category == category_id
    )


def providers_for_product(product_id: str) -> tuple[ProviderDefinition, ...]:
    return tuple(
        provider
        for provider in PROVIDERS
        if product_id in provider.products
    )