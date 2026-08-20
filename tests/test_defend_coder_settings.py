from __future__ import annotations

import pytest

from defend_coder.config import CoderSettings


def _settings(monkeypatch, **overrides) -> CoderSettings:
    monkeypatch.setenv("CODER_DATABASE_URL", "postgresql://redacted")
    for key, value in overrides.items():
        monkeypatch.setenv(key, str(value))
    return CoderSettings.from_env()


def test_defaults(monkeypatch):
    settings = _settings(monkeypatch)

    assert settings.max_steps == 12
    assert settings.finalization_enabled is True
    assert settings.finalization_timeout_seconds == 600.0
    assert settings.max_run_seconds == 2400.0
    assert settings.idle_timeout_seconds == 600


def test_policy_overrides(monkeypatch):
    settings = _settings(
        monkeypatch,
        CODER_MAX_STEPS=20,
        CODER_FINALIZATION_ENABLED=0,
        CODER_FINALIZATION_TIMEOUT_SECONDS=90,
        CODER_MAX_RUN_SECONDS=1200,
    )

    assert settings.max_steps == 20
    assert settings.finalization_enabled is False
    assert settings.finalization_timeout_seconds == 90.0
    assert settings.max_run_seconds == 1200.0


def test_finalization_enabled_true_forms(monkeypatch):
    for form in ("1", "true", "yes", "on"):
        settings = _settings(monkeypatch, CODER_FINALIZATION_ENABLED=form)
        assert settings.finalization_enabled is True


def test_max_steps_bounds(monkeypatch):
    with pytest.raises(RuntimeError, match="CODER_MAX_STEPS"):
        _settings(monkeypatch, CODER_MAX_STEPS=0)
    with pytest.raises(RuntimeError, match="CODER_MAX_STEPS"):
        _settings(monkeypatch, CODER_MAX_STEPS=101)


def test_finalization_timeout_bounds(monkeypatch):
    with pytest.raises(RuntimeError, match="CODER_FINALIZATION_TIMEOUT_SECONDS"):
        _settings(monkeypatch, CODER_FINALIZATION_TIMEOUT_SECONDS=10)
    with pytest.raises(RuntimeError, match="CODER_FINALIZATION_TIMEOUT_SECONDS"):
        _settings(monkeypatch, CODER_FINALIZATION_TIMEOUT_SECONDS=4000)


def test_max_run_seconds_bounds(monkeypatch):
    with pytest.raises(RuntimeError, match="CODER_MAX_RUN_SECONDS"):
        _settings(monkeypatch, CODER_MAX_RUN_SECONDS=30)
    with pytest.raises(RuntimeError, match="CODER_MAX_RUN_SECONDS"):
        _settings(monkeypatch, CODER_MAX_RUN_SECONDS=20000)