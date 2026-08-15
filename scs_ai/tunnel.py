from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
import os
from pathlib import Path
import subprocess
import threading
from typing import Literal

from .config import ScsAiSettings

TunnelState = Literal["stopped", "starting", "connected", "unhealthy"]

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
_MAX_LOG_ENTRIES = 2_000
_MAX_LOG_CHARS = 4_096


@dataclass(frozen=True)
class TunnelStatus:
    state: TunnelState
    enabled: bool
    pid: int | None
    returncode: int | None
    detail: str = ""

    def __repr__(self) -> str:
        return (
            f"TunnelStatus(state={self.state!r}, enabled={self.enabled!r}, "
            f"pid={self.pid!r}, returncode={self.returncode!r})"
        )


class EnvTokenSource:
    """Load the tunnel token from the protected TUNNEL_TOKEN environment."""

    def __init__(self, name: str = "TUNNEL_TOKEN") -> None:
        if not isinstance(name, str) or not name:
            raise ValueError("environment variable name must not be empty")
        self._name = name

    def load(self) -> str:
        value = os.environ.get(self._name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{self._name} must be configured")
        return value


class FileTokenSource:
    """Load the tunnel token from a protected token file (no shell expansion)."""

    def __init__(self, path: Path) -> None:
        if isinstance(path, str):
            path = Path(path)
        if not isinstance(path, Path):
            raise TypeError("token file path must be a Path")
        self._path = path

    def load(self) -> str:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except OSError as error:
            raise ValueError(f"Could not read tunnel token file ({type(error).__name__})") from None
        value = raw.strip()
        if not value or any(char.isspace() for char in value):
            raise ValueError("tunnel token file must contain a single non-empty token")
        return value


class _RedactingLog:
    def __init__(self, known_secrets: Iterable[str] = ()) -> None:
        self._secrets = {
            value for value in known_secrets if isinstance(value, str) and value
        }
        self._entries: deque[tuple[str, str]] = deque(maxlen=_MAX_LOG_ENTRIES)
        self._lock = threading.Lock()

    def add_known_secrets(self, values: Iterable[str]) -> None:
        with self._lock:
            self._secrets.update(
                value for value in values if isinstance(value, str) and value
            )

    def append(self, service: str, line: str) -> None:
        safe = str(line).replace("\r", "\\r").replace("\n", "\\n")
        with self._lock:
            for secret in self._secrets:
                if secret and secret in safe:
                    safe = safe.replace(secret, "[REDACTED]")
            self._entries.append(
                (str(service)[:80], safe[: _MAX_LOG_CHARS])
            )

    def snapshot(self) -> tuple[tuple[str, str], ...]:
        with self._lock:
            return tuple(self._entries)


class TunnelController:
    """SCS-owned cloudflared lifecycle with state tracking and safe logs.

    The token is injected only through the child environment (TUNNEL_TOKEN)
    and never through argv, reprs, statuses, or unredacted logs. Stopping
    terminates only the process this controller spawned; it never queries or
    touches other cloudflared processes.
    """

    def __init__(
        self,
        settings: ScsAiSettings,
        *,
        executable: str,
        token_source: object | None = None,
        popen: Callable[..., object] = subprocess.Popen,
        probe: Callable[[], bool] | None = None,
        logs: _RedactingLog | None = None,
    ) -> None:
        if not isinstance(settings, ScsAiSettings):
            raise TypeError("settings must be an ScsAiSettings")
        if not isinstance(executable, str) or not executable.strip():
            raise ValueError("cloudflared executable must be a non-empty path")
        self._settings = settings
        self._executable = executable
        self._token_source = token_source if token_source is not None else EnvTokenSource()
        self._popen = popen
        self._probe = probe if probe is not None else (lambda: False)
        self._logs = logs if logs is not None else _RedactingLog()
        self._process: object | None = None
        self._pid: int | None = None
        self._lock = threading.RLock()

    def _child_environment(self, token: str) -> dict[str, str]:
        child = {
            name: value
            for name in _PARENT_ENV_ALLOWLIST
            if (value := os.environ.get(name)) is not None
        }
        child["TUNNEL_TOKEN"] = token
        return child

    def _argv(self) -> tuple[str, ...]:
        return (self._executable, "tunnel", "--no-autoupdate", "run")

    def start(self) -> TunnelStatus:
        with self._lock:
            if not self._settings.tunnel_enabled:
                return TunnelStatus(
                    state="stopped",
                    enabled=False,
                    pid=None,
                    returncode=None,
                    detail="tunnel disabled",
                )
            try:
                token = self._token_source.load()
            except ValueError as error:
                return TunnelStatus(
                    state="unhealthy",
                    enabled=True,
                    pid=None,
                    returncode=None,
                    detail=str(error),
                )
            self._logs.add_known_secrets([token])
            env = self._child_environment(token)
            try:
                process = self._popen(
                    self._argv(),
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
            except Exception as error:
                return TunnelStatus(
                    state="unhealthy",
                    enabled=True,
                    pid=None,
                    returncode=None,
                    detail=f"Could not start tunnel ({type(error).__name__})",
                )
            self._process = process
            self._pid = int(getattr(process, "pid", 0))
            self._logs.append("tunnel", f"started pid={self._pid}")
            return self.status()

    def stop(self) -> TunnelStatus:
        with self._lock:
            process = self._process
            if process is None:
                return TunnelStatus(
                    state="stopped",
                    enabled=self._settings.tunnel_enabled,
                    pid=None,
                    returncode=None,
                )
            pid = self._pid
            try:
                process.terminate()
                process.wait(timeout=5)
            except Exception:
                try:
                    process.kill()
                    process.wait(timeout=2)
                except Exception:
                    pass
            self._process = None
            self._pid = None
            self._logs.append("tunnel", f"stopped pid={pid}")
            return TunnelStatus(
                state="stopped",
                enabled=self._settings.tunnel_enabled,
                pid=None,
                returncode=0,
            )

    def status(self) -> TunnelStatus:
        with self._lock:
            process = self._process
            if process is None:
                return TunnelStatus(
                    state="stopped",
                    enabled=self._settings.tunnel_enabled,
                    pid=None,
                    returncode=None,
                )
            try:
                returncode = process.poll()
            except Exception:
                returncode = None
            if returncode is not None:
                return TunnelStatus(
                    state="unhealthy",
                    enabled=self._settings.tunnel_enabled,
                    pid=self._pid,
                    returncode=int(returncode),
                    detail=f"tunnel exited with code {returncode}",
                )
            try:
                connected = bool(self._probe())
            except Exception:
                connected = False
            state: TunnelState = "connected" if connected else "starting"
            return TunnelStatus(
                state=state,
                enabled=self._settings.tunnel_enabled,
                pid=self._pid,
                returncode=None,
            )

    def logs(self) -> tuple[tuple[str, str], ...]:
        return self._logs.snapshot()