from __future__ import annotations

from pathlib import Path

from .application import ApplicationContext, validate_application_pair
from .services import DeploymentProfile, RouteProfile, ServiceProfile, validate_deployment


def phase0_contexts() -> tuple[ApplicationContext, ApplicationContext]:
    """Return reserved boundaries; this performs no I/O and starts no services."""

    defend = ApplicationContext(
        application_id="defend",
        data_root=Path(r"C:\DEFEND_DATA"),
        environment_prefix="DEFEND",
        secret_namespace="DEFEND",
        session_cookie="defend_account_session",
        public_origin="https://ai.defend-network.org",
        api_port=8000,
        web_port=3000,
    )
    scs = ApplicationContext(
        application_id="scs",
        data_root=Path(r"C:\SCS_DATA"),
        environment_prefix="SCS",
        secret_namespace="SCS",
        session_cookie="scs_employee_session",
        public_origin="https://ai.sunshineclimatesolutions.com",
        api_port=8100,
        web_port=3100,
    )
    return validate_application_pair(defend, scs)


def build_phase0_deployment() -> DeploymentProfile:
    contexts = phase0_contexts()
    services = (
        ServiceProfile("defend", "api", "defend:api", 8000, "/health"),
        ServiceProfile("defend", "web", "defend:web", 3000, "/"),
        ServiceProfile("scs", "api", "scs:api", 8100, "/health"),
        ServiceProfile("scs", "web", "scs:web", 3100, "/"),
    )
    routes = (
        RouteProfile("defend", "https://ai.defend-network.org", 3000),
        RouteProfile("scs", "https://ai.sunshineclimatesolutions.com", 3100),
    )
    return validate_deployment(contexts, services, routes)
