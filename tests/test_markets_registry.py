from pathlib import Path

import pytest

from defend_markets.config import MarketsSettings
from shared_platform.application import ApplicationContext, validate_applications
from shared_platform.services import RouteProfile, ServiceProfile, validate_deployment


def _markets_settings(data_root: Path) -> MarketsSettings:
    return MarketsSettings(
        data_root=data_root,
        database_url="postgresql://x:x@localhost:5432/markets",
        api_port=8300,
        web_port=3300,
        public_origin="https://defendmarkets.defend-network.org",
        session_cookie="markets_session",
    )


def ctx(
    app_id: str,
    root: Path,
    prefix: str,
    cookie: str,
    origin: str,
    api: int,
    web: int,
) -> ApplicationContext:
    return ApplicationContext(
        application_id=app_id,
        data_root=root,
        environment_prefix=prefix,
        secret_namespace=prefix,
        session_cookie=cookie,
        public_origin=origin,
        api_port=api,
        web_port=web,
    )


def _existing(tmp_path: Path) -> tuple[ApplicationContext, ...]:
    return (
        ctx(
            "defend",
            tmp_path / "defend",
            "DEFEND",
            "defend_session",
            "https://defend-network.org",
            8000,
            3000,
        ),
        ctx(
            "scs",
            tmp_path / "scs",
            "SCS",
            "scs_session",
            "https://scs.defend-network.org",
            8100,
            3100,
        ),
        ctx(
            "sports",
            tmp_path / "sports",
            "SPORTS",
            "sports_session",
            "https://defendsports.defend-network.org",
            8200,
            3200,
        ),
    )


def test_markets_registers_alongside_defend_scs_sports(tmp_path):
    markets = _markets_settings(tmp_path / "markets").application_context()
    validated = validate_applications((*_existing(tmp_path), markets))
    assert [item.application_id for item in validated] == [
        "defend",
        "scs",
        "sports",
        "markets",
    ]


def test_markets_ports_do_not_collide_with_existing_applications(tmp_path):
    markets = _markets_settings(tmp_path / "markets").application_context()
    existing_ports = {
        port
        for context in _existing(tmp_path)
        for port in (context.api_port, context.web_port)
    }
    assert markets.api_port == 8300
    assert markets.web_port == 3300
    assert markets.api_port not in existing_ports
    assert markets.web_port not in existing_ports


def test_markets_deployment_profile_requires_api_and_web_services(tmp_path):
    markets = _markets_settings(tmp_path / "markets").application_context()
    contexts = (*_existing(tmp_path), markets)
    services = tuple(
        service
        for context in contexts
        for service in (
            ServiceProfile(
                context.application_id,
                "api",
                f"{context.application_id}:api",
                context.api_port,
                "/health",
            ),
            ServiceProfile(
                context.application_id,
                "web",
                f"{context.application_id}:web",
                context.web_port,
                "/",
            ),
        )
    )
    routes = tuple(
        RouteProfile(context.application_id, context.public_origin, context.web_port)
        for context in contexts
    )
    deployment = validate_deployment(contexts, services, routes)
    assert [item.application_id for item in deployment.contexts] == [
        "defend",
        "scs",
        "sports",
        "markets",
    ]
    assert deployment.service("markets", "api").port == 8300
    assert deployment.service("markets", "web").port == 3300


def test_markets_origin_is_a_distinct_https_origin(tmp_path):
    markets = _markets_settings(tmp_path / "markets").application_context()
    existing_origins = {context.public_origin for context in _existing(tmp_path)}
    assert markets.public_origin == "https://defendmarkets.defend-network.org"
    assert markets.public_origin not in existing_origins


def test_markets_settings_application_context_roundtrip(tmp_path):
    settings = _markets_settings(tmp_path / "markets")
    context = settings.application_context()
    assert context.environment_prefix == "MARKETS"
    assert context.secret_namespace == "MARKETS"
    assert context.session_cookie == "markets_session"
    assert context.data_root.is_absolute()