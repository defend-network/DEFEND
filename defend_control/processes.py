from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time
from types import MappingProxyType
from typing import IO, Any, Protocol

from .redaction import redact_text
from .windows_job import WindowsJob


_PARENT_ENV_ALLOWLIST = (
    "APPDATA",
    "COMSPEC",
    "LOCALAPPDATA",
    "NUMBER_OF_PROCESSORS",
    "PATH",
    "PATHEXT",
    "PROCESSOR_ARCHITECTURE",
    "PROGRAMDATA",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "WINDIR",
)
_SECRET_ENV_NAME = re.compile(
    r"(?:^|[_.-])(?:token|password|pass|secret|cookie|authorization|"
    r"api_key|app_password|hmac_key|private_key)(?:$|[_.-])",
    re.IGNORECASE,
)
_SECRET_ARG_SHAPE = re.compile(
    r"(?:^|[-_/])(?:token|password|secret|cookie|authorization|"
    r"api[-_]?key|app[-_]?password)(?:=|:|$)",
    re.IGNORECASE,
)
_MAX_LOG_READ_CHARS = 64 * 1024 + 1
_CREATE_SUSPENDED = 0x00000004
_IO_TEARDOWN_TIMEOUT_SECONDS = 0.5
_CLEANUP_THREAD_CLASS = threading.Thread


class _Job(Protocol):
    def assign(self, process: Any) -> None: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class ProcessSpec:
    name: str
    argv: tuple[str, ...] = field(repr=False)
    cwd: Path
    env: Mapping[str, str] = field(repr=False)
    health_url: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("process name must not be empty")
        if not isinstance(self.argv, tuple) or not self.argv:
            raise ValueError("process argv must be a non-empty tuple")
        if not all(isinstance(argument, str) and argument for argument in self.argv):
            raise ValueError("process argv entries must be non-empty strings")
        if not isinstance(self.cwd, Path):
            object.__setattr__(self, "cwd", Path(self.cwd))
        copied_env = dict(self.env)
        if not all(
            isinstance(name, str)
            and name
            and isinstance(value, str)
            for name, value in copied_env.items()
        ):
            raise ValueError("process environment must contain string names and values")
        object.__setattr__(self, "env", MappingProxyType(copied_env))
        if self.health_url is not None and not isinstance(self.health_url, str):
            raise ValueError("health_url must be a string or None")


@dataclass(frozen=True)
class LogEntry:
    service: str
    text: str


class LogBuffer:
    def __init__(
        self,
        *,
        max_entries: int,
        max_line_chars: int,
        known_secrets: Iterable[str] = (),
    ) -> None:
        if max_entries <= 0 or max_line_chars <= 0:
            raise ValueError("log bounds must be positive")
        self._max_line_chars = int(max_line_chars)
        self._entries: deque[LogEntry] = deque(maxlen=int(max_entries))
        self._known_secrets = {
            value for value in known_secrets if isinstance(value, str) and value
        }
        self._lock = threading.Lock()

    def add_known_secrets(self, values: Iterable[str]) -> None:
        with self._lock:
            self._known_secrets.update(
                value for value in values if isinstance(value, str) and value
            )

    def append(self, service: str, line: str) -> None:
        safe_line = str(line).replace("\r", "\\r").replace("\n", "\\n")
        with self._lock:
            cleaned = redact_text(safe_line, tuple(self._known_secrets))
            self._entries.append(
                LogEntry(str(service)[:80], cleaned[: self._max_line_chars])
            )

    def snapshot(self) -> tuple[LogEntry, ...]:
        with self._lock:
            return tuple(self._entries)


@dataclass(frozen=True)
class ProcessSnapshot:
    name: str
    pid: int
    owned: bool
    running: bool
    health_url: str | None
    returncode: int | None


@dataclass
class _OwnedProcess:
    process: Any
    spec: ProcessSpec
    service_job: _Job
    owns_service_job: bool
    readers: tuple[Any, ...]
    streams: tuple[IO[str], ...]
    service_job_closed: bool = False
    cleanup_threads: tuple[Any | None, ...] = ()
    cleanup_outcomes: tuple[_CleanupOutcome | None, ...] = ()


