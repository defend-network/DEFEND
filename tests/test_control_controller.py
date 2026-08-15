from dataclasses import FrozenInstanceError
from decimal import Decimal
import threading

import pytest

from defend_control.controller import (
    ConfirmationRequired,
    ControlController,
    UIState,
)
from defend_control.orchestrator import ComponentSnapshot, StackSnapshot
from defend_control.processes import LogEntry
from defend_control.types import VastInstance, VastOffer
from defend_control.ui import ControlCenterUI
import defend_control.ui as ui_module


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


class CompletedFuture:
    def __init__(self, function, args):
        self.error = None
        try:
            self.value = function(*args)
        except BaseException as error:
            self.error = error

    def done(self):
        return True

    def cancel(self):
        return False

    def result(self):
        if self.error is not None:
            raise self.error
        return self.value


class SubmitBarrierExecutor(RecordingExecutor):
    def __init__(self):
        super().__init__()
        self.start_submit_entered = threading.Event()
        self.release_start_submit = threading.Event()

    def submit(self, function, *args):
        self.submitted.append((function.__name__, *args))
        if function.__name__ == "start":
            self.start_submit_entered.set()
            assert self.release_start_submit.wait(2)
        return CompletedFuture(function, args)


class RejectFirstExecutor(RecordingExecutor):
    def submit(self, function, *args):
        self.submitted.append((function.__name__, *args))
        if len(self.submitted) == 1:
            raise RuntimeError("synthetic submit detail")
        return CompletedFuture(function, args)


class FakeOrchestrator:
    def __init__(self, *, instance_id=None, logs=()):
        self.instance_id = instance_id
        self.logs = logs
        self.cancelled = 0
        self.destroyed = []
        self.start_cancellations = []
        self.launches = []
        self.offer_confirmations = []
        self.fingerprint_confirmations = []
        self.instance_selections = []
        self.restart_confirmations = []
        self.replacement_confirmations = []
        self.declined_instance_actions = 0

    def start(self, mode, cancellation=None):
        self.start_cancellations.append(cancellation)
        if cancellation is None or not cancellation.is_cancelled():
            self.launches.append(mode)
        return mode

    def cancel_start(self):
        self.cancelled += 1

    def stop_local(self):
        return None

    def restart(self):
        return None

    def stop_and_destroy_vast(self, instance_id):
        self.destroyed.append(instance_id)

    def confirm_offer(self, offer_id, hourly_price):
        self.offer_confirmations.append((offer_id, hourly_price))

    def confirm_fingerprint(self, instance_id, fingerprint):
        self.fingerprint_confirmations.append((instance_id, fingerprint))

    def select_vast_instance(self, instance_id):
        self.instance_selections.append(instance_id)

    def confirm_instance_restart(self, instance_id, hourly_price):
        self.restart_confirmations.append((instance_id, hourly_price))

    def confirm_instance_replacement(self, instance_id, offer_id, hourly_price):
        self.replacement_confirmations.append(
            (instance_id, offer_id, hourly_price)
        )

    def decline_instance_action(self):
        self.declined_instance_actions += 1

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


def test_stop_sees_start_token_before_executor_submit_returns():
    orchestrator = FakeOrchestrator()
    executor = SubmitBarrierExecutor()
    controller = ControlController(orchestrator, executor=executor)
    errors = []

    def run_start():
        try:
            controller.start("ollama")
        except BaseException as error:
            errors.append(error)

    worker = threading.Thread(target=run_start)

    worker.start()
    assert executor.start_submit_entered.wait(1)
    controller.stop_local()
    executor.release_start_submit.set()
    worker.join(2)

    assert not worker.is_alive()
    assert errors == []
    assert len(orchestrator.start_cancellations) == 1
    assert orchestrator.start_cancellations[0].is_cancelled()
    assert orchestrator.launches == []


def test_failed_start_submission_does_not_leave_stale_cancellation_request():
    orchestrator = FakeOrchestrator()
    executor = RejectFirstExecutor()
    controller = ControlController(orchestrator, executor=executor)

    with pytest.raises(RuntimeError, match="synthetic submit detail"):
        controller.start("ollama")
    controller.stop_local()

    assert orchestrator.cancelled == 1
    assert executor.submitted == [("start", "ollama"), ("stop_local",)]


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


def test_price_confirmation_and_resume_stays_on_single_worker():
    orchestrator = FakeOrchestrator()
    executor = RecordingExecutor()
    controller = ControlController(orchestrator, executor=executor)

    controller.confirm_vast_offer(101, "1.75")

    assert executor.submitted == [("confirm_offer_and_start", 101, "1.75")]


