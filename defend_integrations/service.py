"""Integration service: the single backend entry point behind the admin API.

Owns the flow: encrypted secrets -> provider registry/config -> health
adapters -> public (sanitized) views. Nothing in this module ever returns a
raw secret value; providers receive their credentials only inside the test
path, and any error text is redacted against the known values.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .adapters import REAL_ADAPTERS, adapter_for
from .models import (
    AdapterProbe,
    AdapterKind,
    HealthBadge,
    ProviderState,
    badge_from_probe,
    mask_config_value,
    mask_secret,
    utc_now_iso,
)
from .registry import (
    CATEGORIES,
    LEGACY_SECRET_MAP,
    PRODUCTS,
    PROVIDERS,
    find_category,
    find_provider,
    providers_for_product,
    providers_in_category,
)
from .stores import (
    ProviderConfigStore,
    SecretRegistry,
    apply_rotation_invalidation,
)


def _is_secret_shaped(name: str) -> bool:
    lowered = name.lower()
    return any(
        marker in lowered
        for marker in ("token", "password", "secret", "api_key", "key", "auth")
    )


class SetupIntegrationsService:
    def __init__(
        self,
        secret_registry: SecretRegistry,
        config_store: ProviderConfigStore,
        *,
        clock=utc_now_iso,
    ) -> None:
        self._secrets = secret_registry
        self._config = config_store
        self._clock = clock

    # ------------------------------------------------------------------ views
    def snapshot(self) -> dict[str, Any]:
        categories = []
        for category in CATEGORIES:
            providers = [
                self._provider_view(provider.provider_id)
                for provider in providers_in_category(category.category_id)
            ]
            categories.append(
                {
                    **category.to_dict(),
                    "providers": providers,
                }
            )
        return {
            "categories": categories,
            "products": [product.to_dict() for product in PRODUCTS],
            "product_providers": {
                product_id: list(provider_ids)
                for product_id, provider_ids in self._product_assignments().items()
            },
            "legacy_secret_names": sorted(LEGACY_SECRET_MAP),
            "registry_secret_names": sorted(self._secrets.known_names()),
        }

    def _product_assignments(self) -> dict[str, tuple[str, ...]]:
        return {
            product.product_id: tuple(
                provider.provider_id
                for provider in providers_for_product(product.product_id)
            )
            for product in PRODUCTS
        }

    def provider_view(self, provider_id: str) -> dict[str, Any]:
        definition = find_provider(provider_id)
        if definition is None:
            raise KeyError(f"unknown provider: {provider_id}")
        return self._provider_view(provider_id)

    def _provider_view(self, provider_id: str) -> dict[str, Any]:
        definition = find_provider(provider_id)
        if definition is None:
            raise KeyError(f"unknown provider: {provider_id}")
        config = self._config.get(
            provider_id, default_enabled=definition.enabled_default
        )
        credentials = []
        all_configured = True
        for name in definition.required_secrets:
            configured = self._secrets.configured(name)
            all_configured = all_configured and configured
            credentials.append(
                {
                    "name": name,
                    "configured": configured,
                    "masked": self._secrets.masked(name),
                }
            )
        for name in definition.optional_secrets:
            credentials.append(
                {
                    "name": name,
                    "configured": self._secrets.configured(name),
                    "masked": self._secrets.masked(name),
                }
            )
        requires_credentials = (
            definition.auth_type.value not in ("none", "user_agent")
        )
        configured = not requires_credentials or all_configured

        if not config.enabled:
            state = ProviderState.DISABLED.value
        elif definition.adapter_kind is AdapterKind.PLACEHOLDER:
            state = ProviderState.PLACEHOLDER.value
        elif config.tested_at is not None:
            state = ProviderState.TESTED.value
        elif configured:
            state = ProviderState.CONFIGURED.value
        else:
            state = ProviderState.AVAILABLE.value

        badge = self._health_badge(definition, config, configured)

        public_config = {
            name: (
                mask_config_value(value)
                if _is_secret_shaped(name)
                else value
            )
            for name, value in config.config.items()
        }

        return {
            "provider_id": definition.provider_id,
            "display_name": definition.display_name,
            "purpose": definition.purpose,
            "category": definition.category,
            "auth_type": definition.auth_type.value,
            "adapter_kind": definition.adapter_kind.value,
            "state": state,
            "health_badge": badge.value,
            "enabled": config.enabled,
            "credentials": credentials,
            "config": public_config,
            "optional_config": list(definition.optional_config),
            "products": list(definition.products),
            "docs_url": definition.docs_url,
            "rate_limits": definition.rate_limits.to_dict(),
            "license": definition.license.to_dict(),
            "tested_at": config.tested_at,
            "last_success_at": config.last_success_at,
            "last_test_detail": config.last_test_detail,
            "last_status_code": config.last_status_code,
            "last_latency_ms": config.last_latency_ms,
            "remaining_quota": config.remaining_quota,
            "quota_reset_at": config.quota_reset_at,
            "notes": definition.notes,
        }

    @staticmethod
    def _health_badge(definition, config, configured: bool) -> HealthBadge:
        if not config.enabled or definition.adapter_kind is AdapterKind.PLACEHOLDER:
            return HealthBadge.NOT_TESTED
        if (
            definition.auth_type.value not in ("none", "user_agent")
            and not configured
        ):
            return HealthBadge.NOT_CONFIGURED
        return config.health_badge

    # -------------------------------------------------------------- mutations
    def save_secret(
        self, provider_id: str, secret_name: str, value: str
    ) -> dict[str, Any]:
        definition = find_provider(provider_id)
        if definition is None:
            raise KeyError(f"unknown provider: {provider_id}")
        known = (
            (*definition.required_secrets, *definition.optional_secrets)
            + tuple(
                legacy
                for legacy, target in LEGACY_SECRET_MAP.items()
                if target == provider_id
            )
        )
        if secret_name not in known:
            raise ValueError(
                f"secret {secret_name!r} is not accepted by provider {provider_id!r}"
            )
        if not isinstance(value, str) or not value:
            raise ValueError("secret value must be a non-empty string")
        if len(value) > 4096:
            raise ValueError("secret value must not exceed 4096 characters")
        updates = {secret_name: value}
        self._secrets.save(updates)
        apply_rotation_invalidation(self._config, self._secrets, updates=updates)
        return {
            "ok": True,
            "provider_id": provider_id,
            "secret_name": secret_name,
            "configured": True,
            "masked": mask_secret(value),
        }

    def remove_secret(self, provider_id: str, secret_name: str) -> dict[str, Any]:
        definition = find_provider(provider_id)
        if definition is None:
            raise KeyError(f"unknown provider: {provider_id}")
        if secret_name not in (
            *definition.required_secrets,
            *definition.optional_secrets,
        ) and LEGACY_SECRET_MAP.get(secret_name) != provider_id:
            raise ValueError(
                f"secret {secret_name!r} is not accepted by provider {provider_id!r}"
            )
        self._secrets.remove(secret_name)
        apply_rotation_invalidation(
            self._config, self._secrets, removed=secret_name
        )
        return {
            "ok": True,
            "provider_id": provider_id,
            "secret_name": secret_name,
            "configured": False,
            "masked": None,
        }

    def save_config(
        self,
        provider_id: str,
        *,
        enabled: bool | None = None,
        config: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        definition = find_provider(provider_id)
        if definition is None:
            raise KeyError(f"unknown provider: {provider_id}")
        current = self._config.get(
            provider_id, default_enabled=definition.enabled_default
        )
        next_enabled = current.enabled if enabled is None else bool(enabled)
        next_config = dict(current.config)
        if config is not None:
            if not isinstance(config, Mapping):
                raise ValueError("config must be a mapping")
            for name, value in config.items():
                if name not in definition.optional_config:
                    raise ValueError(
                        f"config key {name!r} is not accepted by provider {provider_id!r}"
                    )
                if not isinstance(value, str) or len(value) > 2048:
                    raise ValueError("config values must be strings under 2048 chars")
                if not value:
                    next_config.pop(name, None)
                else:
                    next_config[name] = value
        if enabled is not None or config is not None:
            if config is not None:
                self._config.set_config(
                    provider_id, next_config,
                    default_enabled=definition.enabled_default,
                )
            if enabled is not None:
                self._config.set_enabled(
                    provider_id, next_enabled,
                    default_enabled=definition.enabled_default,
                )
        return self._provider_view(provider_id)

    # ---------------------------------------------------------------- testing
    def test(self, provider_id: str) -> dict[str, Any]:
        definition = find_provider(provider_id)
        if definition is None:
            raise KeyError(f"unknown provider: {provider_id}")
        config = self._config.get(
            provider_id, default_enabled=definition.enabled_default
        )
        if not config.enabled:
            raise ValueError(f"provider {provider_id!r} is disabled")
        adapter = adapter_for(definition)
        secrets = self._secrets.load_all()
        probe = adapter.probe(definition, secrets, dict(config.config))
        return self._record_probe(definition, probe)

    def test_all_configured(self) -> dict[str, Any]:
        results = []
        skipped = []
        for definition in PROVIDERS:
            provider_id = definition.provider_id
            config = self._config.get(
                provider_id, default_enabled=definition.enabled_default
            )
            requires_credentials = (
                definition.auth_type.value not in ("none", "user_agent")
            )
            configured = not requires_credentials or all(
                self._secrets.configured(name)
                for name in definition.required_secrets
            )
            if (
                not config.enabled
                or definition.adapter_kind is AdapterKind.PLACEHOLDER
                or not configured
            ):
                skipped.append(
                    {
                        "provider_id": provider_id,
                        "reason": (
                            "disabled"
                            if not config.enabled
                            else "adapter not implemented"
                            if definition.adapter_kind is AdapterKind.PLACEHOLDER
                            else "missing credentials"
                        ),
                    }
                )
                continue
            try:
                result = self.test(provider_id)
            except Exception as error:
                result = {
                    "provider_id": provider_id,
                    "badge": HealthBadge.UNAVAILABLE.value,
                    "ok": False,
                    "detail": type(error).__name__,
                    "tested_at": self._clock(),
                }
            results.append(result)
        return {
            "results": results,
            "tested": len(results),
            "skipped": skipped,
        }

    def _record_probe(
        self, definition, probe: AdapterProbe
    ) -> dict[str, Any]:
        now = self._clock()
        if definition.adapter_kind is AdapterKind.PLACEHOLDER:
            badge = HealthBadge.NOT_TESTED
            last_success_at = None
        else:
            badge = badge_from_probe(probe)
            last_success_at = now if probe.ok and badge is HealthBadge.HEALTHY else None
        self._config.record_probe(
            definition.provider_id,
            badge=badge,
            tested_at=now,
            detail=probe.detail,
            status_code=probe.status_code,
            latency_ms=probe.latency_ms,
            last_success_at=last_success_at,
            remaining_quota=probe.remaining_quota,
            quota_reset_at=probe.quota_reset_at,
            default_enabled=definition.enabled_default,
        )
        return {
            "provider_id": definition.provider_id,
            "ok": probe.ok,
            "badge": badge.value,
            "detail": probe.detail,
            "status_code": probe.status_code,
            "latency_ms": probe.latency_ms,
            "authenticated": probe.authenticated,
            "remaining_quota": probe.remaining_quota,
            "quota_reset_at": probe.quota_reset_at,
            "tested_at": now,
        }

    # ------------------------------------------------------------ diagnostics
    def diagnostics(self) -> dict[str, Any]:
        rows = []
        for category in CATEGORIES:
            for definition in providers_in_category(category.category_id):
                provider_id = definition.provider_id
                config = self._config.get(
                    provider_id, default_enabled=definition.enabled_default
                )
                requires_credentials = (
                    definition.auth_type.value not in ("none", "user_agent")
                )
                configured = not requires_credentials or all(
                    self._secrets.configured(name)
                    for name in definition.required_secrets
                )
                rows.append(
                    {
                        "provider_id": provider_id,
                        "display_name": definition.display_name,
                        "category": category.category_id,
                        "products": list(definition.products),
                        "auth_type": definition.auth_type.value,
                        "adapter_kind": definition.adapter_kind.value,
                        "enabled": config.enabled,
                        "configured": configured,
                        "health_badge": self._health_badge(
                            definition, config, configured
                        ).value,
                        "last_success_at": config.last_success_at,
                        "last_test_at": config.tested_at,
                        "remaining_quota": config.remaining_quota,
                        "quota_reset_at": config.quota_reset_at,
                        "detail": config.last_test_detail,
                    }
                )
        return {"rows": rows}

    def products(self) -> dict[str, Any]:
        return {
            "products": [product.to_dict() for product in PRODUCTS],
            "product_providers": self._product_assignments(),
        }

    def refresh_secrets(self) -> None:
        self._secrets.refresh()