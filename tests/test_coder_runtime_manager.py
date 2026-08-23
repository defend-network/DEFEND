"""DEFENDcoder concrete runtime manager: fail-closed NEXT authority + states."""

from __future__ import annotations

import pytest

from defend_coder.runtime_manager import (
    ABSENT,
    FAILED,
    READY,
    STARTING,
    STOPPED_RETAINED,
    UNKNOWN,
    CoderRuntimeManager,
    RuntimeSnapshot,
)

NEXT_MODEL = "Qwen/Qwen3-Coder-Next"
ENDPOINT = "http://127.0.0.1:8403/v1"


def _ready_snapshot(*, endpoint: str | None = ENDPOINT, model: str | None = NEXT_MODEL):
    return RuntimeSnapshot(
        state=READY,
        instance_id="i-1",
        model=model,
        endpoint=endpoint,
        gpu="H100",
        hourly_cost="4.04",
        detail=None,
    )


class TestCoderRuntimeManager:
    def test_absent_is_not_selectable_resumable_or_ready(self):
        m = CoderRuntimeManager()
        assert m.model_selectable() is False
        assert m.runtime_resumable() is False
        assert m.runtime_ready() is False
        assert m.get_runtime_endpoint() is None

    def test_stopped_retained_is_selectable_and_resumable_but_not_ready(self):
        m = CoderRuntimeManager(
            snapshot=RuntimeSnapshot(
                state=STOPPED_RETAINED,
                instance_id="i-1",
                model=NEXT_MODEL,
                endpoint=None,
                gpu="H100",
                hourly_cost="4.04",
                detail="retained",
            )
        )
        assert m.model_selectable() is True
        assert m.runtime_resumable() is True
        assert m.runtime_ready() is False

    def test_starting_is_selectable_but_not_resumable_or_ready(self):
        m = CoderRuntimeManager(
            snapshot=RuntimeSnapshot(
                state=STARTING, instance_id="i-1", model=NEXT_MODEL,
                endpoint=None, gpu=None, hourly_cost=None, detail=None,
            )
        )
        assert m.model_selectable() is True
        assert m.runtime_resumable() is False
        assert m.runtime_ready() is False

    def test_unknown_is_not_selectable_resumable_or_ready(self):
        m = CoderRuntimeManager(
            snapshot=RuntimeSnapshot(
                state=UNKNOWN, instance_id=None, model=NEXT_MODEL,
                endpoint=None, gpu=None, hourly_cost=None, detail=None,
            )
        )
        assert m.model_selectable() is False
        assert m.runtime_resumable() is False
        assert m.runtime_ready() is False

    def test_ready_requires_health_probe(self):
        # READY state + endpoint + instance, but no successful health probe.
        m = CoderRuntimeManager(snapshot=_ready_snapshot())
        assert m.runtime_ready() is False
        assert m.get_runtime_endpoint() is None

    def test_ready_with_healthy_probe(self):
        m = CoderRuntimeManager(
            snapshot=_ready_snapshot(),
            health_probe=lambda ep, mdl: ep == ENDPOINT and mdl == NEXT_MODEL,
        )
        assert m.runtime_ready() is True
        assert m.get_runtime_endpoint() == ENDPOINT

    def test_ready_wrong_model_not_ready(self):
        m = CoderRuntimeManager(
            snapshot=_ready_snapshot(model="other-model"),
            health_probe=lambda ep, mdl: False,
        )
        assert m.runtime_ready() is False

    def test_start_runtime_fails_closed_without_authorization(self):
        m = CoderRuntimeManager(snapshot=RuntimeSnapshot(state=STOPPED_RETAINED, instance_id="i-1", model=NEXT_MODEL, endpoint=None, gpu=None, hourly_cost=None, detail=None))
        with pytest.raises(Exception):
            m.start_runtime("defendcoder", authorize_resume=False)

    def test_absent_stop_remains_absent(self):
        m = CoderRuntimeManager()
        result = m.stop_runtime("defendcoder")
        assert result["state"] == ABSENT
        assert result["retained"] is False

    def test_ready_stop_is_retain_not_destroy(self):
        m = CoderRuntimeManager(snapshot=_ready_snapshot(), health_probe=lambda e, m: True)
        result = m.stop_runtime("defendcoder")
        assert result["state"] == STOPPED_RETAINED
        assert result["retained"] is True
