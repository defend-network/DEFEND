from decimal import Decimal
from pathlib import Path
import threading

import pytest

from defend_control.health import HealthResult
from defend_control.orchestrator import (
    AlreadyRunning,
    StackOrchestrator,
    StartCancelled,
    StartFailed,
)
from defend_control.processes import ProcessSnapshot
from defend_control.settings import ControlSettings
from defend_control.types import ModelReady


class FakePreflight:
    def __init__(self, events, *, ok=True):
        self.events = events
        self.ok = ok

    def run(self, mode, _settings, _secrets):
        self.events.append(f"preflight:{mode}")
        return (
            type(
                "Check",
                (),
                {
                    "name": "synthetic-check",
                    "ok": self.ok,
                    "detail": "ready" if self.ok else "missing dependency",
                    "remediation": None if self.ok else "repair setup",
                },
            )(),
        )


class FakeOllama:
    def __init__(self, events, *, entered=None, release=None):
        self.events = events
        self.entered = entered
        self.release = release

    def verify(self, model):
        self.events.append("ollama:verify")
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            self.release.wait(2)
        return ModelReady(model, "ollama", "http://127.0.0.1:11434")


class FakeSupervisor:
    def __init__(self, events):
        self.events = events
        self.started = []
        self.stopped = []
        self.fail_stop_once = set()

    def start(self, spec):
        self.started.append(spec)
        if spec.name in {"api", "web"}:
            self.events.append(f"{spec.name}:start")
        return type("Process", (), {"pid": 100 + len(self.started)})()

    def stop(self, name):
        self.stopped.append(name)
        if name in self.fail_stop_once:
            self.fail_stop_once.remove(name)
            raise RuntimeError("synthetic private stop detail")
        self.started = [spec for spec in self.started if spec.name != name]
        return True

    def snapshot(self):
        return tuple(
            ProcessSnapshot(
                name=spec.name,
                pid=100 + index,
                owned=True,
                running=True,
                health_url=spec.health_url,
                returncode=None,
            )
            for index, spec in enumerate(self.started, 1)
        )


def make_settings(tmp_path):
    return ControlSettings(
        repo_root=tmp_path,
        data_root=tmp_path / "data",
        public_web_origin="https://ai.example.test",
        cloudflared_exe=tmp_path / "cloudflared.exe",
        cloudflared_config=tmp_path / "config.yml",
        cloudflared_tunnel="defend-ai",
        adapter_repo="Defend-network/defend-qwen-32b-lora",
        local_model="defend-ai:latest",
        vast_max_hourly=Decimal("3.00"),
    )


def dependencies(tmp_path, *, health=None, external_tunnel=False, ollama=None):
    events = []
    supervisor = FakeSupervisor(events)
    health_by_name = {"api": True, "web": True, "public": True}
    health_by_name.update(health or {})

    def health_probe(url, _timeout, **_kwargs):
        if url.endswith(":8000/health"):
            name = "api"
        elif url.endswith(":3000/health"):
            name = "web"
        else:
            name = "public"
        events.append(f"{name}:healthy")
        return HealthResult(health_by_name[name], 200 if health_by_name[name] else 503, 1, None)

    def tunnel_probe():
        events.append("tunnel:reuse-or-start")
        return external_tunnel

    values = {
        "DEFEND_OWNER_PASS": "synthetic-owner",
        "DEFEND_VISITOR_HMAC_KEY": "synthetic-visitor-hmac-key-32-chars",
        "DEFEND_GMAIL_SMTP_USERNAME": "operator@example.test",
        "DEFEND_GMAIL_APP_PASSWORD": "synthetic-gmail",
    }
    return {
        "settings": make_settings(tmp_path),
        "secrets": values,
        "preflight": FakePreflight(events),
        "supervisor": supervisor,
        "local_backend": ollama or FakeOllama(events),
        "health_probe": health_probe,
        "external_tunnel_probe": tunnel_probe,
        "health_timeout_seconds": 0.05,
        "poll_interval_seconds": 0,
    }, events, supervisor


def test_local_start_orders_model_api_web_tunnel(tmp_path):
    kwargs, events, _supervisor = dependencies(tmp_path)
    orchestrator = StackOrchestrator(**kwargs)

    result = orchestrator.start("ollama")

    assert not isinstance(result, AlreadyRunning)
    assert events == [
        "preflight:ollama",
        "ollama:verify",
        "api:start",
        "api:healthy",
        "web:start",
        "web:healthy",
        "tunnel:reuse-or-start",
        "public:healthy",
    ]
    assert orchestrator.snapshot().state == "ready"


