from __future__ import annotations

import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import defend_control.health as health_module
from defend_control.health import JsonResult, fetch_http_json, probe_http
from defend_control.products import (
    CoderService,
    DefendService,
    ProductsSettings,
    ProductStatus,
    ScsService,
    SportsService,
    build_products,
    build_sports_process_spec,
    product_rows,
)
from defend_control.processes import LogBuffer, ProcessSnapshot


ROOT = Path(__file__).resolve().parents[1]


class FakeResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, size: int = -1) -> bytes:
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


def snapshot(name: str, *, running: bool = True) -> ProcessSnapshot:
    return ProcessSnapshot(
        name=name,
        pid=1234,
        owned=True,
        running=running,
        health_url=None,
        returncode=None if running else 0,
    )


class RecordingSupervisor:
    def __init__(self, snapshots=()):
        self.started: list[object] = []
        self.stopped: list[str] = []
        self.stop_all_calls = 0
        self._snapshots = list(snapshots)
        self.logs = LogBuffer(max_entries=100, max_line_chars=256)

    def start(self, spec):
        self.started.append(spec)
        return object()

    def stop(self, name: str):
        self.stopped.append(name)
        return True

    def stop_all(self) -> None:
        self.stop_all_calls += 1

    def snapshot(self):
        return tuple(self._snapshots)


class FakeProbe:
    def __init__(self, responses):
        self.responses = responses
        self.calls: list[str] = []

    def __call__(self, url, timeout_seconds, *, public_origin=None):
        self.calls.append(url)
        for path, result in self.responses.items():
            if url.rstrip("/").endswith(path):
                return result
        return JsonResult(False, None, 0, "NotFound")


class FakeController:
    def __init__(self):
        self.started: list[str] = []
        self.stopped_local = 0

    def poll_state(self):
        return SimpleNamespace(
            state="stopped",
            selected_mode=None,
            components=(),
            logs=(),
            message=None,
            vast_gpu=None,
            vast_instance_id=None,
            vast_hourly_price=None,
            vast_offer_id=None,
            vast_gpu_ram_mb=None,
            vast_reliability=None,
            vast_storage_cost_per_gb_month=None,
            vast_storage_total_hourly=None,
            vast_disk_gb=None,
            vast_actual_status=None,
            vast_billing_warning=None,
            pending_confirmation=None,
            pending_fingerprint=None,
            vast_candidates=(),
            vast_replacement_offer=None,
            owned_services=(),
        )

    def start(self, mode: str):
        self.started.append(mode)
        return self.poll_state()

    def stop_local(self):
        self.stopped_local += 1
        return self.poll_state()


def make_sports(
    supervisor=None,
    *,
    settings=None,
    probe=None,
    clock=None,
    database_url="postgresql://sports:devtest123@127.0.0.1:5432/defendsports?sslmode=disable",
):
    return SportsService(
        supervisor=supervisor or RecordingSupervisor(),
        repository=ROOT,
        python_executable=sys.executable,
        settings=settings or ProductsSettings(sports_database_url=database_url),
        probe=probe or FakeProbe({}),
        clock=clock or time.monotonic,
    )


def test_sports_start_spec_targets_sports_api_with_module_server(tmp_path):
    supervisor = RecordingSupervisor()
    service = make_sports(supervisor, database_url="postgresql://u:s@localhost/db")

    service.start()

    assert len(supervisor.started) == 1
    spec = supervisor.started[0]
    assert spec.name == "sports:api"
    assert spec.argv == (sys.executable, "-m", "tools.defend_sports_server")
    assert spec.cwd == ROOT
    assert spec.env["SPORTS_DATABASE_URL"] == "postgresql://u:s@localhost/db"
    assert spec.health_url == "http://127.0.0.1:8200/health"


def test_sports_start_spec_never_touches_vast_or_provider_state():
    supervisor = RecordingSupervisor()
    service = make_sports(supervisor)

    service.start()

    assert supervisor.stop_all_calls == 0
    spec = supervisor.started[0]
    combined = " ".join(spec.argv).casefold() + " ".join(spec.env).casefold()
    assert "vast" not in combined
    assert "huggingface" not in combined
    assert all(
        not key.casefold().startswith("vast") for key in spec.env
    )


def test_sports_stop_only_stops_sports_api():
    supervisor = RecordingSupervisor(
        snapshots=(snapshot("sports:api"), snapshot("api"))
    )
    service = make_sports(supervisor)

    service.stop()

    assert supervisor.stopped == ["sports:api"]
    assert supervisor.stop_all_calls == 0


