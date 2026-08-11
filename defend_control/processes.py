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
        self._job = job
        self._popen = popen
        self.logs = logs or LogBuffer(
            max_entries=2_000, max_line_chars=4_096, known_secrets=()
        )
        self._owned: dict[str, _OwnedProcess] = {}
        self._external: dict[str, _ExternalProcess] = {}
        self._lock = threading.RLock()
        self._closed = False

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
            if spec.name in self._owned or spec.name in self._external:
                raise ValueError("process name is already supervised")
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
                raise RuntimeError(
                    f"Could not start {spec.name} ({_safe_error_type(error)})"
                ) from None

            try:
                self._job.assign(process)
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
                raise RuntimeError(
                    f"Could not own {spec.name} ({_safe_error_type(error)})"
                ) from None

            self._owned[spec.name] = _OwnedProcess(process, spec)
            streams = (("stdout", process.stdout), ("stderr", process.stderr))
            for stream_name, stream in streams:
                if stream is not None:
                    threading.Thread(
                        target=self._read_stream,
                        args=(spec.name, stream_name, stream),
                        daemon=True,
                        name=f"defend-{spec.name}-{stream_name}",
                    ).start()
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
            if name in self._owned:
                raise ValueError("process name is already owned")
            self._external[name] = _ExternalProcess(pid, health_url)

    def _terminate(self, process: Any) -> None:
        if process.poll() is not None:
            return
        terminate_tree = getattr(self._job, "terminate_tree", None)
        if callable(terminate_tree):
            try:
                terminate_tree(process)
                process.wait(timeout=3)
                return
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                pass
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

    def stop(self, name: str) -> bool:
        with self._lock:
            owned = self._owned.get(name)
            if owned is None:
                return False
        try:
            self._terminate(owned.process)
        except Exception as error:
            raise RuntimeError(
                f"Could not stop {name} ({_safe_error_type(error)})"
            ) from None
        with self._lock:
            self._owned.pop(name, None)
        return True

    def _stop_all(self, *, reset_job: bool) -> None:
        with self._lock:
            names = tuple(reversed(self._owned))
        first_error: RuntimeError | None = None
        for name in names:
            try:
                self.stop(name)
            except RuntimeError as error:
                if first_error is None:
                    first_error = error
        if reset_job and self._job_factory is not None:
            try:
                self._job.close()
                self._job = self._job_factory()
            except Exception as error:
                if first_error is None:
                    first_error = RuntimeError(
                        "Could not reset process ownership "
                        f"({_safe_error_type(error)})"
                    )
        if first_error is not None:
            raise first_error

    def stop_all(self) -> None:
        self._stop_all(reset_job=True)

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
        try:
            self._stop_all(reset_job=False)
        finally:
            with self._lock:
                should_close = not self._closed
                if should_close:
                    self._closed = True
                    self._external.clear()
            if should_close:
                self._job.close()

    def __enter__(self) -> "ProcessSupervisor":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
