"""DEFEND cookie transport policy is explicit for local and production paths."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path


def _settings(tmp_path: Path):
    from defend_control.settings import ControlSettings

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


def test_development_environment_disables_secure_cookie(monkeypatch):
    from api_batch3_routes import cookie_secure

    monkeypatch.delenv("DEFEND_COOKIE_SECURE", raising=False)
    monkeypatch.setenv("DEFEND_ENV", "development")
    assert cookie_secure() is False


def test_production_environment_is_secure_by_default(monkeypatch):
    from api_batch3_routes import cookie_secure

    monkeypatch.delenv("DEFEND_COOKIE_SECURE", raising=False)
    monkeypatch.setenv("DEFEND_ENV", "production")
    assert cookie_secure() is True


def test_explicit_cookie_setting_wins_over_environment(monkeypatch):
    from api_batch3_routes import cookie_secure

    monkeypatch.setenv("DEFEND_ENV", "production")
    monkeypatch.setenv("DEFEND_COOKIE_SECURE", "false")
    assert cookie_secure() is False
    monkeypatch.setenv("DEFEND_COOKIE_SECURE", "true")
    assert cookie_secure() is True


def test_local_and_remote_process_specs_have_distinct_cookie_policy(tmp_path):
    from defend_control.local_model import build_local_process_specs
    from defend_control.remote_vllm import build_remote_process_specs
    from defend_control.types import ModelReady

    local = build_local_process_specs(
        _settings(tmp_path),
        {},
        ModelReady("defend-ai:latest", "ollama", "http://127.0.0.1:11434"),
    )
    remote = build_remote_process_specs(
        _settings(tmp_path),
        {"VLLM_API_KEY": "test"},
        ModelReady("defend-ai", "openai_compatible", "http://127.0.0.1:8001/v1"),
    )
    assert local.api.env["DEFEND_ENV"] == "development"
    assert local.api.env["DEFEND_COOKIE_SECURE"] == "false"
    assert remote.api.env["DEFEND_ENV"] == "production"
    assert remote.api.env["DEFEND_COOKIE_SECURE"] == "true"
