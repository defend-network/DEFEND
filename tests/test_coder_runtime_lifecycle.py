"""DEFENDcoder runtime lifecycle: factory, delegation, health probe (deterministic)."""

from __future__ import annotations

import pytest

from defend_coder.runtime.health import probe_endpoint_ready
from defend_coder.runtime.factory import build_runtime_manager
from defend_coder.runtime_manager import (
    ABSENT,
    READY,
    STOPPED_RETAINED,
    CoderRuntimeManager,
    RuntimeSnapshot,
)

NEXT_MODEL = "Qwen/Qwen3-Coder-Next"
ENDPOINT = "http://127.0.0.1:8403/v1"


def _transport(models):
    def fetch(url, *, timeout_seconds):
        del url, timeout_seconds
        return {"data": [{"id": m} for m in models]}

    return fetch


class TestHealthProbe:
    def test_matching_model_ready(self):
        assert probe_endpoint_ready(ENDPOINT, NEXT_MODEL, transport=_transport([NEXT_MODEL]))

    def test_wrong_model_not_ready(self):
        assert not probe_endpoint_ready(ENDPOINT, NEXT_MODEL, transport=_transport(["other-model"]))

    def test_empty_model_list_not_ready(self):
        assert not probe_endpoint_ready(ENDPOINT, NEXT_MODEL, transport=_transport([]))

    def test_transport_error_fails_closed(self):
        def boom(url, *, timeout_seconds):
            raise OSError("connection refused")

        assert not probe_endpoint_ready(ENDPOINT, NEXT_MODEL, transport=boom)


class TestRuntimeFactory:
    def test_no_vast_key_builds_fail_closed_absent(self):
        manager = build_runtime_manager(secret_source={})
        assert manager.runtime_status()["state"] == ABSENT
        assert manager.runtime_ready() is False

    def test_with_vast_key_builds_control_plane(self):
        manager = build_runtime_manager(
            secret_source={"VAST_API_KEY": "k", "HF_TOKEN": "h"},
        )
        # A control plane is attached; status is derived from it (no live
        # call: VastCoderBackend has no tunnel wired, but status() is local).
        status = manager.runtime_status()
        assert status["state"] in (ABSENT, STOPPED_RETAINED)


class TestManagerDelegation:
    def _manager_with_fake_plane(self, plane_status):
        class _FakePlane:
            def __init__(self, status):
                self._status = status
                self.released = None
                self.resumed = False

            def status(self, alias):
                return self._status

            def release(self, alias, destroy=False):
                self.released = ("release", alias, destroy)
                return {"state": "stopped" if destroy else "retained"}

            def resume_existing(self, alias):
                self.resumed = True
                return {"state": "starting"}

        plane = _FakePlane(plane_status)
        manager = CoderRuntimeManager(
            control_plane=plane,
            health_probe=_transport([NEXT_MODEL]),
        )
        return manager, plane

    def test_stop_delegates_retain(self):
        manager, plane = self._manager_with_fake_plane(
            {"state": "ready", "endpoint": ENDPOINT, "instance_id": 5}
        )
        result = manager.stop_runtime()
        assert plane.released == ("release", "defendcoder-default", False)
        assert result["state"] == "retained"

    def test_destroy_exact_delegates_with_id_match(self):
        manager, plane = self._manager_with_fake_plane(
            {"state": "retained", "endpoint": None, "instance_id": 5}
        )
        result = manager.destroy_exact(instance_id=5)
        assert plane.released == ("release", "defendcoder-default", True)

    def test_destroy_mismatch_refused(self):
        manager, plane = self._manager_with_fake_plane(
            {"state": "retained", "endpoint": None, "instance_id": 5}
        )
        with pytest.raises(ValueError):
            manager.destroy_exact(instance_id=99)
        assert plane.released is None

    def test_resume_requires_approval(self):
        manager, plane = self._manager_with_fake_plane(
            {"state": "retained", "endpoint": None, "instance_id": 5}
        )
        with pytest.raises(Exception):
            manager.resume_retained(authorize_resume=False)
        assert plane.resumed is False

    def test_resume_with_approval(self):
        manager, plane = self._manager_with_fake_plane(
            {"state": "retained", "endpoint": None, "instance_id": 5}
        )
        manager.resume_retained(authorize_resume=True)
        assert plane.resumed is True

    def test_routing_ready_requires_health(self):
        # Control plane reports ready + endpoint, but health probe fails.
        manager, _ = self._manager_with_fake_plane(
            {"state": "ready", "endpoint": ENDPOINT, "instance_id": 5}
        )
        manager._health_probe = lambda ep, mdl: False
        assert manager.runtime_ready() is False
        assert manager.get_runtime_endpoint() is None


class TestNoSyntheticTransitions:
    def test_absent_stop_remains_absent(self):
        m = CoderRuntimeManager()
        assert m.stop_runtime()["state"] == ABSENT

    def test_unknown_never_ready(self):
        m = CoderRuntimeManager(
            snapshot=RuntimeSnapshot(
                state="UNKNOWN", instance_id=None, model=NEXT_MODEL,
                endpoint=ENDPOINT, gpu=None, hourly_cost=None, detail=None,
            )
        )
        assert m.runtime_ready() is False
