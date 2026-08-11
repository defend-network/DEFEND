from __future__ import annotations

from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass
import threading
from typing import Any
import webbrowser

from .orchestrator import (
    ComponentSnapshot,
    StackOrchestrator,
    StartCancellation,
)
from .processes import LogEntry
from .redaction import redact_text
from .types import ModelMode, ServiceState


class ConfirmationRequired(RuntimeError):
    pass


@dataclass(frozen=True)
class UIState:
    state: ServiceState
    selected_mode: ModelMode | None
    components: tuple[ComponentSnapshot, ...]
    logs: tuple[LogEntry, ...]
    message: str | None
    vast_gpu: str | None
    vast_instance_id: int | None
    vast_hourly_price: str | None
    owned_services: tuple[str, ...] = ()

    @property
    def services_running(self) -> bool:
        if self.state not in ("stopped", "failed") or self.owned_services:
            return True
        return any(
            component.state
            not in ("stopped", "not needed", "unavailable")
            for component in self.components
        )


class _StartCommand:
    __name__ = "start"

    def __init__(
        self,
        orchestrator: StackOrchestrator,
        cancellation: StartCancellation,
    ) -> None:
        self._orchestrator = orchestrator
        self._cancellation = cancellation

    def __call__(self, mode: ModelMode):
        return self._orchestrator.start(mode, self._cancellation)


@dataclass(frozen=True)
class _StartRequest:
    future: object
    cancellation: StartCancellation


class ControlController:
    def __init__(
        self,
        orchestrator: StackOrchestrator,
        *,
        executor: Executor | Any | None = None,
        max_ui_log_entries: int = 500,
        max_ui_log_chars: int = 2_048,
    ) -> None:
        if max_ui_log_entries <= 0 or max_ui_log_chars <= 0:
            raise ValueError("UI log bounds must be positive")
        self._orchestrator = orchestrator
        self._executor = executor or ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="defend-control"
        )
        self._owns_executor = executor is None
        self._max_ui_log_entries = min(int(max_ui_log_entries), 2_000)
        self._max_ui_log_chars = min(int(max_ui_log_chars), 4_096)
        self._start_requests: list[_StartRequest] = []
        self._future_lock = threading.Lock()

    def _submit(self, function, *args: object) -> UIState:
        self.submit_work(function, *args)
        return self.poll_state()

    def submit_work(self, function, *args: object):
        """Queue non-Tk work on the controller's single worker."""

        return self._executor.submit(function, *args)

    def start(self, mode: ModelMode) -> UIState:
        if mode not in ("vast", "ollama"):
            raise ValueError("an explicit Vast.ai or Local Ollama mode is required")
        cancellation = StartCancellation()
        future = self.submit_work(
            _StartCommand(self._orchestrator, cancellation), mode
        )
        with self._future_lock:
            retained: list[_StartRequest] = []
            for request in self._start_requests:
                done = getattr(request.future, "done", None)
                try:
                    completed = bool(done()) if callable(done) else False
                except Exception:
                    completed = False
                if not completed:
                    retained.append(request)
            self._start_requests = retained
            self._start_requests.append(_StartRequest(future, cancellation))
        return self.poll_state()

    def _cancel_pending_starts(self) -> None:
        with self._future_lock:
            requests = tuple(self._start_requests)
            self._start_requests.clear()
        if not requests:
            self._orchestrator.cancel_start()
            return
        for request in requests:
            request.cancellation.cancel()
            cancel = getattr(request.future, "cancel", None)
            try:
                if callable(cancel):
                    cancel()
            except Exception:
                pass

    def stop_local(self) -> UIState:
        self._cancel_pending_starts()
        return self._submit(self._orchestrator.stop_local)

    def restart(self) -> UIState:
        return self._submit(self._orchestrator.restart)

    def open_defend(self, public_origin: str) -> UIState:
        if not isinstance(public_origin, str) or not public_origin.startswith("https://"):
            raise ValueError("public origin must use HTTPS")
        return self._submit(webbrowser.open, public_origin)

    def stop_and_destroy_vast(self, confirmed_instance_id: int | None) -> UIState:
        snapshot = self._orchestrator.snapshot()
        expected = snapshot.vast_instance_id
        if (
            expected is None
            or isinstance(confirmed_instance_id, bool)
            or type(confirmed_instance_id) is not int
            or confirmed_instance_id != expected
        ):
            identifier = str(expected) if expected is not None else "the active instance"
            raise ConfirmationRequired(
                f"Enter exact Vast instance ID {identifier} to confirm destruction"
            )
        destroy = getattr(self._orchestrator, "stop_and_destroy_vast", None)
        if not callable(destroy):
            raise RuntimeError("Vast.ai destruction is not available")
        return self._submit(destroy, expected)

    def poll_state(self) -> UIState:
        snapshot = self._orchestrator.snapshot()
        selected_logs = snapshot.logs[-self._max_ui_log_entries :]
        logs = tuple(
            LogEntry(
                str(entry.service)[:80],
                redact_text(str(entry.text), [])[: self._max_ui_log_chars],
            )
            for entry in selected_logs
        )
        return UIState(
            state=snapshot.state,
            selected_mode=snapshot.mode,
            components=tuple(snapshot.components),
            logs=logs,
            message=snapshot.error,
            vast_gpu=snapshot.vast_gpu,
            vast_instance_id=snapshot.vast_instance_id,
            vast_hourly_price=snapshot.vast_hourly_price,
            owned_services=snapshot.owned_services,
        )

    def shutdown(self) -> None:
        self._cancel_pending_starts()
        if self._owns_executor:
            self._executor.shutdown(wait=False, cancel_futures=True)