def test_sports_status_never_exposes_database_url():
    secret = "postgresql://sports:sekret-value@127.0.0.1:5432/db?sslmode=disable"
    service = make_sports(database_url=secret)

    status = service.status()

    assert status.application_id == "sports"
    assert secret not in str(status)
    assert secret not in repr(status)


def test_sports_start_registers_database_url_as_known_secret():
    secret = "postgresql://sports:sekret-value@127.0.0.1:5432/db?sslmode=disable"
    supervisor = RecordingSupervisor()
    service = make_sports(supervisor, database_url=secret)

    service.start()

    supervisor.logs.append("sports:api:stderr", f"connecting to {secret}")
    assert secret not in repr(supervisor.logs.snapshot())


def test_sports_start_without_database_url_is_honest():
    supervisor = RecordingSupervisor()
    service = make_sports(supervisor, database_url=None)

    status = service.start()

    assert supervisor.started == []
    assert status.state == "stopped"
    assert "SPORTS_DATABASE_URL" in status.status_text


def test_sports_smoke_probes_health():
    probe = FakeProbe(
        {
            "/health": JsonResult(
                True,
                200,
                12,
                None,
                {
                    "ok": True,
                    "application_id": "sports",
                    "schema_version": 1,
                    "database": "ready",
                },
            )
        }
    )
    service = make_sports(probe=probe)

    smoke = service.smoke()

    assert probe.calls == ["http://127.0.0.1:8200/health"]
    assert smoke.ok
    assert smoke.latency_ms == 12
    assert "schema_version" in smoke.detail


def test_sports_status_reports_db_health_schema_and_sources():
    probe = FakeProbe(
        {
            "/health": JsonResult(
                True,
                200,
                10,
                None,
                {
                    "ok": True,
                    "application_id": "sports",
                    "schema_version": 3,
                    "database": "ready",
                },
            ),
            "/v1/system/sources": JsonResult(
                True,
                200,
                8,
                None,
                {
                    "ok": True,
                    "application_id": "sports",
                    "database": "ready",
                    "sources": [{"source_key": "a"}, {"source_key": "b"}],
                },
            ),
        }
    )
    supervisor = RecordingSupervisor(snapshots=(snapshot("sports:api"),))
    service = make_sports(supervisor, probe=probe)

    status = service.status()

    details = dict(status.details)
    assert status.state == "running"
    assert details["API state"] == "running"
    assert details["DB health"] == "ready"
    assert details["Schema version"] == "3"
    assert details["Public origin"] == "https://defendsports.defend-network.org"
    assert details["Sources"] == "2"


def test_sports_status_stopped_when_no_process():
    service = make_sports()

    status = service.status()

    assert status.state == "stopped"
    assert status.launch_available
    assert status.stop_available


def test_sports_status_never_reports_billable_or_provider_fields():
    supervisor = RecordingSupervisor(snapshots=(snapshot("sports:api"),))
    service = make_sports(supervisor, probe=FakeProbe({"/health": JsonResult(True, 200, 1, None, {})}))

    status = service.status()

    assert "vast" not in repr(status).casefold()
    assert "gpu" not in repr(status).casefold()
    assert "instance_id" not in repr(status).casefold()


def test_build_products_returns_four_products_in_order():
    products = build_products(
        controller=FakeController(),
        supervisor=RecordingSupervisor(),
        repository=ROOT,
        python_executable=sys.executable,
        public_origin="https://ai.defend-network.org",
        settings=ProductsSettings(sports_database_url="postgresql://u:s@localhost/db"),
    )

    assert [product.application_id for product in products] == [
        "defend",
        "sports",
        "scs",
        "coder",
    ]


def test_product_rows_returns_four_rows_in_order():
    products = build_products(
        controller=FakeController(),
        supervisor=RecordingSupervisor(),
        repository=ROOT,
        python_executable=sys.executable,
        public_origin="https://ai.defend-network.org",
        settings=ProductsSettings(sports_database_url=None),
        probe=FakeProbe({}),
    )

    rows = product_rows(products)

    assert len(rows) == 4
    assert [row.application_id for row in rows] == [
        "defend",
        "sports",
        "scs",
        "coder",
    ]
    assert all(isinstance(row, ProductStatus) for row in rows)


def test_defend_service_delegates_launch_to_controller():
    controller = FakeController()
    service = DefendService(controller, public_origin="https://ai.defend-network.org")

    status = service.start("ollama")

    assert controller.started == ["ollama"]
    assert status.application_id == "defend"


