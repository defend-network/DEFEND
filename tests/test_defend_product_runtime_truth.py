from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from defend_control.health import JsonResult
from defend_control.model_registry import ADAPTER_REPO, ADAPTER_REVISION
from defend_control.product_runtime import ProductRuntimeRegistry
from defend_control.products import DefendService


class _Controller:
    def __init__(self, *, mode="vast", state="ready"):
        self.started = []
        self.destroyed = []
        self._state = SimpleNamespace(
            state=state,
            selected_mode=mode,
            owned_services=("ssh tunnel", "cloudflare"),
            message=None,
        )

    def start(self, mode):
        self.started.append(mode)

    def stop_local(self):
        return None

    def stop_and_destroy_vast(self, instance_id):
        self.destroyed.append(instance_id)

    def poll_state(self):
        return self._state


def _probe(payload):
    def run(_url, _timeout):
        return JsonResult(True, 200, 1, None, payload)

    return run


def _details(status):
    return dict(status.details)


def test_vast_status_degrades_when_api_is_legacy_ollama():
    service = DefendService(
        _Controller(),
        public_origin="https://ai.example.test",
        probe=_probe({"provider": "ollama", "model": "defend-ai:latest"}),
    )

    status = service.status()

    assert status.state == "degraded"
    assert _details(status)["Provider"] == "ollama"
    assert _details(status)["Serving alias"] == "defend-ai:latest"
    assert _details(status)["Adapter"] == "built-in local Modelfile"
    assert "backend not active" in status.status_text


def test_vast_status_is_ready_only_for_verified_remote_runtime():
    service = DefendService(
        _Controller(),
        public_origin="https://ai.example.test",
        probe=_probe(
            {
                "provider": "openai_compatible",
                "model": "defend-ai",
                "adapter_repo": ADAPTER_REPO,
                "adapter_revision": ADAPTER_REVISION,
                "base_repo": "unsloth/Qwen2.5-32B-Instruct-bnb-4bit",
                "base_revision": "aa79e3472818bdec779075d80928602591d9f2a0",
            }
        ),
    )

    status = service.status()

    assert status.state == "ready"
    assert _details(status)["Provider"] == "openai_compatible"
    assert _details(status)["Serving alias"] == "defend-ai"
    assert _details(status)["Adapter"] == ADAPTER_REPO
    assert _details(status)["Adapter revision"] == ADAPTER_REVISION


def test_start_releases_control_center_owned_surface_before_model_start():
    controller = _Controller(mode="ollama", state="stopped")
    released = []
    service = DefendService(
        controller,
        public_origin="https://ai.example.test",
        probe=_probe({"provider": "ollama", "model": "defend-ai:latest"}),
        prepare_model_start=lambda: released.append(True),
    )

    service.start("vast")

    assert released == [True]
    assert controller.started == ["vast"]


def test_stop_marks_retained_when_instance_known(tmp_path):
    controller = _Controller(mode="vast", state="stopped")
    registry = ProductRuntimeRegistry(tmp_path / "product-runtime.json")
    registry.update("defend-ai", state="ready", instance_id=48403815)
    service = DefendService(
        controller,
        public_origin="https://ai.example.test",
        probe=_probe({}),
        runtime_registry=registry,
    )

    service.stop()

    assert registry.load()["defend-ai"].state == "stopped_retained"
    assert registry.load()["defend-ai"].instance_id == 48403815


def test_destroy_requires_exact_instance_id(tmp_path):
    controller = _Controller(mode="vast", state="stopped")
    registry = ProductRuntimeRegistry(tmp_path / "product-runtime.json")
    registry.update("defend-ai", state="stopped_retained", instance_id=48403815)
    service = DefendService(
        controller,
        public_origin="https://ai.example.test",
        probe=_probe({}),
        runtime_registry=registry,
    )

    rejected = service.destroy(999)
    assert rejected.state == "failed"
    assert controller.destroyed == []

    destroyed = service.destroy(48403815)
    assert destroyed.state == "stopped"
    assert controller.destroyed == [48403815]
    record = registry.load()["defend-ai"]
    assert record.instance_id is None
    assert record.state == "stopped"
    assert record.provider_instance_state == "destroyed"


def test_destroy_with_no_retained_instance_fails(tmp_path):
    controller = _Controller(mode="vast", state="stopped")
    registry = ProductRuntimeRegistry(tmp_path / "product-runtime.json")
    registry.update("defend-ai", instance_id=None)
    service = DefendService(
        controller,
        public_origin="https://ai.example.test",
        probe=_probe({}),
        runtime_registry=registry,
    )

    status = service.destroy(None)

    assert status.state == "failed"
    assert controller.destroyed == []
