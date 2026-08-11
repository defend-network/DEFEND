from defend_control.ui import ControlCenterUI, SetupDialog
from types import SimpleNamespace


class Variable:
    def __init__(self, value):
        self.value = value
        self.set_values = []

    def get(self):
        return self.value

    def set(self, value):
        self.value = value
        self.set_values.append(value)


class QueueingController:
    def __init__(self):
        self.started = []

    def start(self, mode):
        self.started.append(mode)
        return "queued-state"


def test_start_clears_explicit_mode_immediately_after_successful_queue():
    ui = object.__new__(ControlCenterUI)
    ui._mode = Variable("ollama")
    ui._controller = QueueingController()
    rendered = []
    ui._render = rendered.append
    ui._show_error = lambda error: (_ for _ in ()).throw(error)

    ui._start()

    assert ui._controller.started == ["ollama"]
    assert ui._mode.get() == ""
    assert rendered == ["queued-state"]


class DeferredFuture:
    def __init__(self, value=None):
        self.complete = False
        self.value = value

    def done(self):
        return self.complete

    def result(self):
        assert self.complete
        return self.value


class Root:
    def __init__(self):
        self.callbacks = []

    def after(self, _milliseconds, callback):
        self.callbacks.append(callback)


class StoppedController:
    def __init__(self):
        self.shutdown_calls = 0

    def poll_state(self):
        return SimpleNamespace(services_running=False)

    def shutdown(self):
        self.shutdown_calls += 1


def test_close_callback_queues_cleanup_and_destroys_only_after_future_finishes():
    ui = object.__new__(ControlCenterUI)
    ui.root = Root()
    ui._controller = StoppedController()
    ui._closing_after_stop = False
    ui._exit_future = None
    future = DeferredFuture()
    submitted = []
    destroyed = []
    ui._submit_exit_cleanup = lambda: submitted.append(True) or future
    ui._destroy_window = lambda: destroyed.append(True)
    ui._show_error = lambda error: (_ for _ in ()).throw(error)

    ui._on_close()

    assert submitted == [True]
    assert destroyed == []
    assert ui._controller.shutdown_calls == 0
    assert len(ui.root.callbacks) == 1

    ui.root.callbacks.pop(0)()
    assert destroyed == []
    future.complete = True
    ui.root.callbacks.pop(0)()

    assert ui._controller.shutdown_calls == 1
    assert destroyed == [True]


def test_setup_dialog_waits_for_activation_cleanup_before_destroying():
    dialog = object.__new__(SetupDialog)
    prepared = object()
    prepare_future = DeferredFuture(prepared)
    prepare_future.complete = True
    activation_future = DeferredFuture()
    callbacks = []
    destroyed = []
    dialog._on_saved = lambda result: activation_future
    dialog.after = lambda _milliseconds, callback: callbacks.append(callback)
    dialog.destroy = lambda: destroyed.append(True)

    dialog._finish_save(prepare_future)

    assert destroyed == []
    assert len(callbacks) == 1
    activation_future.complete = True
    callbacks.pop(0)()
    assert destroyed == [True]


def test_controller_swap_does_not_publish_candidate_when_render_fails():
    ui = object.__new__(ControlCenterUI)
    old_controller = object()
    candidate = type(
        "Candidate",
        (),
        {"poll_state": lambda self: "candidate-state"},
    )()
    ui._controller = old_controller
    ui._public_origin = "https://old.example.test"
    ui._render = lambda _state: (_ for _ in ()).throw(
        RuntimeError("synthetic render failure")
    )

    try:
        ui.set_controller(candidate, public_origin="https://new.example.test")
    except RuntimeError:
        pass

    assert ui._controller is old_controller
    assert ui._public_origin == "https://old.example.test"
