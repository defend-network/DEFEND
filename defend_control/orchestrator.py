from __future__ import annotations

from collections.abc import Callable, Mapping
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any

from .health import HealthResult, probe_http
from .local_model import (
    LocalModelUnavailable,
    LocalOllamaBackend,
    build_local_process_specs,
)
from .preflight import PreflightRunner
from .processes import LogEntry, ProcessSupervisor
from .remote_vllm import RemoteVllmError, build_remote_process_specs
from .settings import ControlSettings
from .ssh_tunnel import HostFingerprintConfirmation, SshTunnelError
from .types import (
    AdapterSpec,
    LaunchSpec,
    ModelMode,
    ServiceState,
    VastInstance,
    VastOffer,
)
from .vast import VastError, VastSchedulingTimeout


_MAX_PROCESS_QUERY_BYTES = 64 * 1024


def _split_windows_command_line(command_line: str) -> tuple[str, ...]:
    if sys.platform != "win32" or not command_line:
        return ()
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.CommandLineToArgvW.argtypes = [
        wintypes.LPCWSTR,
        ctypes.POINTER(ctypes.c_int),
    ]
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL
    count = ctypes.c_int()
    pointer = shell32.CommandLineToArgvW(command_line, ctypes.byref(count))
    if not pointer or count.value <= 0:
        return ()
    try:
        return tuple(pointer[index] for index in range(count.value))
    finally:
        kernel32.LocalFree(ctypes.cast(pointer, wintypes.HLOCAL))


