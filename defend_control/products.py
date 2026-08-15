from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import time
from typing import Protocol
import webbrowser

from .health import JsonResult, fetch_http_json
from .processes import LogEntry, ProcessSpec


@dataclass(frozen=True)
class ProductStatus:
    application_id: str
    display_name: str
    state: str
    status_text: str
    details: tuple[tuple[str, str], ...] = ()
    open_url: str | None = None
    launch_available: bool = True
    stop_available: bool = True
    open_available: bool = True
    logs_available: bool = True
    last_error: str | None = None


class ProductService(Protocol):
    application_id: str
    display_name: str

    @property
    def state(self) -> str: ...

    def start(self) -> ProductStatus: ...

    def stop(self) -> ProductStatus: ...

    def status(self) -> ProductStatus: ...

    def health(self) -> bool: ...

    def open_url(self) -> bool: ...

    def logs(self) -> tuple[LogEntry, ...]: ...


@dataclass(frozen=True)
class SmokeResult:
    ok: bool
    endpoint: str
    latency_ms: int
    detail: str


@dataclass(frozen=True)
class ProductsSettings:
    sports_api_port: int = 8200
    sports_web_port: int = 3200
    sports_public_origin: str = "https://defendsports.defend-network.org"
    sports_data_root: Path = Path(r"C:\DEFEND_SPORTS_DATA")
    scs_api_port: int = 8100
    scs_web_port: int = 3100
    scs_public_origin: str = "https://ai.sunshineclimatesolutions.com"
    coder_public_origin: str = "https://defendcoder.defend-network.org"
    sports_database_url: str | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls) -> "ProductsSettings":
        def port(name: str, default: int) -> int:
            value = os.environ.get(name)
            if value is None:
                return default
            try:
                return int(value)
            except ValueError:
                return default

        def text(name: str, default: str) -> str:
            value = os.environ.get(name)
            if value is None or not value.strip():
                return default
            return value

        return cls(
            sports_api_port=port("SPORTS_API_PORT", 8200),
            sports_web_port=port("SPORTS_WEB_PORT", 3200),
            sports_public_origin=text(
                "SPORTS_PUBLIC_ORIGIN",
                "https://defendsports.defend-network.org",
            ),
            sports_data_root=Path(
                text("SPORTS_DATA_ROOT", str(Path(r"C:\DEFEND_SPORTS_DATA")))
            ),
            scs_api_port=port("SCS_API_PORT", 8100),
            scs_web_port=port("SCS_WEB_PORT", 3100),
            scs_public_origin=text(
                "SCS_PUBLIC_ORIGIN",
                "https://ai.sunshineclimatesolutions.com",
            ),
            coder_public_origin=text(
                "CODER_PUBLIC_ORIGIN",
                "https://defendcoder.defend-network.org",
            ),
            sports_database_url=os.environ.get("SPORTS_DATABASE_URL"),
        )


def build_sports_process_spec(
    settings: ProductsSettings,
    repository: Path,
    python_executable: str,
) -> ProcessSpec:
    if not settings.sports_database_url:
        raise ValueError("SPORTS_DATABASE_URL is not configured")
    return ProcessSpec(
        name="sports:api",
        argv=(python_executable, "-m", "tools.defend_sports_server"),
        cwd=Path(repository),
        env={
            "SPORTS_DATA_ROOT": str(settings.sports_data_root),
            "SPORTS_PUBLIC_ORIGIN": settings.sports_public_origin,
            "SPORTS_SESSION_COOKIE": "sports_session",
            "SPORTS_API_PORT": str(settings.sports_api_port),
            "SPORTS_WEB_PORT": str(settings.sports_web_port),
            "SPORTS_DATABASE_URL": settings.sports_database_url,
        },
        health_url=f"http://127.0.0.1:{settings.sports_api_port}/health",
    )


class DefendService:
    application_id = "defend"
    display_name = "DEFEND AI"

    def __init__(self, controller, *, public_origin: str) -> None:
        self._controller = controller
        self._public_origin = public_origin

    @property
    def state(self) -> str:
        return self._controller.poll_state().state

    def start(self, mode: str | None = None) -> ProductStatus:
        if mode not in ("vast", "ollama"):
            return ProductStatus(
                application_id=self.application_id,
                display_name=self.display_name,
                state=self.state,
                status_text="Choose a model backend to launch",
                details=(("Model backend", "none selected"),),
                open_url=self._public_origin,
                last_error="No model backend selected",
            )
        try:
            self._controller.start(mode)
        except Exception as error:
            return self._row(
                state="failed",
                status_text=f"Start failed ({type(error).__name__})",
                last_error=f"start failed ({type(error).__name__})",
            )
        return self.status()

    def stop(self) -> ProductStatus:
        try:
            self._controller.stop_local()
        except Exception as error:
            return self._row(
                state="failed",
                status_text=f"Stop failed ({type(error).__name__})",
                last_error=f"stop failed ({type(error).__name__})",
            )
        return self.status()

    def status(self) -> ProductStatus:
        state = self._controller.poll_state()
        details = (
            ("Model backend", state.selected_mode or "—"),
            (
                "Owned services",
                ", ".join(state.owned_services) if state.owned_services else "—",
            ),
        )
        return self._row(
            state=state.state,
            status_text=state.message or state.state,
            details=details,
            last_error=state.message,
        )

    def health(self) -> bool:
        return self.state in ("ready", "degraded", "starting")

    def open_url(self) -> bool:
        return webbrowser.open(self._public_origin)

    def logs(self) -> tuple[LogEntry, ...]:
        return self._controller.poll_state().logs

    def _row(
        self,
        *,
        state: str,
        status_text: str,
        details: tuple[tuple[str, str], ...] = (),
        last_error: str | None = None,
    ) -> ProductStatus:
        return ProductStatus(
            application_id=self.application_id,
            display_name=self.display_name,
            state=state,
            status_text=status_text,
            details=details,
            open_url=self._public_origin,
            last_error=last_error,
        )


