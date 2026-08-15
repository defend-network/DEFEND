from pathlib import Path

import pytest

from shared_platform.application import ApplicationContext, validate_applications
from shared_platform.services import RouteProfile, ServiceProfile, validate_deployment


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


def test_validate_three_application_contexts(tmp_path):
    defend = ctx(
        "defend",
        tmp_path / "defend",
        "DEFEND",
        "defend_session",
        "https://defend-network.org",
        8000,
        3000,
    )
    scs = ctx(
        "scs",
        tmp_path / "scs",
        "SCS",
        "scs_session",
        "https://scs.defend-network.org",
        8100,
        3100,
    )
    sports = ctx(
        "sports",
        tmp_path / "sports",
        "SPORTS",
        "sports_session",
        "https://defendsports.defend-network.org",
        8200,
        3200,
    )

    validated = validate_applications((defend, scs, sports))

    assert [item.application_id for item in validated] == ["defend", "scs", "sports"]


def test_cross_application_port_collision_is_rejected(tmp_path):
    defend = ctx(
        "defend",
        tmp_path / "defend",
        "DEFEND",
        "defend_session",
        "https://defend-network.org",
        8000,
        3000,
    )
    sports = ctx(
        "sports",
        tmp_path / "sports",
        "SPORTS",
        "sports_session",
        "https://defendsports.defend-network.org",
        8000,
        3200,
    )

    with pytest.raises(ValueError, match="port collision"):
        validate_applications((defend, sports))


def test_deployment_supports_one_owned_route_and_api_web_services_per_application(
    tmp_path,
):
    contexts = (
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
    ]
    assert [item.application_id for item in deployment.routes] == [
        "defend",
        "scs",
        "sports",
    ]
    assert deployment.service("sports", "web").port == 3200


def test_deployment_requires_the_sports_api_service(tmp_path):
    defend = ctx(
        "defend",
        tmp_path / "defend",
        "DEFEND",
        "defend_session",
        "https://defend-network.org",
        8000,
        3000,
    )
    sports = ctx(
        "sports",
        tmp_path / "sports",
        "SPORTS",
        "sports_session",
        "https://defendsports.defend-network.org",
        8200,
        3200,
    )
    services = (
        ServiceProfile("defend", "api", "defend:api", 8000, "/health"),
        ServiceProfile("defend", "web", "defend:web", 3000, "/"),
        ServiceProfile("sports", "web", "sports:web", 3200, "/"),
    )
    routes = (
        RouteProfile("defend", "https://defend-network.org", 3000),
        RouteProfile("sports", "https://defendsports.defend-network.org", 3200),
    )

    with pytest.raises(ValueError, match="sports:api"):
        validate_deployment((defend, sports), services, routes)
