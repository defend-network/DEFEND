from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import os
from pathlib import Path
import shutil
import time
from typing import Protocol
import webbrowser

from .health import JsonResult, fetch_http_json
from .model_registry import ADAPTER_REPO, ADAPTER_REVISION, LOCAL_ALIAS, SERVING_ALIAS
from .processes import LogBuffer, LogEntry, ProcessSpec
from .product_runtime import ProductRuntimeRegistry, PRODUCT_API_PORTS, PRODUCT_FORWARD_PORTS
from .coder_control_plane import (
    CoderNoQualifyingOffer,
    CoderProvisionBlocked,
)
from .coder_m0 import (
    CODER_MAX_HOURLY_UPPER_USD,
    parse_max_hourly_budget,
    resolve_alias,
)
from .coder_provisioning import (
    CoderProvisionFailure,
    format_elapsed,
    wall_clock,
)
from .coder_vast_backend import CoderVastBackendError
from .vast import vast_gpu_ram_floor


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
    error_category: str | None = None
    diagnostics: str | None = None


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


def parse_cuda_floor_env(raw: str | None) -> Decimal | None:
    """Parse CODER_MIN_CUDA_MAX_GOOD; None/'none'/empty disables the filter."""
    if raw is None or not raw.strip():
        return Decimal("13.0")
    value = raw.strip().casefold()
    if value in ("none", "0", "off", "disabled"):
        return None
    try:
        parsed = Decimal(value)
    except (ValueError, TypeError, ArithmeticError):
        return Decimal("13.0")
    if parsed <= 0:
        return None
    return parsed


@dataclass(frozen=True)
class ProductsSettings:
    sports_api_port: int = 8200
    sports_web_port: int = 3200
    sports_public_origin: str = "https://defendsports.defend-network.org"
    sports_data_root: Path = Path(r"C:\DEFEND_SPORTS_DATA")
    scs_api_port: int = 8100
    scs_web_port: int = 3100
    scs_public_origin: str = "https://ai.sunshineclimatesolutions.com"
    scs_data_root: Path = Path(r"C:\SCS_DATA")

    scs_ai_api_port: int = 8300
    scs_ai_web_port: int = 3300
    scs_ai_public_origin: str = "https://ai.sunshineclimatesolutions.com"
    scs_ai_model_alias: str | None = None
    scs_ai_model_name: str | None = None
    scs_ai_model_base_url: str | None = None
    scs_ai_model_api_key: str | None = field(default=None, repr=False)
    scs_ai_model_api_key_file: str | None = None
    coder_api_port: int = 8301
    coder_web_port: int = 3301
    coder_model_alias: str = "defendcoder-heavy"
    coder_model_name: str | None = None
    coder_model_base_url: str | None = None
    coder_model_api_key: str | None = field(default=None, repr=False)
    coder_model_api_key_file: str | None = None
    coder_public_origin: str = "https://defendcoder.defend-network.org"
    coder_workspace_root: Path = Path(r"C:\DEFEND_CODER_DATA")
    coder_database_url: str | None = field(default=None, repr=False)
    coder_max_hourly_usd: Decimal = Decimal("4.50")
    # Acquisition-side CUDA capability floor (provider cuda_max_good): the
    # pinned serving image (vllm-openai v0.27.1, torch cu130) needs CUDA
    # >= 13.0 (driver >= 570); incompatible A100 hosts are filtered before
    # rental. None disables the filter. Never applies to retained instances.
    coder_min_cuda_max_good: Decimal | None = Decimal("13.0")
    coder_config_errors: tuple[str, ...] = ()
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

        coder_config_errors: list[str] = []

        raw_max_hourly = os.environ.get("CODER_MAX_HOURLY_USD")
        if raw_max_hourly is None or not raw_max_hourly.strip():
            coder_max_hourly_usd = Decimal("4.50")
        else:
            try:
                coder_max_hourly_usd = parse_max_hourly_budget(
                    raw_max_hourly
                )
            except ValueError as error:
                coder_max_hourly_usd = Decimal("4.50")
                coder_config_errors.append(
                    f"{error}; using safe default $4.50"
                )

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
            scs_ai_api_port=port("SCS_AI_API_PORT", 8300),
            scs_ai_web_port=port("SCS_AI_WEB_PORT", 3300),
            scs_ai_public_origin=text(
                "SCS_AI_PUBLIC_ORIGIN",
                "https://ai.sunshineclimatesolutions.com",
            ),
            scs_data_root=Path(
                text("SCS_DATA_ROOT", str(Path(r"C:\SCS_DATA")))
            ),
            scs_ai_model_alias=text(
                "SCS_AI_MODEL_ALIAS", ""
            ) or None,
            scs_ai_model_name=text(
                "SCS_AI_MODEL_NAME", ""
            ) or None,
            scs_ai_model_base_url=text(
                "SCS_AI_MODEL_BASE_URL", ""
            ) or None,
            scs_ai_model_api_key=os.environ.get(
                "SCS_AI_MODEL_API_KEY"
            ),
            scs_ai_model_api_key_file=os.environ.get(
                "SCS_AI_MODEL_API_KEY_FILE"
            ) or None,
            coder_api_port=port("CODER_API_PORT", 8301),
            coder_web_port=port("CODER_WEB_PORT", 3301),
            coder_model_alias=text(
                "CODER_MODEL_ALIAS",
                "defendcoder-heavy",
            ),
            coder_model_name=text(
                "CODER_MODEL_NAME", ""
            ) or None,
            coder_model_base_url=text(
                "CODER_MODEL_BASE_URL", ""
            ) or None,
            coder_model_api_key=os.environ.get(
                "CODER_MODEL_API_KEY"
            ),
            coder_model_api_key_file=os.environ.get(
                "CODER_MODEL_API_KEY_FILE"
            ) or None,
            coder_public_origin=text(
                "CODER_PUBLIC_ORIGIN",
                "https://defendcoder.defend-network.org",
            ),
            coder_workspace_root=Path(
                text(
                    "CODER_WORKSPACE_ROOT",
                    str(Path(r"C:\DEFEND_CODER_DATA")),
                )
            ),
            coder_database_url=os.environ.get("CODER_DATABASE_URL"),
            coder_max_hourly_usd=coder_max_hourly_usd,
            coder_min_cuda_max_good=parse_cuda_floor_env(
                os.environ.get("CODER_MIN_CUDA_MAX_GOOD")
            ),
            coder_config_errors=tuple(coder_config_errors),
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


def coder_model_status_file() -> str:
    explicit = os.environ.get("CODER_MODEL_STATUS_FILE")
    if explicit and explicit.strip():
        return explicit.strip()
    return str(
        Path(os.environ.get("LOCALAPPDATA", "."))
        / "DEFEND"
        / "coder-model-status.json"
    )


