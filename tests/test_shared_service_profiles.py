from pathlib import Path

import pytest

from shared_platform.application import ApplicationContext
from shared_platform.services import RouteProfile, ServiceProfile, validate_deployment


def contexts():
    return (
        ApplicationContext("defend", Path("C:/DEFEND_DATA"), "DEFEND", "DEFEND", "defend_account_session", "https://ai.defend-network.org", 8000, 3000),
        ApplicationContext("scs", Path("C:/SCS_DATA"), "SCS", "SCS", "scs_employee_session", "https://ai.sunshineclimatesolutions.com", 8100, 3100),
    )


def services():
    return (
        ServiceProfile("defend", "api", "defend:api", 8000, "/health"),
        ServiceProfile("defend", "web", "defend:web", 3000, "/"),
        ServiceProfile("scs", "api", "scs:api", 8100, "/health"),
        ServiceProfile("scs", "web", "scs:web", 3100, "/"),
    )


def routes():
    return (
        RouteProfile("defend", "https://ai.defend-network.org", 3000),
        RouteProfile("scs", "https://ai.sunshineclimatesolutions.com", 3100),
    )


@pytest.mark.parametrize(
    "args,match",
    [
        (("defend", "api", "api", 8000, "/health"), "qualified"),
        (("defend", "database", "defend:database", 8000, "/health"), "role"),
        (("defend", "api", "defend:api", 0, "/health"), "port"),
        (("defend", "api", "defend:api", 8000, "health"), "health_path"),
        (("defend", "api", "defend:api", 8000, "/health?secret=x"), "health_path"),
    ],
)
def test_service_profile_is_qualified_and_safe(args, match):
    with pytest.raises(ValueError, match=match):
        ServiceProfile(*args)


def test_valid_deployment_has_one_owned_route_per_application():
    deployment = validate_deployment(contexts(), services(), routes())
    assert [route.application_id for route in deployment.routes] == ["defend", "scs"]
    assert deployment.service("scs", "web").port == 3100


def test_deployment_rejects_duplicate_service_ports():
    broken = services() + (ServiceProfile("scs", "vision", "scs:vision", 8000, "/health"),)
    with pytest.raises(ValueError, match="port collision"):
        validate_deployment(contexts(), broken, routes())


def test_deployment_rejects_missing_or_duplicate_routes():
    with pytest.raises(ValueError, match="one route"):
        validate_deployment(contexts(), services(), routes()[:1])
    with pytest.raises(ValueError, match="one route"):
        validate_deployment(contexts(), services(), routes() + (routes()[1],))


def test_deployment_rejects_origin_mismatch_and_cross_wired_upstream():
    wrong_origin = RouteProfile("scs", "https://wrong.sunshineclimatesolutions.com", 3100)
    with pytest.raises(ValueError, match="origin"):
        validate_deployment(contexts(), services(), (routes()[0], wrong_origin))

    cross_wired = RouteProfile("scs", "https://ai.sunshineclimatesolutions.com", 3000)
    with pytest.raises(ValueError, match="owned web service"):
        validate_deployment(contexts(), services(), (routes()[0], cross_wired))


def test_deployment_requires_api_and_web_services_for_each_application():
    without_scs_api = tuple(item for item in services() if item.service_name != "scs:api")
    with pytest.raises(ValueError, match="scs:api"):
        validate_deployment(contexts(), without_scs_api, routes())