class SportsService:
    application_id = "sports"
    display_name = "DEFEND Sports"

    def __init__(
        self,
        *,
        supervisor,
        repository: Path,
        python_executable: str,
        settings: ProductsSettings,
        probe=fetch_http_json,
        clock=time.monotonic,
        probe_ttl_seconds: float = 3.0,
    ) -> None:
        self._supervisor = supervisor
        self._repository = Path(repository)
        self._python_executable = str(python_executable)
        self._settings = settings
        self._probe = probe
        self._clock = clock
        self._probe_ttl = float(probe_ttl_seconds)
        self._probe_cache: dict[str, tuple[float, JsonResult]] = {}
        self._last_error: str | None = None

    @property
    def state(self) -> str:
        for snap in self._supervisor.snapshot():
            if snap.name == "sports:api":
                return "running" if snap.running else "failed"
        return "stopped"

    def _health_url(self) -> str:
        return f"http://127.0.0.1:{self._settings.sports_api_port}/health"

    def _sources_url(self) -> str:
        return (
            f"http://127.0.0.1:{self._settings.sports_api_port}/v1/system/sources"
        )

    def _cached_json(self, url: str) -> JsonResult:
        now = self._clock()
        cached = self._probe_cache.get(url)
        if cached is not None and now - cached[0] < self._probe_ttl:
            return cached[1]
        result = self._probe(url, 2.0)
        self._probe_cache[url] = (now, result)
        return result

    def start(self) -> ProductStatus:
        if not self._settings.sports_database_url:
            self._last_error = "SPORTS_DATABASE_URL is not configured"
            return self.status()
        if self.state == "running":
            return self.status()
        spec = build_sports_process_spec(
            self._settings, self._repository, self._python_executable
        )
        try:
            self._supervisor.logs.add_known_secrets(
                [self._settings.sports_database_url]
            )
            self._supervisor.start(spec)
            self._last_error = None
        except Exception as error:
            self._last_error = f"start failed ({type(error).__name__})"
        return self.status()

    def stop(self) -> ProductStatus:
        try:
            self._supervisor.stop("sports:api")
            self._last_error = None
        except Exception as error:
            self._last_error = f"stop failed ({type(error).__name__})"
        return self.status()

    def status(self) -> ProductStatus:
        state = self.state
        details: list[tuple[str, str]] = [
            ("API state", state),
            ("DB health", "—"),
            ("Schema version", "—"),
            ("Public origin", self._settings.sports_public_origin),
            ("Sources", "—"),
        ]
        if state == "running":
            health = self._cached_json(self._health_url())
            if health.ok and isinstance(health.data, dict):
                details[1] = (
                    "DB health",
                    str(health.data.get("database") or "unknown"),
                )
                schema = health.data.get("schema_version")
                if schema is not None:
                    details[2] = ("Schema version", str(schema))
            sources = self._cached_json(self._sources_url())
            if sources.ok and isinstance(sources.data, dict):
                source_list = sources.data.get("sources")
                if isinstance(source_list, list):
                    details[4] = ("Sources", str(len(source_list)))
        status_text = f"API {state}"
        if self._last_error:
            status_text += f" — {self._last_error}"
        return ProductStatus(
            application_id=self.application_id,
            display_name=self.display_name,
            state=state,
            status_text=status_text,
            details=tuple(details),
            open_url=self._settings.sports_public_origin,
            last_error=self._last_error,
        )

    def smoke(self) -> SmokeResult:
        url = self._health_url()
        result = self._probe(url, 3.0)
        if result.ok and isinstance(result.data, dict):
            detail = (
                "database="
                f"{result.data.get('database')} "
                f"schema_version={result.data.get('schema_version')}"
            )
        elif result.error_type:
            detail = result.error_type
        else:
            detail = "NotReady"
        return SmokeResult(result.ok, url, result.latency_ms, detail)

    def health(self) -> bool:
        return self._cached_json(self._health_url()).ok

    def open_url(self) -> bool:
        return webbrowser.open(self._settings.sports_public_origin)

    def logs(self) -> tuple[LogEntry, ...]:
        snapshot = self._supervisor.logs.snapshot()
        return tuple(
            entry for entry in snapshot if entry.service.startswith("sports:")
        )


