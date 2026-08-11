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
import defend_control.processes as processes_module
import defend_control.windows_job as windows_job_module
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


def test_start_waits_for_stop_all_lifecycle_boundary(fake_job):
    stopping = threading.Event()
    release = threading.Event()
    started = threading.Event()
    errors: list[BaseException] = []

    class BlockingProcess(FakeProcess):
        def terminate(self) -> None:
            stopping.set()
            release.wait(2)
            super().terminate()

    processes = [BlockingProcess(), FakeProcess()]

    def popen(*_args, **_kwargs):
        return processes.pop(0)

    supervisor = ProcessSupervisor(job=fake_job, popen=popen)
    supervisor.start(ProcessSpec("api", ("python", "api"), ROOT, {}, None))
    stop_thread = threading.Thread(target=supervisor.stop_all)
    stop_thread.start()
    assert stopping.wait(1)

    def start_web() -> None:
        try:
            supervisor.start(
                ProcessSpec("web", ("npm", "web"), ROOT, {}, None)
            )
        except BaseException as error:
            errors.append(error)
        finally:
            started.set()

    start_thread = threading.Thread(target=start_web)
    start_thread.start()
    try:
        assert not started.wait(0.1)
    finally:
        release.set()
        stop_thread.join(timeout=2)
        start_thread.join(timeout=2)

    assert started.is_set()
    assert errors == []
    assert [item.name for item in supervisor.snapshot()] == ["web"]


def test_reader_start_failure_rolls_back_owned_child_and_closes_pipes(
    fake_popen, fake_job, monkeypatch
):
    class FailingThread:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self) -> None:
            raise OSError("synthetic-private-thread-error")

    monkeypatch.setattr(processes_module.threading, "Thread", FailingThread)
    supervisor = ProcessSupervisor(job=fake_job, popen=fake_popen)

    with pytest.raises(RuntimeError) as raised:
        supervisor.start(
            ProcessSpec("api", ("python", "api"), ROOT, {}, None)
        )

    process = fake_popen.processes[0]
    assert process.terminate_called
    assert process.stdout.closed
    assert process.stderr.closed
    assert supervisor.snapshot() == ()
    assert "OSError" in str(raised.value)
    assert "synthetic-private-thread-error" not in str(raised.value)


def test_repeated_stop_restart_closes_streams_and_joins_readers(
    fake_popen, fake_job, monkeypatch
):
    readers: list[object] = []

    class TrackingThread:
        def __init__(self, **_kwargs) -> None:
            self.join_timeouts: list[float | None] = []
            readers.append(self)

        def start(self) -> None:
            return None

        def join(self, timeout: float | None = None) -> None:
            self.join_timeouts.append(timeout)

    monkeypatch.setattr(processes_module.threading, "Thread", TrackingThread)
    supervisor = ProcessSupervisor(job=fake_job, popen=fake_popen)

    for _ in range(2):
        process = supervisor.start(
            ProcessSpec("api", ("python", "api"), ROOT, {}, None)
        )
        assert supervisor.stop("api") is True
        assert process.stdout.closed
        assert process.stderr.closed

    assert len(readers) == 4
    assert all(reader.join_timeouts for reader in readers)
    assert all(
        timeout is not None and 0 < timeout <= 2
        for reader in readers
        for timeout in reader.join_timeouts
    )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Objects only")
