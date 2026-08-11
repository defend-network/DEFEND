from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

import pytest

from tools.defend_control_center import _Runtime, _RuntimeCoordinator
from defend_control.settings import ControlSettings


class CompletedFuture:
    def __init__(self, function, args):
        self.error = None
        self.value = None
        try:
            self.value = function(*args)
        except BaseException as error:
            self.error = error

    def done(self):
        return True

    def result(self, timeout=None):
        if self.error is not None:
            raise self.error
        return self.value


class ManualExecutor:
    def __init__(self):
        self.submitted = []

    def submit(self, function, *args):
        self.submitted.append((function, args))
        return type("Pending", (), {"done": lambda self: False})()


class RejectingExecutor:
    def submit(self, function, *args):
        raise RuntimeError("synthetic private maintenance detail")


class Controller:
    def __init__(self, *, run=True, reject_names=()):
        self.run = run
        self.reject_names = set(reject_names)
        self.submitted = []
        self.shutdown_calls = 0

    def submit_work(self, function, *args):
        self.submitted.append((function, args))
        if function.__name__ in self.reject_names:
            raise RuntimeError("synthetic private executor detail")
        if self.run:
            return CompletedFuture(function, args)
        return type("Pending", (), {"done": lambda self: False})()

    def shutdown(self):
        self.shutdown_calls += 1


class Supervisor:
    def __init__(self, *, fail_close=False):
        self.fail_close = fail_close
        self.close_calls = 0

    def close(self):
        self.close_calls += 1
        if self.fail_close:
            raise RuntimeError("synthetic private close detail")


class Store:
    def __init__(self, value):
        self.value = value
        self.fail_saves = 0
        self.save_calls = []

    def load(self):
        return self.value.copy() if isinstance(self.value, dict) else self.value

    def save(self, value):
        self.save_calls.append(value)
        if self.fail_saves:
            self.fail_saves -= 1
            raise RuntimeError("synthetic private persistence detail")
        self.value = value.copy() if isinstance(value, dict) else value


def settings(tmp_path: Path, *, model="old-model") -> ControlSettings:
    return ControlSettings(
        repo_root=tmp_path,
        data_root=tmp_path / "data",
        public_web_origin="https://ai.example.test",
        cloudflared_exe=tmp_path / "cloudflared.exe",
        cloudflared_config=tmp_path / "config.yml",
        cloudflared_tunnel="defend-ai",
        adapter_repo="Defend-network/defend-qwen-32b-lora",
        local_model=model,
        vast_max_hourly=Decimal("3.00"),
    )


def candidate_raw(current: ControlSettings):
    raw = asdict(current)
    raw["local_model"] = "new-model"
    return raw


def make_coordinator(
    tmp_path,
    *,
    builder=None,
    old_close_fails=False,
    maintenance_executor=None,
):
    current = settings(tmp_path)
    old = _Runtime(Controller(), Supervisor(fail_close=old_close_fails))
    settings_store = Store(current)
    secret_store = Store({"DEFEND_OWNER_PASS": "old-value"})
    candidates = []

    def default_builder(updated, _secret_source):
        candidate = _Runtime(Controller(), Supervisor())
        candidates.append(candidate)
        return candidate

    coordinator = _RuntimeCoordinator(
        runtime=old,
        settings=current,
        settings_store=settings_store,
        secret_store=secret_store,
        build_runtime=builder or default_builder,
        maintenance_executor=maintenance_executor,
    )
    return coordinator, old, settings_store, secret_store, candidates


def test_replacement_build_failure_leaves_old_runtime_and_stores_untouched(tmp_path):
    def reject_build(_settings, _secrets):
        raise RuntimeError("synthetic private build detail")

    coordinator, old, settings_store, secret_store, _ = make_coordinator(
        tmp_path, builder=reject_build
    )

    with pytest.raises(RuntimeError, match="runtime build failed"):
        coordinator.prepare(candidate_raw(coordinator.settings), {"NEW": "value"})

    assert coordinator.runtime is old
    assert settings_store.value.local_model == "old-model"
    assert secret_store.value == {"DEFEND_OWNER_PASS": "old-value"}
    assert old.supervisor.close_calls == 0


def test_candidate_executor_rejection_before_persistence_disposes_candidate(tmp_path):
    candidates = []

    def build_rejecting_candidate(_settings, _secrets):
        candidate = _Runtime(
            Controller(reject_names={"_candidate_runtime_probe"}),
            Supervisor(),
        )
        candidates.append(candidate)
        return candidate

    coordinator, old, settings_store, secret_store, _ = make_coordinator(
        tmp_path, builder=build_rejecting_candidate
    )

    with pytest.raises(RuntimeError, match="runtime validation failed"):
        coordinator.prepare(candidate_raw(coordinator.settings), {"NEW": "value"})

    assert coordinator.runtime is old
    assert settings_store.value.local_model == "old-model"
    assert secret_store.value == {"DEFEND_OWNER_PASS": "old-value"}
    assert candidates[0].supervisor.close_calls == 1
    assert candidates[0].controller.shutdown_calls == 1


def test_secret_persistence_failure_closes_candidate_and_keeps_old_state(tmp_path):
    coordinator, old, settings_store, secret_store, candidates = make_coordinator(
        tmp_path
    )
    secret_store.fail_saves = 1

    with pytest.raises(RuntimeError, match="setup persistence failed"):
        coordinator.prepare(candidate_raw(coordinator.settings), {"NEW": "value"})

    assert coordinator.runtime is old
    assert settings_store.value.local_model == "old-model"
    assert secret_store.value == {"DEFEND_OWNER_PASS": "old-value"}
    assert candidates[0].supervisor.close_calls == 1
    assert candidates[0].controller.shutdown_calls == 1
    assert old.supervisor.close_calls == 0


