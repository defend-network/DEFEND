from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import threading
import time
from typing import Any

from .health import HealthResult, probe_http
from .local_model import (
    LocalModelUnavailable,
    LocalOllamaBackend,
    build_local_process_specs,
)
from .preflight import PreflightRunner
from .processes import LogEntry, ProcessSupervisor
from .settings import ControlSettings
from .types import ModelMode, ServiceState


class StartFailed(RuntimeError):
    def __init__(self, component: str, detail: str = "not ready") -> None:
        super().__init__(f"{component} start failed: {detail}")
        self.component = component


class StartCancelled(StartFailed):
    def __init__(self) -> None:
        super().__init__("startup", "cancelled")


@dataclass(frozen=True)
class AlreadyRunning:
    state: ServiceState
    mode: ModelMode | None


@dataclass(frozen=True)
class ComponentSnapshot:
    name: str
    state: str
    detail: str = ""


@dataclass(frozen=True)
class StackSnapshot:
    state: ServiceState
    mode: ModelMode | None
    components: tuple[ComponentSnapshot, ...]
    error: str | None
    vast_gpu: str | None = None
    vast_instance_id: int | None = None
    vast_hourly_price: str | None = None
    logs: tuple[LogEntry, ...] = ()


class StackOrchestrator:
    _COMPONENTS = ("model", "ssh tunnel", "api", "frontend", "cloudflare")

    def __init__(
        self,
        *,
        settings: ControlSettings,
        secrets: Mapping[str, str] | Any,
        preflight: PreflightRunner,
        supervisor: ProcessSupervisor,
        local_backend: LocalOllamaBackend,
        health_probe: Callable[..., HealthResult] = probe_http,
        external_tunnel_probe: Callable[[], bool] | None = None,
        health_timeout_seconds: float = 30.0,
        poll_interval_seconds: float = 0.2,
    ) -> None:
        if health_timeout_seconds <= 0 or poll_interval_seconds < 0:
            raise ValueError("health timing values are invalid")
        self._settings = settings
        self._secrets_source = secrets
        self._preflight = preflight
        self._supervisor = supervisor
        self._local_backend = local_backend
        self._health_probe = health_probe
        self._health_timeout_seconds = float(health_timeout_seconds)
        self._poll_interval_seconds = float(poll_interval_seconds)
        self._external_tunnel_probe = (
            external_tunnel_probe
            if external_tunnel_probe is not None
            else self._probe_existing_tunnel
        )
        self._state_lock = threading.RLock()
        self._operation_lock = threading.RLock()
        self._cancel = threading.Event()
        self._state: ServiceState = "stopped"
        self._mode: ModelMode | None = None
        self._last_explicit_mode: ModelMode | None = None
        self._error: str | None = None
        self._components = {name: "stopped" for name in self._COMPONENTS}
        self._owned_order: list[str] = []

    def _set_state(
        self,
        state: ServiceState,
        *,
        error: str | None = None,
    ) -> None:
        with self._state_lock:
            self._state = state
            self._error = error

    def _set_component(self, name: str, state: str) -> None:
        with self._state_lock:
            self._components[name] = state

    def _check_cancelled(self) -> None:
        if self._cancel.is_set():
            raise StartCancelled()

    def _load_secrets(self) -> dict[str, str]:
        source = self._secrets_source
        values = source.load() if hasattr(source, "load") else source
        if not isinstance(values, Mapping) or not all(
            isinstance(name, str) and isinstance(value, str)
            for name, value in values.items()
        ):
            raise StartFailed("secrets", "local secret store is invalid")
        return dict(values)

    def _wait_healthy(
        self,
        component: str,
        url: str,
        *,
        public: bool = False,
    ) -> None:
        deadline = time.monotonic() + self._health_timeout_seconds
        while True:
            self._check_cancelled()
            remaining = max(0.001, deadline - time.monotonic())
            result = self._health_probe(
                url,
                min(5.0, remaining),
                **(
                    {"public_origin": self._settings.public_web_origin}
                    if public
                    else {}
                ),
            )
            self._check_cancelled()
            if result.ok:
                return
            if time.monotonic() >= deadline:
                raise StartFailed(component, "health check timed out")
            self._cancel.wait(
                min(self._poll_interval_seconds, max(0.0, deadline - time.monotonic()))
            )

    def _probe_existing_tunnel(self) -> bool:
        result = self._health_probe(
            f"{self._settings.public_web_origin}/health",
            min(2.0, self._health_timeout_seconds),
            public_origin=self._settings.public_web_origin,
        )
        return bool(result.ok)

    def _remember_owned(self, name: str, attempt: list[str]) -> None:
        with self._state_lock:
            self._owned_order.append(name)
            attempt.append(name)

    def _forget_owned(self, name: str) -> None:
        with self._state_lock:
            if name in self._owned_order:
                self._owned_order.remove(name)

    def _rollback(self, attempt: list[str]) -> None:
        for name in reversed(attempt):
            try:
                self._supervisor.stop(name)
            except Exception:
                component = "frontend" if name == "web" else name
                self._set_component(component, "cleanup pending")
                continue
            self._forget_owned(name)
            component = "frontend" if name == "web" else name
            self._set_component(component, "stopped")

    def start(self, mode: ModelMode) -> StackSnapshot | AlreadyRunning:
        if mode not in ("vast", "ollama"):
            raise ValueError("mode must be vast or ollama")
        if not self._operation_lock.acquire(blocking=False):
            current = self.snapshot()
            return AlreadyRunning(current.state, current.mode)
        attempt: list[str] = []
        try:
            with self._state_lock:
                if self._state not in ("stopped", "failed") or self._owned_order:
                    return AlreadyRunning(self._state, self._mode)
                self._cancel.clear()
                self._mode = mode
                self._last_explicit_mode = mode
                self._state = "validating"
                self._error = None
                self._components = {name: "stopped" for name in self._COMPONENTS}

            secrets = self._load_secrets()
            self._check_cancelled()
            checks = self._preflight.run(mode, self._settings, secrets)
            failed_checks = tuple(check for check in checks if not check.ok)
            if failed_checks:
                raise StartFailed("preflight", "required checks did not pass")
            self._check_cancelled()
            if mode == "vast":
                raise StartFailed("model", "Vast.ai provider is not configured")

            self._set_state("starting")
            self._set_component("model", "starting")
            try:
                ready = self._local_backend.verify(self._settings.local_model)
            except LocalModelUnavailable as error:
                raise StartFailed("model", str(error)) from None
            self._set_component("model", "ready")
            self._check_cancelled()
            specs = build_local_process_specs(self._settings, secrets, ready)

            self._set_component("api", "starting")
            self._check_cancelled()
            self._supervisor.start(specs.api)
            self._remember_owned("api", attempt)
            self._wait_healthy("API", specs.api.health_url or "")
            self._set_component("api", "ready")
            self._check_cancelled()

            self._set_component("frontend", "starting")
            self._check_cancelled()
            self._supervisor.start(specs.web)
            self._remember_owned("web", attempt)
            self._wait_healthy("frontend", specs.web.health_url or "")
            self._set_component("frontend", "ready")
            self._check_cancelled()

            self._set_component("cloudflare", "starting")
            self._check_cancelled()
            if self._external_tunnel_probe():
                self._set_component("cloudflare", "ready (external)")
            else:
                self._check_cancelled()
                self._supervisor.start(specs.cloudflare)
                self._remember_owned("cloudflare", attempt)
                self._set_component("cloudflare", "running")
            self._check_cancelled()
            self._wait_healthy(
                "public route",
                f"{self._settings.public_web_origin}/health",
                public=True,
            )
            self._set_component("cloudflare", "ready")
            self._set_state("ready")
            return self.snapshot()
        except StartCancelled:
            self._rollback(attempt)
            self._set_state("stopped")
            raise
        except StartFailed as error:
            self._rollback(attempt)
            self._set_state("failed", error=str(error))
            raise
        except Exception as error:
            self._rollback(attempt)
            safe = StartFailed("startup", f"unexpected {type(error).__name__}")
            self._set_state("failed", error=str(safe))
            raise safe from None
        finally:
            self._operation_lock.release()

    def cancel_start(self) -> None:
        with self._state_lock:
            self._cancel.set()

    def stop_local(self) -> StackSnapshot:
        self.cancel_start()
        with self._operation_lock:
            self._set_state("stopping")
            with self._state_lock:
                owned = tuple(reversed(self._owned_order))
            first_error: RuntimeError | None = None
            for name in owned:
                try:
                    self._supervisor.stop(name)
                except Exception as error:
                    if first_error is None:
                        first_error = RuntimeError(
                            f"Could not stop {name} ({type(error).__name__})"
                        )
                    continue
                self._forget_owned(name)
                self._set_component(
                    "frontend" if name == "web" else name, "stopped"
                )
            self._set_component("model", "stopped")
            self._set_component("ssh tunnel", "stopped")
            if first_error is not None:
                self._set_state("failed", error=str(first_error))
                raise first_error
            self._set_state("stopped")
            return self.snapshot()

    def restart(self) -> StackSnapshot | AlreadyRunning:
        with self._state_lock:
            mode = self._last_explicit_mode
        if mode is None:
            raise StartFailed("restart", "no explicit launch mode has been selected")
        with self._operation_lock:
            self.stop_local()
            return self.start(mode)

    def snapshot(self) -> StackSnapshot:
        logs = ()
        log_buffer = getattr(self._supervisor, "logs", None)
        if log_buffer is not None and hasattr(log_buffer, "snapshot"):
            logs = tuple(log_buffer.snapshot())
        with self._state_lock:
            return StackSnapshot(
                state=self._state,
                mode=self._mode,
                components=tuple(
                    ComponentSnapshot(name, self._components[name])
                    for name in self._COMPONENTS
                ),
                error=self._error,
                logs=logs,
            )