def test_stop_catches_child_spawned_after_initial_descendant_snapshot(tmp_path):
    ready = tmp_path / "spawner-ready"
    pids = tmp_path / "spawned-pids"
    child_script = "import time;time.sleep(30)"
    parent_script = """
import os
import pathlib
import subprocess
import sys
import threading
import time

pids = pathlib.Path(os.environ["PIDS"])
lock = threading.Lock()

def spawn():
    return subprocess.Popen([sys.executable, "-c", os.environ["CHILD"]])

def record(pid):
    with lock:
        with pids.open("a", encoding="utf-8") as output:
            output.write(f"{pid}\\n")

def replace_after_exit(child):
    child.wait()
    replacement = spawn()
    record(replacement.pid)

children = [spawn() for _ in range(24)]
for child in children:
    record(child.pid)
    threading.Thread(
        target=replace_after_exit, args=(child,), daemon=True
    ).start()
pathlib.Path(os.environ["READY"]).write_text("ready", encoding="utf-8")
time.sleep(30)
"""
    supervisor = ProcessSupervisor(job=WindowsJob())
    observed: set[int] = set()
    try:
        supervisor.start(
            ProcessSpec(
                "late-spawner",
                (sys.executable, "-c", parent_script),
                ROOT,
                {
                    "CHILD": child_script,
                    "PIDS": str(pids),
                    "READY": str(ready),
                },
                None,
            )
        )
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists()

        started_stop = time.monotonic()
        assert supervisor.stop("late-spawner") is True
        assert time.monotonic() - started_stop < 10

        time.sleep(0.1)
        observed = {
            int(value)
            for value in pids.read_text(encoding="utf-8").splitlines()
            if value
        }
        assert observed
        assert all(not _windows_process_running(pid) for pid in observed)
    finally:
        supervisor.close()
        for pid in observed:
            if _windows_process_running(pid):
                _terminate_windows_process(pid)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Objects only")
def test_job_stop_finds_orphan_from_unknown_short_lived_intermediary(
    tmp_path,
):
    trigger = tmp_path / "spawn-intermediary"
    intermediary_done = tmp_path / "intermediary-done"
    grandchild_file = tmp_path / "unknown-grandchild.pid"
    intermediary_script = """
import os
import pathlib
import subprocess
import sys

child = subprocess.Popen(
    [sys.executable, "-c", "import time;time.sleep(30)"],
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
pathlib.Path(os.environ["GRANDCHILD_FILE"]).write_text(
    str(child.pid), encoding="utf-8"
)
"""
    root_script = """
import os
import pathlib
import subprocess
import sys
import time

trigger = pathlib.Path(os.environ["TRIGGER"])
while not trigger.exists():
    time.sleep(0.005)
subprocess.Popen(
    [sys.executable, "-c", os.environ["INTERMEDIARY_SCRIPT"]],
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    env=os.environ,
).wait()
pathlib.Path(os.environ["INTERMEDIARY_DONE"]).write_text(
    "done", encoding="utf-8"
)
time.sleep(30)
"""
    class RaceJob(WindowsJob):
        first_observation = True

        def _active_process_ids(self, job_handle: int) -> set[int]:
            process_ids = super()._active_process_ids(job_handle)
            if self.first_observation:
                self.first_observation = False
                trigger.write_text("spawn", encoding="utf-8")
                deadline = time.monotonic() + 5
                while (
                    not intermediary_done.exists()
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.005)
                assert intermediary_done.exists()
            return process_ids

    job = RaceJob()
    supervisor = ProcessSupervisor(job=job)
    grandchild_pid: int | None = None
    try:
        process = supervisor.start(
            ProcessSpec(
                "unknown-intermediary",
                (sys.executable, "-c", root_script),
                ROOT,
                {
                    "GRANDCHILD_FILE": str(grandchild_file),
                    "INTERMEDIARY_DONE": str(intermediary_done),
                    "INTERMEDIARY_SCRIPT": intermediary_script,
                    "TRIGGER": str(trigger),
                },
                None,
            )
        )
        job.terminate_tree(process)
        process.wait(timeout=3)
        assert intermediary_done.exists()
        grandchild_pid = int(grandchild_file.read_text(encoding="utf-8"))

        assert not _windows_process_running(grandchild_pid)
    finally:
        supervisor.close()
        if grandchild_pid is not None and _windows_process_running(grandchild_pid):
            _terminate_windows_process(grandchild_pid)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Objects only")
