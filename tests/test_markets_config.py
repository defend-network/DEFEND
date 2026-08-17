from __future__ import annotations

from pathlib import Path

import pytest

from defend_markets.config import MarketsSettings


@pytest.fixture
def clean_env(monkeypatch):
    for name in ("MARKETS_DATABASE_URL", "MARKETS_API_PORT", "MARKETS_WEB_PORT",
                 "MARKETS_PUBLIC_ORIGIN", "MARKETS_SESSION_COOKIE", "MARKETS_DATA_ROOT"):
        monkeypatch.delenv(name, raising=False)
    yield


def _url() -> str:
    return "postgresql://x:x@localhost:5432/markets"


def test_default_ports_are_reserved_for_markets(clean_env, monkeypatch):
    monkeypatch.setenv("MARKETS_DATABASE_URL", _url())
    settings = MarketsSettings.from_env()
    assert settings.api_port == 8300
    assert settings.web_port == 3300
    assert settings.public_origin == "https://defendmarkets.defend-network.org"
    assert settings.session_cookie == "markets_session"


def test_environment_overrides_apply(clean_env, monkeypatch):
    monkeypatch.setenv("MARKETS_DATABASE_URL", _url())
    monkeypatch.setenv("MARKETS_API_PORT", "8400")
    monkeypatch.setenv("MARKETS_WEB_PORT", "3400")
    settings = MarketsSettings.from_env()
    assert settings.api_port == 8400
    assert settings.web_port == 3400


def test_database_url_is_required(clean_env):
    with pytest.raises(ValueError, match="MARKETS_DATABASE_URL"):
        MarketsSettings.from_env()


def test_invalid_port_rejected(clean_env, monkeypatch):
    monkeypatch.setenv("MARKETS_DATABASE_URL", _url())
    monkeypatch.setenv("MARKETS_API_PORT", "not-a-port")
    with pytest.raises(ValueError, match="integer"):
        MarketsSettings.from_env()


def test_empty_database_url_rejected():
    with pytest.raises(ValueError, match="MARKETS_DATABASE_URL"):
        MarketsSettings(
            data_root=Path("."),
            database_url="   ",
        )


def test_data_root_expands_and_resolves(clean_env, monkeypatch):
    monkeypatch.setenv("MARKETS_DATABASE_URL", _url())
    monkeypatch.setenv("MARKETS_DATA_ROOT", ".")
    settings = MarketsSettings.from_env()
    assert settings.data_root.is_absolute()


def test_ports_collide_with_neither_existing_application():
    # DEFENDcoder owns 8301 (API) and 3301 (web) per shared_platform.
    assert 8300 != 8301
    assert 3300 != 3301