def test_defend_service_start_without_mode_is_honest():
    controller = FakeController()
    service = DefendService(controller, public_origin="https://ai.defend-network.org")

    status = service.start()

    assert controller.started == []
    assert "Choose a model backend" in status.status_text


def test_coder_service_without_observation_is_not_configured():
    service = CoderService(
        ProductsSettings(),
    )

    status = service.status()

    assert status.application_id == "coder"
    assert status.state == "not configured"
    assert not status.launch_available
    assert not status.stop_available
    assert not status.logs_available
    assert status.open_url == "https://defendcoder.defend-network.org"
    details = dict(status.details)
    assert details["Alias"] == "—"


def test_coder_service_observation_fields_are_read_only():
    observation = {
        "state": "ready",
        "alias": "defendcoder-m0",
        "gpu_name": "H200",
        "instance_id": 42,
        "hourly_price": "1.23",
        "session_budget_usd": "45.00",
    }
    service = CoderService(ProductsSettings(), observation=observation)

    status = service.status()

    assert status.state == "ready"
    details = dict(status.details)
    assert details["Alias"] == "defendcoder-m0"
    assert details["GPU"] == "H200"
    assert details["Instance"] == "42"
    assert details["$/hr"] == "$1.23"
    assert details["Session cost"] == "$45.00"
    assert not status.launch_available
    assert not status.stop_available


def test_scs_service_is_honest_when_unreachable():
    service = ScsService(
        ProductsSettings(sports_database_url=None),
        probe=FakeProbe({"/health": JsonResult(False, None, 0, "ConnectionRefusedError")}),
    )

    status = service.status()

    assert status.application_id == "scs"
    assert status.state == "not configured"
    assert not status.launch_available
    assert not status.stop_available
    assert not status.logs_available
    assert status.open_url == "https://ai.sunshineclimatesolutions.com"
    assert status.open_available


def test_scs_service_reports_running_when_loopback_reachable():
    probe = FakeProbe(
        {"/health": JsonResult(True, 200, 5, None, {"ok": True})}
    )
    service = ScsService(ProductsSettings(sports_database_url=None), probe=probe)

    status = service.status()

    assert status.state == "running"
    assert probe.calls == ["http://127.0.0.1:8100/health"]


def test_fetch_http_json_parses_json(monkeypatch):
    install_fake_opener(
        monkeypatch, FakeResponse(200, b'{"ok": true, "schema_version": 1}')
    )

    result = fetch_http_json("http://127.0.0.1:8200/health", 1)

    assert result.ok
    assert result.status_code == 200
    assert result.error_type is None
    assert result.data == {"ok": True, "schema_version": 1}


def test_fetch_http_json_rejects_non_loopback_without_network(monkeypatch):
    called = False

    def unexpected_call(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("network must not be called")

    install_fake_opener(monkeypatch, unexpected_call)

    result = fetch_http_json("http://example.test/health", 1)

    assert not result.ok
    assert result.error_type == "UnsafeUrl"
    assert called is False


def test_fetch_http_json_rejects_invalid_json(monkeypatch):
    install_fake_opener(monkeypatch, FakeResponse(200, b"not-json"))

    result = fetch_http_json("http://127.0.0.1:8200/health", 1)

    assert not result.ok
    assert result.status_code == 200
    assert result.error_type == "InvalidJson"


def test_sports_settings_from_env(monkeypatch):
    monkeypatch.setenv("SPORTS_API_PORT", "8300")
    monkeypatch.setenv("SPORTS_PUBLIC_ORIGIN", "https://sports.example.test")
    monkeypatch.setenv("SPORTS_DATABASE_URL", "postgresql://u:s@localhost/db")
    monkeypatch.delenv("SPORTS_WEB_PORT", raising=False)

    settings = ProductsSettings.from_env()

    assert settings.sports_api_port == 8300
    assert settings.sports_web_port == 3200
    assert settings.sports_public_origin == "https://sports.example.test"
    assert settings.sports_database_url == "postgresql://u:s@localhost/db"
    assert settings.sports_database_url not in repr(settings)


def test_sports_process_spec_env_contains_only_sports_variables():
    spec = build_sports_process_spec(
        ProductsSettings(sports_database_url="postgresql://u:s@localhost/db"),
        ROOT,
        sys.executable,
    )

    assert set(spec.env) == {
        "SPORTS_DATA_ROOT",
        "SPORTS_PUBLIC_ORIGIN",
        "SPORTS_SESSION_COOKIE",
        "SPORTS_API_PORT",
        "SPORTS_WEB_PORT",
        "SPORTS_DATABASE_URL",
    }