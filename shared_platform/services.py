from __future__ import annotations

from dataclasses import dataclass
from .application import (
    ApplicationContext,
    ApplicationId,
    _canonical_origin,
    validate_application_pair,
)


_ROLES = frozenset({"api", "web", "language", "embedding", "vision", "coding"})


def _port(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65_535:
        raise ValueError("service port must be an integer in 1..65535")
    return value


@dataclass(frozen=True)
class ServiceProfile:
    application_id: ApplicationId
    role: str
    service_name: str
    port: int
    health_path: str

    def __post_init__(self) -> None:
        if self.application_id not in {"defend", "scs"}:
            raise ValueError("service application_id must be defend or scs")
        if self.role not in _ROLES:
            raise ValueError("unsupported service role")
        if self.service_name != f"{self.application_id}:{self.role}":
            raise ValueError("service_name must be application-qualified")
        object.__setattr__(self, "port", _port(self.port))
        if (
            not isinstance(self.health_path, str)
            or not self.health_path.startswith("/")
            or self.health_path.startswith("//")
            or "?" in self.health_path
            or "#" in self.health_path
            or "\\" in self.health_path
            or any(ord(char) < 0x20 for char in self.health_path)
        ):
            raise ValueError("health_path must be a safe absolute URL path")


@dataclass(frozen=True)
class RouteProfile:
    application_id: ApplicationId
    public_origin: str
    upstream_port: int

    def __post_init__(self) -> None:
        if self.application_id not in {"defend", "scs"}:
            raise ValueError("route application_id must be defend or scs")
        try:
            origin = _canonical_origin(self.public_origin)
        except ValueError as error:
            raise ValueError(str(error).replace("public_origin", "route public_origin")) from None
        object.__setattr__(self, "public_origin", origin)
        object.__setattr__(self, "upstream_port", _port(self.upstream_port))


@dataclass(frozen=True)
class DeploymentProfile:
    contexts: tuple[ApplicationContext, ApplicationContext]
    services: tuple[ServiceProfile, ...]
    routes: tuple[RouteProfile, RouteProfile]

    def service(self, application_id: ApplicationId, role: str) -> ServiceProfile:
        name = f"{application_id}:{role}"
        return next(item for item in self.services if item.service_name == name)


def validate_deployment(
    contexts: tuple[ApplicationContext, ...],
    services: tuple[ServiceProfile, ...],
    routes: tuple[RouteProfile, ...],
) -> DeploymentProfile:
    if len(contexts) != 2:
        raise ValueError("deployment requires exactly two application contexts")
    defend, scs = validate_application_pair(contexts[0], contexts[1])
    ordered_contexts = (defend, scs)
    context_by_id = {item.application_id: item for item in ordered_contexts}

    names: set[str] = set()
    ports: set[int] = set()
    service_by_name: dict[str, ServiceProfile] = {}
    for service in services:
        if service.service_name in names:
            raise ValueError("service name collision")
        if service.port in ports:
            raise ValueError("service port collision")
        names.add(service.service_name)
        ports.add(service.port)
        service_by_name[service.service_name] = service

    for context in ordered_contexts:
        for role, expected_port in (("api", context.api_port), ("web", context.web_port)):
            name = f"{context.application_id}:{role}"
            service = service_by_name.get(name)
            if service is None:
                raise ValueError(f"deployment requires {name}")
            if service.port != expected_port:
                raise ValueError(f"{name} port does not match application context")

    route_by_id: dict[str, RouteProfile] = {}
    for route in routes:
        if route.application_id in route_by_id:
            raise ValueError("deployment requires exactly one route per application")
        route_by_id[route.application_id] = route
    if set(route_by_id) != {"defend", "scs"}:
        raise ValueError("deployment requires exactly one route per application")

    ordered_routes: list[RouteProfile] = []
    for app_id in ("defend", "scs"):
        route = route_by_id[app_id]
        context = context_by_id[app_id]
        if route.public_origin != context.public_origin:
            raise ValueError(f"{app_id} route origin does not match application context")
        web = service_by_name[f"{app_id}:web"]
        if route.upstream_port != web.port:
            raise ValueError(f"{app_id} route must target its owned web service")
        ordered_routes.append(route)

    return DeploymentProfile(
        contexts=ordered_contexts,
        services=tuple(services),
        routes=(ordered_routes[0], ordered_routes[1]),
    )