def _query_cloudflared_processes() -> tuple[Mapping[str, object], ...]:
    system_root = os.environ.get("SYSTEMROOT")
    if not system_root:
        return ()
    powershell = (
        Path(system_root)
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    if not powershell.is_file():
        return ()
    script = (
        "Get-CimInstance Win32_Process -Filter \"Name = 'cloudflared.exe'\" | "
        "Select-Object ProcessId,ExecutablePath,CommandLine | "
        "ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(
            [
                str(powershell),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        return ()
    if completed.returncode != 0:
        return ()
    encoded = completed.stdout.encode("utf-8", errors="replace")
    if not encoded or len(encoded) > _MAX_PROCESS_QUERY_BYTES:
        return ()
    try:
        raw = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return ()
    rows = raw if isinstance(raw, list) else [raw]
    candidates: list[Mapping[str, object]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        command_line = row.get("CommandLine")
        candidates.append(
            {
                "pid": row.get("ProcessId"),
                "executable": row.get("ExecutablePath"),
                "argv": _split_windows_command_line(command_line)
                if isinstance(command_line, str)
                else (),
            }
        )
    return tuple(candidates)


class ExternalCloudflaredDetector:
    """Reduce a verified local cloudflared identity to its PID only."""

    def __init__(
        self,
        *,
        query: Callable[[], tuple[Mapping[str, object], ...]] = (
            _query_cloudflared_processes
        ),
    ) -> None:
        self._query = query

    @staticmethod
    def _same_path(left: object, right: Path) -> bool:
        if not isinstance(left, str) or not left:
            return False
        try:
            return str(Path(left).resolve(strict=False)).casefold() == str(
                right.resolve(strict=False)
            ).casefold()
        except (OSError, ValueError):
            return False

    @staticmethod
    def _has_config(argv: tuple[str, ...], expected: Path) -> bool:
        expected_text = str(expected.resolve(strict=False)).casefold()
        for index, argument in enumerate(argv):
            normalized = argument.casefold()
            if normalized == "--config" and index + 1 < len(argv):
                try:
                    candidate = str(
                        Path(argv[index + 1]).resolve(strict=False)
                    ).casefold()
                except (OSError, ValueError):
                    return False
                return candidate == expected_text
            if normalized.startswith("--config="):
                try:
                    candidate = str(
                        Path(argument.split("=", 1)[1]).resolve(strict=False)
                    ).casefold()
                except (OSError, ValueError):
                    return False
                return candidate == expected_text
        return False

    def __call__(self, settings: ControlSettings) -> int | None:
        try:
            candidates = self._query()
        except Exception:
            return None
        exact_matches: list[int] = []
        name_matches: list[int] = []
        for candidate in candidates:
            pid = candidate.get("pid") if isinstance(candidate, Mapping) else None
            executable = (
                candidate.get("executable")
                if isinstance(candidate, Mapping)
                else None
            )
            raw_argv = (
                candidate.get("argv") if isinstance(candidate, Mapping) else None
            )
            if (
                isinstance(pid, bool)
                or not isinstance(pid, int)
                or pid <= 0
                or not self._same_path(executable, settings.cloudflared_exe)
                or not isinstance(raw_argv, (tuple, list))
                or not all(isinstance(item, str) for item in raw_argv)
            ):
                continue
            argv = tuple(raw_argv)
            normalized = tuple(item.casefold() for item in argv)
            try:
                run_index = normalized.index("run")
            except ValueError:
                continue
            if "tunnel" not in normalized[1:run_index]:
                continue
            tunnel_name = settings.cloudflared_tunnel
            exact_config = self._has_config(argv, settings.cloudflared_config)
            named = (
                run_index + 1 < len(argv)
                and argv[run_index + 1] == tunnel_name
            ) or any(item == tunnel_name for item in argv)
            if exact_config and named:
                exact_matches.append(pid)
            elif named:
                name_matches.append(pid)
        if len(exact_matches) == 1:
            return exact_matches[0]
        if len(name_matches) == 1:
            return name_matches[0]
        return None


class StartFailed(RuntimeError):
    def __init__(self, component: str, detail: str = "not ready") -> None:
        super().__init__(f"{component} start failed: {detail}")
        self.component = component


class StartCancelled(StartFailed):
    def __init__(self) -> None:
        super().__init__("startup", "cancelled")


class PriceConfirmationRequired(RuntimeError):
    def __init__(self, offer: VastOffer) -> None:
        super().__init__(
            f"Confirm Vast offer {offer.offer_id} at ${offer.dph_total}/hour"
        )
        self.offer = offer


class InstanceSelectionRequired(RuntimeError):
    def __init__(self, count: int) -> None:
        super().__init__(f"Choose one of {count} existing DEFEND Vast instances")
        self.count = count


class InstanceRestartConfirmationRequired(RuntimeError):
    def __init__(self, instance: VastInstance) -> None:
        super().__init__(
            "Confirm restart of Vast instance "
            f"{instance.instance_id} at ${instance.dph_total}/hour"
        )
        self.instance = instance


class InstanceReplacementConfirmationRequired(RuntimeError):
    def __init__(self, old_instance: VastInstance, offer: VastOffer) -> None:
        super().__init__(
            "Confirm replacement of Vast instance "
            f"{old_instance.instance_id} with offer {offer.offer_id} "
            f"at ${offer.dph_total}/hour"
        )
        self.old_instance = old_instance
        self.offer = offer


class StartCancellation:
    """One cancellation signal whose lifetime is exactly one start attempt."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: float) -> bool:
        return self._event.wait(timeout)


@dataclass(frozen=True)
class AlreadyRunning:
    state: ServiceState
    mode: ModelMode | None


@dataclass(frozen=True)
class ComponentSnapshot:
    name: str
    state: str
    detail: str = ""


@dataclass(frozen=True)
class StackSnapshot:
    state: ServiceState
    mode: ModelMode | None
    components: tuple[ComponentSnapshot, ...]
    error: str | None
    vast_gpu: str | None = None
    vast_instance_id: int | None = None
    vast_hourly_price: str | None = None
    vast_offer_id: int | None = None
    vast_gpu_ram_mb: int | None = None
    vast_reliability: str | None = None
    vast_storage_cost_per_gb_month: str | None = None
    vast_storage_total_hourly: str | None = None
    vast_disk_gb: int | None = None
    vast_actual_status: str | None = None
    vast_billing_warning: str | None = None
    pending_confirmation: str | None = None
    pending_fingerprint: str | None = None
    vast_candidates: tuple[VastInstance, ...] = ()
    vast_replacement_offer: VastOffer | None = None
    logs: tuple[LogEntry, ...] = ()
    owned_services: tuple[str, ...] = ()


class StackOrchestrator:
    _COMPONENTS = ("model", "ssh tunnel", "api", "frontend", "cloudflare")

    def __init__(
        self,
        *,
        settings: ControlSettings,
        secrets: Mapping[str, str] | Any,
        preflight: PreflightRunner,
        supervisor: ProcessSupervisor,
        local_backend: LocalOllamaBackend,
        health_probe: Callable[..., HealthResult] = probe_http,
        external_tunnel_detector: Callable[[ControlSettings], int | None] | None = None,
        health_timeout_seconds: float = 30.0,
        public_health_timeout_seconds: float = 90.0,
        poll_interval_seconds: float = 0.2,
        huggingface_client: Any | None = None,
        vast_client_factory: Callable[[str], Any] | None = None,
        ssh_tunnel: Any | None = None,
        remote_bootstrap: Any | None = None,
        model_probe: Any | None = None,
        adopt_shared_surface: bool = False,
    ) -> None:
        if health_timeout_seconds <= 0 or poll_interval_seconds < 0:
            raise ValueError("health timing values are invalid")
        if public_health_timeout_seconds <= 0:
            raise ValueError("public health timing values are invalid")
        self._settings = settings
        self._secrets_source = secrets
        self._preflight = preflight
        self._supervisor = supervisor
        self._local_backend = local_backend
        self._health_probe = health_probe
        self._health_timeout_seconds = float(health_timeout_seconds)
        self._public_health_timeout_seconds = float(public_health_timeout_seconds)
        self._poll_interval_seconds = float(poll_interval_seconds)
        self._external_tunnel_detector = (
            external_tunnel_detector
            if external_tunnel_detector is not None
            else ExternalCloudflaredDetector()
        )
        self._state_lock = threading.RLock()
        self._operation_lock = threading.RLock()
        self._active_cancellation: StartCancellation | None = None
        self._state: ServiceState = "stopped"
        self._mode: ModelMode | None = None
        self._last_explicit_mode: ModelMode | None = None
        self._error: str | None = None
        self._components = {name: "stopped" for name in self._COMPONENTS}
        self._owned_order: list[str] = []
        self._huggingface_client = huggingface_client
        self._vast_client_factory = vast_client_factory
        self._ssh_tunnel = ssh_tunnel
        self._remote_bootstrap = remote_bootstrap
        self._model_probe = model_probe
        self._vast_client: Any | None = None
        self._vast_adapter: AdapterSpec | None = None
        self._vast_offer: VastOffer | None = None
        self._confirmed_offer: tuple[int, Decimal] | None = None
        self._vast_instance: VastInstance | None = None
        self._pending_confirmation: str | None = None
        self._pending_fingerprint: str | None = None
        self._confirmed_fingerprint: tuple[int, str] | None = None
        self._vast_candidates: tuple[VastInstance, ...] = ()
        self._confirmed_restart: tuple[int, Decimal] | None = None
        self._replacement_instance: VastInstance | None = None
        self._replacement_offer: VastOffer | None = None
        self._confirmed_replacement: tuple[int, int, Decimal] | None = None
        self._ssh_key_registered = False
        self._adopt_shared_surface = bool(adopt_shared_surface)

    def _shared_surface_ports(self) -> frozenset[int]:
        """Ports already served by a healthy shared admin surface.

        The Control Center owns the web/admin surface (api + web); when both
        are healthy the DEFEND AI stack adopts them instead of starting
        duplicates and instead of failing the port-availability preflight.
        """
        if not self._adopt_shared_surface:
            return frozenset()
        probe_timeout = min(2.0, self._health_timeout_seconds)
        api_ok = bool(
            self._health_probe(
                f"http://127.0.0.1:{self._settings.api_port}/health",
                probe_timeout,
            ).ok
        )
        web_ok = bool(
            self._health_probe(
                f"http://127.0.0.1:{self._settings.web_port}/",
                probe_timeout,
            ).ok
        )
        if api_ok and web_ok:
            return frozenset(
                {self._settings.api_port, self._settings.web_port}
            )
        return frozenset()

    def _clear_replacement(self) -> None:
        self._replacement_instance = None
        self._replacement_offer = None
        self._confirmed_replacement = None

    def _search_offers(self):
        """Always search under the current ResourceProfile (140GB+ by default)."""
        return self._vast_client.search_offers(
            self._settings.vast_max_hourly,
            profile=self._settings.resource_profile(),
        )

    def _replace_scheduled_instance(
        self,
        cancellation: StartCancellation,
    ) -> None:
        old_instance = self._replacement_instance
        offer = self._replacement_offer
        confirmed = self._confirmed_replacement
        expected = (
            old_instance.instance_id,
            offer.offer_id,
            offer.dph_total,
        ) if old_instance is not None and offer is not None else None
        if old_instance is None or offer is None or confirmed != expected:
            return
        existing_ids = self._vast_client.list_labeled_instance_ids(
            LaunchSpec.default().label
        )
        current = self._vast_client.show_instance(old_instance.instance_id)
        current_offers = self._search_offers()
        current_offer = next(
            (candidate for candidate in current_offers if candidate.offer_id == offer.offer_id),
            None,
        )
        if (
            existing_ids != (old_instance.instance_id,)
            or current.instance_id != old_instance.instance_id
            or current.actual_status not in ("scheduling", "stopped", "exited")
            or current.dph_total != old_instance.dph_total
            or current_offer != offer
        ):
            self._clear_replacement()
            self._pending_confirmation = None
            raise StartFailed("Vast.ai", "instance or offer changed before replacement")
        self._check_cancelled(cancellation)
        self._vast_client.destroy_instance(
            old_instance.instance_id,
            confirmed_instance_id=old_instance.instance_id,
        )
        self._vast_instance = None
        self._vast_offer = None
        self._clear_replacement()
        self._pending_confirmation = None
        self._confirmed_restart = None
        self._confirmed_fingerprint = None
        self._check_cancelled(cancellation)
        self._vast_instance = self._vast_client.create_instance(
            current_offer,
            LaunchSpec.default(),
        )

    def _set_state(
        self,
        state: ServiceState,
        *,
        error: str | None = None,
    ) -> None:
        with self._state_lock:
            self._state = state
            self._error = error

    def _set_component(self, name: str, state: str) -> None:
        with self._state_lock:
            self._components[name] = state

    @staticmethod
    def _check_cancelled(cancellation: StartCancellation) -> None:
        if cancellation.is_cancelled():
            raise StartCancelled()

    def _load_secrets(self) -> dict[str, str]:
        source = self._secrets_source
        values = source.load() if hasattr(source, "load") else source
        if not isinstance(values, Mapping) or not all(
            isinstance(name, str) and isinstance(value, str)
            for name, value in values.items()
        ):
            raise StartFailed("secrets", "local secret store is invalid")
        return dict(values)

    def _ensure_remote_dependencies(self, secrets: Mapping[str, str]) -> None:
        if self._huggingface_client is None:
            from .huggingface import HuggingFaceClient

            self._huggingface_client = HuggingFaceClient()
        if self._vast_client is None:
            if self._vast_client_factory is None:
                from .vast import VastClient

                self._vast_client_factory = VastClient
            self._vast_client = self._vast_client_factory(secrets["VAST_API_KEY"])
        if self._ssh_tunnel is None:
            from .ssh_tunnel import SshTunnel

            local_app_data = os.environ.get("LOCALAPPDATA")
            if not local_app_data:
                raise StartFailed("SSH", "LOCALAPPDATA is unavailable")
            ssh_root = Path(local_app_data) / "DEFEND" / "ssh"
            self._ssh_tunnel = SshTunnel(
                self._supervisor,
                known_hosts=ssh_root / "known_hosts",
                key_path=ssh_root / "vast_ed25519",
                local_port=self._settings.model_port,
            )
        if self._remote_bootstrap is None:
            from .remote_vllm import RemoteVllmBootstrap

            self._remote_bootstrap = RemoteVllmBootstrap(
                ssh_exe=self._ssh_tunnel.ssh_exe,
                known_hosts=self._ssh_tunnel.known_hosts,
                key_path=self._ssh_tunnel.key_path,
                max_model_len=self._settings.max_model_len,
            )
        if self._model_probe is None:
            from .model_probe import ModelProbe

            self._model_probe = ModelProbe()

    def _prepare_vast_model(
        self,
        secrets: Mapping[str, str],
        cancellation: StartCancellation,
        attempt: list[str],
    ):
        self._set_state("provisioning")
        self._set_component("model", "provisioning")
        self._ensure_remote_dependencies(secrets)
        self._check_cancelled(cancellation)

        self._replace_scheduled_instance(cancellation)

        if self._vast_adapter is None:
            self._vast_adapter = self._huggingface_client.resolve_adapter(
                self._settings.adapter_repo, secrets["HF_TOKEN"]
            )
        self._check_cancelled(cancellation)
        if not self._ssh_key_registered:
            public_key = self._ssh_tunnel.ensure_identity()
            self._vast_client.ensure_account_ssh_key(public_key)
            self._ssh_key_registered = True
        self._check_cancelled(cancellation)

        if self._vast_instance is None:
            existing_ids = self._vast_client.list_labeled_instance_ids(
                LaunchSpec.default().label
            )
            if existing_ids:
                candidates = tuple(
                    self._vast_client.show_instance(instance_id)
                    for instance_id in existing_ids
                )
                self._vast_candidates = candidates
                if len(candidates) > 1:
                    self._pending_confirmation = "instance_selection"
                    raise InstanceSelectionRequired(len(candidates))
                self._vast_instance = candidates[0]
                self._vast_candidates = ()
                self._vast_offer = None
                self._confirmed_offer = None
                self._pending_confirmation = None
            else:
                self._vast_candidates = ()
        if self._vast_instance is None:
            if self._vast_offer is None:
                offers = self._search_offers()
                if not offers:
                    search_summary = getattr(
                        self._vast_client, "offer_search_summary", None
                    )
                    detail = "no eligible offer is available"
                    if isinstance(search_summary, str) and search_summary:
                        detail += f" ({search_summary})"
                    raise StartFailed("Vast.ai", detail)
                self._vast_offer = offers[0]
            offer = self._vast_offer
            expected_confirmation = (offer.offer_id, offer.dph_total)
            if self._confirmed_offer != expected_confirmation:
                self._pending_confirmation = "price"
                raise PriceConfirmationRequired(offer)
            self._pending_confirmation = None
            self._check_cancelled(cancellation)
            self._vast_instance = self._vast_client.create_instance(
                offer,
                LaunchSpec.default(),
            )
            self._confirmed_offer = None
        self._check_cancelled(cancellation)
        instance = self._vast_instance
        restarting_existing = False
        if instance.actual_status in ("stopped", "exited"):
            expected_restart = (instance.instance_id, instance.dph_total)
            if self._confirmed_restart != expected_restart:
                self._pending_confirmation = "instance_restart"
                raise InstanceRestartConfirmationRequired(instance)
            current = self._vast_client.show_instance(instance.instance_id)
            if (
                current.instance_id != instance.instance_id
                or current.dph_total != instance.dph_total
            ):
                self._confirmed_restart = None
                raise StartFailed(
                    "Vast.ai", "existing instance changed before restart"
                )
            self._vast_instance = current
            if current.actual_status in ("stopped", "exited"):
                self._vast_client.set_state(current.instance_id, "running")
                restarting_existing = True
            self._confirmed_restart = None
            self._pending_confirmation = None
            self._check_cancelled(cancellation)
        try:
            self._vast_instance = self._vast_client.wait_until_running(
                self._vast_instance.instance_id,
                allow_stopped_transition=restarting_existing,
                scheduling_timeout_seconds=(30.0 if restarting_existing else None),
            )
        except VastSchedulingTimeout:
            current = self._vast_client.show_instance(
                self._vast_instance.instance_id
            )
            if current.actual_status == "running":
                self._vast_instance = current
            else:
                offers = self._search_offers()
                if not offers:
                    raise StartFailed(
                        "Vast.ai",
                        "restart remained scheduled and no replacement offer is available",
                    ) from None
                self._vast_instance = current
                self._replacement_instance = current
                self._replacement_offer = offers[0]
                self._confirmed_replacement = None
                self._pending_confirmation = "instance_replace"
                raise InstanceReplacementConfirmationRequired(current, offers[0])
        instance = self._vast_instance

        confirmed_fingerprint = None
        if (
            self._confirmed_fingerprint is not None
            and self._confirmed_fingerprint[0] == instance.instance_id
        ):
            confirmed_fingerprint = self._confirmed_fingerprint[1]
        try:
            self._ssh_tunnel.prepare_host(instance, confirmed_fingerprint)
        except HostFingerprintConfirmation as pending:
            self._pending_confirmation = "fingerprint"
            self._pending_fingerprint = pending.fingerprint
            raise
        self._pending_confirmation = None
        self._pending_fingerprint = None
        self._check_cancelled(cancellation)

        self._set_component("ssh tunnel", "starting")
        self._ssh_tunnel.start(instance)
        self._remember_owned("ssh tunnel", attempt)
        self._set_component("ssh tunnel", "ready")
        self._check_cancelled(cancellation)

        try:
            self._remote_bootstrap.start(
                instance,
                self._vast_adapter,
                secrets,
                cancelled=cancellation.is_cancelled,
            )
        except Exception:
            self._check_cancelled(cancellation)
            raise
        self._check_cancelled(cancellation)
        try:
            ready = self._model_probe.wait_ready(
                "http://127.0.0.1:8001/v1",
                secrets["VLLM_API_KEY"],
                model="defend-ai",
                cancelled=cancellation.is_cancelled,
                on_models_ready=lambda: self._remote_bootstrap.cleanup_token_file(
                    instance
                ),
            )
        except Exception:
            self._check_cancelled(cancellation)
            raise
        self._check_cancelled(cancellation)
        self._set_component("model", "ready")
        return build_remote_process_specs(self._settings, secrets, ready)

    def _wait_healthy(
        self,
        component: str,
        url: str,
        cancellation: StartCancellation,
        *,
        public: bool = False,
        timeout_seconds: float | None = None,
    ) -> None:
        limit = (
            float(timeout_seconds)
            if timeout_seconds is not None
            else (
                self._public_health_timeout_seconds
                if public
                else self._health_timeout_seconds
            )
        )
        if limit <= 0:
            raise ValueError("health timeout must be positive")
        deadline = time.monotonic() + limit
        while True:
            self._check_cancelled(cancellation)
            remaining = max(0.001, deadline - time.monotonic())
            result = self._health_probe(
                url,
                min(5.0, remaining),
                **(
                    {"public_origin": self._settings.public_web_origin}
                    if public
                    else {}
                ),
            )
            self._check_cancelled(cancellation)
            if result.ok:
                return
            if time.monotonic() >= deadline:
                raise StartFailed(component, "health check timed out")
            cancellation.wait(
                min(self._poll_interval_seconds, max(0.0, deadline - time.monotonic()))
            )

    def _remember_owned(self, name: str, attempt: list[str]) -> None:
        with self._state_lock:
            self._owned_order.append(name)
            attempt.append(name)

    def _forget_owned(self, name: str) -> None:
        with self._state_lock:
            if name in self._owned_order:
                self._owned_order.remove(name)

    def _rollback(self, attempt: list[str]) -> bool:
        for name in reversed(attempt):
            try:
                self._supervisor.stop(name)
            except Exception:
                component = "frontend" if name == "web" else name
                self._set_component(component, "cleanup pending")
                continue
            self._forget_owned(name)
            component = "frontend" if name == "web" else name
            self._set_component(component, "stopped")

        with self._state_lock:
            return not any(name in self._owned_order for name in attempt)

    def start(
        self,
        mode: ModelMode,
        cancellation: StartCancellation | None = None,
    ) -> StackSnapshot | AlreadyRunning:
        if mode not in ("vast", "ollama"):
            raise ValueError("mode must be vast or ollama")
        attempt_cancellation = cancellation or StartCancellation()
        self._check_cancelled(attempt_cancellation)
        if not self._operation_lock.acquire(blocking=False):
            current = self.snapshot()
            return AlreadyRunning(current.state, current.mode)
        attempt: list[str] = []
        try:
            with self._state_lock:
                confirmation_resumed = (
                    self._state == "provisioning"
                    and self._pending_confirmation is None
                )
                switching_from_vast_gate = (
                    self._state == "provisioning"
                    and mode == "ollama"
                    and not self._owned_order
                )
                if (
                    self._state not in ("stopped", "failed")
                    and not confirmation_resumed
                    and not switching_from_vast_gate
                ) or self._owned_order:
                    return AlreadyRunning(self._state, self._mode)
                if mode == "ollama":
                    self._pending_confirmation = None
                    self._pending_fingerprint = None
                    if self._vast_instance is None:
                        self._vast_offer = None
                        self._confirmed_offer = None
                self._active_cancellation = attempt_cancellation
                self._mode = mode
                self._last_explicit_mode = mode
                self._state = "validating"
                self._error = None
                self._components = {name: "stopped" for name in self._COMPONENTS}

            secrets = self._load_secrets()
            self._check_cancelled(attempt_cancellation)
            adopted = self._shared_surface_ports()
            checks = (
                self._preflight.run(
                    mode, self._settings, secrets, adopted_ports=adopted
                )
                if adopted
                else self._preflight.run(mode, self._settings, secrets)
            )
            failed_checks = tuple(check for check in checks if not check.ok)
            if failed_checks:
                first_failure = failed_checks[0]
                failure_detail = f"{first_failure.name}: {first_failure.detail}"
                if first_failure.remediation:
                    failure_detail += f"; {first_failure.remediation}"
                raise StartFailed("preflight", failure_detail)
            self._check_cancelled(attempt_cancellation)
            if mode == "vast":
                specs = self._prepare_vast_model(
                    secrets, attempt_cancellation, attempt
                )
            else:
                self._set_state("starting")
                self._set_component("model", "starting")
                try:
                    ready = self._local_backend.verify(self._settings.local_model)
                except LocalModelUnavailable as error:
                    raise StartFailed("model", str(error)) from None
                self._set_component("model", "ready")
                self._check_cancelled(attempt_cancellation)
                specs = build_local_process_specs(self._settings, secrets, ready)

            self._set_state("starting")

            if self._settings.api_port in adopted:
                self._set_component("api", "ready (shared)")
            else:
                self._set_component("api", "starting")
                self._check_cancelled(attempt_cancellation)
                self._supervisor.start(specs.api)
                self._remember_owned("api", attempt)
                self._wait_healthy(
                    "API", specs.api.health_url or "", attempt_cancellation
                )
                self._set_component("api", "ready")
            self._check_cancelled(attempt_cancellation)

            if self._settings.web_port in adopted:
                self._set_component("frontend", "ready (shared)")
            else:
                self._set_component("frontend", "starting")
                self._check_cancelled(attempt_cancellation)
                self._supervisor.start(specs.web)
                self._remember_owned("web", attempt)
                self._wait_healthy(
                    "frontend", specs.web.health_url or "", attempt_cancellation
                )
                self._set_component("frontend", "ready")
            self._check_cancelled(attempt_cancellation)

            self._set_component("cloudflare", "starting")
            self._check_cancelled(attempt_cancellation)
            try:
                external_tunnel_pid = self._external_tunnel_detector(
                    self._settings
                )
            except Exception:
                external_tunnel_pid = None
            if (
                type(external_tunnel_pid) is int
                and external_tunnel_pid > 0
            ):
                self._supervisor.observe_external(
                    "external-cloudflare",
                    pid=external_tunnel_pid,
                    health_url=self._settings.public_web_origin,
                )
                self._set_component("cloudflare", "ready (external)")
            else:
                self._check_cancelled(attempt_cancellation)
                self._supervisor.start(specs.cloudflare)
                self._remember_owned("cloudflare", attempt)
                self._set_component("cloudflare", "running")
            self._check_cancelled(attempt_cancellation)
            # Public frontend may not expose /health; probe the origin root instead.
            self._wait_healthy(
                "public route",
                f"{self._settings.public_web_origin.rstrip('/')}/",
                attempt_cancellation,
                public=True,
            )
            self._set_component("cloudflare", "ready")
            self._set_state("ready")
            return self.snapshot()
        except (
            PriceConfirmationRequired,
            HostFingerprintConfirmation,
            InstanceSelectionRequired,
            InstanceRestartConfirmationRequired,
            InstanceReplacementConfirmationRequired,
        ) as pending:
            self._rollback(attempt)
            self._set_state("provisioning", error=str(pending))
            raise
        except StartCancelled:
            rollback_complete = self._rollback(attempt)
            if rollback_complete:
                self._set_component("model", "stopped")
                self._set_component("ssh tunnel", "stopped")
                self._set_state("stopped")
            else:
                self._set_state(
                    "failed", error="startup cancelled; cleanup pending"
                )
            raise
        except StartFailed as error:
            # Public edge lag must not tear down a healthy local stack or an
            # already-provisioned remote model. Degrade instead of hard-fail.
            if error.component == "public route":
                self._set_component("cloudflare", "degraded")
                self._set_state(
                    "degraded",
                    error=(
                        "Local API and frontend are up; public route is not healthy yet. "
                        f"{error}"
                    ),
                )
                return self.snapshot()
            self._rollback(attempt)
            self._set_state("failed", error=str(error))
            raise
        except VastError as error:
            self._rollback(attempt)
            safe = StartFailed("Vast.ai", str(error))
            self._set_state("failed", error=str(safe))
            raise safe from None
        except SshTunnelError as error:
            self._rollback(attempt)
            safe = StartFailed("SSH tunnel", str(error))
            self._set_state("failed", error=str(safe))
            raise safe from None
        except RemoteVllmError as error:
            self._rollback(attempt)
            safe = StartFailed("remote vLLM", str(error))
            self._set_state("failed", error=str(safe))
            raise safe from None
        except Exception as error:
            self._rollback(attempt)
            safe = StartFailed("startup", f"unexpected {type(error).__name__}")
            self._set_state("failed", error=str(safe))
            raise safe from None
        finally:
            with self._state_lock:
                if self._active_cancellation is attempt_cancellation:
                    self._active_cancellation = None
            self._operation_lock.release()

    def cancel_start(self) -> None:
        with self._state_lock:
            cancellation = self._active_cancellation
        if cancellation is not None:
            cancellation.cancel()

    def confirm_offer(self, offer_id: int, hourly_price: Decimal | str) -> None:
        with self._state_lock:
            offer = self._vast_offer
            if offer is None or self._pending_confirmation != "price":
                raise ValueError("there is no pending Vast offer confirmation")
            if type(offer_id) is not int or offer_id != offer.offer_id:
                raise ValueError("confirmation requires the exact offer ID and price")
            try:
                parsed_price = Decimal(str(hourly_price))
            except (InvalidOperation, ValueError):
                raise ValueError(
                    "confirmation requires the exact offer ID and price"
                ) from None
            if not parsed_price.is_finite() or parsed_price != offer.dph_total:
                raise ValueError("confirmation requires the exact offer ID and price")
            self._confirmed_offer = (offer.offer_id, offer.dph_total)
            self._pending_confirmation = None
            self._error = None

    def confirm_fingerprint(self, instance_id: int, fingerprint: str) -> None:
        with self._state_lock:
            instance = self._vast_instance
            expected = self._pending_fingerprint
            if (
                instance is None
                or self._pending_confirmation != "fingerprint"
                or type(instance_id) is not int
                or instance_id != instance.instance_id
                or not isinstance(fingerprint, str)
                or fingerprint != expected
            ):
                raise ValueError(
                    "confirmation requires the exact instance and exact fingerprint"
                )
            self._confirmed_fingerprint = (instance_id, fingerprint)
            self._pending_confirmation = None
            self._error = None

    def select_vast_instance(self, instance_id: int) -> None:
        with self._state_lock:
            if (
                self._pending_confirmation != "instance_selection"
                or type(instance_id) is not int
            ):
                raise ValueError("selection requires an exact listed instance")
            selected = next(
                (
                    candidate
                    for candidate in self._vast_candidates
                    if candidate.instance_id == instance_id
                ),
                None,
            )
            if selected is None:
                raise ValueError("selection requires an exact listed instance")
            self._vast_instance = selected
            self._vast_candidates = ()
            self._vast_offer = None
            self._confirmed_offer = None
            self._confirmed_restart = None
            self._pending_confirmation = None
            self._error = None

    def confirm_instance_restart(
        self, instance_id: int, hourly_price: Decimal | str
    ) -> None:
        with self._state_lock:
            instance = self._vast_instance
            try:
                parsed_price = Decimal(str(hourly_price))
            except (InvalidOperation, ValueError):
                parsed_price = Decimal("NaN")
            if (
                instance is None
                or self._pending_confirmation != "instance_restart"
                or type(instance_id) is not int
                or instance_id != instance.instance_id
                or not parsed_price.is_finite()
                or parsed_price != instance.dph_total
            ):
                raise ValueError(
                    "confirmation requires the exact instance ID and price"
                )
            self._confirmed_restart = (instance.instance_id, instance.dph_total)
            self._pending_confirmation = None
            self._error = None

    def confirm_instance_replacement(
        self,
        instance_id: int,
        offer_id: int,
        hourly_price: Decimal | str,
    ) -> None:
        with self._state_lock:
            instance = self._replacement_instance
            offer = self._replacement_offer
            try:
                parsed_price = Decimal(str(hourly_price))
            except (InvalidOperation, ValueError):
                parsed_price = Decimal("NaN")
            if (
                instance is None
                or offer is None
                or self._pending_confirmation != "instance_replace"
                or type(instance_id) is not int
                or instance_id != instance.instance_id
                or type(offer_id) is not int
                or offer_id != offer.offer_id
                or not parsed_price.is_finite()
                or parsed_price != offer.dph_total
            ):
                raise ValueError(
                    "confirmation requires the exact instance, offer, and price"
                )
            self._confirmed_replacement = (
                instance.instance_id,
                offer.offer_id,
                offer.dph_total,
            )
            self._pending_confirmation = None
            self._error = None

    def decline_instance_action(self) -> StackSnapshot:
        with self._state_lock:
            if self._pending_confirmation not in (
                "instance_selection",
                "instance_restart",
                "instance_replace",
            ):
                raise ValueError("there is no pending instance action")
            self._pending_confirmation = None
            self._vast_candidates = ()
            self._confirmed_restart = None
            self._clear_replacement()
            self._error = None
            self._state = "stopped"
        return self.snapshot()

    def stop_local(self) -> StackSnapshot:
        self.cancel_start()
        with self._operation_lock:
            self._set_state("stopping")
            with self._state_lock:
                owned = tuple(reversed(self._owned_order))
            first_error: RuntimeError | None = None
            for name in owned:
                try:
                    self._supervisor.stop(name)
                except Exception as error:
                    if first_error is None:
                        first_error = RuntimeError(
                            f"Could not stop {name} ({type(error).__name__})"
                        )
                    continue
                self._forget_owned(name)
                self._set_component(
                    "frontend" if name == "web" else name, "stopped"
                )
            self._set_component("model", "stopped")
            self._set_component("ssh tunnel", "stopped")
            with self._state_lock:
                self._pending_confirmation = None
                self._pending_fingerprint = None
                self._vast_candidates = ()
                self._confirmed_restart = None
                self._clear_replacement()
            if first_error is not None:
                self._set_state("failed", error=str(first_error))
                raise first_error
            self._set_state("stopped")
            return self.snapshot()

    def destroy_vast(self, confirmed_instance_id: int) -> StackSnapshot:
        with self._state_lock:
            instance = self._vast_instance
        if (
            instance is None
            or type(confirmed_instance_id) is not int
            or confirmed_instance_id != instance.instance_id
        ):
            raise ValueError("destruction requires the exact instance ID")
        with self._operation_lock:
            local_cleanup_error: str | None = None
            try:
                self.stop_local()
            except Exception as error:
                local_cleanup_error = type(error).__name__
            self._set_state("stopping")
            try:
                if self._vast_client is None:
                    raise RuntimeError("Vast.ai provider is unavailable")
                self._vast_client.destroy_instance(
                    instance.instance_id,
                    confirmed_instance_id=confirmed_instance_id,
                )
            except Exception as error:
                self._set_state(
                    "degraded",
                    error=f"Vast.ai destruction failed ({type(error).__name__})",
                )
                raise RuntimeError(
                    f"Vast.ai destruction failed ({type(error).__name__})"
                ) from None
            with self._state_lock:
                self._vast_instance = None
                self._vast_offer = None
                self._confirmed_offer = None
                self._confirmed_fingerprint = None
                self._confirmed_restart = None
                self._clear_replacement()
                self._pending_confirmation = None
                self._pending_fingerprint = None
                self._vast_candidates = ()
                if local_cleanup_error is None:
                    self._state = "stopped"
                    self._error = None
                else:
                    self._state = "failed"
                    self._error = (
                        "Vast.ai instance destroyed; local cleanup is incomplete "
                        f"({local_cleanup_error})"
                    )
            if local_cleanup_error is not None:
                raise RuntimeError(
                    "Vast.ai instance destroyed; local cleanup is incomplete "
                    f"({local_cleanup_error})"
                )
            return self.snapshot()

    def stop_and_destroy_vast(self, confirmed_instance_id: int) -> StackSnapshot:
        return self.destroy_vast(confirmed_instance_id)

    def restart(self) -> StackSnapshot | AlreadyRunning:
        with self._state_lock:
            mode = self._last_explicit_mode
        if mode is None:
            raise StartFailed("restart", "no explicit launch mode has been selected")
        with self._operation_lock:
            self.stop_local()
            return self.start(mode)

    def snapshot(self) -> StackSnapshot:
        logs = ()
        log_buffer = getattr(self._supervisor, "logs", None)
        if log_buffer is not None and hasattr(log_buffer, "snapshot"):
            logs = tuple(log_buffer.snapshot())
        with self._state_lock:
            offer = self._vast_offer
            instance = self._vast_instance
            billing_warning = None
            if instance is not None:
                if instance.actual_status in ("stopped", "exited"):
                    billing_warning = (
                        "Instance is stopped; storage billing may remain active until "
                        "this instance is destroyed."
                    )
                else:
                    billing_warning = (
                        "Compute billing may remain active until this instance is destroyed."
                    )
            return StackSnapshot(
                state=self._state,
                mode=self._mode,
                components=tuple(
                    ComponentSnapshot(name, self._components[name])
                    for name in self._COMPONENTS
                ),
                error=self._error,
                vast_gpu=(
                    instance.gpu_name
                    if instance is not None
                    else offer.gpu_name if offer is not None else None
                ),
                vast_instance_id=(
                    instance.instance_id if instance is not None else None
                ),
                vast_hourly_price=(
                    str(instance.dph_total)
                    if instance is not None
                    else str(offer.dph_total) if offer is not None else None
                ),
                vast_offer_id=offer.offer_id if offer is not None else None,
                vast_gpu_ram_mb=(
                    instance.gpu_ram_mb
                    if instance is not None
                    else offer.gpu_ram_mb if offer is not None else None
                ),
                vast_reliability=(
                    str(offer.reliability) if offer is not None else None
                ),
                vast_storage_cost_per_gb_month=(
                    str(offer.storage_cost_per_gb_month)
                    if offer is not None
                    and offer.storage_cost_per_gb_month is not None
                    else None
                ),
                vast_storage_total_hourly=(
                    str(offer.storage_total_hourly)
                    if offer is not None
                    and offer.storage_total_hourly is not None
                    else None
                ),
                vast_disk_gb=(
                    self._settings.vllm_disk_gb
                    if offer is not None or instance is not None
                    else None
                ),
                vast_actual_status=(
                    instance.actual_status if instance is not None else None
                ),
                vast_billing_warning=billing_warning,
                pending_confirmation=self._pending_confirmation,
                pending_fingerprint=self._pending_fingerprint,
                vast_candidates=self._vast_candidates,
                vast_replacement_offer=self._replacement_offer,
                logs=logs,
                owned_services=tuple(self._owned_order),
            )
