from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class IntegrationOwner(str, Enum):
    PLATFORM = "platform"
    DEFEND = "defend"
    CODER = "coder"
    SPORTS = "sports"
    SCS = "scs"


class CostClass(str, Enum):
    FREE = "free"
    FREE_TIER = "free_tier"
    TRIAL = "trial"
    USAGE = "usage"
    PAID = "paid"
    UNKNOWN = "unknown"


class StartupCheck(str, Enum):
    LOCAL = "local"
    FREE_PING = "free_ping"
    BACKGROUND = "background"
    MANUAL = "manual"


class SecretRequirement(str, Enum):
    REQUIRED = "required"
    OPTIONAL = "optional"


@dataclass(frozen=True)
class SecretDefinition:
    key: str
    display_name: str
    owner: IntegrationOwner
    requirement: SecretRequirement = SecretRequirement.OPTIONAL
    secret_type: str = "api_key"
    redact: bool = True


@dataclass(frozen=True)
class IntegrationDefinition:
    integration_id: str
    display_name: str
    owner: IntegrationOwner
    category: str
    capabilities: tuple[str, ...]
    cost_class: CostClass
    credential_keys: tuple[str, ...] = ()
    enabled_by_default: bool = False
    startup_check: StartupCheck = StartupCheck.MANUAL
    required_for: tuple[str, ...] = ()
    notes: str = ""


