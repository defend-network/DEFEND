from __future__ import annotations

from pathlib import Path

import pytest

from defend_control.preflight import CheckResult
from defend_data.ingest_policy import AIIngestExcluded, assert_ai_ingest_allowed
from tools import defend_control_center


class RecordingVastProvider:
    def __init__(self) -> None:
        self.mutations: list[str] = []

    def __getattr__(self, name: str):
        self.mutations.append(name)
        raise AssertionError(f"check mode must not access Vast provider method {name}")


class RecordingPreflight:
    def __init__(self) -> None:
        self.modes: list[str] = []

    def run(self, mode, settings, secrets):
        self.modes.append(mode)
        return (
            CheckResult("python-version", True, "ready"),
            CheckResult("node-version", True, "ready"),
            CheckResult("git", True, "ready"),
            CheckResult("ssh.exe", True, "ready"),
            CheckResult("import:fastapi", True, "ready"),
            CheckResult("cloudflared.exe", True, "ready"),
            CheckResult("cloudflared-config", True, "ready"),
            CheckResult("service-ports", True, "ready"),
            CheckResult("port:3000", True, "ready"),
            CheckResult("port:8000", True, "ready"),
            CheckResult("port:8001", True, "ready"),
            CheckResult("data-root", True, "ready"),
            CheckResult("settings-root", True, "ready"),
            CheckResult("logs", True, "ready"),
            CheckResult("secrets", True, "ready"),
            CheckResult("invitations", True, "ready"),
            CheckResult("next-build", True, "ready"),
        )


def test_check_mode_never_provisions_or_starts(tmp_path):
    provider = RecordingVastProvider()
    preflight = RecordingPreflight()
    settings = defend_control_center._default_settings(tmp_path)

    result = defend_control_center.run_check_mode(
        settings,
        {"synthetic": "not-a-real-secret"},
        vast=provider,
        preflight=preflight,
    )

    assert provider.mutations == []
    assert preflight.modes == ["ollama", "vast"]
    assert result.ready is True
    assert {item.name for item in result.checks} >= {
        "dependencies",
        "settings",
        "secrets",
        "ports",
        "data-root",
        "invitation-transport",
        "cloudflare",
    }
    assert "synthetic" not in repr(result)
    assert "not-a-real-secret" not in repr(result)


def test_check_mode_preserves_one_safe_remediation_per_failed_group(tmp_path):
    class FailingPreflight(RecordingPreflight):
        def run(self, mode, settings, secrets):
            results = list(super().run(mode, settings, secrets))
            results[0] = CheckResult(
                "python-version",
                False,
                "Python missing",
                "Run Bootstrap-DEFEND.ps1 -Repair",
            )
            return tuple(results)

    report = defend_control_center.run_check_mode(
        defend_control_center._default_settings(tmp_path),
        {},
        preflight=FailingPreflight(),
    )

    dependencies = next(item for item in report.checks if item.name == "dependencies")
    assert report.ready is False
    assert dependencies.ok is False
    assert dependencies.remediation == "Run Bootstrap-DEFEND.ps1 -Repair"


def test_check_mode_reports_vast_only_missing_secret_names(tmp_path):
    class ModeSpecificPreflight(RecordingPreflight):
        def run(self, mode, settings, secrets):
            results = list(super().run(mode, settings, secrets))
            missing = "DEFEND_OWNER_PASS"
            if mode == "vast":
                missing += ", HF_TOKEN, VAST_API_KEY, VLLM_API_KEY"
            results[-3] = CheckResult(
                "secrets",
                False,
                f"Missing required secret names: {missing}",
                "Enter the named secrets in local setup",
            )
            return tuple(results)

    report = defend_control_center.run_check_mode(
        defend_control_center._default_settings(tmp_path),
        {},
        preflight=ModeSpecificPreflight(),
    )

    secrets = next(item for item in report.checks if item.name == "secrets")
    assert "VAST_API_KEY" in secrets.detail
    assert "HF_TOKEN" in secrets.detail
    assert "VLLM_API_KEY" in secrets.detail


def test_tracked_operations_docs_are_ingest_excluded():
    path = Path("docs/operations/DEFEND-Control-Center.md")
    assert path.read_text("utf-8").startswith("<!-- DEFEND-AI-INGEST: EXCLUDE -->")
    with pytest.raises(AIIngestExcluded):
        assert_ai_ingest_allowed(
            filename=str(path), content_prefix=path.read_bytes()[:4096]
        )


def test_operator_docs_use_control_center_not_direct_python_or_npm_launches():
    for name in ("RUN_DEFEND.txt", "start_api.TXT"):
        text = Path(name).read_text("utf-8")
        assert "Start-DEFEND.cmd" in text
        assert "npm run dev" not in text
        assert "python.exe api_server.py" not in text
