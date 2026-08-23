"""Strict, dynamic provider credential resolution (no cross-routing).

Each provider resolves ONLY its own credential (env, key file, then the
platform DPAPI store). A DeepSeek key is never returned for Sol and an
OpenAI key is never returned for DeepSeek. Unknown providers fail closed
(None). ``configured()`` is evaluated at call time so a credential saved
after process startup takes effect without a restart. No secrets are ever
stored in ModelTarget, run records, or API output.
"""

from __future__ import annotations

import os
from typing import Callable, Mapping


#: provider -> (env key, optional key-file env)
PROVIDER_CREDENTIAL_ENV: dict[str, tuple[str, str | None]] = {
    "deepseek": ("DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY_FILE"),
    "sol": ("OPENAI_API_KEY", "OPENAI_API_KEY_FILE"),
}

_SUPPORTED_PROVIDERS = frozenset(PROVIDER_CREDENTIAL_ENV)


class CredentialStore:
    """Owner-facing credential resolution backed by env + platform store.

    ``store_loader`` returns an object exposing ``load()`` (dict[str,str])
    and ``save(values)`` — the DpapiSecretStore contract. The store is
    consulted lazily so runtime credential changes are visible immediately.
    """

    def __init__(
        self,
        *,
        store_loader: Callable[[], object] | object | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._env = env if env is not None else os.environ
        self._store_loader = store_loader

    def _store(self) -> dict[str, str]:
        loader = self._store_loader
        if loader is None:
            return {}
        store = loader() if callable(loader) else loader
        load = getattr(store, "load", None)
        if load is None:
            return {}
        try:
            values = load()
        except Exception:
            return {}
        if not isinstance(values, dict):
            return {}
        return {str(k): str(v) for k, v in values.items()}

    def _env_value(self, provider: str) -> str | None:
        names = PROVIDER_CREDENTIAL_ENV.get(provider)
        if names is None:
            return None
        value = (self._env.get(names[0]) or "").strip()
        if value:
            return value
        path = names[1] and (self._env.get(names[1]) or "").strip()
        if path:
            try:
                value = open(path, encoding="utf-8").read().strip()
            except OSError:
                value = ""
            if value:
                return value
        return None

    def resolve(self, provider: str) -> str | None:
        """Strict: return ONLY this provider's credential or None."""
        if provider not in _SUPPORTED_PROVIDERS:
            return None
        value = self._env_value(provider)
        if value:
            return value
        env_key = PROVIDER_CREDENTIAL_ENV[provider][0]
        return self._store().get(env_key) or None

    def configured(self, provider: str) -> bool:
        return bool(self.resolve(provider))

    def status(self) -> dict[str, str]:
        return {
            provider: ("CONFIGURED" if self.configured(provider) else "MISSING")
            for provider in ("deepseek", "sol")
        }

    def set(self, provider: str, api_key: str) -> None:
        """Persist a provider credential to the platform store."""
        if provider not in _SUPPORTED_PROVIDERS:
            raise ValueError(f"unknown provider {provider!r}")
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("api_key must be a non-empty string")
        loader = self._store_loader
        store = loader() if callable(loader) else loader
        save = getattr(store, "save", None)
        if save is None:
            raise RuntimeError("no credential store is configured to save into")
        env_key = PROVIDER_CREDENTIAL_ENV[provider][0]
        current = self._store()
        current[env_key] = api_key
        save(current)
