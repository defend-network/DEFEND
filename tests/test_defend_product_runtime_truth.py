from __future__ import annotations

from types import SimpleNamespace

from defend_control.health import JsonResult
from defend_control.model_registry import ADAPTER_REPO, ADAPTER_REVISION
from defend_control.products import DefendService


class _Controller:
    def __init__(self, *, mode="vast", state="ready"):
        self.started = []
        self._state = SimpleNamespace(
            state=state,
            selected_mode=mode,
            owned_services=("ssh tunnel", "cloudflare"),
            message=None,
        )

    def start(self, mode):
        self.started.append(mode)

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