@dataclass
class _CleanupOutcome:
    completed: bool = False
    error_type: str | None = None


@dataclass(frozen=True)
class _IoTeardownOutcome:
    complete: bool
    error_type: str | None = None


@dataclass(frozen=True)
class _ExternalProcess:
    pid: int
    health_url: str | None


def _safe_error_type(error: BaseException) -> str:
    name = type(error).__name__
    return name if name.isidentifier() and len(name) <= 64 else "Error"


def _is_secret_env_name(name: str) -> bool:
    normalized = name.casefold()
    return bool(_SECRET_ENV_NAME.search(normalized)) or (
        "gmail" in normalized and "username" in normalized
    )


def _child_environment(injected: Mapping[str, str]) -> dict[str, str]:
    child = {
        name: value
        for name in _PARENT_ENV_ALLOWLIST
        if (value := os.environ.get(name)) is not None
    }
    child.update(injected)
    return child


class ProcessSupervisor:
    def __init__(
        self,
        *,
        job: _Job | None = None,
        popen: Callable[..., Any] = subprocess.Popen,
        logs: LogBuffer | None = None,
    ) -> None:
        self._job_factory: Callable[[], _Job] | None = None
        if job is None:
            self._job_factory = WindowsJob
            job = self._job_factory()
        self._service_job_factory = self._job_factory
        if self._service_job_factory is None and isinstance(job, WindowsJob):
            self._service_job_factory = WindowsJob
        self._job = job
        self._retained_jobs: list[_Job] = []
        self._popen = popen
        self.logs = logs or LogBuffer(
            max_entries=2_000, max_line_chars=4_096, known_secrets=()
        )
        self._owned: dict[str, _OwnedProcess] = {}
        self._external: dict[str, _ExternalProcess] = {}
        self._lock = threading.RLock()
        self._closed = False
        self._closing = False
        self._stopping = False

    @staticmethod
    def _validate_secret_argv(spec: ProcessSpec) -> None:
        if any(
            _SECRET_ARG_SHAPE.search(argument) or "bearer " in argument.casefold()
            for argument in spec.argv
        ):
            raise ValueError("secret-shaped arguments are environment only")
        for name, value in spec.env.items():
            if (
                value
                and _is_secret_env_name(name)
                and any(value in argument for argument in spec.argv)
            ):
                raise ValueError(
                    f"{name} is environment only and must not appear in argv"
                )

    def _read_stream(self, name: str, stream_name: str, stream: IO[str]) -> None:
        try:
            while line := stream.readline(_MAX_LOG_READ_CHARS):
                if len(line) >= _MAX_LOG_READ_CHARS and not line.endswith(
                    ("\r", "\n")
                ):
                    while line and not line.endswith(("\r", "\n")):
                        line = stream.readline(_MAX_LOG_READ_CHARS)
                    self.logs.append(
                        f"{name}:{stream_name}", "[oversized log line omitted]"
                    )
                    continue
                self.logs.append(f"{name}:{stream_name}", line)
        except Exception as error:
            self.logs.append(
                f"{name}:{stream_name}",
                f"Log reader failed ({_safe_error_type(error)})",
            )

    @staticmethod
    def _teardown_io(owned: _OwnedProcess) -> _IoTeardownOutcome:
        deadline = time.monotonic() + _IO_TEARDOWN_TIMEOUT_SECONDS
        if owned.streams:
            cleanup_threads: list[Any | None] = (
                list(owned.cleanup_threads)
                if owned.cleanup_threads
                else [None] * len(owned.streams)
            )
            cleanup_outcomes: list[_CleanupOutcome | None] = (
                list(owned.cleanup_outcomes)
                if owned.cleanup_outcomes
                else [None] * len(owned.streams)
            )
            for index, stream in enumerate(owned.streams):
                if cleanup_threads[index] is not None:
                    continue

                outcome = _CleanupOutcome()

                def close_stream(
                    target: IO[str] = stream,
                    result: _CleanupOutcome = outcome,
                ) -> None:
                    try:
                        target.close()
                    except Exception as error:
                        result.error_type = _safe_error_type(error)
                    finally:
                        result.completed = True

                try:
                    worker = _CLEANUP_THREAD_CLASS(
                        target=close_stream,
                        daemon=True,
                        name=f"defend-{owned.spec.name}-close-{index}",
                    )
                    worker.start()
                except Exception:
                    cleanup_threads[index] = None
                    cleanup_outcomes[index] = None
                else:
                    cleanup_threads[index] = worker
                    cleanup_outcomes[index] = outcome
            owned.cleanup_threads = tuple(cleanup_threads)
            owned.cleanup_outcomes = tuple(cleanup_outcomes)

        for reader in owned.readers:
            remaining = max(0.0, deadline - time.monotonic())
            try:
                reader.join(timeout=remaining)
            except Exception:
                pass
        for worker in owned.cleanup_threads:
            if worker is None:
                continue
            remaining = max(0.0, deadline - time.monotonic())
            try:
                worker.join(timeout=remaining)
            except Exception:
                pass

        def finished(worker: Any | None) -> bool:
            if worker is None:
                return False
            is_alive = getattr(worker, "is_alive", None)
            if not callable(is_alive):
                return True
            try:
                return not bool(is_alive())
            except Exception:
                return False

        readers_finished = True
        for reader in owned.readers:
            is_alive = getattr(reader, "is_alive", None)
            if callable(is_alive):
                try:
                    if is_alive():
                        readers_finished = False
                except Exception:
                    readers_finished = False
        cleanup_finished: list[bool] = []
        error_types: list[str] = []
        cleanup_threads = list(owned.cleanup_threads)
        for index, worker in enumerate(cleanup_threads):
            outcome = owned.cleanup_outcomes[index]
            worker_finished = finished(worker)
            successful = bool(
                worker_finished
                and outcome is not None
                and outcome.completed
                and outcome.error_type is None
            )
            cleanup_finished.append(successful)
            if (
                worker_finished
                and outcome is not None
                and outcome.completed
                and outcome.error_type is not None
            ):
                error_types.append(outcome.error_type)
                cleanup_threads[index] = None
        owned.cleanup_threads = tuple(cleanup_threads)
        return _IoTeardownOutcome(
            readers_finished and all(cleanup_finished),
            error_types[0] if error_types else None,
        )

    @staticmethod
    def _close_service_job(owned: _OwnedProcess) -> bool:
        if not owned.owns_service_job or owned.service_job_closed:
            return True
        try:
            owned.service_job.close()
        except Exception:
            return False
        owned.service_job_closed = True
        return True

    def _rollback_reader_start(
        self,
        owned: _OwnedProcess,
    ) -> bool:
        terminated = False
        try:
            self._terminate(owned)
            terminated = owned.process.poll() is not None
        except Exception:
            try:
                owned.process.kill()
                owned.process.wait(timeout=2)
            except Exception:
                pass
        service_closed = self._close_service_job(owned) if terminated else False
        io_outcome = self._teardown_io(owned)
        return terminated and service_closed and io_outcome.complete

    def start(self, spec: ProcessSpec) -> Any:
        if not isinstance(spec, ProcessSpec):
            raise TypeError("spec must be a ProcessSpec")
        self._validate_secret_argv(spec)
        secret_values = [
            value
            for name, value in spec.env.items()
            if _is_secret_env_name(name) and value
        ]
        self.logs.add_known_secrets(secret_values)

        with self._lock:
            if self._closed:
                raise RuntimeError("process supervisor is closed")
            if self._closing:
                raise RuntimeError("process supervisor is closing")
            if self._stopping:
                raise RuntimeError("process supervisor is stopping")
            if spec.name in self._owned or spec.name in self._external:
                raise ValueError("process name is already supervised")
            owns_service_job = self._service_job_factory is not None
            try:
                service_job = (
                    self._service_job_factory()
                    if self._service_job_factory is not None
                    else self._job
                )
            except Exception as error:
                raise RuntimeError(
                    "Could not create service process ownership "
                    f"({_safe_error_type(error)})"
                ) from None
            try:
                resume = getattr(self._job, "resume", None)
                creationflags = getattr(
                    subprocess, "CREATE_NEW_PROCESS_GROUP", 0
                )
                if sys.platform == "win32" and callable(resume):
                    creationflags |= _CREATE_SUSPENDED
                process = self._popen(
                    spec.argv,
                    cwd=spec.cwd,
                    env=_child_environment(spec.env),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    creationflags=creationflags,
                )
            except Exception as error:
                if owns_service_job:
                    try:
                        service_job.close()
                    except Exception:
                        self._retained_jobs.append(service_job)
                raise RuntimeError(
                    f"Could not start {spec.name} ({_safe_error_type(error)})"
                ) from None

            try:
                self._job.assign(process)
                if owns_service_job:
                    service_job.assign(process)
                if callable(resume):
                    resume(process)
            except Exception as error:
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except Exception:
                    try:
                        process.kill()
                    except Exception:
                        pass
                if owns_service_job:
                    try:
                        service_job.close()
                    except Exception:
                        self._retained_jobs.append(service_job)
                raise RuntimeError(
                    f"Could not own {spec.name} ({_safe_error_type(error)})"
                ) from None

            named_streams = tuple(
                (stream_name, stream)
                for stream_name, stream in (
                    ("stdout", process.stdout),
                    ("stderr", process.stderr),
                )
                if stream is not None
            )
            streams = tuple(stream for _name, stream in named_streams)
            owned = _OwnedProcess(
                process,
                spec,
                service_job,
                owns_service_job,
                (),
                streams,
            )
            self._owned[spec.name] = owned
            readers: list[Any] = []
            started_readers: list[Any] = []
            try:
                for stream_name, stream in named_streams:
                    reader = threading.Thread(
                        target=self._read_stream,
                        args=(spec.name, stream_name, stream),
                        daemon=True,
                        name=f"defend-{spec.name}-{stream_name}",
                    )
                    readers.append(reader)
                    reader.start()
                    started_readers.append(reader)
                    owned.readers = tuple(started_readers)
            except Exception as error:
                if self._rollback_reader_start(owned):
                    self._owned.pop(spec.name, None)
                raise RuntimeError(
                    "Could not start process log readers "
                    f"({_safe_error_type(error)})"
                ) from None
            owned.readers = tuple(readers)
            return process

    def observe_external(
        self, name: str, *, pid: int, health_url: str | None = None
    ) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("external process name must not be empty")
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            raise ValueError("external process pid must be positive")
        with self._lock:
            if self._closed:
                raise RuntimeError("process supervisor is closed")
            if self._closing:
                raise RuntimeError("process supervisor is closing")
            if name in self._owned:
                raise ValueError("process name is already owned")
            self._external[name] = _ExternalProcess(pid, health_url)

    def _terminate(self, owned: _OwnedProcess) -> None:
        process = owned.process
        if process.poll() is not None and owned.service_job_closed:
            return
        terminate_tree = getattr(owned.service_job, "terminate_tree", None)
        if callable(terminate_tree):
            terminate_tree(process)
            process.wait(timeout=3)
            return
        if process.poll() is not None:
            return
        send_signal = getattr(process, "send_signal", None)
        if sys.platform == "win32" and callable(send_signal):
            try:
                send_signal(signal.CTRL_BREAK_EVENT)
                process.wait(timeout=3)
                return
            except (OSError, ValueError, subprocess.TimeoutExpired):
                pass
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)

    def _stop_locked(self, name: str) -> bool:
        owned = self._owned.get(name)
        if owned is None:
            return False
        try:
            self._terminate(owned)
        except Exception as error:
            self._teardown_io(owned)
            raise RuntimeError(
                f"Could not stop {name} ({_safe_error_type(error)})"
            ) from None
        if not self._close_service_job(owned):
            self._teardown_io(owned)
            raise RuntimeError(f"Could not close {name} ownership (OSError)")
        io_outcome = self._teardown_io(owned)
        if io_outcome.error_type is not None:
            raise RuntimeError(
                f"Could not close {name} streams ({io_outcome.error_type})"
            )
        if io_outcome.complete:
            self._owned.pop(name, None)
        return True

    def stop(self, name: str) -> bool:
        with self._lock:
            return self._stop_locked(name)

    def _stop_all_locked(self, *, reset_job: bool) -> None:
        retained_errors: list[BaseException] = []
        still_retained: list[_Job] = []
        for retained in self._retained_jobs:
            try:
                retained.close()
            except Exception as error:
                retained_errors.append(error)
                still_retained.append(retained)
        self._retained_jobs = still_retained

        names = tuple(reversed(self._owned))
        first_error: RuntimeError | None = (
            RuntimeError(
                "Could not dispose replacement process ownership "
                f"({_safe_error_type(retained_errors[0])})"
            )
            if retained_errors
            else None
        )
        for name in names:
            try:
                self._stop_locked(name)
            except RuntimeError as error:
                if first_error is None:
                    first_error = error
        if reset_job and self._job_factory is not None:
            try:
                replacement = self._job_factory()
            except Exception as error:
                if first_error is None:
                    first_error = RuntimeError(
                        "Could not reset process ownership "
                        f"({_safe_error_type(error)})"
                    )
            else:
                previous = self._job
                try:
                    previous.close()
                except Exception as error:
                    try:
                        replacement.close()
                    except Exception:
                        self._retained_jobs.append(replacement)
                    if first_error is None:
                        first_error = RuntimeError(
                            "Could not reset process ownership "
                            f"({_safe_error_type(error)})"
                        )
                else:
                    self._job = replacement
                    for name, owned in tuple(self._owned.items()):
                        service_closed = self._close_service_job(owned)
                        io_outcome = self._teardown_io(owned)
                        if service_closed and io_outcome.complete:
                            self._owned.pop(name, None)
        if first_error is not None:
            raise first_error

    def stop_all(self) -> None:
        with self._lock:
            if self._closed:
                return
            if self._closing:
                raise RuntimeError("process supervisor is closing")
            self._stopping = True
            try:
                self._stop_all_locked(reset_job=True)
            finally:
                self._stopping = False

    def snapshot(self) -> tuple[ProcessSnapshot, ...]:
        with self._lock:
            owned_items = tuple(self._owned.items())
            external_items = tuple(self._external.items())
        snapshots: list[ProcessSnapshot] = []
        for name, owned in owned_items:
            returncode = owned.process.poll()
            snapshots.append(
                ProcessSnapshot(
                    name=name,
                    pid=int(owned.process.pid),
                    owned=True,
                    running=returncode is None,
                    health_url=owned.spec.health_url,
                    returncode=returncode,
                )
            )
        snapshots.extend(
            ProcessSnapshot(
                name=name,
                pid=external.pid,
                owned=False,
                running=True,
                health_url=external.health_url,
                returncode=None,
            )
            for name, external in external_items
        )
        return tuple(snapshots)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closing = True
            self._stopping = True
            try:
                stop_error: RuntimeError | None = None
                try:
                    self._stop_all_locked(reset_job=False)
                except RuntimeError as error:
                    stop_error = error
                if self._retained_jobs:
                    if stop_error is not None:
                        raise stop_error
                    raise RuntimeError(
                        "Could not close retained process ownership"
                    )
                try:
                    self._job.close()
                except Exception as error:
                    raise RuntimeError(
                        "Could not close process ownership "
                        f"({_safe_error_type(error)})"
                    ) from None
                if self._owned:
                    if stop_error is not None:
                        raise stop_error
                    raise RuntimeError("Process cleanup pending (TimeoutError)")
                self._closed = True
                self._closing = False
                self._external.clear()
                if stop_error is not None:
                    raise stop_error
            finally:
                self._stopping = False

    def __enter__(self) -> "ProcessSupervisor":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
