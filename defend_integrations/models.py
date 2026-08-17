"""Declarative data model for the Setup / Integrations control plane.

These structures describe *what a provider is* (definition metadata), how it is
*configured* (config + credentials state), and the *observed health* of its
read-only probe. No I/O happens in this module; the stores, adapters, and
service layers own behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AuthType(str, Enum):
    """How a provider expects credentials.

    ``none`` is a normal, first-class case: public data providers (SEC EDGAR,
    World Bank, Polymarket) still get health/config cards even though they
    require no key.
    """

    API_KEY = "api_key"
    BEARER = "bearer"
    USER_AGENT = "user_agent"
    ACCOUNT = "account"
    NONE = "none"


class AdapterKind(str, Enum):
    REAL = "real"
    PLACEHOLDER = "placeholder"


class ProviderState(str, Enum):
    """Lifecycle state shown on a provider card (computed, not stored).

    The four semantic dimensions stay separate in the provider view:
    implementation (``PLANNED`` vs real), credentials
    (``NEEDS_CREDENTIAL``), enabled (``DISABLED``), and health (the badge
    states). A saved credential alone never implies operational health —
    ``READY_TO_TEST`` is the bridge state before the first probe.
    """

    DISABLED = "DISABLED"
    PLANNED = "PLANNED"
    NEEDS_CREDENTIAL = "NEEDS_CREDENTIAL"
    READY_TO_TEST = "READY_TO_TEST"
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    RATE_LIMITED = "RATE_LIMITED"
    AUTH_FAILED = "AUTH_FAILED"
    UNAVAILABLE = "UNAVAILABLE"


class HealthBadge(str, Enum):
    """Health taxonomy. Only HEALTHY may follow a real, recent probe."""

    NOT_CONFIGURED = "NOT_CONFIGURED"
    NOT_TESTED = "NOT_TESTED"
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    RATE_LIMITED = "RATE_LIMITED"
    UNAVAILABLE = "UNAVAILABLE"
    AUTH_FAILED = "AUTH_FAILED"


@dataclass(frozen=True)
class ProviderRateLimits:
    requests_per_second: float | None = None
    requests_per_minute: int | None = None
    requests_per_day: int | None = None
    monthly_credits: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "requests_per_second": self.requests_per_second,
            "requests_per_minute": self.requests_per_minute,
            "requests_per_day": self.requests_per_day,
            "monthly_credits": self.monthly_credits,
        }


@dataclass(frozen=True)
class ProviderLicense:
    terms_url: str | None = None
    commercial_use_status: str = "unknown"
    redistribution_status: str = "unknown"
    attribution_requirement: str | None = None
    notes: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "terms_url": self.terms_url,
            "commercial_use_status": self.commercial_use_status,
            "redistribution_status": self.redistribution_status,
            "attribution_requirement": self.attribution_requirement,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class ProviderDefinition:
    """Declarative registry entry. One source of truth for provider metadata."""

    provider_id: str
    display_name: str
    purpose: str
    category: str
    auth_type: AuthType
    adapter_kind: AdapterKind
    required_secrets: tuple[str, ...] = ()
    optional_secrets: tuple[str, ...] = ()
    optional_config: tuple[str, ...] = ()
    docs_url: str | None = None
    products: tuple[str, ...] = ()
    rate_limits: ProviderRateLimits = ProviderRateLimits()
    license: ProviderLicense = ProviderLicense()
    enabled_default: bool = True
    notes: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "purpose": self.purpose,
            "category": self.category,
            "auth_type": self.auth_type.value,
            "adapter_kind": self.adapter_kind.value,
            "required_secrets": list(self.required_secrets),
            "optional_secrets": list(self.optional_secrets),
            "optional_config": list(self.optional_config),
            "docs_url": self.docs_url,
            "products": list(self.products),
            "rate_limits": self.rate_limits.to_dict(),
            "license": self.license.to_dict(),
            "enabled_default": self.enabled_default,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class Category:
    category_id: str
    display_name: str
    description: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "category_id": self.category_id,
            "display_name": self.display_name,
            "description": self.description,
        }


@dataclass(frozen=True)
class Product:
    product_id: str
    display_name: str
    description: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "product_id": self.product_id,
            "display_name": self.display_name,
            "description": self.description,
        }


@dataclass(frozen=True)
class ProviderConfiguration:
    """Mutable, non-secret configuration persisted by the config store."""

    enabled: bool = True
    config: dict[str, str] = field(default_factory=dict)
    health_badge: HealthBadge = HealthBadge.NOT_TESTED
    tested_at: str | None = None
    last_success_at: str | None = None
    last_test_detail: str | None = None
    last_status_code: int | None = None
    last_latency_ms: int | None = None
    remaining_quota: int | None = None
    quota_reset_at: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "config": dict(self.config),
            "health_badge": self.health_badge.value,
            "tested_at": self.tested_at,
            "last_success_at": self.last_success_at,
            "last_test_detail": self.last_test_detail,
            "last_status_code": self.last_status_code,
            "last_latency_ms": self.last_latency_ms,
            "remaining_quota": self.remaining_quota,
            "quota_reset_at": self.quota_reset_at,
        }


@dataclass(frozen=True)
class ProviderCredentialState:
    """Masked credential view. Never carries a raw secret value."""

    name: str
    configured: bool
    masked: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "configured": self.configured,
            "masked": self.masked,
        }


@dataclass(frozen=True)
class AdapterProbe:
    """Result of one real adapter probe (already sanitized)."""

    ok: bool
    status_code: int | None
    latency_ms: int
    detail: str
    authenticated: bool | None = None
    remaining_quota: int | None = None
    quota_reset_at: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "status_code": self.status_code,
            "latency_ms": self.latency_ms,
            "detail": self.detail,
            "authenticated": self.authenticated,
            "remaining_quota": self.remaining_quota,
            "quota_reset_at": self.quota_reset_at,
        }


def utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def badge_from_probe(probe: AdapterProbe) -> HealthBadge:
    """Map a sanitized probe to the health taxonomy."""

    if not probe.ok:
        if probe.status_code == 429:
            return HealthBadge.RATE_LIMITED
        if probe.status_code in (401, 403):
            return HealthBadge.AUTH_FAILED
        return HealthBadge.UNAVAILABLE
    if probe.authenticated is False:
        return HealthBadge.AUTH_FAILED
    return HealthBadge.HEALTHY


def state_from_badge(badge: HealthBadge) -> ProviderState:
    """Map a stored health badge onto the lifecycle state progression.

    ``NOT_TESTED`` / ``NOT_CONFIGURED`` are pre-test bookkeeping states; the
    caller decides those before calling here.
    """

    return {
        HealthBadge.HEALTHY: ProviderState.HEALTHY,
        HealthBadge.DEGRADED: ProviderState.DEGRADED,
        HealthBadge.RATE_LIMITED: ProviderState.RATE_LIMITED,
        HealthBadge.AUTH_FAILED: ProviderState.AUTH_FAILED,
        HealthBadge.UNAVAILABLE: ProviderState.UNAVAILABLE,
    }.get(badge, ProviderState.READY_TO_TEST)


def mask_secret(value: str) -> str:
    """Return a safe masked view (last four characters) of a secret value."""

    value = str(value)
    if not value:
        return ""
    if len(value) <= 4:
        return "****"
    return f"****{value[-4:]}"


def mask_config_value(value: str) -> str:
    """Mask optional config values that look secret-shaped (best effort)."""

    lowered = value.lower()
    if any(
        marker in lowered
        for marker in ("token", "password", "secret", "api_key", "key=", "auth")
    ):
        return mask_secret(value)
    return value


def to_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}