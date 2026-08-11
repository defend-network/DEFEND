from __future__ import annotations

from collections.abc import Callable, Mapping
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
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


_MAX_PROCESS_QUERY_BYTES = 64 * 1024


def _split_windows_command_line(command_line: str) -> tuple[str, ...]:
    if sys.platform != "win32" or not command_line:
        return ()
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.CommandLineToArgvW.argtypes = [
        wintypes.LPCWSTR,
        ctypes.POINTER(ctypes.c_int),
    ]
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL
    count = ctypes.c_int()
    pointer = shell32.CommandLineToArgvW(command_line, ctypes.byref(count))
    if not pointer or count.value <= 0:
        return ()
    try:
        return tuple(pointer[index] for index in range(count.value))
    finally:
        kernel32.LocalFree(ctypes.cast(pointer, wintypes.HLOCAL))


def _query_cloudflared_processes() -> tuple[Mapping[str, object], ...]:
    system_root = os.environ.get("SYSTEMROOT")
    if not system_root:
        return ()
    powershell = (
        Path(system_root)
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    if not powershell.is_file():
        return ()
    script = (
        "Get-CimInstance Win32_Process -Filter \"Name = 'cloudflared.exe'\" | "
        "Select-Object ProcessId,ExecutablePath,CommandLine | "
        "ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(
            [
                str(powershell),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        return ()
    if completed.returncode != 0:
        return ()
    encoded = completed.stdout.encode("utf-8", errors="replace")
    if not encoded or len(encoded) > _MAX_PROCESS_QUERY_BYTES:
        return ()
    try:
        raw = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return ()
    rows = raw if isinstance(raw, list) else [raw]
    candidates: list[Mapping[str, object]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        command_line = row.get("CommandLine")
        candidates.append(
            {
                "pid": row.get("ProcessId"),
                "executable": row.get("ExecutablePath"),
                "argv": _split_windows_command_line(command_line)
                if isinstance(command_line, str)
                else (),
            }
        )
    return tuple(candidates)


class ExternalCloudflaredDetector:
    """Reduce a verified local cloudflared identity to its PID only."""

    def __init__(
        self,
        *,
        query: Callable[[], tuple[Mapping[str, object], ...]] = (
            _query_cloudflared_processes
        ),
    ) -> None:
        self._query = query

    @staticmethod
    def _same_path(left: object, right: Path) -> bool:
        if not isinstance(left, str) or not left:
            return False
        try:
            return str(Path(left).resolve(strict=False)).casefold() == str(
                right.resolve(strict=False)
            ).casefold()
        except (OSError, ValueError):
            return False

    @staticmethod
    def _has_config(argv: tuple[str, ...], expected: Path) -> bool:
        expected_text = str(expected.resolve(strict=False)).casefold()
        for index, argument in enumerate(argv):
            normalized = argument.casefold()
            if normalized == "--config" and index + 1 < len(argv):
                try:
                    candidate = str(
                        Path(argv[index + 1]).resolve(strict=False)
                    ).casefold()
                except (OSError, ValueError):
                    return False
                return candidate == expected_text
            if normalized.startswith("--config="):
                try:
                    candidate = str(
                        Path(argument.split("=", 1)[1]).resolve(strict=False)
                    ).casefold()
                except (OSError, ValueError):
                    return False
                return candidate == expected_text
        return False

    def __call__(self, settings: ControlSettings) -> int | None:
        try:
            candidates = self._query()
        except Exception:
            return None
        matches: list[int] = []
        for candidate in candidates:
            pid = candidate.get("pid") if isinstance(candidate, Mapping) else None
            executable = (
                candidate.get("executable")
                if isinstance(candidate, Mapping)
                else None
            )
            raw_argv = (
                candidate.get("argv") if isinstance(candidate, Mapping) else None
            )
            if (
                isinstance(pid, bool)
                or not isinstance(pid, int)
                or pid <= 0
                or not self._same_path(executable, settings.cloudflared_exe)
                or not isinstance(raw_argv, (tuple, list))
                or not all(isinstance(item, str) for item in raw_argv)
            ):
                continue
            argv = tuple(raw_argv)
            normalized = tuple(item.casefold() for item in argv)
            try:
                run_index = normalized.index("run")
            except ValueError:
                continue
            if (
                "tunnel" not in normalized[1:run_index]
                or run_index + 1 >= len(argv)
                or argv[run_index + 1] != settings.cloudflared_tunnel
                or not self._has_config(argv, settings.cloudflared_config)
            ):
                continue
            matches.append(pid)
        return matches[0] if len(matches) == 1 else None


class StartFailed(RuntimeError):
    def __init__(self, component: str, detail: str = "not ready") -> None:
        super().__init__(f"{component} start failed: {detail}")
        self.component = component


class StartCancelled(StartFailed):
    def __init__(self) -> None:
        super().__init__("startup", "cancelled")


class StartCancellation:
    """One cancellation signal whose lifetime is exactly one start attempt."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: float) -> bool:
        return self._event.wait(timeout)


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
    owned_services: tuple[str, ...] = ()


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
        external_tunnel_detector: Callable[[ControlSettings], int | None] | None = None,
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
        self._external_tunnel_detector = (
            external_tunnel_detector
            if external_tunnel_detector is not None
            else ExternalCloudflaredDetector()
        )
        self._state_lock = threading.RLock()
        self._operation_lock = threading.RLock()
        self._active_cancellation: StartCancellation | None = None
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

    @staticmethod
    def _check_cancelled(cancellation: StartCancellation) -> None:
        if cancellation.is_cancelled():
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
        cancellation: StartCancellation,
        *,
        public: bool = False,
    ) -> None:
        deadline = time.monotonic() + self._health_timeout_seconds
        while True:
            self._check_cancelled(cancellation)
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
            self._check_cancelled(cancellation)
            if result.ok:
                return
            if time.monotonic() >= deadline:
                raise StartFailed(component, "health check timed out")
            cancellation.wait(
                min(self._poll_interval_seconds, max(0.0, deadline - time.monotonic()))
            )

    def _remember_owned(self, name: str, attempt: list[str]) -> None:
        with self._state_lock:
            self._owned_order.append(name)
            attempt.append(name)

    def _forget_owned(self, name: str) -> None:
        with self._state_lock:
            if name in self._owned_order:
                self._owned_order.remove(name)

    def _rollback(self, attempt: list[str]) -> bool:
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

        with self._state_lock:
            return not any(name in self._owned_order for name in attempt)

    def start(
        self,
        mode: ModelMode,
        cancellation: StartCancellation | None = None,
    ) -> StackSnapshot | AlreadyRunning:
        if mode not in ("vast", "ollama"):
            raise ValueError("mode must be vast or ollama")
        attempt_cancellation = cancellation or StartCancellation()
        self._check_cancelled(attempt_cancellation)
        if not self._operation_lock.acquire(blocking=False):
            current = self.snapshot()
            return AlreadyRunning(current.state, current.mode)
        attempt: list[str] = []
        try:
            with self._state_lock:
                if self._state not in ("stopped", "failed") or self._owned_order:
                    return AlreadyRunning(self._state, self._mode)
                self._active_cancellation = attempt_cancellation
                self._mode = mode
                self._last_explicit_mode = mode
                self._state = "validating"
                self._error = None
                self._components = {name: "stopped" for name in self._COMPONENTS}

            secrets = self._load_secrets()
            self._check_cancelled(attempt_cancellation)
            checks = self._preflight.run(mode, self._settings, secrets)
            failed_checks = tuple(check for check in checks if not check.ok)
            if failed_checks:
                raise StartFailed("preflight", "required checks did not pass")
            self._check_cancelled(attempt_cancellation)
            if mode == "vast":
                raise StartFailed("model", "Vast.ai provider is not configured")

            self._set_state("starting")
            self._set_component("model", "starting")
            try:
                ready = self._local_backend.verify(self._settings.local_model)
            except LocalModelUnavailable as error:
                raise StartFailed("model", str(error)) from None
            self._set_component("model", "ready")
            self._check_cancelled(attempt_cancellation)
            specs = build_local_process_specs(self._settings, secrets, ready)

            self._set_component("api", "starting")
            self._check_cancelled(attempt_cancellation)
            self._supervisor.start(specs.api)
            self._remember_owned("api", attempt)
            self._wait_healthy(
                "API", specs.api.health_url or "", attempt_cancellation
            )
            self._set_component("api", "ready")
            self._check_cancelled(attempt_cancellation)

            self._set_component("frontend", "starting")
            self._check_cancelled(attempt_cancellation)
            self._supervisor.start(specs.web)
            self._remember_owned("web", attempt)
            self._wait_healthy(
                "frontend", specs.web.health_url or "", attempt_cancellation
            )
            self._set_component("frontend", "ready")
            self._check_cancelled(attempt_cancellation)

            self._set_component("cloudflare", "starting")
            self._check_cancelled(attempt_cancellation)
            try:
                external_tunnel_pid = self._external_tunnel_detector(
                    self._settings
                )
            except Exception:
                external_tunnel_pid = None
            if (
                type(external_tunnel_pid) is int
                and external_tunnel_pid > 0
            ):
                self._supervisor.observe_external(
                    "external-cloudflare",
                    pid=external_tunnel_pid,
                    health_url=self._settings.public_web_origin,
                )
                self._set_component("cloudflare", "ready (external)")
            else:
                self._check_cancelled(attempt_cancellation)
                self._supervisor.start(specs.cloudflare)
                self._remember_owned("cloudflare", attempt)
                self._set_component("cloudflare", "running")
            self._check_cancelled(attempt_cancellation)
            self._wait_healthy(
                "public route",
                f"{self._settings.public_web_origin}/health",
                attempt_cancellation,
                public=True,
            )
            self._set_component("cloudflare", "ready")
            self._set_state("ready")
            return self.snapshot()
        except StartCancelled:
            rollback_complete = self._rollback(attempt)
            if rollback_complete:
                self._set_component("model", "stopped")
                self._set_component("ssh tunnel", "stopped")
                self._set_state("stopped")
            else:
                self._set_state(
                    "failed", error="startup cancelled; cleanup pending"
                )
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
            with self._state_lock:
                if self._active_cancellation is attempt_cancellation:
                    self._active_cancellation = None
            self._operation_lock.release()

    def cancel_start(self) -> None:
        with self._state_lock:
            cancellation = self._active_cancellation
        if cancellation is not None:
            cancellation.cancel()

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
                owned_services=tuple(self._owned_order),
            )
