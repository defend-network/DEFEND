from __future__ import annotations

import inspect


def test_coder_server_entrypoint_composes_production_stack():
    from tools import defend_coder_server

    source = inspect.getsource(defend_coder_server)

    assert "CoderSettings.from_env()" in source
    assert "CoderDatabase(settings.database_url)" in source
    assert "database.migrate()" in source
    assert "CoderRepository(database)" in source
    assert "AuthService(repository)" in source
    assert "build_coder_app(" in source
    assert "uvicorn.run(" in source


def test_coder_server_binds_configured_loopback_host_and_port():
    from tools import defend_coder_server

    source = inspect.getsource(defend_coder_server)

    assert "host=settings.host" in source
    assert "port=settings.port" in source


def test_coder_server_runtime_status_is_truthful_before_control_plane_binding():
    from tools import defend_coder_server

    status = defend_coder_server.runtime_status()

    assert status["state"] == "not_connected"
    assert status["provider"] is None
    assert status["model"] is None


def test_coder_server_source_contains_no_embedded_credentials():
    from tools import defend_coder_server

    source = inspect.getsource(defend_coder_server).lower()

    for banned in (
        "hvacboss",
        "postgresql://postgres:",
        "vast_api_key=",
        "hf_token=",
        "password=",
    ):
        assert banned not in source
