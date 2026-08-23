from __future__ import annotations

import inspect
import json

from tools import defend_coder_server


def test_coder_server_entrypoint_composes_production_stack():
    source = inspect.getsource(defend_coder_server)

    assert "CoderSettings.from_env()" in source
    assert "CoderDatabase(settings.database_url)" in source
    assert "database.migrate()" in source
    assert "CoderRepository(database)" in source
    assert "AuthService(repository)" in source
    assert "build_coder_app(" in source
    assert "uvicorn.run(" in source


def test_coder_server_binds_configured_loopback_host_and_port():
    source = inspect.getsource(defend_coder_server)

    assert "host=settings.host" in source
    assert "port=settings.port" in source


def test_runtime_status_is_product_owned_not_control_center():
    source = inspect.getsource(defend_coder_server)

    assert "coder_runtime_status" in source
    assert "CODER_MODEL_STATUS_FILE" not in source
    assert "DEFAULT_STATUS_FILE" not in source
    assert "_STATUS_STATE_MAP" not in source


def test_runtime_status_placeholder_reports_starting():
    status = defend_coder_server.runtime_status()

    assert status["state"] == "starting"
    assert status["alias"] == "DEFENDcoder"


def test_coder_runtime_status_derives_from_credentials():
    from defend_coder.runtime_status import coder_runtime_status

    class _Configured:
        def configured(self, provider):
            return provider == "deepseek"

    status = coder_runtime_status(_Configured())
    assert status["state"] == "ready"
    assert status["provider"] == "deepseek"
    assert status["deepseek_configured"] is True
    assert status["sol_configured"] is False
    assert status["next_state"] == "ABSENT"

    class _Missing:
        def configured(self, provider):
            return False

    offline = coder_runtime_status(_Missing())
    assert offline["state"] == "offline"
    assert offline["model"] is None


def test_coder_server_source_contains_no_embedded_credentials():
    source = inspect.getsource(defend_coder_server).lower()

    for banned in (
        "hvacboss",
        "postgresql://postgres:",
        "vast_api_key=",
        "hf_token=",
        "password=",
    ):
        assert banned not in source