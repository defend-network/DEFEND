from __future__ import annotations

import ctypes
from ctypes import wintypes
from io import StringIO
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

import defend_control.health as health_module
from defend_control.health import probe_http
from defend_control.processes import LogBuffer, ProcessSpec, ProcessSupervisor
from defend_control.windows_job import WindowsJob


ROOT = Path(__file__).resolve().parents[1]


class FakeProcess:
    next_pid = 100

    def __init__(self, *, stdout: str = "", stderr: str = "") -> None:
        self.pid = FakeProcess.next_pid
        FakeProcess.next_pid += 1
        self.stdout = StringIO(stdout)
        self.stderr = StringIO(stderr)
        self.returncode: int | None = None
        self.terminate_called = False
        self.kill_called = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminate_called = True
        self.returncode = 0

    def kill(self) -> None:
        self.kill_called = True
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            raise subprocess.TimeoutExpired("synthetic", timeout)
        return self.returncode


class FakePopen:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], dict[str, object]]] = []
        self.processes: list[FakeProcess] = []

    def __call__(self, argv, **kwargs) -> FakeProcess:
        process = FakeProcess()
        self.calls.append((tuple(argv), kwargs))
        self.processes.append(process)
        return process


class FakeJob:
    def __init__(self) -> None:
        self.assigned_pids: list[int] = []
        self.terminated_pids: list[int] = []
        self.operations: list[tuple[str, int]] = []

    def assign(self, process: FakeProcess) -> None:
        self.assigned_pids.append(process.pid)
        self.operations.append(("assign", process.pid))

    def resume(self, process: FakeProcess) -> None:
        self.operations.append(("resume", process.pid))

    def close(self) -> None:
        return None


@pytest.fixture
def fake_popen() -> FakePopen:
    return FakePopen()


@pytest.fixture
def fake_job() -> FakeJob:
    return FakeJob()


def test_stop_all_terminates_only_owned_handles(fake_popen, fake_job):
    supervisor = ProcessSupervisor(job=fake_job, popen=fake_popen)
    api = supervisor.start(
        ProcessSpec("api", ("python", "api_server.py"), ROOT, {}, None)
    )
    supervisor.observe_external("cloudflare", pid=999)
    supervisor.stop_all()
    assert api.terminate_called
    assert 999 not in fake_job.terminated_pids


def test_log_buffer_redacts_and_bounds_entries():
    logs = LogBuffer(max_entries=2, max_line_chars=80, known_secrets=["hf_secret"])
    logs.append("api", "token=hf_secret")
    logs.append("api", "safe-2")
    logs.append("api", "safe-3")
    assert len(logs.snapshot()) == 2
    assert "hf_secret" not in repr(logs.snapshot())


def test_start_uses_owned_job_process_group_and_allowlisted_environment(
    fake_popen, fake_job, monkeypatch
):
    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")
    monkeypatch.setenv("PATH", r"C:\Windows\System32")
    monkeypatch.setenv("UNRELATED_PARENT_SECRET", "must-not-be-inherited")
    supervisor = ProcessSupervisor(job=fake_job, popen=fake_popen)
    spec = ProcessSpec(
        "api",
        ("python", "api_server.py"),
        ROOT,
        {"HF_TOKEN": "synthetic-private-value", "DEFEND_DATA_ROOT": "C:/data"},
        None,
    )

    process = supervisor.start(spec)

    argv, kwargs = fake_popen.calls[0]
    assert argv == ("python", "api_server.py")
    assert kwargs["creationflags"] & subprocess.CREATE_NEW_PROCESS_GROUP
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stdout"] is subprocess.PIPE
    assert kwargs["stderr"] is subprocess.PIPE
    assert kwargs["text"] is True
    child_env = kwargs["env"]
    assert child_env["PATH"] == r"C:\Windows\System32"
    assert child_env["SYSTEMROOT"] == r"C:\Windows"
    assert child_env["DEFEND_DATA_ROOT"] == "C:/data"
    assert child_env["HF_TOKEN"] == "synthetic-private-value"
    assert "UNRELATED_PARENT_SECRET" not in child_env
    assert fake_job.assigned_pids == [process.pid]
    assert fake_job.operations == [("assign", process.pid), ("resume", process.pid)]
    assert kwargs["creationflags"] & 0x00000004