def test_fingerprint_confirmation_and_resume_stays_on_single_worker():
    orchestrator = FakeOrchestrator(instance_id=4815)
    executor = RecordingExecutor()
    controller = ControlController(orchestrator, executor=executor)

    controller.confirm_vast_fingerprint(4815, "SHA256:synthetic")

    assert executor.submitted == [
        ("confirm_fingerprint_and_start", 4815, "SHA256:synthetic")
    ]


def test_instance_selection_and_restart_resume_stay_on_single_worker():
    orchestrator = FakeOrchestrator(instance_id=4815)
    executor = RecordingExecutor()
    controller = ControlController(orchestrator, executor=executor)

    controller.select_vast_instance(4815)
    controller.confirm_vast_restart(4815, "1.75")

    assert executor.submitted == [
        ("select_vast_instance_and_start", 4815),
        ("confirm_instance_restart_and_start", 4815, "1.75"),
    ]


def test_replacement_confirmation_resumes_on_single_worker():
    orchestrator = FakeOrchestrator(instance_id=4815)
    executor = RecordingExecutor()
    controller = ControlController(orchestrator, executor=executor)

    controller.confirm_vast_replacement(4815, 901, "1.25")

    assert executor.submitted == [
        ("confirm_instance_replacement_and_start", 4815, 901, "1.25")
    ]


def test_declining_instance_action_is_queued_without_starting():
    orchestrator = FakeOrchestrator(instance_id=4815)
    executor = RecordingExecutor()
    controller = ControlController(orchestrator, executor=executor)

    controller.decline_vast_instance_action()

    assert executor.submitted == [("decline_instance_action",)]


class ConfirmationController:
    def __init__(self):
        self.offer_confirmations = []
        self.fingerprint_confirmations = []
        self.instance_selections = []
        self.restart_confirmations = []
        self.replacement_confirmations = []
        self.declined_instance_actions = 0

    def confirm_vast_offer(self, offer_id, price):
        self.offer_confirmations.append((offer_id, price))
        return "offer-queued"

    def confirm_vast_fingerprint(self, instance_id, fingerprint):
        self.fingerprint_confirmations.append((instance_id, fingerprint))
        return "fingerprint-queued"

    def select_vast_instance(self, instance_id):
        self.instance_selections.append(instance_id)
        return "selection-queued"

    def confirm_vast_restart(self, instance_id, price):
        self.restart_confirmations.append((instance_id, price))
        return "restart-queued"

    def confirm_vast_replacement(self, instance_id, offer_id, price):
        self.replacement_confirmations.append((instance_id, offer_id, price))
        return "replacement-queued"

    def decline_vast_instance_action(self):
        self.declined_instance_actions += 1
        return "decline-queued"


def confirmation_state(kind):
    return UIState(
        state="provisioning",
        selected_mode="vast",
        components=(),
        logs=(),
        message=None,
        vast_gpu="A100 SXM4",
        vast_instance_id=4815 if kind == "fingerprint" else None,
        vast_hourly_price="1.75",
        vast_offer_id=101,
        vast_gpu_ram_mb=81920,
        vast_reliability="0.987",
        vast_storage_cost_per_gb_month="0.15",
        vast_storage_total_hourly="0.032",
        vast_disk_gb=160,
        vast_actual_status="running" if kind == "fingerprint" else None,
        vast_billing_warning=(
            "Compute billing may remain active until this instance is destroyed."
            if kind == "fingerprint"
            else None
        ),
        pending_confirmation=kind,
        pending_fingerprint=(
            "SHA256:syntheticFingerprint" if kind == "fingerprint" else None
        ),
    )


def existing_instance_state(kind):
    first = VastInstance(
        47468263,
        "exited",
        None,
        None,
        "A100 SXM4",
        81920,
        Decimal("0.9629629629629629"),
    )
    second = VastInstance(
        47468264,
        "running",
        None,
        None,
        "H100 SXM",
        81920,
        Decimal("1.25"),
    )
    return UIState(
        state="provisioning",
        selected_mode="vast",
        components=(),
        logs=(),
        message=None,
        vast_gpu=first.gpu_name if kind == "instance_restart" else None,
        vast_instance_id=(
            first.instance_id if kind == "instance_restart" else None
        ),
        vast_hourly_price=(
            str(first.dph_total) if kind == "instance_restart" else None
        ),
        vast_gpu_ram_mb=(
            first.gpu_ram_mb if kind == "instance_restart" else None
        ),
        vast_actual_status=(
            first.actual_status if kind == "instance_restart" else None
        ),
        vast_billing_warning=(
            "Instance is stopped; storage billing may remain active until this "
            "instance is destroyed."
            if kind == "instance_restart"
            else None
        ),
        pending_confirmation=kind,
        vast_candidates=(first, second) if kind == "instance_selection" else (),
    )


