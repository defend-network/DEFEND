"""Regression tests for the shared web/admin surface integration.

The Control Center owns the platform admin surface (api_server.py + the
Next.js defend-ui-v2 app) so the web Setup/Integrations control plane works
without any product runtime. The DEFEND AI stack adopts the surface instead
of starting duplicate processes.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from defend_control.admin_surface import (
    AdminSurfaceController,
    AdminSurfaceStartFailed,
    build_admin_surface_specs,
    resolve_setup_target,
)
from defend_control.health import HealthResult
from defend_control.model_registry import ADAPTER_REPO
from defend_control.orchestrator import StackOrchestrator, StartFailed
from defend_control.preflight import CheckResult, PreflightRunner
from defend_control.settings import ControlSettings
from defend_control.types import ModelReady


def settings(tmp_path: Path) -> ControlSettings:
    return ControlSettings(
        repo_root=tmp_path,
        data_root=tmp_path / "data",
        public_web_origin="https://ai.example.test",
        cloudflared_exe=tmp_path / "cloudflared.exe",
        cloudflared_config=tmp_path / "config.yml",
        cloudflared_tunnel="defend-ai",
        adapter_repo=ADAPTER_REPO,
        local_model="defend-ai:latest",
        vast_max_hourly=Decimal("3.00"),
    )


def complete_secrets() -> dict[str, str]:
    return {
        "VAST_API_KEY": "synthetic-vast-value",
        "HF_TOKEN": "synthetic-hf-value",
        "VLLM_API_KEY": "synthetic-vllm-value",
        "DEFEND_OWNER_PASS": "synthetic-owner-value",
        "DEFEND_VISITOR_HMAC_KEY": "synthetic-visitor-value",
        "DEFEND_GMAIL_SMTP_USERNAME": "synthetic-mail-user",
        "DEFEND_GMAIL_APP_PASSWORD": "synthetic-mail-password",
    }


class FakeSupervisor:
    def __init__(self, events=None, *, reject_duplicates=False):
        self._events = events if events is not None else []
        self.started: list[str] = []
        self.stopped: list[str] = []
        self._reject_duplicates = reject_duplicates

    def start(self, spec):
        if self._reject_duplicates and spec.name in self.started:
            raise ValueError("process name is already supervised")
        self.started.append(spec.name)
        self._events.append(f"{spec.name}:start")
        return object()

    def stop(self, name):
        if name in self.started:
            self.started.remove(name)
            self.stopped.append(name)
            return True
        return False

    def close(self):
        for name in reversed(list(self.started)):
            self.stop(name)


def make_controller(
    supervisor: FakeSupervisor,
    settings: ControlSettings,
    *,
    probe,
):
    return AdminSurfaceController(
        supervisor=supervisor,
        settings=settings,
        secrets=complete_secrets(),
        python_executable="python.exe",
        health_probe=probe,
        ready_timeout_seconds=0.5,
        probe_timeout_seconds=0.1,
    )


def surface_health(healthy: dict[str, bool], default: bool = False):
    def probe(url: str, _timeout: float, **_kwargs):
        ok = healthy.get(url, default)
        return HealthResult(ok, 200 if ok else 503, 1, None)

    return probe


def test_admin_surface_specs_use_canonical_ports_and_no_model_env(tmp_path):
    current = settings(tmp_path)
    specs = build_admin_surface_specs(
        current, complete_secrets(), "python.exe"
    )

    assert specs.api.name == "api"
    assert specs.api.argv == ("python.exe", "api_server.py")
    assert specs.api.cwd == tmp_path
    assert specs.api.env["DEFEND_API_PORT"] == "8000"
    assert specs.api.health_url == "http://127.0.0.1:8000/health"

    assert specs.web.name == "web"
    assert specs.web.argv == ("npm.cmd", "run", "start")
    assert specs.web.cwd == tmp_path / "defend-ui-v2"
    assert specs.web.env["PORT"] == "3000"
    assert specs.web.env["HOSTNAME"] == "127.0.0.1"
    assert specs.web.health_url == "http://127.0.0.1:3000/"

    model_env = {"DEFEND_MODEL", "DEFEND_MODEL_BACKEND", "OLLAMA_HOST"}
    assert not (model_env & set(specs.api.env))


def test_admin_surface_specs_honor_configured_ports(tmp_path):
    from dataclasses import replace

    current = replace(settings(tmp_path), api_port=8123, web_port=3123)
    specs = build_admin_surface_specs(current, {}, "python.exe")

    assert specs.api.env["DEFEND_API_PORT"] == "8123"
    assert specs.api.health_url == "http://127.0.0.1:8123/health"
    assert specs.web.env["PORT"] == "3123"
    assert specs.web.health_url == "http://127.0.0.1:3123/"


def test_ensure_ready_verifies_without_starting_when_healthy(tmp_path):
    current = settings(tmp_path)
    supervisor = FakeSupervisor()
    controller = make_controller(
        supervisor,
        current,
        probe=surface_health(
            {
                "http://127.0.0.1:8000/health": True,
                "http://127.0.0.1:3000/": True,
            }
        ),
    )

    controller.ensure_ready()

    assert supervisor.started == []


def test_ensure_ready_starts_api_then_web_when_unhealthy(tmp_path):
    current = settings(tmp_path)
    supervisor = FakeSupervisor()

    def dynamic_probe(url: str, _timeout: float, **_kwargs):
        ok = (url.endswith("/health") and "api" in supervisor.started) or (
            url.endswith(":3000/") and "web" in supervisor.started
        )
        return HealthResult(ok, 200 if ok else 503, 1, None)

    controller = make_controller(supervisor, current, probe=dynamic_probe)

    controller.ensure_ready()

    assert supervisor.started == ["api", "web"]


def test_ensure_ready_rolls_back_api_on_web_failure(tmp_path):
    current = settings(tmp_path)
    supervisor = FakeSupervisor()
    controller = make_controller(
        supervisor,
        current,
        probe=surface_health({"http://127.0.0.1:8000/health": True}),
    )

    with pytest.raises(AdminSurfaceStartFailed, match="web"):
        controller.ensure_ready()

    assert supervisor.started == []
    assert supervisor.stopped == ["web", "api"]


def test_ensure_ready_does_not_duplicate_when_already_healthy(tmp_path):
    current = settings(tmp_path)
    supervisor = FakeSupervisor()

    def dynamic_probe(url: str, _timeout: float, **_kwargs):
        ok = (url.endswith("/health") and "api" in supervisor.started) or (
            url.endswith(":3000/") and "web" in supervisor.started
        )
        return HealthResult(ok, 200 if ok else 503, 1, None)

    controller = make_controller(supervisor, current, probe=dynamic_probe)
    controller.ensure_ready()
    assert supervisor.started == ["api", "web"]

    controller.ensure_ready()

    assert supervisor.started == ["api", "web"]


def test_ensure_ready_adopts_already_supervised_processes(tmp_path):
    current = settings(tmp_path)
    supervisor = FakeSupervisor(reject_duplicates=True)
    supervisor.started = ["api", "web"]
    controller = make_controller(
        supervisor,
        current,
        probe=surface_health(
            {
                "http://127.0.0.1:8000/health": True,
                "http://127.0.0.1:3000/": True,
            }
        ),
    )

    controller.ensure_ready()

    assert supervisor.started == ["api", "web"]


def test_ensure_ready_accepts_secret_store_loader(tmp_path):
    current = settings(tmp_path)
    supervisor = FakeSupervisor()

    def dynamic_probe(url: str, _timeout: float, **_kwargs):
        ok = (url.endswith("/health") and "api" in supervisor.started) or (
            url.endswith(":3000/") and "web" in supervisor.started
        )
        return HealthResult(ok, 200 if ok else 503, 1, None)

    class SecretStore:
        def load(self) -> dict[str, str]:
            return complete_secrets()

    controller = AdminSurfaceController(
        supervisor=supervisor,
        settings=current,
        secrets=SecretStore(),
        python_executable="python.exe",
        health_probe=dynamic_probe,
        ready_timeout_seconds=0.5,
        probe_timeout_seconds=0.1,
    )

    controller.ensure_ready()

    assert supervisor.started == ["api", "web"]


def test_resolve_setup_target_uses_web_port_and_falls_back(tmp_path):
    current = settings(tmp_path)
    local_url, public_url, local_ok = resolve_setup_target(
        current, surface_health({})
    )

    assert local_url == "http://127.0.0.1:3000/setup"
    assert public_url == "https://ai.example.test/setup"
    assert local_ok is False

    local_url, _public_url, local_ok = resolve_setup_target(
        current,
        surface_health(
            {"http://127.0.0.1:3000/health": True}
        ),
    )
    assert local_url == "http://127.0.0.1:3000/setup"
    assert local_ok is True


def test_preflight_adopted_ports_skip_availability_probe(tmp_path):
    observed: list[int] = []
    runner = PreflightRunner.for_test(
        port_available=lambda port: not observed.append(port)
    )

    results = runner.run(
        "vast",
        settings(tmp_path),
        complete_secrets(),
        adopted_ports=frozenset({3000, 8000}),
    )

    assert observed == [8001]
    by_name = {result.name: result for result in results}
    assert by_name["port:3000"].ok
    assert by_name["port:8000"].ok
    assert "adopted" in by_name["port:3000"].detail


def test_preflight_rejects_invalid_adopted_ports(tmp_path):
    runner = PreflightRunner.for_test()

    with pytest.raises(TypeError):
        runner.run(
            "vast", settings(tmp_path), complete_secrets(), adopted_ports="3000"
        )
    with pytest.raises(ValueError, match="service ports"):
        runner.run(
            "vast",
            settings(tmp_path),
            complete_secrets(),
            adopted_ports=frozenset({9999}),
        )


class FakeOllama:
    def __init__(self, events):
        self._events = events

    def verify(self, model: str) -> ModelReady:
        self._events.append("ollama:verify")
        return ModelReady(model, "ollama", "http://127.0.0.1:11434")


class RecordingPreflight:
    def __init__(self, events, *, ok=True):
        self._events = events
        self._ok = ok
        self.adopted = frozenset()

    def run(self, mode, _settings, _secrets, *, adopted_ports=frozenset()):
        self._events.append("preflight")
        self.adopted = frozenset(adopted_ports)
        return (CheckResult("preflight", self._ok, "ok" if self._ok else "failed"),)


def orchestrator_dependencies(tmp_path, *, events, healthy):
    def health_probe(url, _timeout, **_kwargs):
        ok = healthy.get(url, True)
        return HealthResult(ok, 200 if ok else 503, 1, None)

    return {
        "settings": settings(tmp_path),
        "secrets": complete_secrets(),
        "preflight": RecordingPreflight(events),
        "supervisor": FakeSupervisor(events),
        "local_backend": FakeOllama(events),
        "health_probe": health_probe,
        "external_tunnel_detector": lambda _settings: None,
        "health_timeout_seconds": 0.05,
        "public_health_timeout_seconds": 0.05,
        "poll_interval_seconds": 0,
    }


def test_orchestrator_adopts_healthy_shared_surface(tmp_path):
    events = []
    kwargs = orchestrator_dependencies(
        tmp_path,
        events=events,
        healthy={
            "http://127.0.0.1:8000/health": True,
            "http://127.0.0.1:3000/": True,
        },
    )
    orchestrator = StackOrchestrator(**kwargs, adopt_shared_surface=True)
    preflight = kwargs["preflight"]
    supervisor = kwargs["supervisor"]

    result = orchestrator.start("ollama")

    assert preflight.adopted == frozenset({8000, 3000})
    assert "api:start" not in events
    assert "web:start" not in events
    assert result.state == "ready"
    components = {item.name: item.state for item in result.components}
    assert components["api"] == "ready (shared)"
    assert components["frontend"] == "ready (shared)"
    assert supervisor.started == ["cloudflare"]


def test_orchestrator_starts_surface_when_shared_surface_unhealthy(tmp_path):
    events = []
    kwargs = orchestrator_dependencies(
        tmp_path,
        events=events,
        healthy={
            "http://127.0.0.1:8000/health": True,
            "http://127.0.0.1:3000/": False,
        },
    )
    orchestrator = StackOrchestrator(**kwargs, adopt_shared_surface=True)
    preflight = kwargs["preflight"]

    with pytest.raises(StartFailed, match="frontend"):
        orchestrator.start("ollama")

    assert preflight.adopted == frozenset()
    assert "api:start" in events
    assert "web:start" in events


def test_orchestrator_default_keeps_full_start_flow(tmp_path):
    events = []
    kwargs = orchestrator_dependencies(
        tmp_path,
        events=events,
        healthy={
            "http://127.0.0.1:8000/health": True,
            "http://127.0.0.1:3000/": True,
        },
    )
    orchestrator = StackOrchestrator(**kwargs)
    preflight = kwargs["preflight"]

    result = orchestrator.start("ollama")

    assert preflight.adopted == frozenset()
    assert "api:start" in events
    assert "web:start" in events
    assert result.state == "ready"
    supervisor = kwargs["supervisor"]
    assert supervisor.started == ["api", "web", "cloudflare"]