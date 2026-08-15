from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping, Protocol

GatewayState = Literal["not_configured", "configured", "unavailable"]


@dataclass(frozen=True)
class ProviderProfile:
    provider_id: str
    model_name: str
    base_url: str | None = None
    requires_api_key: bool = False


@dataclass(frozen=True)
class GatewayStatus:
    state: GatewayState
    alias: str | None
    provider: str | None
    model_name: str | None
    ready: bool

    def __repr__(self) -> str:
        return (
            f"GatewayStatus(state={self.state!r}, alias={self.alias!r}, "
            f"provider={self.provider!r}, model_name={self.model_name!r}, "
            f"ready={self.ready!r})"
        )


class _ClientFactory(Protocol):
    def __call__(self, profile: ProviderProfile, *, api_key: str | None) -> object: ...


class ModelGateway:
    """Provider-neutral gateway mapping a model alias to a provider profile.

    The gateway holds no provider SDK, never calls a model service, and
    reports an honest non-ready state until an explicit alias, provider
    profile, and (when required) API key are configured.
    """

    def __init__(
        self,
        alias: str | None = None,
        providers: Mapping[str, ProviderProfile] | None = None,
        *,
        api_key: str | None = None,
        client_factory: _ClientFactory | None = None,
    ) -> None:
        if alias is not None and (not isinstance(alias, str) or not alias.strip()):
            raise ValueError("model alias must not be empty")
        self._alias = alias.strip() if alias is not None else None
        self._providers = dict(providers or {})
        self._api_key = api_key
        self._client_factory = client_factory
        self._client: object | None = None

    def _profile(self) -> ProviderProfile | None:
        if self._alias is None:
            return None
        return self._providers.get(self._alias)

    def status(self) -> GatewayStatus:
        profile = self._profile()
        if profile is None:
            return GatewayStatus(
                state="not_configured",
                alias=self._alias,
                provider=None,
                model_name=None,
                ready=False,
            )
        if profile.requires_api_key and not self._api_key:
            return GatewayStatus(
                state="unavailable",
                alias=self._alias,
                provider=profile.provider_id,
                model_name=profile.model_name,
                ready=False,
            )
        if not profile.base_url:
            return GatewayStatus(
                state="unavailable",
                alias=self._alias,
                provider=profile.provider_id,
                model_name=profile.model_name,
                ready=False,
            )
        return GatewayStatus(
            state="configured",
            alias=self._alias,
            provider=profile.provider_id,
            model_name=profile.model_name,
            ready=True,
        )

    def client(self) -> object | None:
        if self.status().state != "configured":
            return None
        if self._client is not None:
            return self._client
        if self._client_factory is None:
            return None
        self._client = self._client_factory(
            self._providers[self._alias], api_key=self._api_key
        )
        return self._client