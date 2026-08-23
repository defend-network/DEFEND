from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from defend_control.products import (
    ProductsSettings,
    ScsService,
    build_scs_ai_process_spec,
    build_scs_api_process_spec,
    build_scs_web_process_spec,
)


class FakeLogs:
    def __init__(self):
        self.entries = []

    def snapshot(self):
        return tuple(self.entries)


class FakeSupervisor:
    def __init__(self):
        self.started = []
        self.stopped = []
        self._running = set()
        self.logs = FakeLogs()

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


class FakeTunnel:
    def __init__(self):
        self.started = 0
        self.stopped = 0
        self.state = "stopped"

    def start(self):
        self.started += 1
        self.state = "connected"
        return SimpleNamespace(
            state="connected",
            enabled=True,
            pid=123,
            returncode=None,
            detail="",
        )

    def stop(self):
        self.stopped += 1
        self.state = "stopped"
        return SimpleNamespace(
            state="stopped",
            enabled=True,
            pid=None,
            returncode=0,
            detail="",
        )

    def status(self):
        return SimpleNamespace(
            state=self.state,
            enabled=True,
            pid=123 if self.state == "connected" else None,
            returncode=None,
            detail="",
        )

    def logs(self):
        return (("tunnel", "safe tunnel log"),)


class ReadyProbe:
    def __call__(self, url, timeout):
        return SimpleNamespace(
            ok=True,
            data={
                "ok": True,
                "application_id": "scs-ai",
            },
            latency_ms=1,
            error_type=None,
        )


def settings():
    return ProductsSettings(
        scs_ai_api_port=8300,
        scs_ai_web_port=3300,
        scs_ai_public_origin="https://ai.sunshineclimatesolutions.com",
    )


def test_scs_ai_process_spec_uses_dedicated_8300_lane(tmp_path):
    spec = build_scs_ai_process_spec(
        settings(),
        tmp_path,
        r"C:\Python\python.exe",
    )

    assert spec.name == "scs-ai:api"
    assert spec.argv == (
        r"C:\Python\python.exe",
        "-m",
        "uvicorn",
        "scs_ai.runtime:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8300",
    )
    assert spec.env["SCS_AI_API_PORT"] == "8300"
    assert spec.env["SCS_AI_WEB_PORT"] == "3300"


def test_scs_ai_process_spec_passes_model_config_without_secrets(tmp_path):
    spec = build_scs_ai_process_spec(
        settings(),
        tmp_path,
        r"C:\Python\python.exe",
    )
    assert "SCS_AI_MODEL_API_KEY" not in spec.env
    assert "SCS_AI_MODEL_BASE_URL" not in spec.env

    configured = ProductsSettings(
        scs_ai_api_port=8300,
        scs_ai_web_port=3300,
        scs_ai_public_origin="https://ai.sunshineclimatesolutions.com",
        scs_ai_model_alias="scs-language",
        scs_ai_model_name="Qwen/Qwen3-30B-A3B-Instruct-2507",
        scs_ai_model_base_url="http://127.0.0.1:8001/v1",
        scs_ai_model_api_key="top-secret",
        scs_ai_model_api_key_file=r"C:\SCS_AI\model.key",
    )
    spec = build_scs_ai_process_spec(configured, tmp_path, r"C:\Python\python.exe")
    assert spec.env["SCS_AI_MODEL_ALIAS"] == "scs-language"
    assert spec.env["SCS_AI_MODEL_NAME"] == "Qwen/Qwen3-30B-A3B-Instruct-2507"
    assert spec.env["SCS_AI_MODEL_BASE_URL"] == "http://127.0.0.1:8001/v1"
    assert spec.env["SCS_AI_MODEL_API_KEY"] == "top-secret"
    assert spec.env["SCS_AI_MODEL_API_KEY_FILE"] == r"C:\SCS_AI\model.key"
    assert "top-secret" not in repr(configured)
    assert "top-secret" not in str(configured)


def test_scs_api_process_spec_builds_core_operations_api(tmp_path):
    spec = build_scs_api_process_spec(
        settings(),
        tmp_path,
        r"C:\Python\python.exe",
    )

    assert spec.name == "scs:api"
    assert spec.argv == (
        r"C:\Python\python.exe",
        "-m",
        "uvicorn",
        "scs_api.runtime:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8100",
    )
    assert spec.env["SCS_API_PORT"] == "8100"
    assert spec.env["SCS_WEB_PORT"] == "3100"
    assert spec.env["SCS_DATA_ROOT"] == r"C:\SCS_DATA"
    assert spec.env["SCS_SESSION_COOKIE"] == "scs_employee_session"
    assert spec.health_url == "http://127.0.0.1:8100/health"


def test_scs_web_process_spec_serves_scs_ui_on_3100_lane(tmp_path):
    spec = build_scs_web_process_spec(settings(), tmp_path)

    assert spec.name == "scs:web"
    assert spec.argv == (
        "npm.cmd",
        "--prefix",
        "scs-ui",
        "run",
        "start",
    )
    assert spec.cwd == tmp_path
    assert spec.env["SCS_WEB_PORT"] == "3100"
    assert spec.env["SCS_API_ORIGIN"] == "http://127.0.0.1:8100"
    assert spec.env["SCS_AI_API_ORIGIN"] == "http://127.0.0.1:8300"
    assert spec.health_url == "http://127.0.0.1:3100/"


def test_start_starts_core_api_ai_api_web_and_tunnel(tmp_path):
    supervisor = FakeSupervisor()
    tunnel = FakeTunnel()

    service = ScsService(
        settings(),
        supervisor=supervisor,
        repository=tmp_path,
        python_executable=r"C:\Python\python.exe",
        tunnel=tunnel,
        probe=ReadyProbe(),
    )

    result = service.start()

    assert [spec.name for spec in supervisor.started] == [
        "scs:api",
        "scs-ai:api",
        "scs:web",
    ]
    assert tunnel.started == 1
    assert result.launch_available is True
    assert result.stop_available is True