def test_stop_drains_job_descendant_after_root_already_exited(tmp_path):
    child_file = tmp_path / "exited-root-child.pid"
    root_script = """
import os
import pathlib
import subprocess
import sys

child = subprocess.Popen(
    [sys.executable, "-c", "import time;time.sleep(30)"],
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
pathlib.Path(os.environ["CHILD_FILE"]).write_text(
    str(child.pid), encoding="utf-8"
)
"""
    supervisor = ProcessSupervisor(job=WindowsJob())
    child_pid: int | None = None
    try:
        root = supervisor.start(
            ProcessSpec(
                "exited-root",
                (sys.executable, "-c", root_script),
                ROOT,
                {"CHILD_FILE": str(child_file)},
                None,
            )
        )
        root.wait(timeout=5)
        child_pid = int(child_file.read_text(encoding="utf-8"))
        assert _windows_process_running(child_pid)

        assert supervisor.stop("exited-root") is True

        assert not _windows_process_running(child_pid)
    finally:
        supervisor.close()
        if child_pid is not None and _windows_process_running(child_pid):
            _terminate_windows_process(child_pid)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Objects only")
@pytest.mark.parametrize("explicit_global", [False, True])
def test_named_stop_preserves_sibling_service_then_stop_all_kills_it(
    explicit_global,
):
    supervisor = ProcessSupervisor(
        job=WindowsJob() if explicit_global else None
    )
    first = supervisor.start(
        ProcessSpec(
            "probe-a",
            (sys.executable, "-c", "import time;time.sleep(30)"),
            ROOT,
            {},
            None,
        )
    )
    second = supervisor.start(
        ProcessSpec(
            "probe-b",
            (sys.executable, "-c", "import time;time.sleep(30)"),
            ROOT,
            {},
            None,
        )
    )
    try:
        assert supervisor.stop("probe-a") is True
        assert first.poll() is not None
        assert second.poll() is None
        assert [(item.name, item.running) for item in supervisor.snapshot()] == [
            ("probe-b", True)
        ]

        supervisor.stop_all()
        assert second.poll() is not None
    finally:
        supervisor.close()


def test_windows_job_enumeration_failure_is_not_treated_as_empty(monkeypatch):
    class FailingKernel:
        @staticmethod
        def QueryInformationJobObject(*_args) -> bool:
            return False

    job = object.__new__(WindowsJob)
    job._kernel32 = FailingKernel()
    job._lock = threading.Lock()
    job._handle = None
    monkeypatch.setattr(windows_job_module.ctypes, "get_last_error", lambda: 5)

    with pytest.raises(OSError):
        job._active_process_ids(123)


def test_windows_job_close_failure_preserves_native_handle():
    class CloseKernel:
        succeeds = False

        def CloseHandle(self, _handle: int) -> bool:
            return self.succeeds

    kernel = CloseKernel()
    job = object.__new__(WindowsJob)
    job._kernel32 = kernel
    job._lock = threading.Lock()
    job._handle = 123

    with pytest.raises(OSError):
        job.close()

    assert job._handle == 123
    kernel.succeeds = True
    job.close()
    assert job._handle is None


def test_stop_all_preserves_generation_when_native_job_close_fails(
    monkeypatch,
):
    jobs: list[object] = []

    class CloseKernel:
        def __init__(self, succeeds: bool) -> None:
            self.succeeds = succeeds

        def CloseHandle(self, _handle: int) -> bool:
            return self.succeeds

    class NativeCloseJob:
        def __init__(self) -> None:
            native = object.__new__(WindowsJob)
            native._kernel32 = CloseKernel(succeeds=bool(jobs))
            native._lock = threading.Lock()
            native._handle = 100 + len(jobs)
            self.native = native
            self.stop_fails = len(jobs) < 2
            jobs.append(self)

        def assign(self, _process: FakeProcess) -> None:
            return None

        def resume(self, _process: FakeProcess) -> None:
            return None

        def terminate_tree(self, process: FakeProcess) -> None:
            if self.stop_fails:
                raise OSError("synthetic-native-stop-detail")
            process.terminate()

        def close(self) -> None:
            self.native.close()

    monkeypatch.setattr(processes_module, "WindowsJob", NativeCloseJob)
    fake_popen = FakePopen()
    supervisor = ProcessSupervisor(popen=fake_popen)
    supervisor.start(ProcessSpec("api", ("python", "api"), ROOT, {}, None))

    with pytest.raises(RuntimeError) as raised:
        supervisor.stop_all()

    assert "OSError" in str(raised.value)
    assert "synthetic-native-stop-detail" not in str(raised.value)
    assert [item.name for item in supervisor.snapshot()] == ["api"]
    assert supervisor._job is jobs[0]
    assert jobs[0].native._handle == 100
    assert jobs[2].native._handle is None

    jobs[1].stop_fails = False
    jobs[0].native._kernel32.succeeds = True
    supervisor.stop_all()
    assert supervisor.snapshot() == ()
    supervisor.close()


