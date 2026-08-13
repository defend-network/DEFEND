from pathlib import Path

import pytest

from shared_platform.application import ApplicationContext
from shared_platform.secrets import NamespacedSecrets


def app(app_id: str) -> ApplicationContext:
    return ApplicationContext(
        application_id=app_id,
        data_root=Path("C:/DEFEND_DATA" if app_id == "defend" else "C:/SCS_DATA"),
        environment_prefix=app_id.upper(),
        secret_namespace=app_id.upper(),
        session_cookie="defend_account_session" if app_id == "defend" else "scs_employee_session",
        public_origin="https://ai.defend-network.org" if app_id == "defend" else "https://ai.sunshineclimatesolutions.com",
        api_port=8000 if app_id == "defend" else 8100,
        web_port=3000 if app_id == "defend" else 3100,
    )


def test_each_application_can_read_only_its_physical_secret_namespace():
    values = {
        "DEFEND_OWNER_PASS": "defend-private",
        "SCS_OWNER_PASS": "scs-private",
        "UNSCOPED": "never-visible",
    }
    defend = NamespacedSecrets(values, app("defend"))
    scs = NamespacedSecrets(values, app("scs"))

    assert defend.get("OWNER_PASS") == "defend-private"
    assert scs.get("OWNER_PASS") == "scs-private"
    assert defend.export(["OWNER_PASS"]) == {"OWNER_PASS": "defend-private"}
    assert scs.export(["OWNER_PASS"]) == {"OWNER_PASS": "scs-private"}
    assert defend.get("MISSING") is None


@pytest.mark.parametrize("name", ["", "owner_pass", "SCS_OWNER_PASS", "OWNER-PASS", " OWNER_PASS"])
def test_logical_secret_names_are_strict_and_cannot_escape_namespace(name):
    secrets = NamespacedSecrets({}, app("defend"))
    with pytest.raises(ValueError, match="logical secret name"):
        secrets.get(name)


def test_required_secret_errors_and_representation_never_expose_values():
    private = "synthetic-private-value"
    secrets = NamespacedSecrets({"SCS_PRESENT": private}, app("scs"))

    with pytest.raises(ValueError) as captured:
        secrets.require("PRESENT", "MISSING")
    rendered = repr(secrets) + str(captured.value)
    assert private not in rendered
    assert "SCS_PRESENT" not in rendered
    assert "MISSING" in str(captured.value)


def test_source_mapping_is_copied_and_export_is_bounded():
    source = {"SCS_API_KEY": "first", "DEFEND_API_KEY": "other"}
    secrets = NamespacedSecrets(source, app("scs"))
    source["SCS_API_KEY"] = "changed"

    assert secrets.require("API_KEY") == {"API_KEY": "first"}
    with pytest.raises(KeyError, match="MISSING"):
        secrets.export(["MISSING"])
