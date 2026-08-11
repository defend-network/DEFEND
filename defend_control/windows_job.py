from __future__ import annotations

import ctypes
from ctypes import wintypes
import sys
import threading
from typing import Protocol


_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_TH32CS_SNAPTHREAD = 0x00000004
_TH32CS_SNAPPROCESS = 0x00000002
_THREAD_SUSPEND_RESUME = 0x0002
_PROCESS_TERMINATE = 0x0001
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_SYNCHRONIZE = 0x00100000
_INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value


class _ProcessHandle(Protocol):
    pid: int
    _handle: int


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _ThreadEntry32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", wintypes.LONG),
        ("tpDeltaPri", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
    ]


class _ProcessEntry32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class WindowsJob:
    """One Windows Job Object that kills only explicitly assigned children."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise OSError("Windows Job Objects are available only on Windows")
        self._lock = threading.Lock()
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self._kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        self._kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        self._kernel32.SetInformationJobObject.restype = wintypes.BOOL
        self._kernel32.AssignProcessToJobObject.argtypes = [
            wintypes.HANDLE,
            wintypes.HANDLE,
        ]
        self._kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.CloseHandle.restype = wintypes.BOOL
        self._kernel32.CreateToolhelp32Snapshot.argtypes = [
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        self._kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        self._kernel32.Thread32First.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_ThreadEntry32),
        ]
        self._kernel32.Thread32First.restype = wintypes.BOOL
        self._kernel32.Thread32Next.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_ThreadEntry32),
        ]
        self._kernel32.Thread32Next.restype = wintypes.BOOL
        self._kernel32.OpenThread.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        self._kernel32.OpenThread.restype = wintypes.HANDLE
        self._kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
        self._kernel32.ResumeThread.restype = wintypes.DWORD
        self._kernel32.Process32FirstW.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_ProcessEntry32),
        ]
        self._kernel32.Process32FirstW.restype = wintypes.BOOL
        self._kernel32.Process32NextW.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_ProcessEntry32),
        ]
        self._kernel32.Process32NextW.restype = wintypes.BOOL
        self._kernel32.OpenProcess.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        self._kernel32.OpenProcess.restype = wintypes.HANDLE
        self._kernel32.IsProcessInJob.argtypes = [
            wintypes.HANDLE,
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.BOOL),
        ]
        self._kernel32.IsProcessInJob.restype = wintypes.BOOL
        self._kernel32.TerminateProcess.argtypes = [
            wintypes.HANDLE,
            wintypes.UINT,
        ]
        self._kernel32.TerminateProcess.restype = wintypes.BOOL

        handle = self._kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise OSError("CreateJobObjectW failed")
        self._handle: int | None = handle
        limits = _ExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = (
            _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        if not self._kernel32.SetInformationJobObject(
            handle,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            self._kernel32.CloseHandle(handle)
            self._handle = None
            raise OSError("SetInformationJobObject failed")

    def assign(self, process: _ProcessHandle) -> None:
        process_handle = getattr(process, "_handle", None)
        if process_handle is None:
            raise TypeError("process must expose a Windows process handle")
        with self._lock:
            if self._handle is None:
                raise RuntimeError("Windows Job Object is closed")
            if not self._kernel32.AssignProcessToJobObject(
                self._handle, wintypes.HANDLE(process_handle)
            ):
                raise OSError("AssignProcessToJobObject failed")

    def resume(self, process: _ProcessHandle) -> None:
        snapshot = self._kernel32.CreateToolhelp32Snapshot(
            _TH32CS_SNAPTHREAD, 0
        )
        if snapshot == _INVALID_HANDLE_VALUE:
            raise OSError("CreateToolhelp32Snapshot failed")
        resumed = 0
        try:
            entry = _ThreadEntry32()
            entry.dwSize = ctypes.sizeof(entry)
            available = self._kernel32.Thread32First(snapshot, ctypes.byref(entry))
            while available:
                if entry.th32OwnerProcessID == process.pid:
                    thread = self._kernel32.OpenThread(
                        _THREAD_SUSPEND_RESUME, False, entry.th32ThreadID
                    )
                    if thread:
                        try:
                            if self._kernel32.ResumeThread(thread) != 0xFFFFFFFF:
                                resumed += 1
                        finally:
                            self._kernel32.CloseHandle(thread)
                available = self._kernel32.Thread32Next(
                    snapshot, ctypes.byref(entry)
                )
        finally:
            self._kernel32.CloseHandle(snapshot)
        if resumed == 0:
            raise OSError("Could not resume the owned process")

    def terminate_tree(self, process: _ProcessHandle) -> None:
        snapshot = self._kernel32.CreateToolhelp32Snapshot(
            _TH32CS_SNAPPROCESS, 0
        )
        if snapshot == _INVALID_HANDLE_VALUE:
            raise OSError("CreateToolhelp32Snapshot failed")
        children: dict[int, list[int]] = {}
        try:
            entry = _ProcessEntry32()
            entry.dwSize = ctypes.sizeof(entry)
            available = self._kernel32.Process32FirstW(
                snapshot, ctypes.byref(entry)
            )
            while available:
                children.setdefault(int(entry.th32ParentProcessID), []).append(
                    int(entry.th32ProcessID)
                )
                available = self._kernel32.Process32NextW(
                    snapshot, ctypes.byref(entry)
                )
        finally:
            self._kernel32.CloseHandle(snapshot)

        targets: list[int] = []

        def collect(pid: int) -> None:
            for child_pid in children.get(pid, ()):
                collect(child_pid)
            targets.append(pid)

        collect(int(process.pid))
        with self._lock:
            if self._handle is None:
                raise RuntimeError("Windows Job Object is closed")
            job_handle = self._handle
            for pid in targets:
                handle = self._kernel32.OpenProcess(
                    _PROCESS_TERMINATE
                    | _PROCESS_QUERY_LIMITED_INFORMATION
                    | _SYNCHRONIZE,
                    False,
                    pid,
                )
                if not handle:
                    continue
                try:
                    in_job = wintypes.BOOL()
                    if (
                        self._kernel32.IsProcessInJob(
                            handle, job_handle, ctypes.byref(in_job)
                        )
                        and in_job.value
                    ):
                        self._kernel32.TerminateProcess(handle, 1)
                finally:
                    self._kernel32.CloseHandle(handle)

    def close(self) -> None:
        with self._lock:
            handle = self._handle
            self._handle = None
        if handle is not None:
            self._kernel32.CloseHandle(handle)

    def __enter__(self) -> "WindowsJob":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