def test_failed_web_health_rolls_back_only_new_processes(tmp_path):
    kwargs, _events, supervisor = dependencies(tmp_path, health={"web": False})

    with pytest.raises(StartFailed, match="frontend"):
        StackOrchestrator(**kwargs).start("ollama")

    assert supervisor.stopped == ["web", "api"]
    assert "external-cloudflare" not in supervisor.stopped


def test_public_failure_rolls_back_owned_cloudflare_but_not_reused_tunnel(tmp_path):
    kwargs, _events, supervisor = dependencies(
        tmp_path, health={"public": False}, external_tunnel=False
    )
    with pytest.raises(StartFailed, match="public"):
        StackOrchestrator(**kwargs).start("ollama")
    assert supervisor.stopped == ["cloudflare", "web", "api"]

    kwargs, _events, supervisor = dependencies(
        tmp_path, health={"public": False}, external_tunnel=True
    )
    with pytest.raises(StartFailed, match="public"):
        StackOrchestrator(**kwargs).start("ollama")
    assert supervisor.stopped == ["web", "api"]


def test_failed_rollback_stop_retains_owned_resource_for_later_cleanup(tmp_path):
    kwargs, _events, supervisor = dependencies(
        tmp_path, health={"public": False}, external_tunnel=False
    )
    supervisor.fail_stop_once.add("cloudflare")
    orchestrator = StackOrchestrator(**kwargs)

    with pytest.raises(StartFailed, match="public"):
        orchestrator.start("ollama")

    assert [item.name for item in supervisor.snapshot()] == ["cloudflare"]
    orchestrator.stop_local()
    assert supervisor.stopped == ["cloudflare", "web", "api", "cloudflare"]
    assert supervisor.snapshot() == ()


def test_preflight_failure_starts_no_resources_and_reports_safe_component(tmp_path):
    kwargs, events, supervisor = dependencies(tmp_path)
    kwargs["preflight"] = FakePreflight(events, ok=False)

    with pytest.raises(StartFailed, match="preflight") as raised:
        StackOrchestrator(**kwargs).start("ollama")

    assert "synthetic-owner" not in str(raised.value)
    assert supervisor.started == []


def test_duplicate_start_returns_already_running_without_second_attempt(tmp_path):
    entered = threading.Event()
    release = threading.Event()
    kwargs, events, _supervisor = dependencies(tmp_path)
    kwargs["local_backend"] = FakeOllama(events, entered=entered, release=release)
    orchestrator = StackOrchestrator(**kwargs)
    errors = []

    worker = threading.Thread(
        target=lambda: _capture_error(errors, orchestrator.start, "ollama")
    )
    worker.start()
    assert entered.wait(1)
    try:
        duplicate = orchestrator.start("ollama")
    finally:
        release.set()
        worker.join(2)

    assert isinstance(duplicate, AlreadyRunning)
    assert events.count("preflight:ollama") == 1
    assert errors == []


def test_stop_during_start_cancels_and_rolls_back_created_services(tmp_path):
    api_started = threading.Event()
    release_api_health = threading.Event()
    kwargs, _events, supervisor = dependencies(tmp_path)
    original_probe = kwargs["health_probe"]

    def blocking_probe(url, timeout, **options):
        if url.endswith(":8000/health"):
            api_started.set()
            release_api_health.wait(2)
        return original_probe(url, timeout, **options)

    kwargs["health_probe"] = blocking_probe
    orchestrator = StackOrchestrator(**kwargs)
    errors = []
    start_worker = threading.Thread(
        target=lambda: _capture_error(errors, orchestrator.start, "ollama")
    )
    start_worker.start()
    assert api_started.wait(1)

    stop_worker = threading.Thread(target=orchestrator.stop_local)
    stop_worker.start()
    release_api_health.set()
    start_worker.join(2)
    stop_worker.join(2)

    assert len(errors) == 1 and isinstance(errors[0], StartCancelled)
    assert supervisor.stopped == ["api"]
    assert orchestrator.snapshot().state == "stopped"


def _capture_error(target, function, *args):
    try:
        function(*args)
    except BaseException as error:
        target.append(error)
