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
from .types import ModelMode, ServiceState, VastInstance, VastOffer


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
    vast_offer_id: int | None = None
    vast_gpu_ram_mb: int | None = None
    vast_reliability: str | None = None
    vast_storage_cost_per_gb_month: str | None = None
    vast_storage_total_hourly: str | None = None
    vast_disk_gb: int | None = None
    vast_actual_status: str | None = None
    vast_billing_warning: str | None = None
    pending_confirmation: str | None = None
    pending_fingerprint: str | None = None
    vast_candidates: tuple[VastInstance, ...] = ()
    vast_replacement_offer: VastOffer | None = None
    owned_services: tuple[str, ...] = ()

    @property
    def services_running(self) -> bool:
        if (
            self.pending_confirmation == "price"
            and self.vast_instance_id is None
            and not self.owned_services
        ):
            return False
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


class _ConfirmOfferAndStartCommand(_StartCommand):
    __name__ = "confirm_offer_and_start"

    def __call__(self, offer_id: int, hourly_price: str):
        self._orchestrator.confirm_offer(offer_id, hourly_price)
        return self._orchestrator.start("vast", self._cancellation)


class _ConfirmFingerprintAndStartCommand(_StartCommand):
    __name__ = "confirm_fingerprint_and_start"

    def __call__(self, instance_id: int, fingerprint: str):
        self._orchestrator.confirm_fingerprint(instance_id, fingerprint)
        return self._orchestrator.start("vast", self._cancellation)


class _SelectVastInstanceAndStartCommand(_StartCommand):
    __name__ = "select_vast_instance_and_start"

    def __call__(self, instance_id: int):
        self._orchestrator.select_vast_instance(instance_id)
        return self._orchestrator.start("vast", self._cancellation)


class _ConfirmInstanceRestartAndStartCommand(_StartCommand):
    __name__ = "confirm_instance_restart_and_start"

    def __call__(self, instance_id: int, hourly_price: str):
        self._orchestrator.confirm_instance_restart(instance_id, hourly_price)
        return self._orchestrator.start("vast", self._cancellation)


class _ConfirmInstanceReplacementAndStartCommand(_StartCommand):
    __name__ = "confirm_instance_replacement_and_start"

    def __call__(self, instance_id: int, offer_id: int, hourly_price: str):
        self._orchestrator.confirm_instance_replacement(
            instance_id,
            offer_id,
            hourly_price,
        )
        return self._orchestrator.start("vast", self._cancellation)


@dataclass
class _StartRequest:
    cancellation: StartCancellation
    future: object | None = None


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
        return self._queue_start(
            _StartCommand(self._orchestrator, StartCancellation()), mode
        )

    def _queue_start(self, function, *args: object) -> UIState:
        cancellation = function._cancellation
        with self._future_lock:
            retained: list[_StartRequest] = []
            for candidate in self._start_requests:
                done = getattr(candidate.future, "done", None)
                try:
                    completed = bool(done()) if callable(done) else False
                except Exception:
                    completed = False
                if not completed:
                    retained.append(candidate)
            self._start_requests = retained
            request = _StartRequest(cancellation)
            self._start_requests.append(request)
        try:
            future = self.submit_work(
                function, *args
            )
        except Exception:
            with self._future_lock:
                self._start_requests = [
                    candidate
                    for candidate in self._start_requests
                    if candidate is not request
                ]
            raise
        with self._future_lock:
            request.future = future
        return self.poll_state()

    def confirm_vast_offer(self, offer_id: int, hourly_price: str) -> UIState:
        if type(offer_id) is not int or offer_id <= 0:
            raise ValueError("Vast offer ID must be a positive integer")
        if not isinstance(hourly_price, str) or not hourly_price:
            raise ValueError("Vast hourly price must be provided exactly")
        cancellation = StartCancellation()
        return self._queue_start(
            _ConfirmOfferAndStartCommand(self._orchestrator, cancellation),
            offer_id,
            hourly_price,
        )

    def confirm_vast_fingerprint(
        self, instance_id: int, fingerprint: str
    ) -> UIState:
        if type(instance_id) is not int or instance_id <= 0:
            raise ValueError("Vast instance ID must be a positive integer")
        if not isinstance(fingerprint, str) or not fingerprint.startswith("SHA256:"):
            raise ValueError("SSH fingerprint must use SHA256")
        cancellation = StartCancellation()
        return self._queue_start(
            _ConfirmFingerprintAndStartCommand(
                self._orchestrator, cancellation
            ),
            instance_id,
            fingerprint,
        )

    def select_vast_instance(self, instance_id: int) -> UIState:
        if type(instance_id) is not int or instance_id <= 0:
            raise ValueError("Vast instance ID must be a positive integer")
        cancellation = StartCancellation()
        return self._queue_start(
            _SelectVastInstanceAndStartCommand(
                self._orchestrator, cancellation
            ),
            instance_id,
        )

    def confirm_vast_restart(
        self, instance_id: int, hourly_price: str
    ) -> UIState:
        if type(instance_id) is not int or instance_id <= 0:
            raise ValueError("Vast instance ID must be a positive integer")
        if not isinstance(hourly_price, str) or not hourly_price:
            raise ValueError("Vast hourly price must be provided exactly")
        cancellation = StartCancellation()
        return self._queue_start(
            _ConfirmInstanceRestartAndStartCommand(
                self._orchestrator, cancellation
            ),
            instance_id,
            hourly_price,
        )

    def confirm_vast_replacement(
        self,
        instance_id: int,
        offer_id: int,
        hourly_price: str,
    ) -> UIState:
        if type(instance_id) is not int or instance_id <= 0:
            raise ValueError("Vast instance ID must be a positive integer")
        if type(offer_id) is not int or offer_id <= 0:
            raise ValueError("Vast offer ID must be a positive integer")
        if not isinstance(hourly_price, str) or not hourly_price:
            raise ValueError("Vast hourly price must be provided exactly")
        cancellation = StartCancellation()
        return self._queue_start(
            _ConfirmInstanceReplacementAndStartCommand(
                self._orchestrator,
                cancellation,
            ),
            instance_id,
            offer_id,
            hourly_price,
        )

    def decline_vast_instance_action(self) -> UIState:
        return self._submit(self._orchestrator.decline_instance_action)

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
            vast_offer_id=snapshot.vast_offer_id,
            vast_gpu_ram_mb=snapshot.vast_gpu_ram_mb,
            vast_reliability=snapshot.vast_reliability,
            vast_storage_cost_per_gb_month=(
                snapshot.vast_storage_cost_per_gb_month
            ),
            vast_storage_total_hourly=snapshot.vast_storage_total_hourly,
            vast_disk_gb=snapshot.vast_disk_gb,
            vast_actual_status=snapshot.vast_actual_status,
            vast_billing_warning=snapshot.vast_billing_warning,
            pending_confirmation=snapshot.pending_confirmation,
            pending_fingerprint=snapshot.pending_fingerprint,
            vast_candidates=snapshot.vast_candidates,
            vast_replacement_offer=snapshot.vast_replacement_offer,
            owned_services=snapshot.owned_services,
        )

    def shutdown(self) -> None:
        self._cancel_pending_starts()
        if self._owns_executor:
            self._executor.shutdown(wait=False, cancel_futures=True)
