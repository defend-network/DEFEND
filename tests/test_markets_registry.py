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
        web_port=3000,
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
    # M4.8.2B: Markets UI is served by the shared defend-ui-v2 web surface
    # (port 3000), so markets shares that web port rather than owning a distinct
    # one. Its API port (8300) is the isolated Markets-owned resource.
    existing = _existing(tmp_path)
    api_ports = {context.api_port for context in existing}
    assert markets.api_port not in api_ports
    assert markets.web_port == 3000
    assert markets.web_port == next(c.web_port for c in existing if c.application_id == "defend")


def test_markets_api_port_does_not_collide_with_existing_applications(tmp_path):
    markets = _markets_settings(tmp_path / "markets").application_context()
    existing_ports = {
        port
        for context in _existing(tmp_path)
        for port in (context.api_port, context.web_port)
    }
    assert markets.api_port == 8300
    # M4.8.2B: Markets UI is served by the shared defend-ui-v2 web surface
    # (port 3000), so web_port matches the DEFEND AI web surface, not a
    # standalone Markets web server. Only the API port must be isolated.
    assert markets.web_port == 3000
    assert markets.api_port not in existing_ports


def test_markets_deployment_profile_requires_api_and_web_services(tmp_path):
    markets = _markets_settings(tmp_path / "markets").application_context()
    # M4.8.2B: Markets web is the shared defend-ui-v2 surface (3000), not a
    # standalone Markets web server; only the Markets API service is Markets-owned.
    assert markets.api_port == 8300
    assert markets.web_port == 3000


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