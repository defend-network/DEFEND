from __future__ import annotations

from defend_coder.app import (
    CONSUMER_RUNTIME_FIELDS,
    project_runtime_status,
)


def test_projection_keeps_only_documented_safe_fields():
    status = project_runtime_status(
        {
            "state": "ready",
            "model": "Qwen/Qwen3-Coder-30B-A3B-Instruct",
            "provider": "Vast.ai",
            "context_used": 120,
            "context_limit": 8192,
            "internal_endpoint": "http://127.0.0.1:9000",
            "api_key": "sensitive-value",
        }
    )

    assert status == {
        "state": "ready",
        "model": "Qwen/Qwen3-Coder-30B-A3B-Instruct",
        "provider": "Vast.ai",
        "context_used": 120,
        "context_limit": 8192,
    }


def test_projection_never_exposes_control_plane_detail():
    status = project_runtime_status(
        {
            "state": "not_connected",
            "ssh_endpoint": "host:22",
            "instance_id": "12345",
        }
    )

    assert status == {"state": "not_connected"}
    assert "ssh_endpoint" not in status
    assert "instance_id" not in status


def test_projection_omits_missing_fields():
    status = project_runtime_status({"state": "ready"})

    assert status == {"state": "ready"}
    assert set(status).issubset(CONSUMER_RUNTIME_FIELDS)


def test_projection_preserves_null_values_as_reported():
    status = project_runtime_status(
        {
            "state": "not_connected",
            "provider": None,
            "model": None,
        }
    )

    assert status == {
        "state": "not_connected",
        "provider": None,
        "model": None,
    }