class ScsService:
    application_id = "scs"
    display_name = "SCS"

    def __init__(
        self,
        settings: ProductsSettings,
        *,
        probe=fetch_http_json,
        clock=time.monotonic,
        probe_ttl_seconds: float = 5.0,
    ) -> None:
        self._settings = settings
        self._probe = probe
        self._clock = clock
        self._probe_ttl = float(probe_ttl_seconds)
        self._health_cache: tuple[float, JsonResult] | None = None

    @property
    def state(self) -> str:
        return "running" if self._cached_health().ok else "not configured"

    def _cached_health(self) -> JsonResult:
        now = self._clock()
        if (
            self._health_cache is not None
            and now - self._health_cache[0] < self._probe_ttl
        ):
            return self._health_cache[1]
        result = self._probe(
            f"http://127.0.0.1:{self._settings.scs_api_port}/health", 2.0
        )
        self._health_cache = (now, result)
        return result

    def start(self) -> ProductStatus:
        return self.status()

    def stop(self) -> ProductStatus:
        return self.status()

    def status(self) -> ProductStatus:
        health = self._cached_health()
        state = "running" if health.ok else "not configured"
        status_text = (
            "SCS API reachable"
            if health.ok
            else "Lifecycle not managed from Control Center"
        )
        return ProductStatus(
            application_id=self.application_id,
            display_name=self.display_name,
            state=state,
            status_text=status_text,
            details=(
                ("Public origin", self._settings.scs_public_origin),
                ("API port", str(self._settings.scs_api_port)),
                ("Web port", str(self._settings.scs_web_port)),
                ("Health", "reachable" if health.ok else "unreachable"),
            ),
            open_url=self._settings.scs_public_origin,
            launch_available=False,
            stop_available=False,
            logs_available=False,
        )

    def health(self) -> bool:
        return self._cached_health().ok

    def open_url(self) -> bool:
        return webbrowser.open(self._settings.scs_public_origin)

    def logs(self) -> tuple[LogEntry, ...]:
        return ()


class CoderService:
    application_id = "coder"
    display_name = "DEFENDcoder"

    def __init__(
        self,
        settings: ProductsSettings,
        observation: object | None = None,
    ) -> None:
        self._settings = settings
        self._observation = observation

    @property
    def state(self) -> str:
        public = self._observation_public()
        if public is None:
            return "not configured"
        return str(public.get("state") or "unavailable")

    def _observation_public(self) -> dict[str, object] | None:
        observation = self._observation
        if observation is None:
            return None
        status = getattr(observation, "status", None)
        if callable(status):
            try:
                value = status()
            except Exception:
                return None
        else:
            value = observation
        as_public = getattr(value, "as_public_dict", None)
        if callable(as_public):
            try:
                value = as_public()
            except Exception:
                value = None
        if not isinstance(value, dict):
            return None
        return value

    def status(self) -> ProductStatus:
        public = self._observation_public()
        alias = gpu = instance = hourly = budget = "—"
        if public is not None:
            alias = str(public.get("alias") or "—")
            gpu = str(public.get("gpu_name") or public.get("gpu") or "—")
            instance = str(public.get("instance_id") or "—")
            hourly = str(public.get("hourly_price") or "—")
            budget = str(public.get("session_budget_usd") or "—")
        state = self.state
        return ProductStatus(
            application_id=self.application_id,
            display_name=self.display_name,
            state=state,
            status_text=(
                "Observation-only (read-only)"
                if public is not None
                else "Observation not wired in this build"
            ),
            details=(
                ("Alias", alias),
                ("GPU", gpu),
                ("Instance", instance),
                ("$/hr", f"${hourly}" if public is not None else hourly),
                ("Session cost", f"${budget}" if public is not None else budget),
            ),
            open_url=self._settings.coder_public_origin,
            launch_available=False,
            stop_available=False,
            logs_available=False,
        )

    def start(self) -> ProductStatus:
        return self.status()

    def stop(self) -> ProductStatus:
        return self.status()

    def health(self) -> bool:
        return self.state == "ready"

    def open_url(self) -> bool:
        return webbrowser.open(self._settings.coder_public_origin)

    def logs(self) -> tuple[LogEntry, ...]:
        return ()


def build_products(
    *,
    controller,
    supervisor,
    repository: Path,
    python_executable: str,
    public_origin: str,
    settings: ProductsSettings | None = None,
    probe=fetch_http_json,
    clock=time.monotonic,
) -> tuple[ProductService, ...]:
    products_settings = settings or ProductsSettings.from_env()
    return (
        DefendService(controller, public_origin=public_origin),
        SportsService(
            supervisor=supervisor,
            repository=repository,
            python_executable=python_executable,
            settings=products_settings,
            probe=probe,
            clock=clock,
        ),
        ScsService(products_settings, probe=probe, clock=clock),
        CoderService(products_settings),
    )


def product_rows(products) -> tuple[ProductStatus, ...]:
    return tuple(product.status() for product in products)