from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import sys
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .processes import ProcessSpec
from .settings import ControlSettings
from .types import ModelReady


_OLLAMA_ENDPOINT = "http://127.0.0.1:11434"
_TAGS_URL = f"{_OLLAMA_ENDPOINT}/api/tags"
_MAX_TAGS_BYTES = 64 * 1024
_API_ENV_NAMES = frozenset(
    {
        "DEFEND_API_TOKEN",
        "DEFEND_OWNER_USER",
        "DEFEND_OWNER_PASS",
        "DEFEND_OWNER_EMAIL",
        "DEFEND_ADMIN_SESSION_HOURS",
        "DEFEND_ACCOUNT_SESSION_HOURS",
        "DEFEND_VISITOR_HMAC_KEY",
        "DEFEND_GMAIL_SMTP_USERNAME",
        "DEFEND_GMAIL_APP_PASSWORD",
        "DEFEND_GMAIL_SMTP_SECURITY",
        "DEFEND_GMAIL_SMTP_HOST",
        "DEFEND_GMAIL_SMTP_PORT",
        "DEFEND_GMAIL_SMTP_TIMEOUT",
        "DEFEND_GMAIL_SENDER",
        "TAVILY_API_KEY",
    }
)


class LocalModelUnavailable(RuntimeError):
    """Raised when loopback Ollama cannot prove the configured tag exists."""


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def _fetch_json(url: str, timeout_seconds: float) -> object:
    request = Request(url, method="GET", headers={"Accept": "application/json"})
    opener = build_opener(_NoRedirectHandler())
    with opener.open(request, timeout=timeout_seconds) as response:
        payload = response.read(_MAX_TAGS_BYTES + 1)
    if len(payload) > _MAX_TAGS_BYTES:
        raise ValueError("Ollama response exceeds the supported size")
    return json.loads(payload.decode("utf-8"))


class LocalOllamaBackend:
    def __init__(
        self,
        *,
        fetch_json: Callable[[str, float], object] = _fetch_json,
        timeout_seconds: float = 5.0,
    ) -> None:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not 0 < float(timeout_seconds) <= 60
        ):
            raise ValueError("timeout_seconds must be in (0, 60]")
        self._fetch_json = fetch_json
        self._timeout_seconds = float(timeout_seconds)

    def verify(self, model: str) -> ModelReady:
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be a non-empty string")
        try:
            document = self._fetch_json(_TAGS_URL, self._timeout_seconds)
        except Exception as error:
            error_type = type(error).__name__
            raise LocalModelUnavailable(
                f"configured Ollama model could not be verified ({error_type})"
            ) from None

        models = document.get("models") if isinstance(document, Mapping) else None
        names = {
            candidate
            for entry in models
            if isinstance(entry, Mapping)
            for candidate in (entry.get("name"), entry.get("model"))
            if isinstance(candidate, str)
        } if isinstance(models, list) else set()
        if model not in names:
            raise LocalModelUnavailable(
                "configured Ollama model is not installed on loopback"
            )
        return ModelReady(model, "ollama", _OLLAMA_ENDPOINT)


@dataclass(frozen=True)
class LocalProcessSpecs:
    api: ProcessSpec
    web: ProcessSpec
    cloudflare: ProcessSpec


def build_local_process_specs(
    settings: ControlSettings,
    secrets: Mapping[str, str],
    model_ready: ModelReady,
) -> LocalProcessSpecs:
    if model_ready.backend != "ollama" or model_ready.endpoint != _OLLAMA_ENDPOINT:
        raise ValueError("local process specs require loopback Ollama readiness")
    secret_env = {
        name: value
        for name, value in secrets.items()
        if name in _API_ENV_NAMES and isinstance(value, str) and value
    }
    api_env = {
        "DEFEND_API_MODE": "defend_ai",
        "DEFEND_MODEL_BACKEND": "ollama",
        "DEFEND_MODEL": model_ready.model,
        "OLLAMA_HOST": model_ready.endpoint,
        "DEFEND_API_PORT": str(settings.defend_ai_api_port),
        "DEFEND_OWNER_USER": "MASSA",
        "DEFEND_OWNER_EMAIL": "chairman@defend-network.org",
        "DEFEND_ADMIN_SESSION_HOURS": "12",
        "DEFEND_ACCOUNT_SESSION_HOURS": "12",
        "DEFEND_GMAIL_SMTP_SECURITY": "ssl",
        "DEFEND_GMAIL_SMTP_HOST": "smtp.gmail.com",
        "DEFEND_GMAIL_SMTP_PORT": "465",
        "DEFEND_GMAIL_SMTP_TIMEOUT": "15",
        "DEFEND_GMAIL_SENDER": secret_env.get(
            "DEFEND_GMAIL_SMTP_USERNAME", "chairman@defend-network.org"
        ),
        "DEFEND_DATA_ROOT": str(settings.data_root),
        "DEFEND_PUBLIC_WEB_ORIGIN": settings.public_web_origin,
        "DEFEND_CORS_ORIGINS": settings.public_web_origin,
        "DEFEND_TRUST_CLOUDFLARE": "true",
        "DEFEND_COOKIE_SECURE": "true",
        **secret_env,
    }
    repo = settings.repo_root
    api_port = settings.defend_ai_api_port
    python = sys.executable
    return LocalProcessSpecs(
        api=ProcessSpec(
            "api",
            (python, "api_server.py"),
            repo,
            api_env,
            f"http://127.0.0.1:{api_port}/health",
        ),
        web=ProcessSpec(
            "web",
            ("npm.cmd", "run", "start"),
            repo / "defend-ui-v2",
            {"PORT": "3000", "HOSTNAME": "127.0.0.1"},
            "http://127.0.0.1:3000/",
        ),
        cloudflare=ProcessSpec(
            "cloudflare",
            (
                str(settings.cloudflared_exe),
                "tunnel",
                "--config",
                str(settings.cloudflared_config),
                "run",
                settings.cloudflared_tunnel,
            ),
            repo,
            {},
            settings.public_web_origin,
        ),
    )
