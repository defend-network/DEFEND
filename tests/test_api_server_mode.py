"""DEFEND AI API mode split: admin (model-independent) vs product inference."""

from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace


def _reload_api_server(monkeypatch, mode: str | None):
    if mode is None:
        monkeypatch.delenv("DEFEND_API_MODE", raising=False)
    else:
        monkeypatch.setenv("DEFEND_API_MODE", mode)
    import api_server

    return importlib.reload(api_server)


def test_admin_mode_health_is_healthy_with_data_core(monkeypatch):
    api_server = _reload_api_server(monkeypatch, "admin")
    assert api_server.ADMIN_MODE is True
    monkeypatch.setattr(
        api_server,
        "state",
        SimpleNamespace(data=object(), cp=None, model=None),
    )

    result = asyncio.run(api_server._health_payload())

    assert result["ok"] is True
    assert result["mode"] == "admin"
    assert result["model"] is None
    assert result["tools"] == []


def test_product_mode_health_requires_controlplane(monkeypatch):
    api_server = _reload_api_server(monkeypatch, "defend_ai")
    assert api_server.ADMIN_MODE is False
    monkeypatch.setattr(
        api_server,
        "state",
        SimpleNamespace(data=object(), cp=None, model=None),
    )

    result = asyncio.run(api_server._health_payload())

    assert result["ok"] is False
    assert result["model_state"] == "failed"
