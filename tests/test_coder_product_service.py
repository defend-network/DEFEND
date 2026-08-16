from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from defend_control.products import (
    CoderService,
    ProductsSettings,
    build_coder_api_process_spec,
    build_coder_web_process_spec,
)


class FakeLogs:
    def __init__(self):
        self.entries = []
        self.known = []

    def add_known_secrets(self, values):
        self.known.extend(values)

    def snapshot(self):
        return tuple(self.entries)


class FakeSupervisor:
    def __init__(self):
        self.started = []
        self.stopped = []
        self.logs = FakeLogs()
        self._running = set()

    def start(self, spec):
        self.started.append(spec)
        self._running.add(spec.name)

    def stop(self, name):
        self.stopped.append(name)
        self._running.discard(name)

    def snapshot(self):
        return tuple(
            SimpleNamespace(
                name=name,
                running=True,
            )
            for name in sorted(self._running)
        )


class ReadyProbe:
    def __call__(self, url, timeout):
        return SimpleNamespace(
            ok=True,
            data={
                "ok": True,
                "application_id": "coder",
            },
            latency_ms=1,
            error_type=None,
        )


def settings():
    return ProductsSettings(
        coder_api_port=8301,
        coder_web_port=3301,
        coder_public_origin="https://defendcoder.defend-network.org",
        coder_database_url="postgresql://synthetic/test",
        coder_workspace_root=Path(r"C:\DEFEND_CODER_DATA"),
    )


def test_coder_api_spec_launches_real_server_without_secret_argv(tmp_path):
    spec = build_coder_api_process_spec(
        settings(),
        tmp_path,
        r"C:\Python\python.exe",
    )

    assert spec.name == "coder:api"
    assert spec.argv == (
        r"C:\Python\python.exe",
        "-m",
        "tools.defend_coder_server",
    )

    assert spec.env["CODER_DATABASE_URL"] == "postgresql://synthetic/test"
    assert spec.env["CODER_PORT"] == "8301"
    assert spec.env["CODER_WORKSPACE_ROOT"] == r"C:\DEFEND_CODER_DATA"

    assert "postgresql://synthetic/test" not in " ".join(spec.argv)


def test_coder_web_spec_launches_next_ui(tmp_path):
    spec = build_coder_web_process_spec(
        settings(),
        tmp_path,
    )

    assert spec.name == "coder:web"
    assert spec.cwd == tmp_path / "defendcoder-ui"
    assert spec.argv[0].lower().endswith("npm.cmd")
    assert spec.argv[1:] == ("run", "start")
    assert spec.env["PORT"] == "3301"
    assert spec.env["DEFENDCODER_INTERNAL_API_URL"] == "http://127.0.0.1:8301"


def test_start_starts_only_owned_coder_api_and_web(tmp_path):
    supervisor = FakeSupervisor()

    service = CoderService(
        settings(),
        supervisor=supervisor,
        repository=tmp_path,
        python_executable=r"C:\Python\python.exe",
        probe=ReadyProbe(),
    )

    result = service.start()

    assert [spec.name for spec in supervisor.started] == [
        "coder:api",
        "coder:web",
    ]
    assert result.launch_available is True
    assert result.stop_available is True


def test_start_is_idempotent_when_services_already_running(tmp_path):
    supervisor = FakeSupervisor()

    service = CoderService(
        settings(),
        supervisor=supervisor,
        repository=tmp_path,
        python_executable=r"C:\Python\python.exe",
        probe=ReadyProbe(),
    )

    service.start()
    service.start()

    assert [spec.name for spec in supervisor.started] == [
        "coder:api",
        "coder:web",
    ]


def test_stop_stops_only_coder_services(tmp_path):
    supervisor = FakeSupervisor()

    service = CoderService(
        settings(),
        supervisor=supervisor,
        repository=tmp_path,
        python_executable=r"C:\Python\python.exe",
        probe=ReadyProbe(),
    )

    service.start()
    service.stop()

    assert supervisor.stopped == [
        "coder:web",
        "coder:api",
    ]


def test_database_secret_is_registered_for_log_redaction(tmp_path):
    supervisor = FakeSupervisor()

    service = CoderService(
        settings(),
        supervisor=supervisor,
        repository=tmp_path,
        python_executable=r"C:\Python\python.exe",
        probe=ReadyProbe(),
    )

    service.start()

    assert "postgresql://synthetic/test" in supervisor.logs.known


def test_status_reports_local_services_and_observation_without_inventing_values(
    tmp_path,
):
    supervisor = FakeSupervisor()

    observation = {
        "state": "ready",
        "alias": "defendcoder-default",
        "gpu_name": "H100 NVL",
        "instance_id": "instance-123",
    }

    service = CoderService(
        settings(),
        supervisor=supervisor,
        repository=tmp_path,
        python_executable=r"C:\Python\python.exe",
        observation=observation,
        probe=ReadyProbe(),
    )

    service.start()
    result = service.status()

    details = dict(result.details)

    assert details["API"] == "running"
    assert details["Web"] == "running"
    assert details["Alias"] == "defendcoder-default"
    assert details["GPU"] == "H100 NVL"
    assert details["Instance"] == "instance-123"
    assert details["$/hr"] == "\u2014"
    assert details["Session cost"] == "\u2014"


def test_logs_only_return_coder_service_entries(tmp_path):
    supervisor = FakeSupervisor()
    supervisor.logs.entries = [
        SimpleNamespace(service="coder:api:stdout", text="api"),
        SimpleNamespace(service="sports:api:stdout", text="sports"),
        SimpleNamespace(service="coder:web:stderr", text="web"),
    ]

    service = CoderService(
        settings(),
        supervisor=supervisor,
        repository=tmp_path,
        python_executable=r"C:\Python\python.exe",
        probe=ReadyProbe(),
    )

    assert [entry.text for entry in service.logs()] == ["api", "web"]


def test_launch_does_not_call_provider_or_create_gpu_instance(tmp_path):
    supervisor = FakeSupervisor()

    class ObservationOnly:
        def status(self):
            return {
                "state": "ready",
                "alias": "defendcoder-default",
            }

    observation = ObservationOnly()

    service = CoderService(
        settings(),
        supervisor=supervisor,
        repository=tmp_path,
        python_executable=r"C:\Python\python.exe",
        observation=observation,
        probe=ReadyProbe(),
    )

    service.start()

    assert [spec.name for spec in supervisor.started] == [
        "coder:api",
        "coder:web",
    ]
