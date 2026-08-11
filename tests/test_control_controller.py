from dataclasses import FrozenInstanceError

import pytest

from defend_control.controller import (
    ConfirmationRequired,
    ControlController,
    UIState,
)
from defend_control.orchestrator import ComponentSnapshot, StackSnapshot
from defend_control.processes import LogEntry


class RecordingExecutor:
    def __init__(self):
        self.submitted = []

    def submit(self, function, *args):
        self.submitted.append((function.__name__, *args))
        return type("Future", (), {})()


class CancellableFuture:
    def __init__(self):
        self.cancel_calls = 0

    def cancel(self):
        self.cancel_calls += 1
        return True


class RunningFuture(CancellableFuture):
    def cancel(self):
        self.cancel_calls += 1
        return False


class PendingExecutor(RecordingExecutor):
    def __init__(self):
        super().__init__()
        self.futures = []

    def submit(self, function, *args):
        self.submitted.append((function.__name__, *args))
        future = CancellableFuture()
        self.futures.append(future)
        return future


class BoundaryExecutor(RecordingExecutor):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.futures = []

    def submit(self, function, *args):
        self.submitted.append((function.__name__, *args))
        self.calls.append((function, args))
        future = RunningFuture()
        self.futures.append(future)
        return future


class InlineExecutor(RecordingExecutor):
    def submit(self, function, *args):
        self.submitted.append((function.__name__, *args))
        return type("Future", (), {"result": lambda self: function(*args)})()


class FakeOrchestrator:
    def __init__(self, *, instance_id=None, logs=()):
        self.instance_id = instance_id
        self.logs = logs
        self.cancelled = 0
        self.destroyed = []
        self.start_cancellations = []

    def start(self, mode, cancellation=None):
        self.start_cancellations.append(cancellation)
        return mode

    def cancel_start(self):
        self.cancelled += 1

    def stop_local(self):
        return None

    def restart(self):
        return None

    def stop_and_destroy_vast(self, instance_id):
        self.destroyed.append(instance_id)

    def snapshot(self):
        return StackSnapshot(
            state="ready" if self.instance_id else "stopped",
            mode="vast" if self.instance_id else None,
            components=tuple(
                ComponentSnapshot(name, "ready")
                for name in ("model", "ssh tunnel", "api", "frontend", "cloudflare")
            ),
            error=None,
            vast_gpu="H100 SXM" if self.instance_id else None,
            vast_instance_id=self.instance_id,
            vast_hourly_price="2.1250" if self.instance_id else None,
            logs=self.logs,
        )


def test_controller_never_blocks_ui_thread():
    executor = RecordingExecutor()
    controller = ControlController(FakeOrchestrator(), executor=executor)

    state = controller.start("ollama")

    assert executor.submitted == [("start", "ollama")]
    assert isinstance(state, UIState)


def test_controller_requires_explicit_mode_for_each_start():
    executor = RecordingExecutor()
    controller = ControlController(FakeOrchestrator(), executor=executor)

    with pytest.raises(ValueError, match="explicit"):
        controller.start(None)  # type: ignore[arg-type]

    assert executor.submitted == []


def test_stop_signals_cancellation_before_queueing_local_cleanup():
    orchestrator = FakeOrchestrator()
    executor = RecordingExecutor()
    controller = ControlController(orchestrator, executor=executor)

    controller.stop_local()

    assert orchestrator.cancelled == 1
    assert executor.submitted == [("stop_local",)]


def test_stop_cancels_start_that_is_queued_but_not_running():
    orchestrator = FakeOrchestrator()
    executor = PendingExecutor()
    controller = ControlController(orchestrator, executor=executor)

    controller.start("ollama")
    controller.stop_local()

    assert executor.futures[0].cancel_calls == 1
    assert orchestrator.cancelled == 0
    assert executor.submitted == [("start", "ollama"), ("stop_local",)]


def test_stop_token_survives_future_running_before_orchestrator_entry():
    orchestrator = FakeOrchestrator()
    executor = BoundaryExecutor()
    controller = ControlController(orchestrator, executor=executor)

    controller.start("ollama")
    controller.stop_local()
    start_function, start_args = executor.calls[0]
    start_function(*start_args)

    assert executor.futures[0].cancel_calls == 1
    assert len(orchestrator.start_cancellations) == 1
    assert orchestrator.start_cancellations[0].is_cancelled()


def test_ui_state_services_running_when_failed_snapshot_retains_ownership():
    orchestrator = FakeOrchestrator()
    controller = ControlController(orchestrator, executor=RecordingExecutor())
    snapshot = orchestrator.snapshot()
    orchestrator.snapshot = lambda: type(snapshot)(
        state="failed",
        mode="ollama",
        components=(ComponentSnapshot("api", "cleanup pending"),),
        error="startup cancelled; cleanup pending",
        logs=(),
        owned_services=("api",),
    )

    assert controller.poll_state().services_running


def test_setup_work_uses_the_same_nonblocking_executor():
    executor = RecordingExecutor()
    controller = ControlController(FakeOrchestrator(), executor=executor)

    controller.submit_work(str.upper, "setup")

    assert executor.submitted == [("upper", "setup")]


def test_destroy_requires_exact_instance_confirmation():
    controller = ControlController(
        FakeOrchestrator(instance_id=4815), executor=InlineExecutor()
    )

    for confirmation in (None, 4814, "4815"):
        with pytest.raises(ConfirmationRequired, match="4815"):
            controller.stop_and_destroy_vast(confirmed_instance_id=confirmation)


def test_exact_destroy_confirmation_is_submitted_without_provider_logic():
    executor = RecordingExecutor()
    controller = ControlController(
        FakeOrchestrator(instance_id=4815), executor=executor
    )

    controller.stop_and_destroy_vast(confirmed_instance_id=4815)

    assert executor.submitted == [("stop_and_destroy_vast", 4815)]


def test_ui_state_is_immutable_bounded_and_has_exact_component_rows():
    logs = tuple(LogEntry("api", f"line {index}") for index in range(700))
    controller = ControlController(
        FakeOrchestrator(instance_id=4815, logs=logs),
        executor=RecordingExecutor(),
        max_ui_log_entries=500,
        max_ui_log_chars=40,
    )

    state = controller.poll_state()

    assert tuple(component.name for component in state.components) == (
        "model",
        "ssh tunnel",
        "api",
        "frontend",
        "cloudflare",
    )
    assert len(state.logs) == 500
    assert state.logs[0].text == "line 200"
    assert state.vast_gpu == "H100 SXM"
    assert state.vast_instance_id == 4815
    assert state.vast_hourly_price == "2.1250"
    with pytest.raises(FrozenInstanceError):
        state.state = "failed"  # type: ignore[misc]


def test_ui_log_lines_are_rebounded_and_secret_shapes_are_redacted():
    logs = (
        LogEntry("api", "password=synthetic-visible-value " + "x" * 100),
    )
    controller = ControlController(
        FakeOrchestrator(logs=logs),
        executor=RecordingExecutor(),
        max_ui_log_entries=10,
        max_ui_log_chars=40,
    )

    state = controller.poll_state()

    assert "synthetic-visible-value" not in state.logs[0].text
    assert len(state.logs[0].text) <= 40