def _canonical_model_name(alias: str) -> str:
    """Canonical logical model name for an alias (registry repo_id)."""
    try:
        return resolve_alias(alias).repo_id
    except ValueError:
        return ""


def build_coder_api_process_spec(
    settings: ProductsSettings,
    repository: Path,
    python_executable: str,
) -> ProcessSpec:
    if not settings.coder_database_url:
        raise ValueError("CODER_DATABASE_URL is not configured")

    env: dict[str, str] = {
        "CODER_DATABASE_URL": settings.coder_database_url,
        "CODER_HOST": "127.0.0.1",
        "CODER_PORT": str(settings.coder_api_port),
        "CODER_PUBLIC_HTTPS": "true",
        "CODER_WORKSPACE_ROOT": str(
            settings.coder_workspace_root
        ),
        "CODER_MODEL_ALIAS": settings.coder_model_alias,
        "CODER_MODEL_NAME": (
            settings.coder_model_name
            or _canonical_model_name(settings.coder_model_alias)
        ),
        "CODER_MODEL_BASE_URL": (
            settings.coder_model_base_url
            or "http://127.0.0.1:8001/v1"
        ),
        "CODER_MODEL_STATUS_FILE": coder_model_status_file(),
    }
    if settings.coder_model_api_key:
        env["CODER_MODEL_API_KEY"] = settings.coder_model_api_key
    if settings.coder_model_api_key_file:
        env["CODER_MODEL_API_KEY_FILE"] = (
            settings.coder_model_api_key_file
        )

    return ProcessSpec(
        name="coder:api",
        argv=(
            str(python_executable),
            "-m",
            "tools.defend_coder_server",
        ),
        cwd=Path(repository),
        env=env,
        health_url=(
            f"http://127.0.0.1:"
            f"{settings.coder_api_port}/health"
        ),
    )


def build_coder_web_process_spec(
    settings: ProductsSettings,
    repository: Path,
) -> ProcessSpec:
    return ProcessSpec(
        name="coder:web",
        argv=(
            "node",
            ".next/standalone/server.js",
        ),
        cwd=Path(repository) / "defendcoder-ui",
        env={
            "HOSTNAME": "127.0.0.1",
            "PORT": str(settings.coder_web_port),
            "NODE_ENV": "production",
            "DEFENDCODER_INTERNAL_API_URL": (
                f"http://127.0.0.1:"
                f"{settings.coder_api_port}"
            ),
        },
        health_url=(
            f"http://127.0.0.1:"
            f"{settings.coder_web_port}/"
        ),
    )


class StandaloneWebBuildError(FileNotFoundError):
    """DEFENDcoder standalone web bundle is missing or incomplete."""


def prepare_standalone_web(repository: Path) -> Path:
    """Make the standalone web bundle self-contained and return server.js.

    The `output: "standalone"` build produces .next/standalone/server.js
    but does NOT include static assets; `node .next/standalone/server.js`
    serves them from .next/standalone/.next/static and
    .next/standalone/public. This syncs those two trees (idempotent,
    always-fresh) and fails closed with a clear message when the build
    itself is missing — there is no silent fallback to `next start`.
    """
    ui = Path(repository) / "defendcoder-ui"
    standalone = ui / ".next" / "standalone"
    server = standalone / "server.js"
    if not server.is_file():
        raise StandaloneWebBuildError(
            f"standalone web build missing at {server}; run "
            "'npm run build' in defendcoder-ui before launching"
        )
    for relative in ("public", ".next/static"):
        source = ui / relative
        destination = standalone / relative
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)
    return server


def build_scs_api_process_spec(
    settings: ProductsSettings,
    repository: Path,
    python_executable: str,
) -> ProcessSpec:
    """SCS core operations API (scs_api.runtime) on the SCS lane."""
    return ProcessSpec(
        name="scs:api",
        argv=(
            str(python_executable),
            "-m",
            "uvicorn",
            "scs_api.runtime:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(settings.scs_api_port),
        ),
        cwd=Path(repository),
        env={
            "SCS_DATA_ROOT": str(settings.scs_data_root),
            "SCS_PUBLIC_ORIGIN": settings.scs_public_origin,
            "SCS_SESSION_COOKIE": "scs_employee_session",
            "SCS_API_PORT": str(settings.scs_api_port),
            "SCS_WEB_PORT": str(settings.scs_web_port),
        },
        health_url=(
            f"http://127.0.0.1:"
            f"{settings.scs_api_port}/health"
        ),
    )


def build_scs_ai_process_spec(
    settings: ProductsSettings,
    repository: Path,
    python_executable: str,
) -> ProcessSpec:
    env: dict[str, str] = {
        "SCS_AI_PUBLIC_ORIGIN": settings.scs_ai_public_origin,
        "SCS_AI_API_PORT": str(settings.scs_ai_api_port),
        "SCS_AI_WEB_PORT": str(settings.scs_ai_web_port),

        # Control Center owns the tunnel separately.
        # runtime.py must therefore construct it disabled in this child.
        "SCS_AI_TUNNEL_ENABLED": "false",
    }
    for name, value in (
        ("SCS_AI_MODEL_ALIAS", settings.scs_ai_model_alias),
        ("SCS_AI_MODEL_NAME", settings.scs_ai_model_name),
        ("SCS_AI_MODEL_BASE_URL", settings.scs_ai_model_base_url),
        ("SCS_AI_MODEL_API_KEY", settings.scs_ai_model_api_key),
        ("SCS_AI_MODEL_API_KEY_FILE", settings.scs_ai_model_api_key_file),
    ):
        if value is not None and value != "":
            env[name] = value

    return ProcessSpec(
        name="scs-ai:api",
        argv=(
            str(python_executable),
            "-m",
            "uvicorn",
            "scs_ai.runtime:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(settings.scs_ai_api_port),
        ),
        cwd=Path(repository),
        env=env,
        health_url=(
            f"http://127.0.0.1:"
            f"{settings.scs_ai_api_port}/health"
        ),
    )


def build_scs_web_process_spec(
    settings: ProductsSettings,
    repository: Path,
    npm_executable: str = "npm.cmd",
) -> ProcessSpec:
    """SCS web (scs-ui Next app) served with `next start` on the SCS lane."""
    return ProcessSpec(
        name="scs:web",
        argv=(
            npm_executable,
            "--prefix",
            "scs-ui",
            "run",
            "start",
        ),
        cwd=Path(repository),
        env={
            "SCS_WEB_PORT": str(settings.scs_web_port),
            "SCS_API_ORIGIN": f"http://127.0.0.1:{settings.scs_api_port}",
            "SCS_AI_API_ORIGIN": f"http://127.0.0.1:{settings.scs_ai_api_port}",
        },
        health_url=f"http://127.0.0.1:{settings.scs_web_port}/",
    )


