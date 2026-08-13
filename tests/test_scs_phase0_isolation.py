from pathlib import Path

import pytest

from shared_platform.phase0 import build_phase0_deployment, phase0_contexts
from shared_platform.secrets import NamespacedSecrets
from shared_platform.services import RouteProfile, validate_deployment


def test_phase0_contract_reserves_completely_isolated_application_boundaries():
    defend, scs = phase0_contexts()
    deployment = build_phase0_deployment()

    assert defend.data_root == Path("C:/DEFEND_DATA").resolve(strict=False)
    assert scs.data_root == Path("C:/SCS_DATA").resolve(strict=False)
    assert defend.environment_prefix == defend.secret_namespace == "DEFEND"
    assert scs.environment_prefix == scs.secret_namespace == "SCS"
    assert defend.session_cookie == "defend_account_session"
    assert scs.session_cookie == "scs_employee_session"
    assert defend.public_origin == "https://ai.defend-network.org"
    assert scs.public_origin == "https://ai.sunshineclimatesolutions.com"
    assert {service.service_name for service in deployment.services} == {
        "defend:api", "defend:web", "scs:api", "scs:web"
    }


def test_phase0_secret_views_do_not_share_owner_or_session_material():
    physical = {
        "DEFEND_OWNER_PASS": "defend-owner-secret",
        "DEFEND_SESSION_KEY": "defend-session-secret",
        "SCS_OWNER_PASS": "scs-owner-secret",
        "SCS_SESSION_KEY": "scs-session-secret",
    }
    defend, scs = phase0_contexts()

    assert NamespacedSecrets(physical, defend).require("OWNER_PASS", "SESSION_KEY") == {
        "OWNER_PASS": "defend-owner-secret",
        "SESSION_KEY": "defend-session-secret",
    }
    assert NamespacedSecrets(physical, scs).require("OWNER_PASS", "SESSION_KEY") == {
        "OWNER_PASS": "scs-owner-secret",
        "SESSION_KEY": "scs-session-secret",
    }


def test_phase0_contract_rejects_cross_wired_scs_route():
    contexts = phase0_contexts()
    deployment = build_phase0_deployment()
    routes = (
        deployment.routes[0],
        RouteProfile("scs", "https://ai.sunshineclimatesolutions.com", 3000),
    )
    with pytest.raises(ValueError, match="owned web service"):
        validate_deployment(contexts, deployment.services, routes)