def test_settings_persistence_failure_rolls_back_secret_and_closes_candidate(tmp_path):
    coordinator, old, settings_store, secret_store, candidates = make_coordinator(
        tmp_path
    )
    settings_store.fail_saves = 1

    with pytest.raises(RuntimeError, match="setup persistence failed"):
        coordinator.prepare(candidate_raw(coordinator.settings), {"NEW": "value"})

    assert coordinator.runtime is old
    assert settings_store.value.local_model == "old-model"
    assert secret_store.value == {"DEFEND_OWNER_PASS": "old-value"}
    assert len(secret_store.save_calls) == 2
    assert candidates[0].supervisor.close_calls == 1
    assert old.supervisor.close_calls == 0


def test_swap_failure_rolls_back_stores_and_closes_candidate(tmp_path):
    coordinator, old, settings_store, secret_store, candidates = make_coordinator(
        tmp_path
    )
    prepared = coordinator.prepare(
        candidate_raw(coordinator.settings), {"NEW": "value"}
    )

    completion = coordinator.activate(
        prepared,
        lambda _controller, _origin: (_ for _ in ()).throw(
            RuntimeError("synthetic private swap detail")
        ),
    )
    with pytest.raises(RuntimeError, match="runtime swap failed"):
        completion.result()

    assert coordinator.runtime is old
    assert settings_store.value.local_model == "old-model"
    assert secret_store.value == {"DEFEND_OWNER_PASS": "old-value"}
    assert candidates[0].supervisor.close_calls == 1
    assert candidates[0].controller.shutdown_calls == 1
    assert old.supervisor.close_calls == 0


def test_old_close_failure_keeps_new_runtime_and_config_active_for_retry(tmp_path):
    coordinator, old, settings_store, secret_store, candidates = make_coordinator(
        tmp_path, old_close_fails=True
    )
    prepared = coordinator.prepare(
        candidate_raw(coordinator.settings), {"NEW": "value"}
    )
    applied = []

    completion = coordinator.activate(
        prepared,
        lambda controller, origin: applied.append((controller, origin)),
    )
    with pytest.raises(RuntimeError, match="retired runtime cleanup failed"):
        completion.result()

    assert coordinator.runtime is candidates[0]
    assert coordinator.settings.local_model == "new-model"
    assert settings_store.value.local_model == "new-model"
    assert secret_store.value["NEW"] == "value"
    assert old.supervisor.close_calls == 1
    assert old.controller.shutdown_calls == 0
    assert candidates[0].supervisor.close_calls == 0
    assert applied == [(candidates[0].controller, "https://ai.example.test")]


def test_activation_retirement_never_uses_candidate_controller_executor(tmp_path):
    candidates = []

    def build_candidate(_settings, _secrets):
        candidate = _Runtime(
            Controller(reject_names={"_retire_runtime"}),
            Supervisor(),
        )
        candidates.append(candidate)
        return candidate

    coordinator, old, settings_store, _secret_store, _ = make_coordinator(
        tmp_path, builder=build_candidate
    )
    prepared = coordinator.prepare(candidate_raw(coordinator.settings), {})

    completion = coordinator.activate(prepared, lambda _controller, _origin: None)
    completion.result()

    assert coordinator.runtime is candidates[0]
    assert settings_store.value.local_model == "new-model"
    assert old.supervisor.close_calls == 1
    assert candidates[0].controller.submit_work(str.upper, "usable").result() == (
        "USABLE"
    )


def test_activation_handoff_rejection_rolls_back_before_ui_publication(tmp_path):
    coordinator, old, settings_store, secret_store, candidates = make_coordinator(
        tmp_path, maintenance_executor=RejectingExecutor()
    )
    prepared = coordinator.prepare(
        candidate_raw(coordinator.settings), {"NEW": "value"}
    )
    applied = []

    with pytest.raises(RuntimeError, match="runtime swap failed"):
        coordinator.activate(
            prepared,
            lambda controller, origin: applied.append((controller, origin)),
        )

    assert applied == []
    assert coordinator.runtime is old
    assert settings_store.value.local_model == "old-model"
    assert secret_store.value == {"DEFEND_OWNER_PASS": "old-value"}
    assert candidates[0].supervisor.close_calls == 1
    assert candidates[0].controller.shutdown_calls == 1


def test_exit_cleanup_is_submitted_without_closing_on_caller_thread(tmp_path):
    maintenance = ManualExecutor()
    coordinator, _old, _settings_store, _secret_store, _ = make_coordinator(
        tmp_path, maintenance_executor=maintenance
    )

    coordinator.submit_exit_cleanup()

    assert coordinator.runtime.supervisor.close_calls == 0
    function, args = maintenance.submitted[0]
    function(*args)
    assert coordinator.runtime.supervisor.close_calls == 1


def test_prepared_replacement_representation_omits_rollback_secrets(tmp_path):
    coordinator, _old, _settings_store, _secret_store, _ = make_coordinator(
        tmp_path
    )

    prepared = coordinator.prepare(
        candidate_raw(coordinator.settings), {"NEW": "value"}
    )

    assert "old-value" not in repr(prepared)