class DefendService:
    application_id = "defend"
    display_name = "DEFEND AI"

    def __init__(
        self,
        controller,
        *,
        public_origin: str,
        api_port: int = 8401,
        probe=fetch_http_json,
        prepare_model_start=None,
        runtime_registry: ProductRuntimeRegistry | None = None,
    ) -> None:
        self._controller = controller
        self._public_origin = public_origin
        self._api_port = int(api_port)
        self._probe = probe
        self._prepare_model_start = prepare_model_start
        self._runtime_registry = runtime_registry
        self._runtime_probe_cache: tuple[float, JsonResult] | None = None

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
            if self._prepare_model_start is not None:
                self._prepare_model_start()
            self._runtime_probe_cache = None
            self._controller.start(mode)
        except Exception as error:
            return self._row(
                state="failed",
                status_text=f"Start failed ({type(error).__name__})",
                last_error=f"start failed ({type(error).__name__})",
            )
        if self._runtime_registry is not None:
            self._runtime_registry.update(
                "defend-ai",
                state="starting",
                provider=mode,
                product_api_port=self._api_port,
                model_forward_port=PRODUCT_FORWARD_PORTS["defend-ai"],
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
        if self._runtime_registry is not None:
            self._runtime_registry.record_stopped("defend-ai")
        return self.status()

    def destroy(self, confirmed_instance_id: int | None) -> ProductStatus:
        """Permanently destroy the retained provider instance.

        Never part of normal Stop. Requires the exact retained instance ID and
        provider-confirmed absence before the registry is cleared.
        """
        record = (
            self._runtime_registry.load().get("defend-ai")
            if self._runtime_registry is not None
            else None
        )
        retained = record.instance_id if record is not None else None
        if retained is None or isinstance(confirmed_instance_id, bool):
            return self._row(
                state="failed",
                status_text="No retained instance to destroy",
                last_error="no retained provider instance",
            )
        if type(confirmed_instance_id) is not int or confirmed_instance_id != retained:
            return self._row(
                state="failed",
                status_text="Enter the exact retained instance ID to destroy",
                last_error="exact instance ID confirmation required",
            )
        try:
            destroy = getattr(self._controller, "stop_and_destroy_vast", None)
            if not callable(destroy):
                raise RuntimeError("Vast.ai destruction is not available")
            self._controller.stop_and_destroy_vast(confirmed_instance_id)
        except Exception as error:
            return self._row(
                state="failed",
                status_text=f"Destroy failed ({type(error).__name__})",
                last_error=f"destroy failed ({type(error).__name__})",
            )
        if self._runtime_registry is not None:
            self._runtime_registry.record_destroyed(
                "defend-ai", confirmed_instance_id
            )
        return self.status()

    def status(self) -> ProductStatus:
        state = self._controller.poll_state()
        runtime_result = self._runtime_health()
        runtime_data = getattr(runtime_result, "data", None)
        runtime = runtime_data if isinstance(runtime_data, dict) else {}
        provider = str(runtime.get("provider") or "unreported")
        model = str(runtime.get("model") or "unreported")
        adapter = str(
            runtime.get("adapter_repo")
            or ("built-in local Modelfile" if provider == "ollama" else "unreported")
        )
        adapter_revision = str(
            runtime.get("adapter_revision")
            or ("not applicable" if provider == "ollama" else "unreported")
        )
        base_model = str(runtime.get("base_repo") or "unreported")
        base_revision = str(runtime.get("base_revision") or "unreported")
        serving_engine = {
            "ollama": "Ollama",
            "openai_compatible": "OpenAI-compatible (vLLM expected)",
            "vllm": "vLLM",
        }.get(provider.casefold(), provider)
        details = (
            ("Model backend", state.selected_mode or "â€”"),
            (
                "Owned services",
                ", ".join(state.owned_services) if state.owned_services else "â€”",
            ),
            ("Serving alias", model),
            ("Provider", provider),
            ("Serving engine", serving_engine),
            ("Adapter", adapter),
            ("Adapter revision", adapter_revision),
            ("Base model", base_model),
            ("Base revision", base_revision),
        )
        state_value = state.state
        status_text = state.message or state.state
        last_error = state.message
        if state.selected_mode in ("vast", "ollama") and state.state in (
            "starting",
            "ready",
            "degraded",
        ):
            runtime_matches = self._runtime_matches(state.selected_mode, runtime)
            if runtime_result.ok and not runtime_matches:
                state_value = "degraded"
                status_text = (
                    f"{state.selected_mode} selected but API runtime reports "
                    f"provider={provider}, model={model}; backend not active"
                )
                last_error = status_text
            elif not runtime_result.ok and state.state == "ready":
                state_value = "degraded"
                status_text = "Selected backend API health is unavailable"
                last_error = status_text
        return self._row(
            state=state_value,
            status_text=status_text,
            details=details,
            last_error=last_error,
        )

    def _runtime_health(self) -> JsonResult:
        now = time.monotonic()
        if (
            self._runtime_probe_cache is not None
            and now - self._runtime_probe_cache[0] < 1.0
        ):
            return self._runtime_probe_cache[1]
        result = self._probe(f"http://127.0.0.1:{self._api_port}/health", 2.0)
        self._runtime_probe_cache = (now, result)
        return result

    @staticmethod
    def _runtime_matches(mode: str, runtime: dict[str, object]) -> bool:
        provider = str(runtime.get("provider") or "").casefold()
        model = str(runtime.get("model") or "")
        if mode == "ollama":
            return provider == "ollama" and model == LOCAL_ALIAS
        return (
            provider in {"openai_compatible", "vllm"}
            and model == SERVING_ALIAS
            and runtime.get("adapter_repo") == ADAPTER_REPO
            and runtime.get("adapter_revision") == ADAPTER_REVISION
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
    display_name = "DEFENDmarkets"

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
            ("DB health", "â€”"),
            ("Schema version", "â€”"),
            ("Public origin", self._settings.sports_public_origin),
            ("Sources", "â€”"),
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
            status_text += f" â€” {self._last_error}"
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
    display_name = "SCS AI"

    def __init__(
        self,
        settings: ProductsSettings,
        *,
        supervisor=None,
        repository: Path | None = None,
        python_executable: str | None = None,
        tunnel=None,
        probe=fetch_http_json,
        npm_executable: str | None = None,
    ) -> None:
        self._settings = settings
        self._supervisor = supervisor
        self._repository = (
            Path(repository)
            if repository is not None
            else None
        )
        self._python_executable = (
            str(python_executable)
            if python_executable is not None
            else None
        )
        self._tunnel = tunnel
        self._probe = probe
        self._npm_executable = npm_executable or "npm.cmd"
        self._last_error: str | None = None

    @property
    def _lifecycle_enabled(self) -> bool:
        return (
            self._supervisor is not None
            and self._repository is not None
            and self._python_executable is not None
            and self._tunnel is not None
        )

    def _api_running(self) -> bool:
        if not self._lifecycle_enabled:
            return False

        for snapshot in self._supervisor.snapshot():
            if snapshot.name == "scs-ai:api":
                return bool(snapshot.running)

        return False

    def _core_api_running(self) -> bool:
        if not self._lifecycle_enabled:
            return False

        for snapshot in self._supervisor.snapshot():
            if snapshot.name == "scs:api":
                return bool(snapshot.running)

        return False

    def _web_running(self) -> bool:
        if not self._lifecycle_enabled:
            return False

        for snapshot in self._supervisor.snapshot():
            if snapshot.name == "scs:web":
                return bool(snapshot.running)

        return False

    def _local_web_url(self) -> str:
        return f"http://127.0.0.1:{self._settings.scs_web_port}"

    def _resolve_open_url(self) -> str:
        if (
            self._lifecycle_enabled
            and self._tunnel.status().state == "connected"
        ):
            return self._settings.scs_ai_public_origin
        return self._local_web_url()

    @property
    def state(self) -> str:
        if not self._lifecycle_enabled:
            result = self._probe(
                (
                    f"http://127.0.0.1:"
                    f"{self._settings.scs_api_port}/health"
                ),
                2.0,
            )
            return "running" if result.ok else "not configured"

        api = self._api_running()
        core_api = self._core_api_running()
        web = self._web_running()
        tunnel_state = self._tunnel.status().state

        if api and core_api and web and tunnel_state == "connected":
            return "running"

        if api or core_api or web or tunnel_state in {"starting", "connected"}:
            return "degraded"

        return "stopped"

    def start(self) -> ProductStatus:
        if not self._lifecycle_enabled:
            return self.status()

        try:
            if not self._core_api_running():
                self._supervisor.start(
                    build_scs_api_process_spec(
                        self._settings,
                        self._repository,
                        self._python_executable,
                    )
                )

            if not self._api_running():
                self._supervisor.start(
                    build_scs_ai_process_spec(
                        self._settings,
                        self._repository,
                        self._python_executable,
                    )
                )

            if not self._web_running():
                self._supervisor.start(
                    build_scs_web_process_spec(
                        self._settings,
                        self._repository,
                        self._npm_executable,
                    )
                )

            tunnel_state = self._tunnel.status().state

            if tunnel_state == "stopped":
                self._tunnel.start()

            self._last_error = None

        except Exception as error:
            self._last_error = (
                f"start failed ({type(error).__name__})"
            )

        return self.status()

    def stop(self) -> ProductStatus:
        if not self._lifecycle_enabled:
            return self.status()

        errors: list[str] = []

        try:
            self._tunnel.stop()
        except Exception as error:
            errors.append(
                f"tunnel stop failed ({type(error).__name__})"
            )

        if self._web_running():
            try:
                self._supervisor.stop("scs:web")
            except Exception as error:
                errors.append(
                    f"web stop failed ({type(error).__name__})"
                )

        if self._api_running():
            try:
                self._supervisor.stop("scs-ai:api")
            except Exception as error:
                errors.append(
                    f"api stop failed ({type(error).__name__})"
                )

        if self._core_api_running():
            try:
                self._supervisor.stop("scs:api")
            except Exception as error:
                errors.append(
                    f"core api stop failed ({type(error).__name__})"
                )

        self._last_error = (
            "; ".join(errors)
            if errors
            else None
        )

        return self.status()

    def status(self) -> ProductStatus:
        if not self._lifecycle_enabled:
            health = self._probe(
                (
                    f"http://127.0.0.1:"
                    f"{self._settings.scs_api_port}/health"
                ),
                2.0,
            )

            state = "running" if health.ok else "not configured"

            return ProductStatus(
                application_id=self.application_id,
                display_name=self.display_name,
                state=state,
                status_text=(
                    "SCS API reachable"
                    if health.ok
                    else "Lifecycle not managed from Control Center"
                ),
                details=(
                    ("Public origin", self._settings.scs_public_origin),
                    ("API port", str(self._settings.scs_api_port)),
                    ("Web port", str(self._settings.scs_web_port)),
                    ("Health", "reachable" if health.ok else "unreachable"),
                ),
                open_url=self._local_web_url(),
                launch_available=False,
                stop_available=False,
                logs_available=False,
            )

        api = "running" if self._api_running() else "stopped"
        core_api = (
            "running" if self._core_api_running() else "stopped"
        )
        web = "running" if self._web_running() else "stopped"
        tunnel = self._tunnel.status()

        state = self.state

        if self._last_error:
            status_text = self._last_error
        elif state == "running":
            status_text = (
                "Core API, AI API, web, and tunnel running"
            )
        elif state == "degraded":
            status_text = "SCS partially running"
        else:
            status_text = "SCS stopped"

        return ProductStatus(
            application_id=self.application_id,
            display_name=self.display_name,
            state=state,
            status_text=status_text,
            details=(
                ("Web", web),
                ("Core API", core_api),
                ("AI API", api),
                ("AI model", self._ai_model_state()),
                ("Tunnel", str(tunnel.state)),
                ("API port", str(self._settings.scs_api_port)),
                ("AI API port", str(self._settings.scs_ai_api_port)),
                ("Web port", str(self._settings.scs_web_port)),
                ("Public origin", self._settings.scs_ai_public_origin),
            ),
            open_url=self._resolve_open_url(),
            launch_available=True,
            stop_available=True,
            open_available=True,
            logs_available=True,
            last_error=self._last_error,
        )

    def _ai_model_state(self) -> str:
        """Report the AI API's configured model gateway state."""
        if not self._api_running():
            return "stopped"
        try:
            health = self._probe(
                (
                    f"http://127.0.0.1:"
                    f"{self._settings.scs_ai_api_port}/health"
                ),
                2.0,
            )
            if not health.ok:
                return "unreachable"
            payload = getattr(health, "payload", None) or {}
            gateway = payload.get("model_gateway") or {}
            return str(gateway.get("state", "unknown"))
        except Exception:
            return "unknown"

    def health(self) -> bool:
        result = self._probe(
            (
                f"http://127.0.0.1:"
                f"{self._settings.scs_api_port}/health"
            ),
            2.0,
        )

        return bool(result.ok)

    def open_url(self) -> bool:
        return webbrowser.open(self._resolve_open_url())

    def logs(self) -> tuple[LogEntry, ...]:
        if not self._lifecycle_enabled:
            return ()

        entries = [
            entry
            for entry in self._supervisor.logs.snapshot()
            if entry.service.startswith(("scs-ai:", "scs:web"))
        ]

        for service, text in self._tunnel.logs():
            entries.append(
                LogEntry(
                    service=f"scs-ai:{service}",
                    text=text,
                )
            )

        return tuple(entries)


def coder_plan_rows(prepared) -> tuple[tuple[str, str], ...]:
    """Owner-visible plan rows for the approval dialog and status detail."""
    plan = prepared.plan
    offer = prepared.offer
    public = plan.as_public_dict()
    offer_id = public.get("offer_id")
    hourly = public.get("provider_hourly_rate")
    gpu_name = (
        offer.gpu_name
        if offer is not None
        else None
    ) or public.get("gpu_family") or "\u2014"
    reliability = (
        str(offer.reliability)
        if offer is not None
        else "\u2014"
    )
    return (
        ("Logical model", public["logical_repo_id"]),
        ("Deployment", public["deployment_repo_id"]),
        ("Pinned revision", str(public["deployment_revision"])),
        ("Precision", str(public["precision"])),
        ("GPU", str(gpu_name)),
        ("GPU count", str(public["gpu_count"])),
        (
            "VRAM per GPU",
            (
                f"{offer.gpu_ram_mb:,} MB reported"
                if offer is not None
                else f'{public["vram_per_gpu_mb"]} MB'
            ),
        ),
        ("Reliability", reliability),
        (
            "Offer ID",
            str(offer_id) if offer_id is not None else "\u2014",
        ),
        (
            "Exact $/hr",
            f"${hourly}" if hourly is not None else "\u2014",
        ),
        (
            "Configured max $/hr",
            f"${public['max_hourly_price_usd']}",
        ),
        (
            "Session budget",
            f"${public['session_budget_usd']}",
        ),
        ("vLLM image", str(public["serving_runtime"])),
        ("Max model length", str(public["max_model_len"])),
        (
            "Tensor parallel",
            str(public["tensor_parallel_size"]),
        ),
        ("Tool parser", str(public["tool_call_parser"])),
        (
            "Transport",
            (
                "Direct SSH"
                if str(public["launch_runtype"]) == "ssh_direct"
                else "Vast SSH Proxy"
            ),
        ),
        (
            "Runtype",
            (
                "ssh_direct (direct SSH \u2014 explicit alternative)"
                if str(public["launch_runtype"]) == "ssh_direct"
                else "ssh_proxy (Vast SSH Proxy \u2014 qualification default)"
            ),
        ),
        ("Plan ID", str(public["plan_id"])),
        ("Plan hash", str(public["plan_hash"])),
    )


def _provider_category(error: BaseException) -> str | None:
    category = getattr(error, "category", None)
    if isinstance(category, str) and category:
        return category
    if isinstance(error, CoderNoQualifyingOffer):
        return "no_qualifying_offer"
    return None


def coder_approval_ready(prepared) -> tuple[bool, tuple[str, ...]]:
    """A prepared plan is spend-ready ONLY when every provider field is
    concrete and within policy. Returns (ready, problems)."""
    problems: list[str] = []
    offer = getattr(prepared, "offer", None)
    public = prepared.plan.as_public_dict()
    if offer is None:
        problems.append("no concrete provider offer")
    else:
        if public.get("offer_id") is None:
            problems.append("missing offer ID")
        if not public.get("gpu_family"):
            problems.append("missing GPU name/family")
        if getattr(offer, "reliability", None) is None:
            problems.append("missing reliability")
    if not (public.get("gpu_count") or 0) > 0:
        problems.append("missing GPU count")
    if not (public.get("vram_per_gpu_mb") or 0) > 0:
        problems.append("missing VRAM per GPU")
    rate = public.get("provider_hourly_rate")
    ceiling = public.get("max_hourly_price_usd")
    if not rate:
        problems.append("missing exact provider hourly price")
    else:
        try:
            if Decimal(str(rate)) > Decimal(str(ceiling or "0")):
                problems.append("offer exceeds configured max $/hr")
        except Exception:
            problems.append("invalid provider hourly price")
    if not public.get("plan_hash"):
        problems.append("missing plan fingerprint")
    return (not problems), tuple(problems)


class CoderService:
    application_id = "coder"
    display_name = "DEFENDcoder"

    # Typed lifecycle states (plane-wired builds). "running" is only reported
    # after remote compute readiness AND local API/UI are genuinely up.
    # "no_offer" means the qualification search found nothing spend-ready.
    _LIFECYCLE_STATES = (
        "stopped",
        "preparing",
        "approval_required",
        "provisioning",
        "starting_local",
        "running",
        "failed",
        "no_offer",
    )

    def __init__(
        self,
        settings: ProductsSettings,
        *,
        supervisor=None,
        repository: Path | None = None,
        python_executable: str | None = None,
        observation: object | None = None,
        plane: object | None = None,
        probe=fetch_http_json,
        destroy_runtime_on_stop: bool = True,
    ) -> None:
        self._settings = settings
        self._supervisor = supervisor
        self._repository = (
            Path(repository)
            if repository is not None
            else None
        )
        self._python_executable = (
            str(python_executable)
            if python_executable is not None
            else None
        )
        self._observation = observation
        self._plane = plane
        self._probe = probe
        self._last_error: str | None = None
        self._last_error_category: str | None = None
        self._last_qualification: CoderNoQualifyingOffer | None = None
        self._last_provision_failure: CoderProvisionFailure | None = None
        self._prepared: object | None = None
        self._approval: object | None = None
        self._coder_state: str = "stopped"
        self._destroy_runtime_on_stop = bool(destroy_runtime_on_stop)
        self._lifecycle_log = LogBuffer(max_entries=400, max_line_chars=240)

        # Wire every remote provisioning layer into the owner-visible
        # DEFENDcoder lifecycle log.
        if self._plane is not None:
            try:
                self._plane.lifecycle_log = self.lifecycle_emit
            except Exception:
                pass
            try:
                backend = getattr(self._plane, "backend", None)
                if backend is not None:
                    backend.log = self.lifecycle_emit
                    bootstrap = getattr(backend, "bootstrap", None)
                    if bootstrap is not None:
                        bootstrap.log = self.lifecycle_emit
            except Exception:
                pass

    def lifecycle_emit(self, line: str) -> None:
        """Timestamped, owner-visible provisioning transition."""
        self._lifecycle_log.append("coder:lifecycle", f"[{wall_clock()}] {line}")

    def _refresh_provision_failure(self) -> None:
        failure = getattr(self._plane, "last_provision_failure", None)
        if failure is not None:
            self._last_provision_failure = failure

    def _emit_failure_line(self) -> None:
        failure = self._last_provision_failure
        if failure is None:
            return
        reason = failure.sanitized_message.replace("\n", " ")[:240]
        self.lifecycle_emit(
            f"FAILED phase={failure.phase} reason={reason}"
        )

    @property
    def _lifecycle_enabled(self) -> bool:
        return (
            self._supervisor is not None
            and self._repository is not None
            and self._python_executable is not None
        )

    def _service_running(self, name: str) -> bool:
        if not self._lifecycle_enabled:
            return False

        for snapshot in self._supervisor.snapshot():
            if snapshot.name == name:
                return bool(snapshot.running)
        return False

    @property
    def state(self) -> str:
        if self._plane is not None:
            if self._coder_state in self._LIFECYCLE_STATES:
                return self._coder_state
            return "stopped"

        if not self._lifecycle_enabled:
            public = self._observation_public()

            if public is None:
                return "not configured"

            return str(
                public.get("state") or "unavailable"
            )

        api = self._service_running("coder:api")
        web = self._service_running("coder:web")

        if api and web:
            return "running"

        if api or web:
            return "degraded"

        public = self._observation_public()

        if public is not None:
            remote_state = str(
                public.get("state") or "unavailable"
            )

            if remote_state == "ready":
                return "runtime ready"

        return "stopped"

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

    def start(self) -> ProductStatus:
        if self._plane is None:
            return self._start_local_only()

        if self._coder_state in (
            "preparing",
            "provisioning",
            "starting_local",
        ):
            return self.status()

        alias = str(self._settings.coder_model_alias)

        try:
            endpoint = self._plane.status(alias)
        except Exception as error:
            self._coder_state = "failed"
            self._last_error = (
                "runtime status unavailable "
                f"({type(error).__name__})"
            )
            return self.status()

        if endpoint.get("state") == "ready":
            return self._start_local_and_finish()

        try:
            lease = self._plane.resume_existing(alias)
        except Exception as error:
            self._coder_state = "failed"
            self._last_error = (
                f"resume check failed ({type(error).__name__})"
            )
            self._last_error_category = _provider_category(error)
            return self.status()

        if lease is not None:
            self._coder_state = "provisioning"
            try:
                smoke = self._plane.smoke(alias)
            except Exception as error:
                self._fail_after_remote_error(
                    alias,
                    "resumed runtime verification failed "
                    f"({type(error).__name__})",
                    _provider_category(error),
                )
                return self.status()
            if not smoke.ok:
                self._fail_after_remote_error(
                    alias,
                    "resumed runtime failed smoke",
                    "provider",
                )
                return self.status()
            self.lifecycle_emit(f"resumed runtime ready: {alias}")
            return self._start_local_and_finish()

        self._coder_state = "preparing"
        self._last_error = None
        self._last_error_category = None
        self._last_qualification = None

        try:
            prepared = self._plane.prepared_provision(alias)
        except CoderNoQualifyingOffer as error:
            self._prepared = None
            self._approval = None
            self._coder_state = "no_offer"
            self._last_error = None
            self._last_error_category = "no_qualifying_offer"
            self._last_qualification = error
            return self.status()
        except Exception as error:
            self._prepared = None
            self._approval = None
            self._coder_state = "failed"
            self._last_error = (
                f"plan preparation failed "
                f"({type(error).__name__})"
            )
            self._last_error_category = _provider_category(error)
            return self.status()

        self._prepared = prepared
        self._approval = None
        self._coder_state = "approval_required"

        return self.status()

    def approve(self) -> ProductStatus:
        if self._plane is None or self._prepared is None:
            self._last_error = "no pending coder plan to approve"
            self._last_error_category = None
            return self.status()

        if self._coder_state != "approval_required":
            self._last_error = (
                "no pending coder plan to approve"
            )
            self._last_error_category = None
            return self.status()

        ready, problems = coder_approval_ready(self._prepared)
        if not ready:
            self._prepared = None
            self._approval = None
            self._coder_state = "failed"
            self._last_error = (
                "plan is not spend-ready: "
                + "; ".join(problems)
            )
            self._last_error_category = "no_qualifying_offer"
            return self.status()

        prepared = self._prepared
        alias = str(prepared.plan.alias)
        self.lifecycle_emit(f"provisioning approved for {alias}")
        self._coder_state = "provisioning"

        try:
            approval = self._plane.approve(prepared)
            self._approval = approval
            self._plane.provision(prepared, approval)
            smoke = self._plane.smoke(alias)
        except CoderProvisionBlocked as error:
            self._fail_after_remote_error(
                alias,
                f"provisioning blocked: {error}",
                _provider_category(error),
            )
            return self.status()
        except Exception as error:
            self._fail_after_remote_error(
                alias,
                f"provisioning failed ({type(error).__name__})",
                _provider_category(error),
            )
            return self.status()

        if not smoke.ok:
            self._fail_after_remote_error(
                alias,
                f"remote readiness failed: {smoke.detail}",
            )
            return self.status()

        self._prepared = None
        self._approval = None
        self._last_provision_failure = None
        self.lifecycle_emit(f"runtime ready: {alias} (smoke passed)")

        return self._start_local_and_finish()

    def cancel(self) -> ProductStatus:
        if self._plane is None:
            self._last_error = "no pending coder plan to cancel"
            return self.status()

        if self._coder_state == "approval_required":
            self._prepared = None
            self._approval = None
            self._coder_state = "stopped"
            self._last_error = None
            self._last_error_category = None
            self._last_qualification = None

        return self.status()

    def pending_plan(self):
        return self._prepared

    def _start_local_only(self) -> ProductStatus:
        if not self._lifecycle_enabled:
            return self.status()

        if not self._settings.coder_database_url:
            self._last_error = (
                "CODER_DATABASE_URL is not configured"
            )
            return self.status()

        self.lifecycle_emit("starting local coder services (api + web)")

        try:
            self._supervisor.logs.add_known_secrets(
                [self._settings.coder_database_url]
            )

            if not self._service_running("coder:api"):
                self._supervisor.start(
build_coder_api_process_spec(
                        self._settings,
                        self._repository,
                        self._python_executable,
                    )
                )

            if not self._service_running("coder:web"):
                prepare_standalone_web(self._repository)
                self._supervisor.start(
                    build_coder_web_process_spec(
                        self._settings,
                        self._repository,
                    )
                )

            self._last_error = None

        except Exception as error:
            self._last_error = (
                f"start failed ({type(error).__name__})"
            )

        return self.status()

    def _start_local_and_finish(self) -> ProductStatus:
        if not self._lifecycle_enabled:
            self._coder_state = "running"
            self._last_error = None
            return self.status()

        if not self._settings.coder_database_url:
            self._coder_state = "failed"
            self._last_error = (
                "CODER_DATABASE_URL is not configured; "
                "local API/UI cannot start"
            )
            return self.status()

        if self._coder_state != "running":
            self.lifecycle_emit("starting local coder services (api + web)")
        self._coder_state = "starting_local"

        try:
            self._supervisor.logs.add_known_secrets(
                [self._settings.coder_database_url]
            )

            if not self._service_running("coder:api"):
                self._supervisor.start(
build_coder_api_process_spec(
                        self._settings,
                        self._repository,
                        self._python_executable,
                    )
                )

            if not self._service_running("coder:web"):
                prepare_standalone_web(self._repository)
                self._supervisor.start(
                    build_coder_web_process_spec(
                        self._settings,
                        self._repository,
                    )
                )

            self._last_error = None
            self._coder_state = "running"

        except Exception as error:
            self._coder_state = "failed"
            self._last_error = (
                f"local start failed ({type(error).__name__})"
            )
            status = (
                self._plane.status(str(self._settings.coder_model_alias))
                if self._plane is not None
                else {}
            )
            self._last_provision_failure = CoderProvisionFailure(
                phase="local_api_start",
                exception_type=type(error).__name__,
                sanitized_message=str(error),
                instance_id=status.get("instance_id"),
                gpu_name=status.get("gpu_type"),
                approved_hourly_rate=status.get("hourly_price"),
                elapsed_seconds=0.0,
                endpoint_state="ready",
                ssh_state="ready",
                bootstrap_state="ready",
                vllm_state="ready",
                readiness_state="ready",
                cleanup_state="not_attempted",
            )
            self._emit_failure_line()

        return self.status()

    def _fail_after_remote_error(
        self,
        alias: str,
        message: str,
        category: str | None = None,
    ) -> None:
        try:
            self._plane.release(alias, destroy=True)
        except Exception:
            pass
        try:
            self._stop_coder_tunnels()
        except Exception:
            pass
        self._refresh_provision_failure()
        self._emit_failure_line()
        self._prepared = None
        self._approval = None
        self._coder_state = "failed"
        self._last_error = message
        self._last_error_category = category or "provider"

    def qualification(self):
        """Sanitized no-offer metadata for the owner UI (None otherwise)."""
        return self._last_qualification

    def _stop_coder_tunnels(self) -> None:
        if not self._lifecycle_enabled:
            return
        for snapshot in self._supervisor.snapshot():
            if not snapshot.name.startswith("coder ssh tunnel"):
                continue
            try:
                self._supervisor.stop(snapshot.name)
            except Exception:
                pass

    def stop(self) -> ProductStatus:
        if not self._lifecycle_enabled:
            return self.status()

        self.lifecycle_emit("stopping coder runtime")
        errors: list[str] = []

        for name in ("coder:web", "coder:api"):
            if not self._service_running(name):
                continue

            try:
                self._supervisor.stop(name)
            except Exception as error:
                errors.append(
                    f"{name} stop failed "
                    f"({type(error).__name__})"
                )

        try:
            self._stop_coder_tunnels()
        except Exception as error:
            errors.append(
                f"coder ssh tunnel stop failed "
                f"({type(error).__name__})"
            )

        if self._plane is not None:
            alias = str(self._settings.coder_model_alias)
            try:
                self._plane.release(
                    alias,
                    destroy=self._destroy_runtime_on_stop,
                )
            except Exception as error:
                errors.append(
                    f"runtime teardown failed "
                    f"({type(error).__name__})"
                )

        self._prepared = None
        self._approval = None
        self._coder_state = "stopped"
        self._last_error = (
            "; ".join(errors)
            if errors
            else None
        )
        self._last_error_category = None
        self._last_qualification = None
        if not errors:
            self.lifecycle_emit("coder runtime stopped")

        return self.status()

    def status(self) -> ProductStatus:
        public = self._observation_public()

        alias = "\u2014"
        gpu = "\u2014"
        instance = "\u2014"
        hourly = "\u2014"
        budget = "\u2014"

        if public is not None:
            alias = str(public.get("alias") or "\u2014")
            gpu = str(
                public.get("gpu_name")
                or public.get("gpu")
                or "\u2014"
            )
            instance = str(
                public.get("instance_id") or "\u2014"
            )

            raw_hourly = public.get("hourly_price")
            if raw_hourly is not None:
                hourly = f"${raw_hourly}"

            raw_budget = public.get(
                "session_budget_usd"
            )
            if raw_budget is not None:
                budget = f"${raw_budget}"

        if self._plane is not None:
            try:
                endpoint = self._plane.status(
                    str(self._settings.coder_model_alias)
                )
            except Exception:
                endpoint = {}
            if endpoint.get("alias"):
                alias = str(endpoint["alias"])
            if endpoint.get("gpu_type"):
                gpu = str(endpoint["gpu_type"])
            if endpoint.get("instance_id") is not None:
                instance = str(endpoint["instance_id"])
            if endpoint.get("hourly_price") is not None:
                hourly = f"${endpoint['hourly_price']}"

        api = (
            "running"
            if self._service_running("coder:api")
            else "stopped"
        )

        web = (
            "running"
            if self._service_running("coder:web")
            else "stopped"
        )

        state = self.state

        plan_rows: tuple[tuple[str, str], ...] = ()
        if (
            state == "approval_required"
            and self._prepared is not None
        ):
            plan_rows = coder_plan_rows(self._prepared)

        if not self._lifecycle_enabled:
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
                    ("$/hr", hourly),
                    ("Session cost", budget),
                    (
                        "Max $/hr (ceiling)",
                        f"${self._settings.coder_max_hourly_usd}",
                    ),
                ),
                open_url=self._settings.coder_public_origin,
                launch_available=False,
                stop_available=False,
                logs_available=False,
            )

        if state == "no_offer" and self._last_qualification is not None:
            qualification = self._last_qualification
            required_gpu = (
                " / ".join(qualification.required_gpu_families)
                or "\u2014"
            )
            return ProductStatus(
                application_id=self.application_id,
                display_name=self.display_name,
                state=state,
                status_text="NO QUALIFYING VAST OFFER",
                details=(
                    (
                        "Required",
                        (
                            f"{qualification.required_gpu_count} \u00d7 "
                            f"{required_gpu}"
                        ),
                    ),
                    (
                        "GPU memory class",
                        (
                            f">= "
                            f"{vast_gpu_ram_floor(qualification.required_vram_per_gpu_mb) // 1000} GB"
                        ),
                    ),
                    (
                        "Vast threshold",
                        (
                            f">= "
                            f"{vast_gpu_ram_floor(qualification.required_vram_per_gpu_mb)} MB"
                        ),
                    ),
                    (
                        "Reliability",
                        f">= {qualification.required_min_reliability}",
                    ),
                    (
                        "Max rate",
                        f"<= ${qualification.max_hourly_usd}/hr",
                    ),
                    (
                        "Offers searched",
                        str(qualification.searched_offer_count),
                    ),
                    *(
                        (
                            ("Provider query matched approved GPU universe", str(qualification.provider_returned_count)),
                        )
                        if qualification.provider_returned_count is not None
                        else ()
                    ),
                    *(
                        (
                            ("Eligible after validation", str(qualification.eligible_count)),
                        )
                        if qualification.eligible_count is not None
                        else ()
                    ),
                    *(
                        (
                            (
                                f"Rejected: {category}",
                                str(count),
                            )
                        )
                        for category, count in qualification.rejections
                    ),
                    *(
                        (("Config", "; ".join(self._settings.coder_config_errors)),)
                        if self._settings.coder_config_errors
                        else ()
                    ),
                    (
                        "Possible reasons",
                        (
                            "no current inventory meeting filters; "
                            "configured hourly ceiling too low; "
                            "Vast provider/API problem"
                        ),
                    ),
                ),
                open_url=self._settings.coder_public_origin,
                launch_available=True,
                stop_available=True,
                open_available=True,
                logs_available=True,
                error_category="no_qualifying_offer",
            )

        failure = self._last_provision_failure
        if failure is not None:
            cleanup_failed = failure.cleanup_state in (
                "destroy_request_failed",
                "destroy_verification_failed",
            )
            return ProductStatus(
                application_id=self.application_id,
                display_name=self.display_name,
                state="failed",
                status_text=(
                    "PROVISIONING FAILED \u2014 PROVIDER CLEANUP FAILED: "
                    "the Vast instance may still be running and billing. "
                    "Destroy it in the Vast console immediately."
                    if cleanup_failed
                    else "PROVISIONING FAILED"
                ),
                details=(
                    ("Phase", failure.phase),
                    ("Reason", f"{failure.phase} failed — see DEFENDcoder logs / COPY DIAGNOSTICS"),
                    ("Instance", (
                        str(failure.instance_id)
                        if failure.instance_id is not None
                        else "\u2014"
                    )),
                    ("GPU", failure.gpu_name or "\u2014"),
                    ("Approved rate", (
                        f"${format(failure.approved_hourly_rate, 'f')}/hr"
                        if failure.approved_hourly_rate is not None
                        else "\u2014"
                    )),
                    (
                        "Runtime before failure",
                        format_elapsed(failure.elapsed_seconds),
                    ),
                    (
                        "Cleanup",
                        {
                            "destroyed": "instance destroyed",
                            "destroy_pending": (
                                "destruction pending \u2014 provider "
                                "acknowledged; teardown in progress"
                            ),
                            "destroy_verification_failed": (
                                "VERIFICATION FAILED \u2014 could not "
                                "confirm the instance is gone"
                            ),
                            "destroy_request_failed": (
                                "DESTROY REQUEST FAILED \u2014 instance "
                                "may still be running"
                            ),
                            "not_attempted": (
                                "not attempted \u2014 instance kept "
                                "running (local start failed)"
                            ),
                            "unknown": "unknown",
                        }.get(
                            failure.cleanup_state or "unknown",
                            failure.cleanup_state or "unknown",
                        ),
                    ),
                ),
                open_url=self._settings.coder_public_origin,
                launch_available=True,
                stop_available=True,
                open_available=True,
                logs_available=True,
                last_error=self._last_error,
                error_category=self._last_error_category,
                diagnostics=failure.as_text(),
            )

        if self._last_error:
            status_text = self._last_error
        elif state == "approval_required":
            status_text = (
                "Plan ready \u2014 owner approval required "
                "before any spend"
            )
        elif state == "preparing":
            status_text = "Preparing NEXT deployment plan\u2026"
        elif state == "provisioning":
            status_text = (
                "Provisioning approved NEXT runtime\u2026"
            )
        elif state == "starting_local":
            status_text = "Starting local API and UI\u2026"
        elif state == "running":
            status_text = "DEFENDcoder API and UI running"
        elif state == "degraded":
            status_text = "DEFENDcoder partially running"
        elif state == "runtime ready":
            status_text = (
                "Runtime observed; local API/UI stopped"
            )
        else:
            status_text = "DEFENDcoder stopped"

        return ProductStatus(
            application_id=self.application_id,
            display_name=self.display_name,
            state=state,
            status_text=status_text,
            details=(
                ("API", api),
                ("Web", web),
                ("Alias", alias),
                ("GPU", gpu),
                ("Instance", instance),
                ("$/hr", hourly),
                ("Session cost", budget),
                (
                    "Max $/hr (ceiling)",
                    f"${self._settings.coder_max_hourly_usd}",
                ),
                *(
                    (("Config", "; ".join(self._settings.coder_config_errors)),)
                    if self._settings.coder_config_errors
                    else ()
                ),
                *plan_rows,
                (
                    "Public origin",
                    self._settings.coder_public_origin,
                ),
            ),
            open_url=self._settings.coder_public_origin,
            launch_available=True,
            stop_available=True,
            open_available=True,
            logs_available=True,
            last_error=self._last_error,
            error_category=self._last_error_category,
        )

    def health(self) -> bool:
        if not self._lifecycle_enabled:
            return self.state == "ready"

        if not self._service_running("coder:api"):
            return False

        result = self._probe(
            (
                f"http://127.0.0.1:"
                f"{self._settings.coder_api_port}/health"
            ),
            2.0,
        )

        return bool(result.ok)

    def open_url(self) -> bool:
        return webbrowser.open(
            self._settings.coder_public_origin
        )

    def logs(self) -> tuple[LogEntry, ...]:
        if not self._lifecycle_enabled:
            return ()

        lifecycle = self._lifecycle_log.snapshot()
        snapshot = getattr(self._supervisor.logs, "snapshot", None)
        supervisor_entries = (
            tuple(
                entry
                for entry in snapshot()
                if entry.service.startswith("coder:")
            )
            if snapshot is not None
            else ()
        )
        return lifecycle + supervisor_entries