def replacement_state():
    old = VastInstance(
        47468263,
        "scheduling",
        None,
        None,
        "A100 SXM4",
        81920,
        Decimal("0.9629629629629629"),
    )
    replacement = VastOffer(
        901,
        "H100 SXM",
        81920,
        Decimal("1.25"),
        Decimal("0.995"),
        Decimal("0.10"),
        Decimal("0.022"),
    )
    return UIState(
        state="provisioning",
        selected_mode="vast",
        components=(),
        logs=(),
        message=None,
        vast_gpu=old.gpu_name,
        vast_instance_id=old.instance_id,
        vast_hourly_price=str(old.dph_total),
        vast_gpu_ram_mb=old.gpu_ram_mb,
        vast_actual_status=old.actual_status,
        vast_billing_warning=(
            "Instance is stopped; storage billing may remain active until this "
            "instance is destroyed."
        ),
        pending_confirmation="instance_replace",
        vast_replacement_offer=replacement,
        vast_disk_gb=160,
    )


def test_ui_shows_every_defend_candidate_and_queues_selected_exact_id(monkeypatch):
    ui = object.__new__(ControlCenterUI)
    ui.root = object()
    ui._controller = ConfirmationController()
    ui._last_confirmation_signature = None
    rendered = []
    prompts = []
    ui._render = rendered.append
    monkeypatch.setattr(
        ui_module.simpledialog,
        "askinteger",
        lambda title, message, **options: prompts.append((title, message))
        or 47468264,
    )

    ui._handle_confirmation(existing_instance_state("instance_selection"))

    assert ui._controller.instance_selections == [47468264]
    assert rendered == ["selection-queued"]
    prompt = " ".join(prompts[0])
    for expected in (
        "47468263",
        "47468264",
        "A100 SXM4",
        "H100 SXM",
        "exited",
        "running",
        "$0.9629629629629629/hour",
        "$1.25/hour",
    ):
        assert expected in prompt


def test_ui_restart_warning_names_exact_instance_price_and_billing(monkeypatch):
    ui = object.__new__(ControlCenterUI)
    ui.root = object()
    ui._controller = ConfirmationController()
    ui._last_confirmation_signature = None
    rendered = []
    prompts = []
    ui._render = rendered.append
    monkeypatch.setattr(
        ui_module.messagebox,
        "askyesno",
        lambda title, message, **options: prompts.append((title, message)) or True,
    )

    ui._handle_confirmation(existing_instance_state("instance_restart"))

    assert ui._controller.restart_confirmations == [
        (47468263, "0.9629629629629629")
    ]
    assert rendered == ["restart-queued"]
    prompt = " ".join(prompts[0])
    for expected in (
        "47468263",
        "A100 SXM4",
        "81920",
        "exited",
        "$0.9629629629629629/hour",
        "storage billing",
        "resume compute billing",
    ):
        assert expected.casefold() in prompt.casefold()


def test_ui_declined_restart_queues_no_provider_mutation(monkeypatch):
    ui = object.__new__(ControlCenterUI)
    ui.root = object()
    ui._controller = ConfirmationController()
    ui._last_confirmation_signature = None
    ui._render = lambda _state: None
    monkeypatch.setattr(
        ui_module.messagebox,
        "askyesno",
        lambda *args, **options: False,
    )

    ui._handle_confirmation(existing_instance_state("instance_restart"))

    assert ui._controller.restart_confirmations == []
    assert ui._controller.declined_instance_actions == 1


def test_ui_replacement_prompt_names_both_sides_and_billing(monkeypatch):
    ui = object.__new__(ControlCenterUI)
    ui.root = object()
    ui._controller = ConfirmationController()
    ui._last_confirmation_signature = None
    rendered = []
    prompts = []
    ui._render = rendered.append
    monkeypatch.setattr(
        ui_module.messagebox,
        "askyesno",
        lambda title, message, **options: prompts.append((title, message)) or True,
    )

    ui._handle_confirmation(replacement_state())

    assert ui._controller.replacement_confirmations == [
        (47468263, 901, "1.25")
    ]
    assert rendered == ["replacement-queued"]
    prompt = " ".join(prompts[0])
    for expected in (
        "47468263",
        "scheduling",
        "Offer ID: 901",
        "H100 SXM",
        "81920",
        "0.995",
        "$1.25/hour",
        "storage billing",
        "destroyed before",
    ):
        assert expected.casefold() in prompt.casefold()