def test_start_rejects_environment_secret_in_argv_before_spawning(
    fake_popen, fake_job
):
    supervisor = ProcessSupervisor(job=fake_job, popen=fake_popen)
    spec = ProcessSpec(
        "remote",
        ("tool", "--token=synthetic-private-value"),
        ROOT,
        {"HF_TOKEN": "synthetic-private-value"},
        None,
    )

    with pytest.raises(ValueError, match="environment only"):
        supervisor.start(spec)

    assert fake_popen.calls == []
    assert fake_job.assigned_pids == []


def test_start_rejects_secret_shaped_argv_without_environment_copy(
    fake_popen, fake_job
):
    supervisor = ProcessSupervisor(job=fake_job, popen=fake_popen)
    spec = ProcessSpec(
        "remote",
        ("tool", "--api-key=synthetic-private-value"),
        ROOT,
        {},
        None,
    )

    with pytest.raises(ValueError, match="environment only"):
        supervisor.start(spec)

    assert fake_popen.calls == []


def test_external_process_is_never_stopped_or_assigned(fake_popen, fake_job):
    supervisor = ProcessSupervisor(job=fake_job, popen=fake_popen)
    supervisor.observe_external("cloudflare", pid=999)

    assert supervisor.stop("cloudflare") is False
    assert fake_job.assigned_pids == []
    assert fake_job.terminated_pids == []
    snapshot = supervisor.snapshot()
    assert snapshot[0].name == "cloudflare"
    assert snapshot[0].pid == 999
    assert snapshot[0].owned is False


def test_snapshot_never_contains_argv_or_environment(fake_popen, fake_job):
    supervisor = ProcessSupervisor(job=fake_job, popen=fake_popen)
    supervisor.start(
        ProcessSpec(
            "api",
            ("python", "api_server.py"),
            ROOT,
            {"HF_TOKEN": "synthetic-private-value"},
            "http://127.0.0.1:8000/health",
        )
    )

    rendered = repr(supervisor.snapshot())
    assert "synthetic-private-value" not in rendered
    assert "api_server.py" not in rendered


def test_process_spec_representation_hides_argv_and_environment():
    spec = ProcessSpec(
        "api",
        ("python", "--token=synthetic-private-value"),
        ROOT,
        {"HF_TOKEN": "synthetic-private-value"},
        None,
    )

    rendered = repr(spec)
    assert "synthetic-private-value" not in rendered
    assert "--token" not in rendered


def test_start_failure_reports_safe_type_without_command_or_secret(fake_job):
    def failing_popen(*_args, **_kwargs):
        raise OSError("synthetic-private-value in api_server.py")

    supervisor = ProcessSupervisor(job=fake_job, popen=failing_popen)

    with pytest.raises(RuntimeError) as raised:
        supervisor.start(
            ProcessSpec(
                "api",
                ("python", "api_server.py"),
                ROOT,
                {"HF_TOKEN": "synthetic-private-value"},
                None,
            )
        )

    rendered = str(raised.value)
    assert "OSError" in rendered
    assert "synthetic-private-value" not in rendered
    assert "api_server.py" not in rendered


def test_stop_all_runs_in_reverse_start_order(fake_popen, fake_job):
    stopped: list[str] = []

    class OrderedProcess(FakeProcess):
        def __init__(self, name: str) -> None:
            super().__init__()
            self.name = name

        def terminate(self) -> None:
            stopped.append(self.name)
            super().terminate()

    def popen(argv, **_kwargs):
        return OrderedProcess(str(argv[1]))

    supervisor = ProcessSupervisor(job=fake_job, popen=popen)
    supervisor.start(ProcessSpec("api", ("python", "api"), ROOT, {}, None))
    supervisor.start(ProcessSpec("web", ("npm", "web"), ROOT, {}, None))

    supervisor.stop_all()

    assert stopped == ["web", "api"]


def test_log_buffer_redacts_before_character_bound_and_escapes_line_breaks():
    logs = LogBuffer(max_entries=3, max_line_chars=12, known_secrets=["secret-value"])

    logs.append("api", "safe\nsecret-value-and-more")

    entry = logs.snapshot()[0]
    assert "secret-value" not in repr(entry)
    assert "\n" not in entry.text
    assert len(entry.text) <= 12


