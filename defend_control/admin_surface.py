"""Shared platform admin surface: FastAPI admin API + Next.js web app.

The surface (``api_server.py`` + ``defend-ui-v2``) hosts the web
Setup/Integrations control plane. It is independent of product runtimes so
setup works without DEFEND AI, DEFENDmarkets, SCS AI, or DEFENDcoder running.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import time

from .health import HealthResult, probe_http
from .processes import ProcessSpec, ProcessSupervisor
from .settings import ControlSettings

_PROBE_TIMEOUT_SECONDS = 2.0
_WAIT_POLL_SECONDS = 0.2
_DEFAULT_READY_TIMEOUT_SECONDS = 60.0

_ADMIN_API_ENV_NAMES = frozenset(
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


def _secret_subset(secrets: Mapping[str, str]) -> dict[str, str]:
    return {
        name: value
        for name, value in secrets.items()
        if name in _ADMIN_API_ENV_NAMES and isinstance(value, str) and value
    }


@dataclass(frozen=True)
class AdminSurfaceSpecs:
    api: ProcessSpec
    web: ProcessSpec


def build_admin_surface_specs(
    settings: ControlSettings,
    secrets: Mapping[str, str],
    python_executable: str,
) -> AdminSurfaceSpecs:
    """Build model-independent api/web specs for the shared admin surface."""
    if not isinstance(python_executable, str) or not python_executable.strip():
        raise ValueError("python_executable must be a non-empty string")
    secret_env = _secret_subset(secrets)
    api_env = {
        "DEFEND_API_PORT": str(settings.api_port),
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
    return AdminSurfaceSpecs(
        api=ProcessSpec(
            "api",
            (python_executable, "api_server.py"),
            repo,
            api_env,
            f"http://127.0.0.1:{settings.api_port}/health",
        ),
        web=ProcessSpec(
            "web",
            ("npm.cmd", "run", "start"),
            repo / "defend-ui-v2",
            {"PORT": str(settings.web_port), "HOSTNAME": "127.0.0.1"},
            f"http://127.0.0.1:{settings.web_port}/",
        ),
    )


class AdminSurfaceStartFailed(RuntimeError):
    def __init__(self, component: str, detail: str = "not ready") -> None:
        super().__init__(f"shared admin surface {component} start failed: {detail}")
        self.component = component


class AdminSurfaceController:
    """Verify-or-start lifecycle for the shared web/admin surface.

    The api/web processes are owned by the platform (names ``api``/``web`` in
    the shared ``ProcessSupervisor``); the DEFEND AI stack adopts them instead
    of starting duplicates.
    """

    def __init__(
        self,
        *,
        supervisor: ProcessSupervisor,
        settings: ControlSettings,
        secrets: Mapping[str, str] | object,
        python_executable: str,
        health_probe: Callable[..., HealthResult] = probe_http,
        build_specs: Callable[..., AdminSurfaceSpecs] = build_admin_surface_specs,
        ready_timeout_seconds: float = _DEFAULT_READY_TIMEOUT_SECONDS,
        probe_timeout_seconds: float = _PROBE_TIMEOUT_SECONDS,
    ) -> None:
        if (
            isinstance(ready_timeout_seconds, bool)
            or not isinstance(ready_timeout_seconds, (int, float))
            or not 0 < float(ready_timeout_seconds) <= 600
        ):
            raise ValueError("ready_timeout_seconds must be in (0, 600]")
        if (
            isinstance(probe_timeout_seconds, bool)
            or not isinstance(probe_timeout_seconds, (int, float))
            or not 0 < float(probe_timeout_seconds) <= 60
        ):
            raise ValueError("probe_timeout_seconds must be in (0, 60]")
        if not isinstance(settings, ControlSettings):
            raise TypeError("settings must be ControlSettings")
        self._supervisor = supervisor
        self._settings = settings
        self._secrets = secrets
        self._python_executable = python_executable
        self._health_probe = health_probe
        self._build_specs = build_specs
        self._ready_timeout_seconds = float(ready_timeout_seconds)
        self._probe_timeout_seconds = float(probe_timeout_seconds)

    def _api_health_url(self) -> str:
        return f"http://127.0.0.1:{self._settings.api_port}/health"

    def _web_health_url(self) -> str:
        return f"http://127.0.0.1:{self._settings.web_port}/"

    def healthy(self) -> bool:
        return bool(
            self._health_probe(
                self._api_health_url(), self._probe_timeout_seconds
            ).ok
            and self._health_probe(
                self._web_health_url(), self._probe_timeout_seconds
            ).ok
        )

    def _wait_healthy(self, component: str, url: str) -> None:
        deadline = time.monotonic() + self._ready_timeout_seconds
        while True:
            result = self._health_probe(url, self._probe_timeout_seconds)
            if result.ok:
                return
            if time.monotonic() >= deadline:
                raise AdminSurfaceStartFailed(
                    component, "health check timed out"
                )
            time.sleep(_WAIT_POLL_SECONDS)

    def ensure_ready(self) -> None:
        """Verify the surface is healthy; otherwise start it. Never duplicates.

        Raises AdminSurfaceStartFailed when the surface cannot be made ready.
        """
        if self.healthy():
            return
        source = self._secrets
        values = source.load() if hasattr(source, "load") else source
        if not isinstance(values, Mapping) or not all(
            isinstance(name, str) and isinstance(value, str)
            for name, value in values.items()
        ):
            raise AdminSurfaceStartFailed("secrets", "local secret store is invalid")
        specs = self._build_specs(
            self._settings, dict(values), self._python_executable
        )
        started: list[str] = []
        try:
            for name, spec in (("api", specs.api), ("web", specs.web)):
                try:
                    self._supervisor.start(spec)
                except ValueError:
                    # Already supervised (e.g. DEFEND AI stack owns it); the
                    # readiness wait below still verifies it becomes healthy.
                    pass
                started.append(name)
                self._wait_healthy(name, spec.health_url)
        except Exception as error:
            for name in reversed(started):
                try:
                    self._supervisor.stop(name)
                except Exception:
                    pass
            if isinstance(error, AdminSurfaceStartFailed):
                raise
            raise AdminSurfaceStartFailed(
                "startup", f"unexpected {type(error).__name__}"
            ) from None

    def stop(self) -> None:
        for name in ("web", "api"):
            try:
                self._supervisor.stop(name)
            except Exception:
                pass


def resolve_setup_target(
    settings: ControlSettings,
    health_probe: Callable[..., HealthResult] = probe_http,
) -> tuple[str, str, bool]:
    """Resolve the Setup URLs: local admin surface and public fallback.

    Returns ``(local_url, public_url, local_ok)``. The local probe hits the
    Next.js /health rewrite, which only succeeds when the admin API is up.
    """
    local_url = f"http://127.0.0.1:{settings.web_port}/setup"
    public_url = f"{settings.public_web_origin}/setup"
    probe = health_probe(
        f"http://127.0.0.1:{settings.web_port}/health",
        _PROBE_TIMEOUT_SECONDS,
    )
    return local_url, public_url, bool(probe.ok)