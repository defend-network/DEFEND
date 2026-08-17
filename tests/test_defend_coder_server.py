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


def test_runtime_status_is_offline_when_control_plane_has_not_published(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "CODER_MODEL_STATUS_FILE",
        str(tmp_path / "missing.json"),
    )

    status = defend_coder_server.runtime_status()

    assert status["state"] == "offline"
    assert status["model"] is None
    assert status["provider"] is None
    assert "not publishing" in (status["detail"] or "")


def test_runtime_status_reads_published_status_file(monkeypatch, tmp_path):
    status_file = tmp_path / "coder-model-status.json"
    status_file.write_text(
        json.dumps(
            {
                "alias": "defendcoder-heavy",
                "state": "ready",
                "model_name": "Qwen/Qwen3-Coder-Next",
                "provider": "Vast.ai",
                "context_limit": 32768,
                "context_used": None,
                "detail": "running",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CODER_MODEL_STATUS_FILE", str(status_file))

    status = defend_coder_server.runtime_status()

    assert status["state"] == "ready"
    assert status["model"] == "Qwen/Qwen3-Coder-Next"
    assert status["provider"] == "Vast.ai"
    assert status["context_limit"] == 32768
    assert status["alias"] == "defendcoder-heavy"


def test_runtime_status_maps_control_plane_states(monkeypatch, tmp_path):
    status_file = tmp_path / "coder-model-status.json"
    monkeypatch.setenv("CODER_MODEL_STATUS_FILE", str(status_file))

    for raw_state, expected in (
        ("running", "ready"),
        ("starting_local", "starting"),
        ("provisioning", "starting"),
        ("approval_required", "starting"),
        ("stopped", "offline"),
        ("no_offer", "offline"),
        ("failed", "failed"),
        ("mystery", "offline"),
    ):
        status_file.write_text(
            json.dumps({"state": raw_state}),
            encoding="utf-8",
        )
        assert defend_coder_server.runtime_status()["state"] == expected


def test_runtime_status_treats_malformed_file_as_offline(monkeypatch, tmp_path):
    status_file = tmp_path / "coder-model-status.json"
    status_file.write_text("not json", encoding="utf-8")
    monkeypatch.setenv("CODER_MODEL_STATUS_FILE", str(status_file))

    status = defend_coder_server.runtime_status()

    assert status["state"] == "offline"
    assert "malformed" in (status["detail"] or "")


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