def test_log_reader_bounds_physical_lines_before_buffering(fake_popen, fake_job):
    logs = LogBuffer(max_entries=3, max_line_chars=80)
    supervisor = ProcessSupervisor(job=fake_job, popen=fake_popen, logs=logs)

    class OversizedLine:
        def __init__(self) -> None:
            self.read_sizes: list[int] = []
            self.calls = 0

        def readline(self, size: int = -1) -> str:
            self.read_sizes.append(size)
            self.calls += 1
            return "x" * size if self.calls == 1 else ""

    stream = OversizedLine()
    supervisor._read_stream("api", "stdout", stream)

    assert stream.read_sizes
    assert all(0 < size <= 64 * 1024 + 1 for size in stream.read_sizes)
    assert "xxxx" not in repr(logs.snapshot())
    assert "oversized" in repr(logs.snapshot()).casefold()


class FakeResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self.body = body
        self.read_sizes: list[int] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        return self.body[:size]


def install_fake_opener(monkeypatch, action):
    class FakeOpener:
        def open(self, *_args, **_kwargs):
            if isinstance(action, BaseException):
                raise action
            if callable(action):
                return action()
            return action

    monkeypatch.setattr(
        health_module, "build_opener", lambda *_handlers: FakeOpener()
    )


def test_probe_rejects_non_loopback_http_without_network_call(monkeypatch):
    called = False

    def unexpected_call(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("network must not be called")

    install_fake_opener(monkeypatch, unexpected_call)

    result = probe_http("http://example.test/health", 1)

    assert not result.ok
    assert result.error_type == "UnsafeUrl"
    assert called is False


def test_probe_allows_only_configured_https_public_origin_and_bounds_read(
    monkeypatch,
):
    response = FakeResponse(200, b"x" * (128 * 1024))
    install_fake_opener(monkeypatch, response)

    rejected = probe_http(
        "https://other.example/health",
        1,
        public_origin="https://ai.defend-network.org",
    )
    accepted = probe_http(
        "https://ai.defend-network.org/health",
        1,
        public_origin="https://ai.defend-network.org",
    )

    assert not rejected.ok
    assert rejected.error_type == "UnsafeUrl"
    assert accepted.ok
    assert accepted.status_code == 200
    assert response.read_sizes == [64 * 1024]


def test_probe_never_exposes_response_body_or_exception_message(monkeypatch):
    secret = "synthetic-private-response"

    class SyntheticNetworkError(OSError):
        pass

    install_fake_opener(monkeypatch, SyntheticNetworkError(secret))

    result = probe_http("http://127.0.0.1:8000/health", 1)

    assert not result.ok
    assert result.error_type == "SyntheticNetworkError"
    assert secret not in repr(result)


def test_probe_non_success_status_discards_bounded_body(monkeypatch):
    response = FakeResponse(503, b"synthetic-private-response")
    install_fake_opener(monkeypatch, response)

    result = probe_http("http://127.0.0.1:8000/health", 1)

    assert not result.ok
    assert result.status_code == 503
    assert result.error_type is None
    assert "synthetic-private-response" not in repr(result)
    assert response.read_sizes == [64 * 1024]


def test_probe_installs_redirect_blocker_before_opening(monkeypatch):
    response = FakeResponse(200, b"ok")
    observed_handlers: list[object] = []

    class FakeOpener:
        def open(self, *_args, **_kwargs):
            return response

    def capture_build_opener(*handlers):
        observed_handlers.extend(handlers)
        return FakeOpener()

    monkeypatch.setattr(health_module, "build_opener", capture_build_opener)

    result = probe_http("http://127.0.0.1:8000/health", 1)

    assert result.ok
    assert len(observed_handlers) == 1
    blocker = observed_handlers[0]
    assert blocker.redirect_request(None, None, 302, "redirect", {}, "http://x") is None


def test_probe_timeout_is_an_end_to_end_deadline(monkeypatch):
    release = threading.Event()

    class SlowResponse(FakeResponse):
        def read(self, size: int = -1) -> bytes:
            release.wait(2)
            return super().read(size)

    install_fake_opener(monkeypatch, SlowResponse(200, b"ok"))
    started = time.monotonic()
    try:
        result = probe_http("http://127.0.0.1:8000/health", 0.05)
    finally:
        release.set()

    assert time.monotonic() - started < 0.5
    assert not result.ok
    assert result.error_type == "TimeoutError"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Objects only")
def test_real_windows_job_accepts_and_stops_owned_child():
    supervisor = ProcessSupervisor(job=WindowsJob())
    process = supervisor.start(
        ProcessSpec(
            "boundary-child",
            (sys.executable, "-c", "import time; time.sleep(30)"),
            ROOT,
            {},
            None,
        )
    )
    try:
        assert process.poll() is None
        assert supervisor.stop("boundary-child") is True
        assert process.poll() is not None
    finally:
        supervisor.close()


def _windows_process_running(pid: int) -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x00100000, False, pid)
    if not handle:
        return False
    try:
        return kernel32.WaitForSingleObject(handle, 0) == 0x00000102
    finally:
        kernel32.CloseHandle(handle)


