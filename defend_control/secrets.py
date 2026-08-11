from collections.abc import Callable, Mapping
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Protocol


_MAX_PAYLOAD_BYTES = 64 * 1024
_PAYLOAD_VERSION = 1
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class UnsupportedPlatformError(RuntimeError):
    """Raised when Windows-only secret protection is used elsewhere."""


class SecretBackend(Protocol):
    def protect(self, data: bytes) -> bytes: ...

    def unprotect(self, data: bytes) -> bytes: ...


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _require_windows() -> None:
    if sys.platform != "win32":
        raise UnsupportedPlatformError(
            "DEFEND DPAPI secret storage is supported only on Windows"
        )


def _last_windows_error(operation: str) -> OSError:
    error = ctypes.get_last_error()
    return ctypes.WinError(error, f"{operation} failed")


def _input_blob(data: bytes) -> tuple[_DataBlob, object]:
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    blob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    return blob, buffer


class WindowsDpapiBackend:
    def __init__(self) -> None:
        _require_windows()

    def protect(self, data: bytes) -> bytes:
        return self._transform(data, protect=True)

    def unprotect(self, data: bytes) -> bytes:
        return self._transform(data, protect=False)

    @staticmethod
    def _transform(data: bytes, *, protect: bool) -> bytes:
        _require_windows()
        if not data:
            return b""

        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        if protect:
            function = crypt32.CryptProtectData
            second_argument = wintypes.LPCWSTR
        else:
            function = crypt32.CryptUnprotectData
            second_argument = ctypes.POINTER(wintypes.LPWSTR)
        function.argtypes = [
            ctypes.POINTER(_DataBlob),
            second_argument,
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]
        function.restype = wintypes.BOOL
        kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
        kernel32.LocalFree.restype = wintypes.HLOCAL

        source, source_buffer = _input_blob(data)
        destination = _DataBlob()
        if not function(
            ctypes.byref(source),
            None,
            None,
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(destination),
        ):
            operation = "CryptProtectData" if protect else "CryptUnprotectData"
            raise _last_windows_error(operation)

        try:
            return ctypes.string_at(destination.pbData, destination.cbData)
        finally:
            del source_buffer  # Keep the input allocation alive through the native call.
            if destination.pbData:
                kernel32.LocalFree(ctypes.cast(destination.pbData, wintypes.HLOCAL))


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


class _TokenUser(ctypes.Structure):
    _fields_ = [("User", _SidAndAttributes)]


def _current_user_sid() -> str:
    _require_windows()
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    token = wintypes.HANDLE()

    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.LPWSTR),
    ]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL

    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)
    ):
        raise _last_windows_error("OpenProcessToken")

    try:
        required = wintypes.DWORD()
        advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(required))
        if not required.value:
            raise _last_windows_error("GetTokenInformation")
        token_buffer = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(
            token,
            1,
            token_buffer,
            required,
            ctypes.byref(required),
        ):
            raise _last_windows_error("GetTokenInformation")

        token_user = ctypes.cast(token_buffer, ctypes.POINTER(_TokenUser)).contents
        sid_pointer = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(
            token_user.User.Sid, ctypes.byref(sid_pointer)
        ):
            raise _last_windows_error("ConvertSidToStringSidW")
        try:
            return sid_pointer.value
        finally:
            kernel32.LocalFree(ctypes.cast(sid_pointer, wintypes.HLOCAL))
    finally:
        kernel32.CloseHandle(token)


def restrict_to_current_user(path: Path) -> None:
    """Replace inherited file permissions with full access for this user SID."""

    _require_windows()
    sid = _current_user_sid()
    completed = subprocess.run(
        [
            "icacls.exe",
            str(path),
            "/inheritance:r",
            "/grant:r",
            f"*{sid}:(F)",
        ],
        capture_output=True,
        text=True,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise OSError(f"could not restrict secret file ACL: {detail}")


class DpapiSecretStore:
    def __init__(
        self,
        path: Path,
        *,
        backend: SecretBackend | None = None,
        acl: Callable[[Path], None] = restrict_to_current_user,
    ) -> None:
        self._path = Path(path)
        self._backend = backend if backend is not None else WindowsDpapiBackend()
        self._acl = acl

    def save(self, values: Mapping[str, str]) -> None:
        if not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in values.items()
        ):
            raise ValueError("secret keys and values must be strings")

        payload = json.dumps(
            {"version": _PAYLOAD_VERSION, "values": dict(values)},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if len(payload) > _MAX_PAYLOAD_BYTES:
            raise ValueError("secret payload must not exceed 64 KiB")

        protected = self._backend.protect(payload)
        if not protected:
            raise ValueError("protected secret payload must not be empty")
        if len(protected) > _MAX_PAYLOAD_BYTES:
            raise ValueError("protected secret payload must not exceed 64 KiB")

        self._path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self._path.parent,
            prefix=f".{self._path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as temporary:
                temporary.write(protected)
                temporary.flush()
                os.fsync(temporary.fileno())
            self._acl(temporary_path)
            os.replace(temporary_path, self._path)
        finally:
            temporary_path.unlink(missing_ok=True)

    def load(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        if self._path.stat().st_size > _MAX_PAYLOAD_BYTES:
            raise ValueError("protected secret payload must not exceed 64 KiB")
        protected = self._path.read_bytes()
        if not protected:
            raise ValueError("protected secret payload must not be empty")

        payload = self._backend.unprotect(protected)
        if not payload:
            raise ValueError("decrypted secret payload must not be empty")
        if len(payload) > _MAX_PAYLOAD_BYTES:
            raise ValueError("decrypted secret payload must not exceed 64 KiB")
        try:
            document = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("decrypted secret payload is not valid UTF-8 JSON") from exc

        if not isinstance(document, dict) or set(document) != {"version", "values"}:
            raise ValueError("decrypted secret payload has an invalid structure")
        if (
            type(document["version"]) is not int
            or document["version"] != _PAYLOAD_VERSION
        ):
            raise ValueError("decrypted secret payload has an unknown version")
        values = document["values"]
        if not isinstance(values, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in values.items()
        ):
            raise ValueError("secret keys and values must be strings")
        return dict(values)
