"""V1.1R5 factory / routing / idle fail-closed tests (deterministic)."""

from __future__ import annotations

import pytest

from defend_coder.runtime.factory import build_runtime_manager
from defend_coder.runtime.no_provider import NoProviderBackend, ProviderNotConfigured
from defend_coder.runtime.models import LocalFakeCoderBackend
from defend_coder.runtime_manager import (
    ABSENT,
    READY,
    STARTING,
    STOPPED_RETAINED,
    CoderRuntimeManager,
    RuntimeSnapshot,
)

NEXT_MODEL = "Qwen/Qwen3-Coder-Next"
ENDPOINT = "http://127.0.0.1:8403/v1"


def _healthy():
    return lambda ep, mdl: ep == ENDPOINT and mdl == NEXT_MODEL


class TestFactoryFailClosed:
    def test_production_factory_never_auto_uses_local_fake_backend(self):
        manager = build_runtime_manager(secret_source={})
        # The control plane's backend must be NoProviderBackend, NOT the fake.
        plane = manager._control_plane
        assert isinstance(plane.backend, NoProviderBackend)

    def test_no_vast_key_is_unconfigured_and_not_ready(self):
        manager = build_runtime_manager(secret_source={})
        assert manager.runtime_status()["state"] in (ABSENT, "ABSENT")
        assert manager.runtime_ready() is False
        assert manager.routing_available() is False

    def test_no_vast_key_cannot_provision(self):
        manager = build_runtime_manager(secret_source={})
        with pytest.raises(ProviderNotConfigured):
            manager._control_plane.backend.start(
                object(), local_port=8003, session_budget_usd=0
            )

    def test_local_fake_backend_is_injectable_only(self):
        # Tests may inject the fake explicitly via backend=.
        manager = build_runtime_manager(secret_source={}, backend=LocalFakeCoderBackend())
        assert isinstance(manager._control_plane.backend, LocalFakeCoderBackend)


class TestRoutingAvailability:
    def test_next_availability_requires_runtime_ready(self):
        m = CoderRuntimeManager(
            snapshot=RuntimeSnapshot(
                state=READY, instance_id="i", model=NEXT_MODEL,
                endpoint=ENDPOINT, gpu="H100", hourly_cost="4", detail=None,
            ),
            health_probe=_healthy(),
        )
        assert m.next_availability() is True
        assert m.routing_available() is True

    def test_next_availability_false_for_starting(self):
        m = CoderRuntimeManager(
            snapshot=RuntimeSnapshot(
                state=STARTING, instance_id="i", model=NEXT_MODEL,
                endpoint=ENDPOINT, gpu=None, hourly_cost=None, detail=None,
            )
        )
        assert m.next_availability() is False

    def test_next_availability_false_for_stopped_retained(self):
        m = CoderRuntimeManager(
            snapshot=RuntimeSnapshot(
                state=STOPPED_RETAINED, instance_id="i", model=NEXT_MODEL,
                endpoint=None, gpu="H100", hourly_cost="4", detail=None,
            )
        )
        assert m.next_availability() is False
        assert m.runtime_resumable() is True

    def test_available_next_always_has_ready_endpoint(self):
        m = CoderRuntimeManager(
            snapshot=RuntimeSnapshot(
                state=READY, instance_id="i", model=NEXT_MODEL,
                endpoint=ENDPOINT, gpu="H100", hourly_cost="4", detail=None,
            ),
            health_probe=_healthy(),
        )
        assert m.next_availability() is True
        assert m.get_runtime_endpoint() == ENDPOINT


class TestIdle:
    def test_maybe_reap_idle_delegates_to_control_plane(self):
        class _FakePlane:
            def __init__(self):
                self.reaped = 0

            def status(self, alias):
                return {"state": "ready", "endpoint": ENDPOINT, "instance_id": 5}

            def maybe_reap_idle(self, alias):
                self.reaped += 1

        plane = _FakePlane()
        m = CoderRuntimeManager(control_plane=plane, health_probe=_healthy())
        m.maybe_reap_idle()
        assert plane.reaped == 1
