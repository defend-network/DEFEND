"""M4.8.2C-R product-owned launch contract + auth bootstrap + proxy tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from defend_markets.launch import (
    MarketsLaunchManifest,
    build_manifest,
    PRODUCT_ID,
    DISPLAY_NAME,
    API_HOST,
    UI_HOST,
)
from defend_markets.config import MarketsSettings


def _settings(api: int = 8500, web: int = 3500) -> MarketsSettings:
    return MarketsSettings(
        data_root=Path("."),
        database_url="postgresql://x:x@localhost:5432/markets",
        api_port=api,
        web_port=web,
    )


def test_manifest_derives_ports_from_settings(tmp_path):
    manifest = build_manifest(tmp_path, settings=_settings(8500, 3500))
    assert manifest.product_id == "markets"
    assert manifest.display_name == "DEFENDmarkets"
    assert manifest.api_host == "127.0.0.1"
    assert manifest.api_port == 8500
    assert manifest.ui_port == 3500
    assert manifest.api_health_url == "http://127.0.0.1:8500/health"
    assert manifest.ui_health_url == "http://127.0.0.1:3500/markets-health"
    assert manifest.open_url == "http://127.0.0.1:3500/markets"
    assert manifest.ui_working_directory.name == "defendmarkets-ui"


def test_manifest_api_argv_and_env(tmp_path):
    manifest = build_manifest(tmp_path, settings=_settings(8500, 3500))
    assert manifest.api_argv("python.exe") == ("python.exe", "-m", "tools.defend_markets_server")
    env = manifest.api_environment()
    assert env["MARKETS_API_PORT"] == "8500"
    assert env["MARKETS_WEB_PORT"] == "3500"


def test_manifest_ui_env_includes_loopback_internal_target(tmp_path):
    manifest = build_manifest(tmp_path, settings=_settings(8500, 3500))
    env = manifest.ui_environment()
    assert env["PORT"] == "3500"
    assert env["MARKETS_INTERNAL_API_ORIGIN"] == "http://127.0.0.1:8500"


def test_manifest_does_not_change_when_api_port_changes(tmp_path):
    # Port drift: a manifest built for a non-default port must reflect it, not
    # silently remain at the stale 8500 default.
    manifest = build_manifest(tmp_path, settings=_settings(8600, 3600))
    assert manifest.api_port == 8600
    assert manifest.ui_port == 3600
    assert manifest.api_health_url == "http://127.0.0.1:8600/health"
    assert manifest.ui_environment()["MARKETS_INTERNAL_API_ORIGIN"] == "http://127.0.0.1:8600"


def test_manifest_is_single_authority_no_control_center_fields():
    # The manifest exposes only supervision fields, not product policy.
    fields = set(MarketsLaunchManifest.__dataclass_fields__)
    for banned in ("risk_policy", "quant_policy", "m5_settings", "provider_policy", "financial_policy", "model_policy"):
        assert banned not in fields


# --- auth bootstrap ---

from defend_markets.auth_bootstrap import (
    OwnerAuthBootstrap,
    resolve_owner_credentials,
    bootstrap_owner_auth,
)


def test_auth_resolution_prefers_environment(monkeypatch):
    monkeypatch.setenv("DEFEND_OWNER_USER", "MASSA")
    monkeypatch.setenv("DEFEND_OWNER_PASS", "x")
    monkeypatch.setenv("DEFEND_OWNER_EMAIL", "o@x.com")
    state, creds, source = resolve_owner_credentials()
    assert state == "READY"
    assert creds is not None and creds["DEFEND_OWNER_USER"] == "MASSA"
    assert source == "environment"


def test_auth_resolution_not_configured(monkeypatch, tmp_path):
    for key in ("DEFEND_OWNER_USER", "DEFEND_OWNER_PASS", "DEFEND_OWNER_EMAIL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    state, creds, source = resolve_owner_credentials()
    assert state == "NOT_CONFIGURED"
    assert creds is None


def test_bootstrap_not_configured_is_explicit(monkeypatch, tmp_path):
    for key in ("DEFEND_OWNER_USER", "DEFEND_OWNER_PASS", "DEFEND_OWNER_EMAIL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    result = bootstrap_owner_auth()
    assert result.state == "NOT_CONFIGURED"
    assert result.credentials_configured is False
    assert "password" not in str(result).lower() or result.detail == ""