def _terminate_windows_process(pid: int) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(0x0001, False, pid)
    if handle:
        try:
            kernel32.TerminateProcess(handle, 1)
        finally:
            kernel32.CloseHandle(handle)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process groups only")
def test_stop_terminates_owned_grandchild_process_group(tmp_path):
    pid_file = tmp_path / "grandchild.pid"
    script = (
        "import os,pathlib,subprocess,sys,time;"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);"
        "pathlib.Path(os.environ['PID_FILE']).write_text(str(child.pid));"
        "time.sleep(30)"
    )
    supervisor = ProcessSupervisor(job=WindowsJob())
    grandchild_pid: int | None = None
    try:
        supervisor.start(
            ProcessSpec(
                "parent-child-tree",
                (sys.executable, "-c", script),
                ROOT,
                {"PID_FILE": str(pid_file)},
                None,
            )
        )
        deadline = time.monotonic() + 5
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        grandchild_pid = int(pid_file.read_text(encoding="utf-8"))
        assert _windows_process_running(grandchild_pid)

        assert supervisor.stop("parent-child-tree") is True

        deadline = time.monotonic() + 3
        while _windows_process_running(grandchild_pid) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not _windows_process_running(grandchild_pid)
    finally:
        supervisor.close()
        if grandchild_pid is not None and _windows_process_running(grandchild_pid):
            _terminate_windows_process(grandchild_pid)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Objects only")
def test_stop_all_job_fallback_kills_isolated_group_descendant(tmp_path):
    pid_file = tmp_path / "isolated-grandchild.pid"
    child_script = "import time;time.sleep(30)"
    parent_script = (
        "import os,pathlib,subprocess,sys,time;"
        "child=subprocess.Popen([sys.executable,'-c',os.environ['CHILD_SCRIPT']],"
        "creationflags=subprocess.CREATE_NEW_PROCESS_GROUP);"
        "pathlib.Path(os.environ['PID_FILE']).write_text(str(child.pid));"
        "time.sleep(30)"
    )
    supervisor = ProcessSupervisor()
    grandchild_pid: int | None = None
    try:
        supervisor.start(
            ProcessSpec(
                "isolated-child-group-tree",
                (sys.executable, "-c", parent_script),
                ROOT,
                {"CHILD_SCRIPT": child_script, "PID_FILE": str(pid_file)},
                None,
            )
        )
        deadline = time.monotonic() + 5
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        grandchild_pid = int(pid_file.read_text(encoding="utf-8"))
        assert _windows_process_running(grandchild_pid)

        supervisor.stop_all()

        deadline = time.monotonic() + 3
        while _windows_process_running(grandchild_pid) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not _windows_process_running(grandchild_pid)
        restarted = supervisor.start(
            ProcessSpec(
                "restart-boundary",
                (sys.executable, "-c", "pass"),
                ROOT,
                {},
                None,
            )
        )
        restarted.wait(timeout=5)
    finally:
        supervisor.close()
        if grandchild_pid is not None and _windows_process_running(grandchild_pid):
            _terminate_windows_process(grandchild_pid)