def test_stop_all_retains_replacement_when_its_disposal_close_fails(
    monkeypatch,
):
    jobs: list[object] = []

    class CloseKernel:
        succeeds = False

        def CloseHandle(self, _handle: int) -> bool:
            return self.succeeds

    class NativeCloseJob:
        def __init__(self) -> None:
            native = object.__new__(WindowsJob)
            native._kernel32 = CloseKernel()
            native._lock = threading.Lock()
            native._handle = 200 + len(jobs)
            self.native = native
            self.stop_fails = not jobs
            jobs.append(self)

        def assign(self, _process: FakeProcess) -> None:
            return None

        def resume(self, _process: FakeProcess) -> None:
            return None

        def terminate_tree(self, process: FakeProcess) -> None:
            if self.stop_fails:
                raise OSError("synthetic-private-stop-detail")
            process.terminate()

        def close(self) -> None:
            self.native.close()

    monkeypatch.setattr(processes_module, "WindowsJob", NativeCloseJob)
    process = FakeProcess()
    supervisor = ProcessSupervisor(popen=lambda *_a, **_k: process)
    supervisor.start(ProcessSpec("api", ("python", "api"), ROOT, {}, None))

    with pytest.raises(RuntimeError) as raised:
        supervisor.stop_all()

    assert "OSError" in str(raised.value)
    assert "synthetic-private" not in str(raised.value)
    assert supervisor._job is jobs[0]
    assert supervisor._retained_jobs == [jobs[2]]
    assert [item.name for item in supervisor.snapshot()] == ["api"]

    jobs[0].stop_fails = False
    jobs[0].native._kernel32.succeeds = True
    jobs[1].native._kernel32.succeeds = True
    jobs[2].native._kernel32.succeeds = True
    supervisor.stop_all()
    assert jobs[2].native._handle is None
    jobs[3].native._kernel32.succeeds = True
    supervisor.close()


def test_supervisor_close_failure_preserves_retryable_state(monkeypatch):
    class FailOnceJob:
        def __init__(self) -> None:
            self.close_calls = 0

        def assign(self, _process: FakeProcess) -> None:
            return None

        def close(self) -> None:
            self.close_calls += 1
            if self.close_calls == 1:
                raise OSError("synthetic-private-close-detail")

    monkeypatch.setattr(processes_module, "WindowsJob", FailOnceJob)
    supervisor = ProcessSupervisor()
    job = supervisor._job
    supervisor.observe_external("observed", pid=901)

    with pytest.raises(RuntimeError) as raised:
        supervisor.close()

    assert "OSError" in str(raised.value)
    assert "synthetic-private" not in str(raised.value)
    assert [(item.name, item.owned) for item in supervisor.snapshot()] == [
        ("observed", False)
    ]
    assert job.close_calls == 1
    with pytest.raises(RuntimeError, match="closing"):
        supervisor.stop_all()
    assert job.close_calls == 1

    supervisor.close()
    assert job.close_calls == 2
    assert supervisor.snapshot() == ()


