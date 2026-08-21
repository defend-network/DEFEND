"""Health contract: /live vs /ready semantics and model readiness checks."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest


class _FakeResponse:
    def __init__(self, status=200, payload=None, raise_err=None):
        self.status_code = status
        self._payload = payload or {}
        self._raise_err = raise_err

    def raise_for_status(self):
        if self._raise_err:
            raise self._raise_err

    def json(self):
        return self._payload


class _FakeTransport:
    def __init__(self, ps_payload=None, tags_payload=None):
        self.ps_payload = ps_payload
        self.tags_payload = tags_payload

    async def get(self, url):
        if "/api/ps" in url:
            return _FakeResponse(payload=self.ps_payload)
        return _FakeResponse(payload=self.tags_payload)


class _Model:
    def __init__(self, ready):
        self._ready = ready

    async def readiness_check(self):
        return self._ready


def _build_api_module():
    import api_server

    return api_server


def test_ollama_readiness_true_when_model_loaded(monkeypatch):
    import ollama_client

    transport = _FakeTransport(
        ps_payload={
            "models": [
                {"name": "defend-ai:latest", "model": "qwen2.5:14b-instruct-q4_K_M:latest"}
            ]
        }
    )
    client = ollama_client.OllamaClient(model="defend-ai:latest", base_url="http://127.0.0.1:11434")
    monkeypatch.setattr(client, "_client", transport)
    assert asyncio.run(client.readiness_check()) is True


def test_ollama_readiness_false_when_nothing_loaded_and_tag_absent(monkeypatch):
    import ollama_client

    transport = _FakeTransport(ps_payload={"models": []}, tags_payload={"models": []})
    client = ollama_client.OllamaClient(model="defend-ai:latest", base_url="http://127.0.0.1:11434")
    monkeypatch.setattr(client, "_client", transport)
    assert asyncio.run(client.readiness_check()) is False


def test_ollama_healthcheck_has_no_stdout_prints(monkeypatch, capsys):
    import ollama_client

    transport = _FakeTransport(tags_payload={"models": [{"name": "defend-ai:latest"}]})
    client = ollama_client.OllamaClient(model="defend-ai:latest", base_url="http://127.0.0.1:11434")
    monkeypatch.setattr(client, "_client", transport)
    assert asyncio.run(client.healthcheck()) is True
    captured = capsys.readouterr()
    assert captured.out == ""


def test_ready_endpoint_all_checks_pass(monkeypatch):
    api_server = _build_api_module()
    state = SimpleNamespace(
        cp=SimpleNamespace(tools={"calculator.evaluate": object()}),
        model=_Model(ready=True),
        data=object(),
    )
    monkeypatch.setattr(api_server, "state", state)
    monkeypatch.setattr(api_server, "MODEL_NAME", "defend-ai:latest")
    result = asyncio.run(api_server.public_ready())
    assert result["ok"] is True
    assert result["checks"]["model_inference_ready"] is True
    assert result["checks"]["control_plane"] is True
    assert result["checks"]["data_core"] is True
    assert result["checks"]["tool_registry"] is True


def test_ready_endpoint_fails_when_model_not_inference_ready(monkeypatch):
    api_server = _build_api_module()
    state = SimpleNamespace(
        cp=SimpleNamespace(tools={"calculator.evaluate": object()}),
        model=_Model(ready=False),
        data=object(),
    )
    monkeypatch.setattr(api_server, "state", state)
    monkeypatch.setattr(api_server, "MODEL_NAME", "defend-ai:latest")
    result = asyncio.run(api_server.public_ready())
    assert result["ok"] is False
    assert result["checks"]["model_inference_ready"] is False


def test_live_endpoint_semantics(monkeypatch):
    api_server = _build_api_module()
    monkeypatch.setattr(
        api_server,
        "state",
        SimpleNamespace(cp=object(), model=object(), data=object()),
    )
    result = asyncio.run(api_server.public_live())
    assert result["ok"] is True