SECRET_CATALOG: tuple[SecretDefinition, ...] = (
    # Platform / compute
    SecretDefinition(
        "VAST_API_KEY",
        "Vast.ai API key",
        IntegrationOwner.PLATFORM,
        SecretRequirement.REQUIRED,
    ),
    SecretDefinition(
        "RUNPOD_API_KEY",
        "RunPod API key",
        IntegrationOwner.PLATFORM,
    ),
    SecretDefinition(
        "HF_TOKEN",
        "Hugging Face token",
        IntegrationOwner.PLATFORM,
        secret_type="token",
    ),
    SecretDefinition(
        "VLLM_API_KEY",
        "vLLM API key",
        IntegrationOwner.PLATFORM,
        secret_type="token",
    ),
    SecretDefinition(
        "CLOUDFLARE_API_TOKEN",
        "Cloudflare API token",
        IntegrationOwner.PLATFORM,
        secret_type="token",
    ),
    SecretDefinition(
        "CLOUDFLARE_TUNNEL_TOKEN",
        "Cloudflare tunnel token",
        IntegrationOwner.PLATFORM,
        secret_type="token",
    ),
    SecretDefinition(
        "CLOUDFLARE_ACCOUNT_ID",
        "Cloudflare account ID",
        IntegrationOwner.PLATFORM,
        secret_type="identifier",
    ),
    SecretDefinition(
        "SENTRY_DSN",
        "Sentry DSN",
        IntegrationOwner.PLATFORM,
        secret_type="dsn",
    ),
    SecretDefinition(
        "OWNER_ALERT_WEBHOOK",
        "Owner alert webhook",
        IntegrationOwner.PLATFORM,
        secret_type="webhook",
    ),
    SecretDefinition(
        "DISCORD_WEBHOOK_URL",
        "Discord webhook URL",
        IntegrationOwner.PLATFORM,
        secret_type="webhook",
    ),
    SecretDefinition(
        "TELEGRAM_BOT_TOKEN",
        "Telegram bot token",
        IntegrationOwner.PLATFORM,
        secret_type="token",
    ),
    SecretDefinition(
        "TELEGRAM_CHAT_ID",
        "Telegram chat ID",
        IntegrationOwner.PLATFORM,
        secret_type="identifier",
    ),
    SecretDefinition(
        "TWILIO_ACCOUNT_SID",
        "Twilio account SID",
        IntegrationOwner.PLATFORM,
        secret_type="identifier",
    ),
    SecretDefinition(
        "TWILIO_AUTH_TOKEN",
        "Twilio auth token",
        IntegrationOwner.PLATFORM,
        secret_type="token",
    ),

    # DEFENDcoder
    SecretDefinition(
        "CODER_VLLM_API_KEY",
        "DEFENDcoder vLLM API key",
        IntegrationOwner.CODER,
        secret_type="token",
    ),
    SecretDefinition(
        "GITHUB_TOKEN",
        "GitHub token",
        IntegrationOwner.CODER,
        secret_type="token",
    ),
    SecretDefinition(
        "GITHUB_APP_ID",
        "GitHub App ID",
        IntegrationOwner.CODER,
        secret_type="identifier",
    ),
    SecretDefinition(
        "GITHUB_APP_PRIVATE_KEY",
        "GitHub App private key",
        IntegrationOwner.CODER,
        secret_type="private_key",
    ),

    # Sports
    SecretDefinition(
        "THE_ODDS_API_KEY",
        "The Odds API key",
        IntegrationOwner.SPORTS,
    ),
    SecretDefinition(
        "SPORTRADAR_API_KEY",
        "Sportradar API key",
        IntegrationOwner.SPORTS,
    ),
    SecretDefinition(
        "API_SPORTS_KEY",
        "API-Sports key",
        IntegrationOwner.SPORTS,
    ),
    SecretDefinition(
        "SPORTS_ODDS_PRIMARY_API_KEY",
        "Primary odds provider API key",
        IntegrationOwner.SPORTS,
    ),
    SecretDefinition(
        "SPORTS_ODDS_SECONDARY_API_KEY",
        "Secondary odds provider API key",
        IntegrationOwner.SPORTS,
    ),
    SecretDefinition(
        "SPORTS_TT_PBP_API_KEY",
        "Table tennis point-by-point provider key",
        IntegrationOwner.SPORTS,
    ),
    SecretDefinition(
        "OPTICODDS_API_KEY",
        "OpticOdds API key",
        IntegrationOwner.SPORTS,
    ),
    SecretDefinition(
        "BETFAIR_APP_KEY",
        "Betfair app key",
        IntegrationOwner.SPORTS,
    ),

    # SCS / payments / operations
    SecretDefinition(
        "STRIPE_SECRET_KEY",
        "Stripe secret key",
        IntegrationOwner.SCS,
        secret_type="secret_key",
    ),
    SecretDefinition(
        "STRIPE_WEBHOOK_SECRET",
        "Stripe webhook secret",
        IntegrationOwner.SCS,
        secret_type="webhook_secret",
    ),
    SecretDefinition(
        "GOOGLE_CLIENT_SECRET",
        "Google Workspace client secret",
        IntegrationOwner.SCS,
        secret_type="oauth_client_secret",
    ),
    SecretDefinition(
        "USPS_CLIENT_SECRET",
        "USPS client secret",
        IntegrationOwner.SCS,
        secret_type="oauth_client_secret",
    ),
    SecretDefinition(
        "ADDRESS_VALIDATION_API_KEY",
        "Address validation API key",
        IntegrationOwner.SCS,
    ),

    # DEFEND identity / communications
    SecretDefinition(
        "DEFEND_OWNER_USER",
        "Owner username",
        IntegrationOwner.DEFEND,
        secret_type="credential",
    ),
    SecretDefinition(
        "DEFEND_OWNER_EMAIL",
        "Owner email",
        IntegrationOwner.DEFEND,
        secret_type="credential",
    ),
    SecretDefinition(
        "DEFEND_OWNER_PASS",
        "Owner password",
        IntegrationOwner.DEFEND,
        secret_type="password",
    ),
    SecretDefinition(
        "DEFEND_VISITOR_HMAC_KEY",
        "Visitor HMAC key",
        IntegrationOwner.DEFEND,
        secret_type="key",
    ),
    SecretDefinition(
        "DEFEND_GMAIL_SMTP_USERNAME",
        "Gmail SMTP username",
        IntegrationOwner.DEFEND,
        secret_type="credential",
    ),
    SecretDefinition(
        "DEFEND_GMAIL_APP_PASSWORD",
        "Gmail app password",
        IntegrationOwner.DEFEND,
        secret_type="password",
    ),
    SecretDefinition(
        "TAVILY_API_KEY",
        "Tavily search API key",
        IntegrationOwner.DEFEND,
    ),
    SecretDefinition(
        "BRAVE_SEARCH_API_KEY",
        "Brave Search API key",
        IntegrationOwner.DEFEND,
    ),
    SecretDefinition(
        "SERPER_API_KEY",
        "Serper API key",
        IntegrationOwner.DEFEND,
    ),
    SecretDefinition(
        "RESEND_API_KEY",
        "Resend API key",
        IntegrationOwner.DEFEND,
    ),
    SecretDefinition(
        "POSTMARK_SERVER_TOKEN",
        "Postmark server token",
        IntegrationOwner.DEFEND,
        secret_type="token",
    ),
)


