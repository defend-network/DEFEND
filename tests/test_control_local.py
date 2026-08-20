from dataclasses import FrozenInstanceError
from decimal import Decimal
from pathlib import Path

import pytest

from defend_control.local_model import (
    LocalModelUnavailable,
    LocalOllamaBackend,
    build_local_process_specs,
)
from defend_control.model_registry import ADAPTER_REPO
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
        adapter_repo=ADAPTER_REPO,
        local_model="defend-ai:latest",
        vast_max_hourly=Decimal("3.00"),
    )


def test_local_ollama_requires_configured_tag_and_returns_immutable_readiness():
    requests = []

    def fetch(url, timeout):
        requests.append((url, timeout))
        return {
            "models": [
                {"name": "other:latest"},
                {"name": "defend-ai:latest"},
            ]
        }

    ready = LocalOllamaBackend(fetch_json=fetch).verify("defend-ai:latest")

    assert requests == [("http://127.0.0.1:11434/api/tags", 5.0)]
    assert ready == ModelReady(
        model="defend-ai:latest",
        backend="ollama",
        endpoint="http://127.0.0.1:11434",
    )
    with pytest.raises(FrozenInstanceError):
        ready.model = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"models": "not-a-list"},
        {"models": [{"name": "other:latest"}]},
        {"models": [{"name": 7}]},
    ],
)
def test_local_ollama_rejects_missing_or_malformed_configured_tag(payload):
    backend = LocalOllamaBackend(fetch_json=lambda _url, _timeout: payload)

    with pytest.raises(LocalModelUnavailable, match="configured Ollama model"):
        backend.verify("defend-ai:latest")


def test_local_process_specs_keep_secrets_in_api_environment_only(tmp_path):
    configured = settings(tmp_path)
    secret_values = {
        "DEFEND_OWNER_PASS": "synthetic-owner-password",
        "DEFEND_VISITOR_HMAC_KEY": "synthetic-hmac-value-with-32-chars",
        "DEFEND_GMAIL_SMTP_USERNAME": "operator@example.test",
        "DEFEND_GMAIL_APP_PASSWORD": "synthetic-gmail-password",
        "TAVILY_API_KEY": "synthetic-search-key",
    }

    specs = build_local_process_specs(
        configured,
        secret_values,
        ModelReady("defend-ai:latest", "ollama", "http://127.0.0.1:11434"),
    )

    assert specs.api.argv == (
        str(tmp_path / ".venv" / "Scripts" / "python.exe"),
        "api_server.py",
    )
    assert specs.api.cwd == tmp_path
    assert specs.api.health_url == "http://127.0.0.1:8000/health"
    assert specs.web.argv == ("npm.cmd", "run", "start")
    assert specs.web.cwd == tmp_path / "defend-ui-v2"
    assert dict(specs.web.env) == {"PORT": "3000", "HOSTNAME": "127.0.0.1"}
    assert specs.web.health_url == "http://127.0.0.1:3000/"
    assert specs.cloudflare.argv == (
        str(configured.cloudflared_exe),
        "tunnel",
        "--config",
        str(configured.cloudflared_config),
        "run",
        "defend-ai",
    )
    assert dict(specs.cloudflare.env) == {}

    expected_api_values = {
        "DEFEND_MODEL_BACKEND": "ollama",
        "DEFEND_MODEL": "defend-ai:latest",
        "OLLAMA_HOST": "http://127.0.0.1:11434",
        "DEFEND_OWNER_USER": "MASSA",
        "DEFEND_OWNER_EMAIL": "chairman@defend-network.org",
        "DEFEND_ADMIN_SESSION_HOURS": "12",
        "DEFEND_ACCOUNT_SESSION_HOURS": "12",
        "DEFEND_GMAIL_SMTP_SECURITY": "ssl",
        "DEFEND_GMAIL_SMTP_HOST": "smtp.gmail.com",
        "DEFEND_GMAIL_SMTP_PORT": "465",
        "DEFEND_GMAIL_SMTP_TIMEOUT": "15",
        "DEFEND_GMAIL_SENDER": "operator@example.test",
        "DEFEND_DATA_ROOT": str(tmp_path / "data"),
        "DEFEND_PUBLIC_WEB_ORIGIN": "https://ai.example.test",
        "DEFEND_CORS_ORIGINS": "https://ai.example.test",
        "DEFEND_TRUST_CLOUDFLARE": "true",
        "DEFEND_COOKIE_SECURE": "true",
        "DEFEND_API_PORT": "8000",
        **secret_values,
    }
    for name, value in expected_api_values.items():
        assert specs.api.env[name] == value
    serialized_argv = " ".join(
        (*specs.api.argv, *specs.web.argv, *specs.cloudflare.argv)
    )
    for value in secret_values.values():
        assert value not in serialized_argv
