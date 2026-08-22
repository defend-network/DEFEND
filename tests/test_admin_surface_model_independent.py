"""Regression tests: Control Center / shared admin surface is model-independent.

Owner architecture requires the Control Center to be the always-available
administrative plane. Starting it must NOT instantiate a DEFEND AI model
client, ControlPlane, tool registry, or RAG embedding lane. DEFEND AI
inference belongs to the independent product service, which is the only
caller that enables DEFEND_AI_PRODUCT_SERVICE.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from defend_control.admin_surface import build_admin_surface_specs
from defend_control.local_model import build_local_process_specs
from defend_control.remote_vllm import build_remote_process_specs
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
        adapter_repo="Defend-network/defend-qwen-32b-lora",
        local_model="defend-ai:latest",
        vast_max_hourly=Decimal("3.00"),
    )


def secrets() -> dict[str, str]:
    return {
        "VAST_API_KEY": "synthetic-vast-value",
        "HF_TOKEN": "synthetic-hf-value",
        "VLLM_API_KEY": "synthetic-vllm-value",
        "DEFEND_OWNER_PASS": "synthetic-owner-value",
        "DEFEND_VISITOR_HMAC_KEY": "synthetic-visitor-value",
        "DEFEND_GMAIL_SMTP_USERNAME": "synthetic-mail-user",
        "DEFEND_GMAIL_APP_PASSWORD": "synthetic-mail-password",
    }


class _FakeDataCore:
    def __init__(self) -> None:
        self.closed = False
        self.identity = SimpleNamespace(assert_invitation_transport_ready=lambda: None)
        self.memory = SimpleNamespace()
        self.conversations = SimpleNamespace()
        self.paths = SimpleNamespace(root="test-data-root")

    def close(self) -> None:
        self.closed = True


class _FakeModel:
    def __init__(self) -> None:
        self.entered = False
        self.exited = False

    async def __aenter__(self):
        self.entered = True
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.exited = True

    async def close(self) -> None:
        self.exited = True


def test_admin_surface_spec_disables_product_service(tmp_path):
    specs = build_admin_surface_specs(settings(tmp_path), secrets(), "python.exe")
    assert specs.api.env["DEFEND_AI_PRODUCT_SERVICE"] == "0"


def test_local_product_spec_enables_product_service(tmp_path):
    configured = settings(tmp_path)
    specs = build_local_process_specs(
        configured,
        secrets(),
        ModelReady("defend-ai:latest", "ollama", "http://127.0.0.1:11434"),
    )
    assert specs.api.env["DEFEND_AI_PRODUCT_SERVICE"] == "1"


def test_remote_product_spec_enables_product_service(tmp_path):
    configured = settings(tmp_path)
    specs = build_remote_process_specs(
        configured,
        secrets(),
        ModelReady("defend-ai", "openai_compatible", "http://127.0.0.1:8001/v1"),
    )
    assert specs.api.env["DEFEND_AI_PRODUCT_SERVICE"] == "1"


class _FakeEmbeddingClient:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def test_admin_surface_lifespan_builds_no_model_client(monkeypatch):
    import api_server

    data = _FakeDataCore()
    build_calls: list[str] = []

    monkeypatch.setattr(api_server, "DEFEND_AI_PRODUCT_SERVICE", False)
    monkeypatch.setattr(api_server, "DataCore", lambda _root: data)
    monkeypatch.setattr(api_server, "configure_identity_store", lambda _store: None)
    monkeypatch.setattr(
        api_server,
        "build_model_client",
        lambda: build_calls.append("build_model_client"),
    )
    monkeypatch.setattr(
        api_server,
        "build_default_registry",
        lambda **_kwargs: build_calls.append("build_default_registry"),
    )
    monkeypatch.setattr(
        api_server,
        "EmbeddingSettings",
        SimpleNamespace(
            from_env=lambda _env: SimpleNamespace(
                provider="ollama", provider_label="test"
            )
        ),
    )

    app = SimpleNamespace(state=SimpleNamespace())

    async def run() -> None:
        async with api_server.lifespan(app):
            assert api_server.state.cp is None
            assert api_server.state.model is None
            assert api_server.state.data is not None

    asyncio.run(run())

    assert build_calls == []
    assert data.closed is True
    assert api_server.state.model is None
    assert api_server.state.cp is None
    assert api_server.state.data is None


def test_product_lifespan_builds_model_client_and_control_plane(monkeypatch):
    import api_server

    data = _FakeDataCore()
    model = _FakeModel()
    calls: list[str] = []

    monkeypatch.setattr(api_server, "DEFEND_AI_PRODUCT_SERVICE", True)
    monkeypatch.setattr(api_server, "DataCore", lambda _root: data)
    monkeypatch.setattr(api_server, "configure_identity_store", lambda _store: None)
    monkeypatch.setattr(
        api_server,
        "EmbeddingSettings",
        SimpleNamespace(
            from_env=lambda _env: SimpleNamespace(
                provider="ollama", provider_label="test"
            )
        ),
    )
    monkeypatch.setattr(
        api_server,
        "build_embedding_client",
        lambda _settings: _FakeEmbeddingClient(),
    )
    monkeypatch.setattr(api_server, "build_default_registry", lambda **_kwargs: {})
    monkeypatch.setattr(api_server, "build_model_client", lambda: model)
    monkeypatch.setattr(
        api_server,
        "ControlPlane",
        lambda **_kwargs: SimpleNamespace(tools={}),
    )

    app = SimpleNamespace(state=SimpleNamespace())

    async def run() -> None:
        async with api_server.lifespan(app):
            assert api_server.state.cp is not None
            assert api_server.state.model is not None

    asyncio.run(run())

    assert model.entered is True
    assert model.exited is True
    assert api_server.state.model is None
    assert api_server.state.cp is None
    assert api_server.state.data is None


def test_admin_surface_health_reports_stopped_and_no_tools(monkeypatch):
    import api_server

    monkeypatch.setattr(api_server, "DEFEND_AI_PRODUCT_SERVICE", False)
    monkeypatch.setattr(
        api_server, "state", SimpleNamespace(data=object(), model=None, cp=None)
    )
    monkeypatch.setattr(api_server, "MODEL_NAME", "defend-ai:latest")

    payload = asyncio.run(api_server._health_payload())

    assert payload["ok"] is True
    assert payload["product_service"] is False
    assert payload["model_state"] == "stopped"
    assert payload["tools"] == []


def test_product_health_requires_model_ready(monkeypatch):
    import api_server

    monkeypatch.setattr(api_server, "DEFEND_AI_PRODUCT_SERVICE", True)

    class _HealthModel:
        async def healthcheck(self) -> bool:
            return True

    monkeypatch.setattr(
        api_server,
        "state",
        SimpleNamespace(
            data=object(),
            model=_HealthModel(),
            cp=SimpleNamespace(tools={"calculator.evaluate": object()}),
        ),
    )
    monkeypatch.setattr(api_server, "MODEL_NAME", "defend-ai")

    payload = asyncio.run(api_server._health_payload())

    assert payload["ok"] is True
    assert payload["product_service"] is True
    assert payload["model_state"] == "ready"
    assert payload["tools"] == ["calculator.evaluate"]