INTEGRATION_CATALOG: tuple[IntegrationDefinition, ...] = (
    # Platform
    IntegrationDefinition(
        "vast",
        "Vast.ai",
        IntegrationOwner.PLATFORM,
        "Compute",
        ("gpu_provisioning", "billing"),
        CostClass.USAGE,
        ("VAST_API_KEY",),
        True,
        StartupCheck.LOCAL,
        ("defend_ai", "defendcoder"),
    ),
    IntegrationDefinition(
        "runpod",
        "RunPod",
        IntegrationOwner.PLATFORM,
        "Compute",
        ("gpu_provisioning", "fallback_compute"),
        CostClass.USAGE,
        ("RUNPOD_API_KEY",),
        False,
        StartupCheck.MANUAL,
        ("defendcoder",),
    ),
    IntegrationDefinition(
        "huggingface",
        "Hugging Face",
        IntegrationOwner.PLATFORM,
        "Models",
        ("model_download", "private_artifacts"),
        CostClass.FREE_TIER,
        ("HF_TOKEN",),
        True,
        StartupCheck.LOCAL,
    ),
    IntegrationDefinition(
        "cloudflare",
        "Cloudflare",
        IntegrationOwner.PLATFORM,
        "Networking",
        ("tunnels", "public_origin"),
        CostClass.FREE_TIER,
        (
            "CLOUDFLARE_API_TOKEN",
            "CLOUDFLARE_TUNNEL_TOKEN",
            "CLOUDFLARE_ACCOUNT_ID",
        ),
        True,
        StartupCheck.LOCAL,
    ),
    IntegrationDefinition(
        "sentry",
        "Sentry",
        IntegrationOwner.PLATFORM,
        "Observability",
        ("errors", "traces"),
        CostClass.FREE_TIER,
        ("SENTRY_DSN",),
        False,
        StartupCheck.MANUAL,
    ),
    IntegrationDefinition(
        "discord_alerts",
        "Discord Alerts",
        IntegrationOwner.PLATFORM,
        "Alerts",
        ("owner_alerts",),
        CostClass.FREE,
        ("DISCORD_WEBHOOK_URL",),
        False,
        StartupCheck.MANUAL,
    ),
    IntegrationDefinition(
        "telegram_alerts",
        "Telegram Alerts",
        IntegrationOwner.PLATFORM,
        "Alerts",
        ("owner_alerts",),
        CostClass.FREE,
        ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"),
        False,
        StartupCheck.MANUAL,
    ),
    IntegrationDefinition(
        "twilio",
        "Twilio",
        IntegrationOwner.PLATFORM,
        "Alerts",
        ("sms", "customer_notifications"),
        CostClass.USAGE,
        ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN"),
        False,
        StartupCheck.MANUAL,
    ),

    # Coder
    IntegrationDefinition(
        "github",
        "GitHub",
        IntegrationOwner.CODER,
        "Development",
        ("repos", "pull_requests", "checks", "issues"),
        CostClass.FREE_TIER,
        ("GITHUB_TOKEN",),
        True,
        StartupCheck.LOCAL,
        ("defendcoder",),
    ),

    # Sports
    IntegrationDefinition(
        "the_odds_api",
        "The Odds API",
        IntegrationOwner.SPORTS,
        "Odds",
        ("odds", "multi_book"),
        CostClass.FREE_TIER,
        ("THE_ODDS_API_KEY",),
        False,
        StartupCheck.MANUAL,
        ("sports",),
    ),
    IntegrationDefinition(
        "sportradar",
        "Sportradar",
        IntegrationOwner.SPORTS,
        "Stats / PBP",
        ("stats", "odds", "table_tennis"),
        CostClass.TRIAL,
        ("SPORTRADAR_API_KEY",),
        False,
        StartupCheck.MANUAL,
        ("sports",),
    ),
    IntegrationDefinition(
        "api_sports",
        "API-Sports",
        IntegrationOwner.SPORTS,
        "Stats",
        ("multi_sport_stats",),
        CostClass.FREE_TIER,
        ("API_SPORTS_KEY",),
        False,
        StartupCheck.MANUAL,
        ("sports",),
    ),
    IntegrationDefinition(
        "opticodds",
        "OpticOdds",
        IntegrationOwner.SPORTS,
        "Odds",
        ("live_odds",),
        CostClass.PAID,
        ("OPTICODDS_API_KEY",),
        False,
        StartupCheck.MANUAL,
        ("sports",),
    ),
    IntegrationDefinition(
        "sports_primary_odds",
        "Primary Odds Provider",
        IntegrationOwner.SPORTS,
        "Odds",
        ("odds",),
        CostClass.UNKNOWN,
        ("SPORTS_ODDS_PRIMARY_API_KEY",),
        False,
        StartupCheck.MANUAL,
        ("sports",),
    ),
    IntegrationDefinition(
        "sports_secondary_odds",
        "Secondary Odds Provider",
        IntegrationOwner.SPORTS,
        "Odds",
        ("odds", "failover"),
        CostClass.UNKNOWN,
        ("SPORTS_ODDS_SECONDARY_API_KEY",),
        False,
        StartupCheck.MANUAL,
        ("sports",),
    ),
    IntegrationDefinition(
        "sports_tt_pbp",
        "Table Tennis Point-by-Point Provider",
        IntegrationOwner.SPORTS,
        "Table Tennis",
        ("point_by_point", "live_state"),
        CostClass.UNKNOWN,
        ("SPORTS_TT_PBP_API_KEY",),
        False,
        StartupCheck.MANUAL,
        ("sports",),
    ),
    IntegrationDefinition(
        "betfair",
        "Betfair Exchange",
        IntegrationOwner.SPORTS,
        "Exchange",
        ("exchange_prices",),
        CostClass.USAGE,
        ("BETFAIR_APP_KEY",),
        False,
        StartupCheck.MANUAL,
        ("sports",),
    ),

    # SCS
    IntegrationDefinition(
        "nws_weather",
        "National Weather Service",
        IntegrationOwner.SCS,
        "Weather",
        ("weather", "forecast"),
        CostClass.FREE,
        (),
        True,
        StartupCheck.FREE_PING,
        ("scs",),
    ),
    IntegrationDefinition(
        "stripe",
        "Stripe",
        IntegrationOwner.SCS,
        "Payments",
        ("invoices", "payments", "webhooks"),
        CostClass.USAGE,
        ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET"),
        False,
        StartupCheck.MANUAL,
        ("scs",),
    ),
    IntegrationDefinition(
        "google_workspace",
        "Google Workspace",
        IntegrationOwner.SCS,
        "Office",
        ("email", "calendar"),
        CostClass.FREE_TIER,
        ("GOOGLE_CLIENT_SECRET",),
        False,
        StartupCheck.MANUAL,
        ("scs",),
    ),
    IntegrationDefinition(
        "address_validation",
        "Address Validation",
        IntegrationOwner.SCS,
        "Operations",
        ("address_validation",),
        CostClass.UNKNOWN,
        ("ADDRESS_VALIDATION_API_KEY",),
        False,
        StartupCheck.MANUAL,
        ("scs",),
    ),

    # DEFEND
    IntegrationDefinition(
        "tavily",
        "Tavily",
        IntegrationOwner.DEFEND,
        "Research",
        ("web_search",),
        CostClass.FREE_TIER,
        ("TAVILY_API_KEY",),
        False,
        StartupCheck.MANUAL,
        ("defend_ai",),
    ),
    IntegrationDefinition(
        "brave_search",
        "Brave Search",
        IntegrationOwner.DEFEND,
        "Research",
        ("web_search", "search_fallback"),
        CostClass.FREE_TIER,
        ("BRAVE_SEARCH_API_KEY",),
        False,
        StartupCheck.MANUAL,
        ("defend_ai",),
    ),
    IntegrationDefinition(
        "serper",
        "Serper",
        IntegrationOwner.DEFEND,
        "Research",
        ("web_search", "search_fallback"),
        CostClass.USAGE,
        ("SERPER_API_KEY",),
        False,
        StartupCheck.MANUAL,
        ("defend_ai",),
    ),
    IntegrationDefinition(
        "resend",
        "Resend",
        IntegrationOwner.DEFEND,
        "Email",
        ("transactional_email",),
        CostClass.FREE_TIER,
        ("RESEND_API_KEY",),
        False,
        StartupCheck.MANUAL,
        ("defend_ai",),
    ),
    IntegrationDefinition(
        "postmark",
        "Postmark",
        IntegrationOwner.DEFEND,
        "Email",
        ("transactional_email",),
        CostClass.USAGE,
        ("POSTMARK_SERVER_TOKEN",),
        False,
        StartupCheck.MANUAL,
        ("defend_ai",),
    ),
)


def get_integration(
    integration_id: str,
) -> IntegrationDefinition:
    for item in INTEGRATION_CATALOG:
        if item.integration_id == integration_id:
            return item

    raise KeyError(integration_id)


def get_secret_definition(
    key: str,
) -> SecretDefinition:
    for item in SECRET_CATALOG:
        if item.key == key:
            return item

    raise KeyError(key)


def definitions_for_owner(
    owner: IntegrationOwner,
) -> tuple[SecretDefinition, ...]:
    return tuple(
        item
        for item in SECRET_CATALOG
        if item.owner == owner
    )


def secret_status(
    definition: SecretDefinition,
    values: dict[str, str],
) -> str:
    value = values.get(definition.key)

    if value:
        return "configured"

    if (
        definition.requirement
        == SecretRequirement.REQUIRED
    ):
        return "missing"

    return "optional"
