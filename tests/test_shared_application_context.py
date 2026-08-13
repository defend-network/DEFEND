from pathlib import Path

import pytest

from shared_platform.application import ApplicationContext, validate_application_pair


def context(app: str, root: Path, **overrides) -> ApplicationContext:
    values = {
        "application_id": app,
        "data_root": root,
        "environment_prefix": app.upper(),
        "secret_namespace": app.upper(),
        "session_cookie": "defend_account_session" if app == "defend" else "scs_employee_session",
        "public_origin": "https://ai.defend-network.org" if app == "defend" else "https://ai.sunshineclimatesolutions.com",
        "api_port": 8000 if app == "defend" else 8100,
        "web_port": 3000 if app == "defend" else 3100,
    }
    values.update(overrides)
    return ApplicationContext(**values)


def test_application_context_accepts_only_explicit_supported_ids(tmp_path):
    assert context("defend", tmp_path / "defend").application_id == "defend"
    assert context("scs", tmp_path / "scs").application_id == "scs"
    with pytest.raises(ValueError, match="application_id"):
        context("", tmp_path / "empty")
    with pytest.raises(ValueError, match="application_id"):
        context("other", tmp_path / "other")


@pytest.mark.parametrize(
    "overrides,match",
    [
        ({"data_root": Path("relative")}, "absolute"),
        ({"public_origin": "http://ai.example.com"}, "HTTPS"),
        ({"public_origin": "https://ai.example.com/path"}, "origin"),
        ({"api_port": 0}, "port"),
        ({"api_port": 8000, "web_port": 8000}, "distinct"),
        ({"environment_prefix": "defend"}, "environment_prefix"),
        ({"secret_namespace": "SCS-SECRET"}, "secret_namespace"),
        ({"session_cookie": "Bad Cookie"}, "session_cookie"),
    ],
)
def test_application_context_rejects_unsafe_values(tmp_path, overrides, match):
    with pytest.raises(ValueError, match=match):
        context("defend", tmp_path / "defend", **overrides)


@pytest.mark.parametrize(
    "field,value",
    [
        ("data_root", "same"),
        ("environment_prefix", "DEFEND"),
        ("secret_namespace", "DEFEND"),
        ("session_cookie", "defend_account_session"),
        ("public_origin", "https://ai.defend-network.org"),
        ("api_port", 8000),
        ("web_port", 3000),
    ],
)
def test_pair_rejects_every_cross_application_collision(tmp_path, field, value):
    defend = context("defend", tmp_path / "defend")
    scs_overrides = {field: (tmp_path / value if field == "data_root" else value)}
    if field == "data_root":
        scs_overrides[field] = defend.data_root
    scs = context("scs", tmp_path / "scs", **scs_overrides)
    with pytest.raises(ValueError, match="collision|overlap"):
        validate_application_pair(defend, scs)


def test_pair_rejects_nested_roots_and_returns_stable_order(tmp_path):
    defend = context("defend", tmp_path / "defend")
    nested_scs = context("scs", defend.data_root / "scs")
    with pytest.raises(ValueError, match="overlap"):
        validate_application_pair(defend, nested_scs)

    scs = context("scs", tmp_path / "scs")
    assert validate_application_pair(scs, defend) == (defend, scs)
    with pytest.raises(ValueError, match="exactly one"):
        validate_application_pair(defend, defend)
