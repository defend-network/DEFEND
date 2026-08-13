from __future__ import annotations

from collections.abc import Callable, Mapping
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime, timezone
import importlib.util
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
from typing import Protocol

from .secrets import DpapiSecretStore
from .settings import ControlSettings
from .types import ModelMode


_SERVICE_PORTS = (3000, 8000, 8001)
_COMMON_REQUIRED_SECRETS = frozenset(
    {
        "DEFEND_OWNER_PASS",
        "DEFEND_VISITOR_HMAC_KEY",
        "DEFEND_GMAIL_SMTP_USERNAME",
        "DEFEND_GMAIL_APP_PASSWORD",
    }
)
_VAST_REQUIRED_SECRETS = frozenset(
    {"VAST_API_KEY", "HF_TOKEN", "VLLM_API_KEY"}
)
_REQUIRED_IMPORTS = (
    "bs4",
    "ddgs",
    "fastapi",
    "fitz",
    "httpx",
    "lancedb",
    "openpyxl",
    "pdfplumber",
    "PIL",
    "pydantic",
    "docx",
    "multipart",
    "uvicorn",
    "yaml",
)


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str
    remediation: str | None = None


class _LoadsSecrets(Protocol):
    def load(self) -> Mapping[str, str]: ...


def _command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def _path_exists(path: Path) -> bool:
    return path.is_file()


