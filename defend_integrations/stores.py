"""Configuration and secret stores for the Setup / Integrations control plane.

The DPAPI-encrypted store stays the single source of truth for credential
values. This module adds:

- ``ProviderConfigStore``: atomic JSON persistence for non-secret provider
  configuration plus cached health-probe observations.
- ``SecretRegistry``: a typed view over the encrypted secret store that masks
  values, applies the legacy compatibility map, and supports save/remove with
  rotation invalidation.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
import tempfile
from typing import Protocol

from .models import (
    HealthBadge,
    ProviderConfiguration,
    utc_now_iso,
)
from .registry import LEGACY_SECRET_MAP, REGISTRY_SECRET_NAMES


class SecretStore(Protocol):
    """Minimal surface of the encrypted store (DpapiSecretStore-compatible)."""

    def load(self) -> dict[str, str]: ...

    def save(self, values: Mapping[str, str]) -> None: ...


def default_secret_root() -> Path:
    """Locate the DPAPI secret store path used by the Control Center.

    Uses the same %LOCALAPPDATA%\\DEFEND location as the desktop launcher so
    both surfaces share one encrypted credential file.
    """
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA is required to locate DEFEND secrets")
    return Path(local_app_data) / "DEFEND"


def default_secret_path() -> Path:
    return default_secret_root() / "secrets.dpapi"


def default_config_path() -> Path:
    return default_secret_root() / "integrations-config.json"


@dataclass
class ProviderConfigStore:
    """Atomic JSON persistence for provider configuration and health cache."""

    path: Path
    _configs: dict[str, ProviderConfiguration] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._configs = self._load()

    def _load(self) -> dict[str, ProviderConfiguration]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError as exc:
            raise ValueError("integration config file is not valid JSON") from exc
        if not isinstance(raw, dict):
            raise ValueError("integration config file must contain a JSON object")
        configs: dict[str, ProviderConfiguration] = {}
        for provider_id, entry in raw.items():
            if not isinstance(provider_id, str) or not isinstance(entry, dict):
                raise ValueError("integration config file has an invalid entry")
            configs[provider_id] = self._from_document(entry)
        return configs

    @staticmethod
    def _from_document(entry: dict[str, object]) -> ProviderConfiguration:
        enabled = entry.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError("integration config 'enabled' must be a boolean")
        raw_config = entry.get("config", {})
        if not isinstance(raw_config, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in raw_config.items()
        ):
            raise ValueError("integration config 'config' must map strings to strings")
        badge = entry.get("health_badge", "NOT_TESTED")
        if badge not in {member.value for member in HealthBadge}:
            badge = HealthBadge.NOT_TESTED.value

        def text(key: str) -> str | None:
            value = entry.get(key)
            return value if isinstance(value, str) else None

        def integer(key: str) -> int | None:
            value = entry.get(key)
            return value if isinstance(value, int) and not isinstance(value, bool) else None

        return ProviderConfiguration(
            enabled=enabled,
            config=dict(raw_config),
            health_badge=HealthBadge(badge),
            tested_at=text("tested_at"),
            last_success_at=text("last_success_at"),
            last_test_detail=text("last_test_detail"),
            last_status_code=integer("last_status_code"),
            last_latency_ms=integer("last_latency_ms"),
            remaining_quota=integer("remaining_quota"),
            quota_reset_at=text("quota_reset_at"),
        )

    def get(self, provider_id: str, *, default_enabled: bool = True) -> ProviderConfiguration:
        existing = self._configs.get(provider_id)
        if existing is not None:
            return existing
        return ProviderConfiguration(enabled=default_enabled)

    def set_enabled(self, provider_id: str, enabled: bool, *, default_enabled: bool = True) -> None:
        current = self._configs.get(provider_id)
        self._configs[provider_id] = ProviderConfiguration(
            enabled=enabled,
            config=current.config if current else {},
            health_badge=current.health_badge if current else HealthBadge.NOT_TESTED,
            tested_at=current.tested_at if current else None,
            last_success_at=current.last_success_at if current else None,
            last_test_detail=current.last_test_detail if current else None,
            last_status_code=current.last_status_code if current else None,
            last_latency_ms=current.last_latency_ms if current else None,
            remaining_quota=current.remaining_quota if current else None,
            quota_reset_at=current.quota_reset_at if current else None,
        )
        self.save()

    def set_config(self, provider_id: str, config: Mapping[str, str], *, default_enabled: bool = True) -> None:
        current = self._configs.get(provider_id)
        self._configs[provider_id] = ProviderConfiguration(
            enabled=(current.enabled if current else default_enabled),
            config={str(key): str(value) for key, value in config.items()},
            health_badge=current.health_badge if current else HealthBadge.NOT_TESTED,
            tested_at=current.tested_at if current else None,
            last_success_at=current.last_success_at if current else None,
            last_test_detail=current.last_test_detail if current else None,
            last_status_code=current.last_status_code if current else None,
            last_latency_ms=current.last_latency_ms if current else None,
            remaining_quota=current.remaining_quota if current else None,
            quota_reset_at=current.quota_reset_at if current else None,
        )
        self.save()

    def record_probe(
        self,
        provider_id: str,
        *,
        badge: HealthBadge,
        tested_at: str,
        detail: str,
        status_code: int | None,
        latency_ms: int,
        last_success_at: str | None,
        remaining_quota: int | None,
        quota_reset_at: str | None,
        default_enabled: bool = True,
    ) -> None:
        current = self._configs.get(provider_id)
        self._configs[provider_id] = ProviderConfiguration(
            enabled=(current.enabled if current else default_enabled),
            config=current.config if current else {},
            health_badge=badge,
            tested_at=tested_at,
            last_success_at=last_success_at or (current.last_success_at if current else None),
            last_test_detail=detail,
            last_status_code=status_code,
            last_latency_ms=latency_ms,
            remaining_quota=remaining_quota,
            quota_reset_at=quota_reset_at,
        )
        self.save()

    def invalidate_health(self, provider_id: str, *, default_enabled: bool = True) -> None:
        """Secret rotation must invalidate cached probes and clients."""
        current = self._configs.get(provider_id)
        self._configs[provider_id] = ProviderConfiguration(
            enabled=(current.enabled if current else default_enabled),
            config=current.config if current else {},
            health_badge=HealthBadge.NOT_TESTED,
            tested_at=None,
            last_success_at=None,
            last_test_detail=None,
            last_status_code=None,
            last_latency_ms=None,
            remaining_quota=None,
            quota_reset_at=None,
        )
        self.save()

    def save(self) -> None:
        document: dict[str, object] = {
            provider_id: config.to_dict()
            for provider_id, config in sorted(self._configs.items())
        }
        encoded = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as temporary:
                temporary.write(encoded)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self.path)
        finally:
            temporary_path.unlink(missing_ok=True)


class SecretRegistry:
    """Typed, masked view over the encrypted secret store.

    Values are never exposed; callers receive configured/missing state and a
    masked last-four view. Saving or removing a secret invalidates any cached
    provider health (rotation semantics).
    """

    def __init__(self, store: SecretStore) -> None:
        self._store = store
        self._cache: dict[str, str] | None = None

    def _load(self) -> dict[str, str]:
        if self._cache is None:
            self._cache = dict(self._store.load())
        return self._cache

    def load_all(self) -> dict[str, str]:
        """Raw (encrypted-store) values. Internal use only — never exposed."""
        return dict(self._load())

    def refresh(self) -> None:
        self._cache = dict(self._store.load())

    def get(self, secret_name: str) -> str | None:
        return self._load().get(secret_name)

    def known_names(self) -> frozenset[str]:
        return REGISTRY_SECRET_NAMES

    def legacy_names(self) -> frozenset[str]:
        return frozenset(LEGACY_SECRET_MAP)

    def masked(self, secret_name: str) -> str | None:
        from .models import mask_secret

        value = self._load().get(secret_name)
        return mask_secret(value) if value is not None else None

    def configured(self, secret_name: str) -> bool:
        value = self._load().get(secret_name)
        return bool(value is not None and value != "")

    def save(self, updates: Mapping[str, str]) -> None:
        """Persist non-empty values; blank values retain the existing secret.

        Returns nothing and never echoes values back.
        """
        pending: dict[str, str] = {}
        for name, value in updates.items():
            if not isinstance(name, str) or not isinstance(value, str):
                raise ValueError("secret names and values must be strings")
            if not value:
                continue
            if name not in REGISTRY_SECRET_NAMES and name not in LEGACY_SECRET_MAP:
                raise ValueError(f"unknown secret name: {name}")
            pending[name] = value
        if not pending:
            return
        merged = dict(self._load())
        merged.update(pending)
        self._store.save(merged)
        self._cache = merged

    def remove(self, secret_name: str) -> None:
        if secret_name not in REGISTRY_SECRET_NAMES and secret_name not in LEGACY_SECRET_MAP:
            raise ValueError(f"unknown secret name: {secret_name}")
        current = dict(self._load())
        if secret_name not in current:
            return
        del current[secret_name]
        self._store.save(current)
        self._cache = current

    def invalidated_keys(self, updates: Mapping[str, str], removed: str | None) -> set[str]:
        """Provider ids whose cached health must be invalidated after a change."""
        affected: set[str] = set()
        for name in list(updates) + ([removed] if removed else []):
            provider_id = LEGACY_SECRET_MAP.get(name)
            if provider_id is not None:
                affected.add(provider_id)
            for provider_id, provider_secrets in _SECRETS_BY_PROVIDER.items():
                if name in provider_secrets:
                    affected.add(provider_id)
        return affected


_SECRETS_BY_PROVIDER: dict[str, frozenset[str]] = {}


def _build_secret_index() -> None:
    from .registry import PROVIDERS

    for provider in PROVIDERS:
        _SECRETS_BY_PROVIDER[provider.provider_id] = frozenset(
            (*provider.required_secrets, *provider.optional_secrets)
        )


_build_secret_index()


def apply_rotation_invalidation(
    config_store: ProviderConfigStore,
    secret_registry: SecretRegistry,
    updates: Mapping[str, str] | None = None,
    removed: str | None = None,
) -> None:
    """Invalidate cached health for every provider touched by a secret change."""
    if updates or removed:
        for provider_id in secret_registry.invalidated_keys(updates or {}, removed):
            definition_default = True
            from .registry import find_provider

            definition = find_provider(provider_id)
            if definition is not None:
                definition_default = definition.enabled_default
            config_store.invalidate_health(provider_id, default_enabled=definition_default)


def clock_now() -> str:
    return utc_now_iso()