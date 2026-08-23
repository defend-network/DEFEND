"""DEFENDcoder concrete runtime manager: fail-closed NEXT authority."""

from __future__ import annotations

import pytest

from defend_coder.runtime_manager import (
    NEXT_STATE_READY,
    NEXT_STATE_STOPPED_RETAINED,
    CoderRuntimeManager,
    RuntimeSnapshot,
)

NEXT_MODEL = "Qwen/Qwen3-Coder-Next"
ENDPOINT = "http://127.0.0.1:8403/v1"


class TestCoderRuntimeManager:
    def test_absent_is_not_routable_and_not_ready(self):
        manager = CoderRuntimeManager()
        assert manager.next_availability() is False
        assert manager.is_next_ready() is False
        assert manager.get_runtime_endpoint() is None

    def test_stopped_retained_is_routable_but_not_ready(self):
        manager = CoderRuntimeManager(
            snapshot=RuntimeSnapshot(
                state=NEXT_STATE_STOPPED_RETAINED,
                instance_id="i-1",
                model=NEXT_MODEL,
                endpoint=None,
                gpu="H100",
                hourly_cost="4.04",
                detail="retained",
            )
        )
        assert manager.next_availability() is True  # routable (resumable)
        assert manager.is_next_ready() is False  # not READY
        assert manager.get_runtime_endpoint() is None

    def test_ready_requires_endpoint_and_instance(self):
        manager = CoderRuntimeManager(
            snapshot=RuntimeSnapshot(
                state=NEXT_STATE_READY,
                instance_id="i-1",
                model=NEXT_MODEL,
                endpoint=ENDPOINT,
                gpu="H100",
                hourly_cost="4.04",
                detail=None,
            )
        )
        assert manager.is_next_ready() is True
        assert manager.get_runtime_endpoint() == ENDPOINT

    def test_ready_without_endpoint_is_not_ready(self):
        manager = CoderRuntimeManager(
            snapshot=RuntimeSnapshot(
                state=NEXT_STATE_READY,
                instance_id="i-1",
                model=NEXT_MODEL,
                endpoint=None,
                gpu="H100",
                hourly_cost="4.04",
                detail=None,
            )
        )
        assert manager.is_next_ready() is False

    def test_start_runtime_fails_closed(self):
        manager = CoderRuntimeManager()
        with pytest.raises(Exception):
            manager.start_runtime("defendcoder", authorize_resume=True)

    def test_stop_runtime_is_retain_not_destroy(self):
        manager = CoderRuntimeManager()
        result = manager.stop_runtime("defendcoder")
        assert result.get("retained") is True