def test_ui_declined_replacement_dispatches_no_provider_mutation(monkeypatch):
    ui = object.__new__(ControlCenterUI)
    ui.root = object()
    ui._controller = ConfirmationController()
    ui._last_confirmation_signature = None
    ui._render = lambda _state: None
    monkeypatch.setattr(
        ui_module.messagebox,
        "askyesno",
        lambda *args, **options: False,
    )

    ui._handle_confirmation(replacement_state())

    assert ui._controller.replacement_confirmations == []
    assert ui._controller.declined_instance_actions == 1


def test_ui_price_prompt_is_prominent_exact_and_queues_resume(monkeypatch):
    ui = object.__new__(ControlCenterUI)
    ui.root = object()
    ui._controller = ConfirmationController()
    ui._last_confirmation_signature = None
    rendered = []
    prompts = []
    ui._render = rendered.append
    monkeypatch.setattr(
        ui_module.messagebox,
        "askyesno",
        lambda title, message, **options: prompts.append((title, message)) or True,
    )

    ui._handle_confirmation(confirmation_state("price"))

    assert ui._controller.offer_confirmations == [(101, "1.75")]
    assert rendered == ["offer-queued"]
    assert len(prompts) == 1
    prompt = " ".join(prompts[0])
    for expected in (
        "101",
        "A100 SXM4",
        "81920",
        "0.987",
        "$1.75",
        "160 GB",
        "$0.15/GB/month",
        "$0.032/hour",
        "vllm/vllm-openai:v0.10.0",
        "ssh_proxy",
        "BILLABLE",
    ):
        assert expected in prompt


def test_ui_fingerprint_prompt_warns_billing_and_queues_exact_resume(monkeypatch):
    ui = object.__new__(ControlCenterUI)
    ui.root = object()
    ui._controller = ConfirmationController()
    ui._last_confirmation_signature = None
    rendered = []
    prompts = []
    ui._render = rendered.append
    monkeypatch.setattr(
        ui_module.messagebox,
        "askyesno",
        lambda title, message, **options: prompts.append((title, message)) or True,
    )

    ui._handle_confirmation(confirmation_state("fingerprint"))

    assert ui._controller.fingerprint_confirmations == [
        (4815, "SHA256:syntheticFingerprint")
    ]
    assert rendered == ["fingerprint-queued"]
    prompt = " ".join(prompts[0])
    assert "4815" in prompt
    assert "SHA256:syntheticFingerprint" in prompt
    assert "billing may remain active" in prompt


def test_ui_declined_confirmation_is_not_reprompted_on_every_poll(monkeypatch):
    ui = object.__new__(ControlCenterUI)
    ui.root = object()
    ui._controller = ConfirmationController()
    ui._last_confirmation_signature = None
    prompts = []
    monkeypatch.setattr(
        ui_module.messagebox,
        "askyesno",
        lambda *args, **options: prompts.append(args) or False,
    )
    state = confirmation_state("price")

    ui._handle_confirmation(state)
    ui._handle_confirmation(state)

    assert len(prompts) == 1
    assert ui._controller.offer_confirmations == []


def test_price_gate_without_instance_is_not_reported_as_running_services():
    assert not confirmation_state("price").services_running
    assert confirmation_state("fingerprint").services_running


class PollRoot:
    def __init__(self):
        self.iconified = 0
        self.callbacks = []

    def iconify(self):
        self.iconified += 1

    def after(self, milliseconds, callback):
        self.callbacks.append((milliseconds, callback))


class FixedStateController:
    def __init__(self, state):
        self.state = state

    def poll_state(self):
        return self.state


def test_window_does_not_discard_active_vast_instance_after_local_stop():
    state = confirmation_state("fingerprint")
    state = UIState(
        **{
            **state.__dict__,
            "state": "stopped",
            "pending_confirmation": None,
            "pending_fingerprint": None,
        }
    )
    ui = object.__new__(ControlCenterUI)
    ui.root = PollRoot()
    ui._controller = FixedStateController(state)
    ui._closing_after_stop = True
    ui._render = lambda _state: None
    ui._handle_confirmation = lambda _state: None
    cleanup = []
    ui._begin_exit_cleanup = lambda: cleanup.append(True)

    ui._poll()

    assert cleanup == []
    assert ui.root.iconified == 1
    assert not ui._closing_after_stop
