from pathlib import Path

import pytest

from defend_sports.config import SportsSettings


def _settings_from_env(monkeypatch, **overrides) -> SportsSettings:
    monkeypatch.setenv("SPORTS_DATABASE_URL", "postgresql://sports:secret@db.example/sports")
    for name, value in overrides.items():
        monkeypatch.setenv(name, value)
    return SportsSettings.from_env()


def test_sports_settings_uses_the_reserved_defaults(monkeypatch):
    settings = _settings_from_env(monkeypatch)

    assert settings.api_port == 8200
    assert settings.web_port == 3200
    assert settings.public_origin == "https://defendsports.defend-network.org"
    assert settings.session_cookie == "sports_session"
    assert settings.data_root.is_absolute()
    assert settings.data_root == Path(r"C:\DEFEND_SPORTS_DATA").resolve(strict=False)


def test_sports_settings_requires_the_namespaced_database_url(monkeypatch):
    monkeypatch.delenv("SPORTS_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://wrong:secret@db.example/other")

    with pytest.raises(ValueError, match="SPORTS_DATABASE_URL"):
        SportsSettings.from_env()


def test_sports_settings_keeps_database_credentials_out_of_repr(monkeypatch):
    database_url = "postgresql://sports:very-secret-password@db.example/sports"
    settings = _settings_from_env(monkeypatch, SPORTS_DATABASE_URL=database_url)

    assert database_url not in repr(settings)
    assert "very-secret-password" not in repr(settings)
    assert "database_url" not in repr(settings)
    assert database_url not in repr(settings.application_context())


def test_sports_context_uses_only_the_sports_application_namespace(monkeypatch, tmp_path):
    settings = _settings_from_env(
        monkeypatch,
        SPORTS_DATA_ROOT=str(tmp_path / "SPORTS_DATA"),
        SPORTS_API_PORT="8220",
        SPORTS_WEB_PORT="3220",
        SPORTS_PUBLIC_ORIGIN="https://sports.example.test",
        SPORTS_SESSION_COOKIE="sports_test_session",
    )

    context = settings.application_context()

    assert context.application_id == "sports"
    assert context.data_root == (tmp_path / "SPORTS_DATA").resolve(strict=False)
    assert context.environment_prefix == "SPORTS"
    assert context.secret_namespace == "SPORTS"
    assert context.session_cookie == "sports_test_session"
    assert context.public_origin == "https://sports.example.test"
    assert (context.api_port, context.web_port) == (8220, 3220)