def build_products(
    *,
    controller,
    supervisor,
    repository: Path,
    python_executable: str,
    public_origin: str,
    settings: ProductsSettings | None = None,
    scs_tunnel=None,
coder_plane=None,
    api_port: int = 8401,
    prepare_model_start=None,
    runtime_registry: ProductRuntimeRegistry | None = None,
    probe=fetch_http_json,
    clock=time.monotonic,
) -> tuple[ProductService, ...]:
    products_settings = settings or ProductsSettings.from_env()
    coder_service = CoderService(
        products_settings,
        supervisor=supervisor,
        repository=repository,
        python_executable=python_executable,
        plane=coder_plane,
        probe=probe,
    )
    if coder_plane is not None:
        setattr(
            coder_plane,
            "lifecycle_log",
            coder_service.lifecycle_emit,
        )
    return (
DefendService(
            controller,
            public_origin=public_origin,
            api_port=api_port,
            probe=probe,
            prepare_model_start=prepare_model_start,
            runtime_registry=runtime_registry,
        ),
        SportsService(
            supervisor=supervisor,
            repository=repository,
            python_executable=python_executable,
            settings=products_settings,
            probe=probe,
            clock=clock,
        ),
        ScsService(
            products_settings,
            supervisor=supervisor if scs_tunnel is not None else None,
            repository=repository if scs_tunnel is not None else None,
            python_executable=(
                python_executable
                if scs_tunnel is not None
                else None
            ),
            tunnel=scs_tunnel,
            probe=probe,
        ),
        coder_service,
    )


def product_rows(products) -> tuple[ProductStatus, ...]:
    return tuple(product.status() for product in products)