def test_start_is_idempotent(tmp_path):
    supervisor = FakeSupervisor()
    tunnel = FakeTunnel()

    service = ScsService(
        settings(),
        supervisor=supervisor,
        repository=tmp_path,
        python_executable=r"C:\Python\python.exe",
        tunnel=tunnel,
        probe=ReadyProbe(),
    )

    service.start()
    service.start()

    assert [spec.name for spec in supervisor.started] == [
        "scs:api",
        "scs-ai:api",
        "scs:web",
    ]
    assert tunnel.started == 1


def test_stop_stops_only_scs_owned_resources(tmp_path):
    supervisor = FakeSupervisor()
    tunnel = FakeTunnel()

    service = ScsService(
        settings(),
        supervisor=supervisor,
        repository=tmp_path,
        python_executable=r"C:\Python\python.exe",
        tunnel=tunnel,
        probe=ReadyProbe(),
    )

    service.start()
    service.stop()

    assert supervisor.stopped == ["scs:web", "scs-ai:api", "scs:api"]
    assert tunnel.stopped == 1


def test_status_reports_web_core_api_ai_api_and_tunnel_truthfully(tmp_path):
    supervisor = FakeSupervisor()
    tunnel = FakeTunnel()

    service = ScsService(
        settings(),
        supervisor=supervisor,
        repository=tmp_path,
        python_executable=r"C:\Python\python.exe",
        tunnel=tunnel,
        probe=ReadyProbe(),
    )

    service.start()
    status = service.status()
    details = dict(status.details)

    assert details["Web"] == "running"
    assert details["Core API"] == "running"
    assert details["AI API"] == "running"
    assert details["AI model"] == "unknown"
    assert details["Tunnel"] == "connected"
    assert details["API port"] == "8100"
    assert details["AI API port"] == "8300"
    assert details["Web port"] == "3100"
    assert status.state == "running"


def test_web_running_with_dead_core_api_is_never_healthy(tmp_path):
    supervisor = FakeSupervisor()
    tunnel = FakeTunnel()

    service = ScsService(
        settings(),
        supervisor=supervisor,
        repository=tmp_path,
        python_executable=r"C:\Python\python.exe",
        tunnel=tunnel,
        probe=ReadyProbe(),
    )

    service.start()
    supervisor.stop("scs:api")

    status = service.status()
    details = dict(status.details)

    assert details["Web"] == "running"
    assert details["Core API"] == "stopped"
    assert status.state == "degraded"
    assert status.state != "running"
    assert status.status_text == "SCS partially running"


def test_core_api_alone_is_not_a_healthy_launched_product(tmp_path):
    supervisor = FakeSupervisor()
    tunnel = FakeTunnel()

    service = ScsService(
        settings(),
        supervisor=supervisor,
        repository=tmp_path,
        python_executable=r"C:\Python\python.exe",
        tunnel=tunnel,
        probe=ReadyProbe(),
    )

    supervisor.start(build_scs_api_process_spec(settings(), tmp_path, r"C:\Python\python.exe"))

    status = service.status()

    assert dict(status.details)["Core API"] == "running"
    assert dict(status.details)["Web"] == "stopped"
    assert status.state == "degraded"


def test_open_url_prefers_public_origin_only_when_tunnel_connected(tmp_path):
    supervisor = FakeSupervisor()
    tunnel = FakeTunnel()

    service = ScsService(
        settings(),
        supervisor=supervisor,
        repository=tmp_path,
        python_executable=r"C:\Python\python.exe",
        tunnel=tunnel,
        probe=ReadyProbe(),
    )

    assert service.status().open_url == "http://127.0.0.1:3100"
    service.start()
    assert service.status().open_url == "https://ai.sunshineclimatesolutions.com"
    tunnel.stop()
    assert service.status().open_url == "http://127.0.0.1:3100"


def test_logs_include_only_scs_ai_and_owned_tunnel_logs(tmp_path):
    supervisor = FakeSupervisor()
    supervisor.logs.entries = [
        SimpleNamespace(service="scs-ai:api:stdout", text="scs"),
        SimpleNamespace(service="scs:web:stdout", text="web"),
        SimpleNamespace(service="coder:api:stdout", text="coder"),
    ]

    tunnel = FakeTunnel()

    service = ScsService(
        settings(),
        supervisor=supervisor,
        repository=tmp_path,
        python_executable=r"C:\Python\python.exe",
        tunnel=tunnel,
        probe=ReadyProbe(),
    )

    texts = [entry.text for entry in service.logs()]

    assert "scs" in texts
    assert "web" in texts
    assert "safe tunnel log" in texts
    assert "coder" not in texts

def test_build_products_wires_operational_scs_ai_when_tunnel_supplied(tmp_path):
    from defend_control.products import build_products

    supervisor = FakeSupervisor()
    tunnel = FakeTunnel()

    class FakeController:
        def poll_state(self):
            return SimpleNamespace(
                state="stopped",
                selected_mode=None,
                owned_services=(),
                message=None,
                logs=(),
            )

    products = build_products(
        controller=FakeController(),
        supervisor=supervisor,
        repository=tmp_path,
        python_executable=r"C:\Python\python.exe",
        public_origin="https://ai.defend-network.org",
        settings=settings(),
        scs_tunnel=tunnel,
        probe=ReadyProbe(),
    )

    scs = next(
        product
        for product in products
        if product.application_id == "scs"
    )

    status = scs.status()

    assert status.launch_available is True
    assert status.stop_available is True
    assert status.logs_available is True