def test_supervisor_close_retries_service_job_before_terminal_state(monkeypatch):
    jobs: list[object] = []

    class FailServiceCloseOnceJob:
        def __init__(self) -> None:
            self.index = len(jobs)
            self.close_calls = 0
            jobs.append(self)

        def assign(self, _process: FakeProcess) -> None:
            return None

        def resume(self, _process: FakeProcess) -> None:
            return None

        def terminate_tree(self, process: FakeProcess) -> None:
            process.terminate()

        def close(self) -> None:
            self.close_calls += 1
            if self.index == 1 and self.close_calls == 1:
                raise OSError("synthetic-private-service-close-detail")

    monkeypatch.setattr(
        processes_module, "WindowsJob", FailServiceCloseOnceJob
    )
    process = FakeProcess()
    supervisor = ProcessSupervisor(popen=lambda *_a, **_k: process)
    supervisor.start(ProcessSpec("api", ("python", "api"), ROOT, {}, None))

    with pytest.raises(RuntimeError) as raised:
        supervisor.close()

    assert "OSError" in str(raised.value)
    assert "synthetic-private" not in str(raised.value)
    assert [item.name for item in supervisor.snapshot()] == ["api"]
    assert jobs[0].close_calls == 1
    assert jobs[1].close_calls == 1

    supervisor.close()
    assert jobs[1].close_calls == 2
    assert supervisor.snapshot() == ()


def test_reader_start_rollback_failure_keeps_live_process_tracked(
    fake_job, monkeypatch
):
    class UnstoppableProcess(FakeProcess):
        def terminate(self) -> None:
            raise OSError("synthetic-private-terminate-detail")

        def kill(self) -> None:
            raise OSError("synthetic-private-kill-detail")

    class FailingThread:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self) -> None:
            raise RuntimeError("synthetic-private-reader-detail")

    process = UnstoppableProcess()
    monkeypatch.setattr(processes_module.threading, "Thread", FailingThread)
    supervisor = ProcessSupervisor(job=fake_job, popen=lambda *_a, **_k: process)

    try:
        with pytest.raises(RuntimeError) as raised:
            supervisor.start(
                ProcessSpec("api", ("python", "api"), ROOT, {}, None)
            )

        assert [item.name for item in supervisor.snapshot()] == ["api"]
        assert supervisor.snapshot()[0].running
        assert "RuntimeError" in str(raised.value)
        assert "synthetic-private" not in str(raised.value)
    finally:
        process.returncode = -9
        supervisor.close()


def test_blocking_pipe_close_cannot_hold_lifecycle_lock_indefinitely(fake_job):
    close_started = threading.Event()
    release_close = threading.Event()
    stop_finished = threading.Event()
    stop_errors: list[BaseException] = []

    class BlockingCloseStream(StringIO):
        def close(self) -> None:
            close_started.set()
            release_close.wait(10)
            super().close()

    process = FakeProcess()
    process.stdout = BlockingCloseStream()
    process.stderr = BlockingCloseStream()
    supervisor = ProcessSupervisor(job=fake_job, popen=lambda *_a, **_k: process)
    supervisor.start(ProcessSpec("api", ("python", "api"), ROOT, {}, None))

    def stop() -> None:
        try:
            supervisor.stop("api")
        except BaseException as error:
            stop_errors.append(error)
        finally:
            stop_finished.set()

    started = time.monotonic()
    stop_thread = threading.Thread(target=stop)
    stop_thread.start()
    try:
        assert close_started.wait(1)
        assert stop_finished.wait(3)
        assert time.monotonic() - started < 3
    finally:
        release_close.set()
        stop_thread.join(timeout=2)
        supervisor.close()

    assert stop_errors == []


def test_repeated_blocking_teardown_retains_one_cleanup_until_release(fake_job):
    release_close = threading.Event()
    close_finished = [threading.Event(), threading.Event()]

    class BlockingCloseStream(StringIO):
        def __init__(self, finished: threading.Event) -> None:
            super().__init__()
            self.finished = finished
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1
            release_close.wait(10)
            super().close()
            self.finished.set()

    process = FakeProcess()
    streams = tuple(BlockingCloseStream(done) for done in close_finished)
    process.stdout, process.stderr = streams
    supervisor = ProcessSupervisor(job=fake_job, popen=lambda *_a, **_k: process)
    supervisor.start(ProcessSpec("api", ("python", "api"), ROOT, {}, None))

    cleanup_worker_ids: tuple[int, ...] | None = None
    try:
        for _ in range(3):
            started = time.monotonic()
            assert supervisor.stop("api") is True
            assert time.monotonic() - started < 3
            assert [(item.name, item.running) for item in supervisor.snapshot()] == [
                ("api", False)
            ]
            assert [stream.close_calls for stream in streams] == [1, 1]
            workers = supervisor._owned["api"].cleanup_threads
            assert len(workers) == 2
            current_ids = tuple(id(worker) for worker in workers)
            if cleanup_worker_ids is None:
                cleanup_worker_ids = current_ids
            assert current_ids == cleanup_worker_ids

        release_close.set()
        assert all(done.wait(2) for done in close_finished)
        assert supervisor.stop("api") is True
        assert supervisor.snapshot() == ()
    finally:
        release_close.set()
        supervisor.close()