def _module_exists(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _path_writable_without_creation(path: Path) -> bool:
    candidate = Path(path)
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    if not candidate.is_dir():
        return False
    if sys.platform != "win32":
        return os.access(candidate, os.W_OK)

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.CreateFileW(
        str(candidate.resolve()),
        0x0002 | 0x0004,  # FILE_ADD_FILE | FILE_ADD_SUBDIRECTORY
        0x0001 | 0x0002 | 0x0004,  # Share read, write, and delete.
        None,
        3,  # OPEN_EXISTING
        0x02000000,  # FILE_FLAG_BACKUP_SEMANTICS: open a directory.
        None,
    )
    if handle == wintypes.HANDLE(-1).value:
        return False
    kernel32.CloseHandle(handle)
    return True


def _port_available_without_binding(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.2)
        return probe.connect_ex(("127.0.0.1", port)) != 0


def _node_version() -> tuple[int, int]:
    completed = subprocess.run(
        ["node", "--version"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        timeout=5,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        raise OSError("node version probe failed")
    version = completed.stdout.strip().removeprefix("v").split(".")
    if len(version) < 2:
        raise ValueError("node returned an invalid version")
    return int(version[0]), int(version[1])


def _safe_error_type(error: BaseException) -> str:
    name = type(error).__name__
    return name if name.isidentifier() and len(name) <= 64 else "Error"


def _parse_expiry(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _path_metadata(path: Path) -> tuple[bool, int, int, int, int]:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return False, 0, 0, 0, 0
    return True, stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def _database_metadata(database: Path) -> tuple[tuple[bool, int, int, int, int], ...]:
    return tuple(
        _path_metadata(path)
        for path in (
            database,
            database.with_name(f"{database.name}-wal"),
            database.with_name(f"{database.name}-shm"),
            database.with_name(f"{database.name}-journal"),
        )
    )


def _unsafe_invitation_sidecars(
    metadata: tuple[tuple[bool, int, int, int, int], ...],
) -> bool:
    _main, wal, _shm, journal = metadata
    return (wal[0] and wal[3] > 0) or journal[0]


def _unstable_invitation_result() -> CheckResult:
    return CheckResult(
        "invitations",
        False,
        "Invitation rollout check requires a stable database",
        "Stop identity database writers and rerun preflight",
    )


def _invitation_rollout_check(data_root: Path) -> CheckResult:
    database = Path(data_root) / "db" / "identity.db"
    if not database.is_file():
        return CheckResult("invitations", True, "No existing identity database")

    # Read through SQLite's WAL-aware read-only mode. A committed, non-empty WAL
    # is normal after an interrupted or forced shutdown and is not by itself
    # evidence of an active writer. Metadata is compared around the transaction
    # below so a concurrent database change still fails closed.
    before = _database_metadata(database)
    uri = f"{database.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=2)
    try:
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(invitations)")
        }
        if not columns:
            pending = 0
        else:
            required = {"expires_at", "consumed_at", "revoked_at"}
            if not required <= columns:
                raise sqlite3.DatabaseError("unsupported invitation schema")

            if "transport_version" in columns:
                rows = connection.execute(
                    """
                    SELECT expires_at FROM invitations
                    WHERE transport_version='legacy_path'
                      AND consumed_at IS NULL
                      AND revoked_at IS NULL
                    """
                )
            else:
                # Schema versions before fragment transport are entirely legacy.
                rows = connection.execute(
                    """
                    SELECT expires_at FROM invitations
                    WHERE consumed_at IS NULL AND revoked_at IS NULL
                    """
                )
            now = datetime.now(timezone.utc)
            pending = sum(
                1
                for (expires_at,) in rows
                if (expiry := _parse_expiry(expires_at)) is None or expiry > now
            )
    finally:
        connection.close()

    after = _database_metadata(database)
    if after != before:
        return _unstable_invitation_result()

    if pending:
        noun = "invitation" if pending == 1 else "invitations"
        return CheckResult(
            "invitations",
            False,
            f"{pending} active legacy {noun} block rollout",
            "Run the offline invitation rollout reissue command",
        )
    return CheckResult("invitations", True, "Invitation rollout ready")


class PreflightRunner:
    def __init__(
        self,
        *,
        command_exists: Callable[[str], bool] = _command_exists,
        port_available: Callable[[int], bool] = _port_available_without_binding,
        writable: Callable[[Path], bool] = _path_writable_without_creation,
        invitation_check: Callable[[], CheckResult] | None = None,
        path_exists: Callable[[Path], bool] = _path_exists,
        module_exists: Callable[[str], bool] = _module_exists,
        python_version: Callable[[], tuple[int, int]] = lambda: (
            sys.version_info.major,
            sys.version_info.minor,
        ),
        node_version: Callable[[], tuple[int, int]] = _node_version,
        settings_root: Path | None = None,
        forced_missing_secrets: frozenset[str] = frozenset(),
    ) -> None:
        self._command_exists = command_exists
        self._port_available = port_available
        self._writable = writable
        self._invitation_check = invitation_check
        self._path_exists = path_exists
        self._module_exists = module_exists
        self._python_version = python_version
        self._node_version = node_version
        self._settings_root = settings_root
        self._forced_missing_secrets = forced_missing_secrets

    @classmethod
    def for_test(
        cls,
        *,
        missing_secrets: set[str] | frozenset[str] = frozenset(),
        port_available: Callable[[int], bool] = lambda _port: True,
        invitation_check: Callable[[], CheckResult] | None = None,
        use_real_invitation_check: bool = False,
    ) -> "PreflightRunner":
        selected_invitation_check = invitation_check
        if selected_invitation_check is None and not use_real_invitation_check:
            selected_invitation_check = lambda: CheckResult(
                "invitations", True, "Invitation rollout ready"
            )
        return cls(
            command_exists=lambda _name: True,
            port_available=port_available,
            writable=lambda _path: True,
            invitation_check=selected_invitation_check,
            path_exists=lambda _path: True,
            module_exists=lambda _name: True,
            python_version=lambda: (3, 14),
            node_version=lambda: (22, 0),
            settings_root=Path("C:/synthetic/DEFEND"),
            forced_missing_secrets=frozenset(missing_secrets),
        )

    @staticmethod
    def _result(
        name: str,
        check: Callable[[], bool],
        *,
        success: str,
        failure: str,
        remediation: str,
    ) -> CheckResult:
        try:
            ok = bool(check())
        except Exception as error:
            return CheckResult(
                name,
                False,
                f"Check failed ({_safe_error_type(error)})",
                remediation,
            )
        return CheckResult(
            name,
            ok,
            success if ok else failure,
            None if ok else remediation,
        )

    def _secret_result(
        self,
        mode: ModelMode,
        secrets: Mapping[str, str] | DpapiSecretStore | _LoadsSecrets,
    ) -> CheckResult:
        try:
            values = secrets.load() if hasattr(secrets, "load") else secrets
            if not isinstance(values, Mapping):
                raise TypeError("secret source must return a mapping")
            required = set(_COMMON_REQUIRED_SECRETS)
            if mode == "vast":
                required.update(_VAST_REQUIRED_SECRETS)
            missing = sorted(
                name
                for name in required
                if name in self._forced_missing_secrets
                or not isinstance(values.get(name), str)
                or not values.get(name)
            )
        except Exception as error:
            return CheckResult(
                "secrets",
                False,
                f"Secret store check failed ({_safe_error_type(error)})",
                "Re-enter the required secret names in local setup",
            )
        if missing:
            return CheckResult(
                "secrets",
                False,
                f"Missing required secret names: {', '.join(missing)}",
                "Enter the named secrets in local setup",
            )
        return CheckResult("secrets", True, "Required secret names are present")

    def run(
        self,
        mode: ModelMode,
        settings: ControlSettings,
        secrets: Mapping[str, str] | DpapiSecretStore | _LoadsSecrets,
    ) -> tuple[CheckResult, ...]:
        if mode not in ("vast", "ollama"):
            raise ValueError("mode must be vast or ollama")

        results: list[CheckResult] = []
        results.append(
            self._result(
                "python-version",
                lambda: self._python_version() >= (3, 14),
                success="Python 3.14+ available",
                failure="Python 3.14+ is required",
                remediation="Install the supported Python release, then run Repair",
            )
        )
        results.append(
            self._result(
                "node-version",
                lambda: self._node_version() >= (22, 0),
                success="Node 22+ available",
                failure="Node 22+ is required",
                remediation="Install the supported Node release, then run Repair",
            )
        )

        commands = ["npm.cmd", "git", "ssh.exe"]
        for name in commands:
            results.append(
                self._result(
                    name,
                    lambda name=name: self._command_exists(name),
                    success=f"{name} available",
                    failure=f"{name} not found",
                    remediation=f"Install {name} through the documented setup",
                )
            )

        results.append(
            self._result(
                "cloudflared.exe",
                lambda: self._path_exists(settings.cloudflared_exe),
                success="cloudflared executable available",
                failure="cloudflared executable not found",
                remediation="Configure the installed cloudflared executable path",
            )
        )
        results.append(
            self._result(
                "cloudflared-config",
                lambda: self._path_exists(settings.cloudflared_config),
                success="cloudflared configuration available",
                failure="cloudflared configuration not found",
                remediation="Configure the existing named-tunnel file",
            )
        )

        for module in _REQUIRED_IMPORTS:
            results.append(
                self._result(
                    f"import:{module}",
                    lambda module=module: self._module_exists(module),
                    success=f"Python module {module} available",
                    failure=f"Python module {module} missing",
                    remediation="Run Bootstrap-DEFEND.ps1 -Repair",
                )
            )

        settings_root = self._settings_root
        if settings_root is None:
            local_app_data = os.environ.get("LOCALAPPDATA")
            settings_root = (
                Path(local_app_data) / "DEFEND"
                if local_app_data
                else settings.repo_root
            )
        writable_paths = (
            ("data-root", settings.data_root),
            ("settings-root", settings_root),
            ("logs", settings.data_root / "logs"),
        )
        for name, path in writable_paths:
            results.append(
                self._result(
                    name,
                    lambda path=path: self._writable(path),
                    success=f"{name} writable",
                    failure=f"{name} is not writable",
                    remediation="Grant the current Windows user write access",
                )
            )

        results.append(
            CheckResult(
                "service-ports",
                (
                    settings.web_port,
                    settings.api_port,
                    settings.model_port,
                )
                == _SERVICE_PORTS,
                "Service ports are 3000/8000/8001"
                if (
                    settings.web_port,
                    settings.api_port,
                    settings.model_port,
                )
                == _SERVICE_PORTS
                else "Service ports must be 3000/8000/8001",
                None
                if (
                    settings.web_port,
                    settings.api_port,
                    settings.model_port,
                )
                == _SERVICE_PORTS
                else "Restore the fixed DEFEND service ports",
            )
        )
        for port in _SERVICE_PORTS:
            results.append(
                self._result(
                    f"port:{port}",
                    lambda port=port: self._port_available(port),
                    success=f"Port {port} available",
                    failure=f"Port {port} is already in use",
                    remediation="Stop or reconfigure the process using this port",
                )
            )

        results.append(self._secret_result(mode, secrets))
        results.append(
            self._result(
                "next-build",
                lambda: self._path_exists(
                    settings.repo_root / "defend-ui-v2" / ".next" / "BUILD_ID"
                ),
                success="Next production build available",
                failure="Next production build is missing",
                remediation="Run Bootstrap-DEFEND.ps1 -Repair",
            )
        )

        try:
            invitation = (
                self._invitation_check()
                if self._invitation_check is not None
                else _invitation_rollout_check(settings.data_root)
            )
            if not isinstance(invitation, CheckResult):
                raise TypeError("invitation check returned an invalid result")
        except Exception as error:
            invitation = CheckResult(
                "invitations",
                False,
                f"Invitation rollout check failed ({_safe_error_type(error)})",
                "Run the offline invitation rollout check",
            )
        results.append(invitation)
        return tuple(results)
