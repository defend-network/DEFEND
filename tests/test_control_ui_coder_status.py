from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from defend_control.products import ProductStatus
from defend_control.ui import (
    coder_runtime_status_payload,
    write_coder_runtime_status_file,
)


class FakeCoderProduct:
    def __init__(self, status, settings=None, plane=None):
        self.application_id = "coder"
        self.display_name = "DEFENDcoder"
        self._status = status
        self._settings = settings
        self._plane = plane

    def status(self):
        return self._status


class FakeSettings:
    coder_model_alias = "defendcoder-heavy"


class FakePlane:
    def __init__(self, endpoint):
        self._endpoint = endpoint

    def status(self, _alias):
        return self._endpoint


def _status(state="running", details=(), last_error=None):
    return ProductStatus(
        application_id="coder",
        display_name="DEFENDcoder",
        state=state,
        status_text="coder runtime",
        details=details,
        last_error=last_error,
    )


def test_payload_is_none_without_coder_product():
    assert coder_runtime_status_payload(()) is None
    assert (
        coder_runtime_status_payload(
            (
                type(
                    "Other",
                    (),
                    {"application_id": "sports", "status": lambda: None},
                )(),
            )
        )
        is None
    )


def test_payload_maps_running_to_ready_with_registry_identity():
    payload = coder_runtime_status_payload(
        (
            FakeCoderProduct(
                _status(),
                settings=FakeSettings(),
                plane=FakePlane(
                    {
                        "provider": "Vast.ai",
                        "gpu_type": "H100 SXM",
                        "instance_id": "12345",
                    }
                ),
            ),
        )
    )

    assert payload is not None
    assert payload["state"] == "ready"
    assert payload["alias"] == "defendcoder-heavy"
    assert payload["model_name"] == "Qwen/Qwen3-Coder-Next"
    assert payload["context_limit"] == 32768
    assert payload["provider"] == "Vast.ai"
    assert payload["gpu"] == "H100 SXM"
    assert payload["instance_id"] == "12345"
    assert "updated_at" in payload


def test_payload_state_mapping_covers_control_plane_states():
    cases = (
        ("running", "ready"),
        ("starting", "starting"),
        ("starting_local", "starting"),
        ("provisioning", "starting"),
        ("preparing", "starting"),
        ("approval_required", "starting"),
        ("stopped", "offline"),
        ("no_offer", "offline"),
        ("failed", "failed"),
        ("mystery", "offline"),
    )
    for raw, expected in cases:
        payload = coder_runtime_status_payload(
            (FakeCoderProduct(_status(state=raw)),)
        )
        assert payload is not None
        assert payload["state"] == expected, raw


def test_payload_uses_failed_error_as_detail():
    payload = coder_runtime_status_payload(
        (
            FakeCoderProduct(
                _status(state="failed", last_error="provision rejected")
            ),
        )
    )

    assert payload is not None
    assert payload["state"] == "failed"
    assert payload["detail"] == "provision rejected"


def test_payload_survives_broken_product():
    class Broken:
        application_id = "coder"

        def status(self):
            raise RuntimeError("boom")

    assert coder_runtime_status_payload((Broken(),)) is None


def test_write_coder_runtime_status_file_is_atomic(tmp_path):
    target = tmp_path / "nested" / "coder-model-status.json"
    payload = {"state": "ready", "alias": "defendcoder-heavy"}

    write_coder_runtime_status_file(payload, target)

    import json

    assert json.loads(target.read_text(encoding="utf-8")) == payload
    assert not list(Path(target.parent).glob("*.tmp"))