def test_cleanup_worker_start_failure_retries_only_missing_worker(
    fake_job, monkeypatch
):
    created: list[object] = []

    class FlakyCleanupThread(threading.Thread):
        def __init__(self, **kwargs) -> None:
            super().__init__(**kwargs)
            self.fail_start = not created
            created.append(self)

        def start(self) -> None:
            if self.fail_start:
                raise RuntimeError("synthetic-private-cleanup-detail")
            super().start()

    monkeypatch.setattr(
        processes_module, "_CLEANUP_THREAD_CLASS", FlakyCleanupThread
    )
    process = FakeProcess()
    supervisor = ProcessSupervisor(job=fake_job, popen=lambda *_a, **_k: process)
    supervisor.start(ProcessSpec("api", ("python", "api"), ROOT, {}, None))

    assert supervisor.stop("api") is True
    assert [item.name for item in supervisor.snapshot()] == ["api"]
    assert len(created) == 2

    assert supervisor.stop("api") is True
    assert supervisor.snapshot() == ()
    assert len(created) == 3
    supervisor.close()


def test_stream_close_failure_retains_state_and_retries_only_failed_worker(
    fake_job, monkeypatch
):
    created_workers: list[threading.Thread] = []

    class TrackingCleanupThread(threading.Thread):
        def __init__(self, **kwargs) -> None:
            super().__init__(**kwargs)
            created_workers.append(self)

    class FailOnceCloseStream(StringIO):
        def __init__(self) -> None:
            super().__init__()
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1
            if self.close_calls == 1:
                raise OSError("synthetic-private-stream-close-detail")
            super().close()

    class CountingCloseStream(StringIO):
        def __init__(self) -> None:
            super().__init__()
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1
            super().close()

    monkeypatch.setattr(
        processes_module, "_CLEANUP_THREAD_CLASS", TrackingCleanupThread
    )
    failed_stream = FailOnceCloseStream()
    successful_stream = CountingCloseStream()
    process = FakeProcess()
    process.stdout = failed_stream
    process.stderr = successful_stream
    supervisor = ProcessSupervisor(job=fake_job, popen=lambda *_a, **_k: process)
    supervisor.start(ProcessSpec("api", ("python", "api"), ROOT, {}, None))

    try:
        started = time.monotonic()
        with pytest.raises(RuntimeError) as raised:
            supervisor.stop("api")
        assert time.monotonic() - started < 1
        assert "OSError" in str(raised.value)
        assert "synthetic-private-stream-close-detail" not in str(raised.value)
        assert [(item.name, item.running) for item in supervisor.snapshot()] == [
            ("api", False)
        ]
        owned = supervisor._owned["api"]
        assert owned.streams == (failed_stream, successful_stream)
        assert failed_stream.close_calls == 1
        assert successful_stream.close_calls == 1
        assert len(created_workers) == 2
        assert owned.cleanup_threads[0] is None
        assert owned.cleanup_threads[1] is created_workers[1]

        started = time.monotonic()
        assert supervisor.stop("api") is True
        assert time.monotonic() - started < 1
        assert supervisor.snapshot() == ()
        assert failed_stream.close_calls == 2
        assert successful_stream.close_calls == 1
        assert len(created_workers) == 3
        assert [worker.name for worker in created_workers] == [
            "defend-api-close-0",
            "defend-api-close-1",
            "defend-api-close-0",
        ]
    finally:
        supervisor.close()
