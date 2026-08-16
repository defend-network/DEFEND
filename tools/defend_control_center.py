from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from decimal import Decimal
import os
from pathlib import Path
import sys
import threading
import tkinter as tk
from tkinter import messagebox

from defend_control.controller import ControlController
from defend_control.health import probe_http
from defend_control.local_model import LocalOllamaBackend
from defend_control.orchestrator import StackOrchestrator
from defend_control.preflight import CheckResult, PreflightRunner
from defend_control.processes import ProcessSupervisor
from defend_control.products import ProductsSettings, build_products
from defend_control.secrets import DpapiSecretStore
from defend_control.settings import ControlSettings, JsonSettingsStore
from defend_control.ui import ControlCenterUI, SetupDialog
from scs_ai.config import ScsAiSettings
from scs_ai.tunnel import (
    EnvTokenSource,
    FileTokenSource,
    TunnelController,
)


@dataclass
class _Runtime:
    controller: ControlController
    supervisor: ProcessSupervisor
    products: tuple[object, ...] = ()
    coder_plane: object | None = None
    coder_fingerprint_confirmer: object | None = None


class _CoderFingerprintConfirmer:
    """Indirection so the UI can supply an interactive SSH confirmation."""

    def __init__(self) -> None:
        self.callback = None

    def set(self, callback) -> None:
        self.callback = callback

    def confirm(self, instance_id: int, fingerprint: str) -> bool:
        if self.callback is None:
            return False
        return bool(self.callback(instance_id, fingerprint))


def _load_coder_secrets(secret_source) -> dict[str, str]:
    loader = getattr(secret_source, "load", None)
    if loader is None:
        return dict(secret_source)
    loaded = loader()
    if not isinstance(loaded, dict):
        raise TypeError("secret store returned invalid state")
    return dict(loaded)


def _build_coder_plane(
    *,
    products_settings,
    secret_source,
    supervisor,
    confirmer: _CoderFingerprintConfirmer | None = None,
):
    """Build the DEFENDcoder control plane; None when Vast is not configured.

    The plane performs zero billable calls on construction; launch flows
    reach approval_required before any create_instance call.
    """
    from defend_control.coder_control_plane import (
        CoderControlPlane,
        CoderPolicy,
    )
    from defend_control.coder_remote_vllm import CoderRemoteVllmBootstrap
    from defend_control.coder_vast_backend import VastCoderBackend
    from defend_control.ssh_tunnel import (
        HostFingerprintConfirmation,
        SshTunnel,
    )
    from defend_control.types import ResourceProfile
    from defend_control.vast import VastClient

    secrets = _load_coder_secrets(secret_source)
    if not secrets.get("VAST_API_KEY"):
        return None

    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return None
    ssh_root = Path(local_app_data) / "DEFEND" / "ssh"
    known_hosts = ssh_root / "known_hosts"
    key_path = ssh_root / "vast_ed25519"

    active_confirmer = (
        confirmer if confirmer is not None else _CoderFingerprintConfirmer()
    )

    def tunnel_start(instance, local_port):
        tunnel = SshTunnel(
            supervisor,
            known_hosts=known_hosts,
            key_path=key_path,
            local_port=local_port,
            name=f"coder ssh tunnel:{local_port}",
        )
        try:
            fingerprint = tunnel.prepare_host(
                instance,
                confirm_fingerprint=None,
                prefer_direct=True,
            )
        except HostFingerprintConfirmation as pending:
            if not active_confirmer.confirm(
                pending.instance_id,
                pending.fingerprint,
            ):
                raise
            fingerprint = tunnel.prepare_host(
                instance,
                confirm_fingerprint=pending.fingerprint,
                prefer_direct=True,
            )
        tunnel.start(instance, prefer_direct=True)
        return f"http://127.0.0.1:{local_port}/v1"

    template = SshTunnel(
        supervisor,
        known_hosts=known_hosts,
        key_path=key_path,
    )
    bootstrap = CoderRemoteVllmBootstrap(
        ssh_exe=template.ssh_exe,
        known_hosts=known_hosts,
        key_path=key_path,
    )
    policy = CoderPolicy()
    backend = VastCoderBackend(
        vast=VastClient(secrets["VAST_API_KEY"]),
        secrets=secrets,
        bootstrap=bootstrap,
        max_hourly=policy.max_hourly_usd,
        profile=ResourceProfile.coder_default(),
        tunnel_start=tunnel_start,
    )
    plane = CoderControlPlane(
        backend=backend,
        token_provider=lambda: secrets.get("HF_TOKEN"),
    )
    plane.fingerprint_confirmer = active_confirmer.confirm
    return plane


@dataclass(frozen=True)
class CheckModeReport:
    """Credential-free summary of the non-billable acceptance checks."""

    checks: tuple[CheckResult, ...]

    @property
    def ready(self) -> bool:
        return all(check.ok for check in self.checks)


_CHECK_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "dependencies",
        (
            "python-version",
            "node-version",
            "npm.cmd",
            "git",
            "ssh.exe",
            "import:",
        ),
    ),
    ("secrets", ("secrets",)),
    ("ports", ("service-ports", "port:")),
    ("data-root", ("data-root", "settings-root", "logs")),
    ("invitation-transport", ("invitations",)),
    ("cloudflare", ("cloudflared.exe", "cloudflared-config")),
    ("frontend-build", ("next-build",)),
)


def _group_check_results(
    raw_results: tuple[CheckResult, ...],
) -> tuple[CheckResult, ...]:
    grouped: list[CheckResult] = [
        CheckResult("settings", True, "Control Center settings are valid")
    ]
    for group_name, selectors in _CHECK_GROUPS:
        members = tuple(
            result
            for result in raw_results
            if any(
                result.name == selector
                or (selector.endswith(":") and result.name.startswith(selector))
                for selector in selectors
            )
        )
        failures = tuple(result for result in members if not result.ok)
        failure = (
            max(failures, key=lambda result: len(result.detail))
            if failures
            else None
        )
        if failure is None:
            grouped.append(CheckResult(group_name, True, f"{group_name} ready"))
        else:
            grouped.append(
                CheckResult(
                    group_name,
                    False,
                    failure.detail,
                    failure.remediation,
                )
            )
    return tuple(grouped)


def run_check_mode(
    settings: ControlSettings,
    secrets: Mapping[str, str] | object,
    *,
    vast: object | None = None,
    preflight: PreflightRunner | None = None,
    health_probe=probe_http,
) -> CheckModeReport:
    """Run both-mode validation without provider access or process mutation."""

    # `vast` is accepted only so tests/callers can prove that check mode never
    # touches the provider. It must remain deliberately unused.
    del vast
    runner = preflight or PreflightRunner()
    raw_results = tuple(
        result
        for mode in ("ollama", "vast")
        for result in runner.run(mode, settings, secrets)
    )
    checks = list(_group_check_results(raw_results))

    occupied = any(
        not result.ok and result.name.startswith("port:")
        for result in raw_results
    )
    if occupied:
        try:
            public = health_probe(
                f"{settings.public_web_origin.rstrip('/')}/health",
                3.0,
                public_origin=settings.public_web_origin,
            )
            checks.append(
                CheckResult(
                    "public-route",
                    bool(public.ok),
                    "Existing public route is healthy"
                    if public.ok
                    else f"Existing public route check failed ({public.error_type or 'NotReady'})",
                    None
                    if public.ok
                    else "Stop duplicate services or repair the named Cloudflare route",
                )
            )
        except Exception as error:
            checks.append(
                CheckResult(
                    "public-route",
                    False,
                    f"Existing public route check failed ({type(error).__name__})",
                    "Stop duplicate services or repair the named Cloudflare route",
                )
            )
    return CheckModeReport(tuple(checks))


@dataclass(frozen=True)
class _PreparedRuntimeReplacement:
    updated_settings: ControlSettings
    candidate_runtime: _Runtime
    previous_settings: ControlSettings
    previous_secrets: dict[str, str] = field(repr=False)


def _candidate_runtime_probe() -> None:
    return None


@dataclass
class _ActivationHandoff:
    prepared: _PreparedRuntimeReplacement
    previous_runtime: _Runtime
    ready: threading.Event = field(default_factory=threading.Event)
    action: str | None = None
    error_type: str | None = None


class _RuntimeCoordinator:
    def __init__(
        self,
        *,
        runtime: _Runtime,
        settings: ControlSettings,
        settings_store,
        secret_store,
        build_runtime,
        maintenance_executor=None,
    ) -> None:
        self._runtime = runtime
        self._settings = settings
        self._settings_store = settings_store
        self._secret_store = secret_store
        self._build_runtime = build_runtime
        self._maintenance_executor = maintenance_executor or ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="defend-runtime-maintenance",
        )
        self._owns_maintenance_executor = maintenance_executor is None
        self._retired: list[_Runtime] = []
        self._lock = threading.RLock()

    @property
    def runtime(self) -> _Runtime:
        with self._lock:
            return self._runtime

    @property
    def settings(self) -> ControlSettings:
        with self._lock:
            return self._settings

    @staticmethod
    def _dispose_candidate(candidate: _Runtime) -> str | None:
        error_type = None
        try:
            candidate.supervisor.close()
        except Exception as error:
            error_type = type(error).__name__
        finally:
            candidate.controller.shutdown()
        return error_type

    def _restore_stores(
        self,
        settings: ControlSettings,
        secrets: dict[str, str],
    ) -> str | None:
        errors: list[str] = []
        for store, value in (
            (self._settings_store, settings),
            (self._secret_store, secrets),
        ):
            try:
                store.save(value)
            except Exception as error:
                errors.append(type(error).__name__)
        return errors[0] if errors else None

    def prepare(
        self,
        raw_settings: dict[str, object],
        secret_updates: dict[str, str],
    ) -> _PreparedRuntimeReplacement:
        try:
            updated = ControlSettings.from_mapping(raw_settings)
            previous_secrets = self._secret_store.load()
            if not isinstance(previous_secrets, dict):
                raise TypeError("secret store returned invalid state")
        except Exception as error:
            raise RuntimeError(
                f"setup validation failed ({type(error).__name__})"
            ) from None
        candidate_secrets = dict(previous_secrets)
        candidate_secrets.update(secret_updates)
        try:
            candidate = self._build_runtime(updated, candidate_secrets)
        except Exception as error:
            raise RuntimeError(
                f"runtime build failed ({type(error).__name__})"
            ) from None

        try:
            validation = candidate.controller.submit_work(
                _candidate_runtime_probe
            )
            validation.result(timeout=5)
        except Exception as error:
            validation_type = type(error).__name__
            cleanup_type = self._dispose_candidate(candidate)
            detail = (
                f"; cleanup failed ({cleanup_type})" if cleanup_type else ""
            )
            raise RuntimeError(
                f"runtime validation failed ({validation_type}){detail}"
            ) from None

        previous_settings = self.settings
        try:
            self._secret_store.save(candidate_secrets)
            self._settings_store.save(updated)
        except Exception as error:
            persistence_type = type(error).__name__
            rollback_type = self._restore_stores(
                previous_settings, previous_secrets
            )
            cleanup_type = self._dispose_candidate(candidate)
            suffix = rollback_type or cleanup_type
            detail = f"; rollback failed ({suffix})" if suffix else ""
            raise RuntimeError(
                f"setup persistence failed ({persistence_type}){detail}"
            ) from None
        return _PreparedRuntimeReplacement(
            updated,
            candidate,
            previous_settings,
            dict(previous_secrets),
        )

    def _rollback_swap(
        self,
        prepared: _PreparedRuntimeReplacement,
        swap_error_type: str,
    ) -> None:
        rollback_type = self._restore_stores(
            prepared.previous_settings, prepared.previous_secrets
        )
        cleanup_type = self._dispose_candidate(prepared.candidate_runtime)
        suffix = rollback_type or cleanup_type
        detail = f"; rollback failed ({suffix})" if suffix else ""
        raise RuntimeError(
            f"runtime swap failed ({swap_error_type}){detail}"
        )

    def _retire_runtime(self, retired: _Runtime) -> None:
        try:
            retired.supervisor.close()
        except Exception as error:
            raise RuntimeError(
                f"retired runtime cleanup failed ({type(error).__name__})"
            ) from None
        retired.controller.shutdown()
        with self._lock:
            if retired in self._retired:
                self._retired.remove(retired)

    def _complete_activation(self, handoff: _ActivationHandoff) -> None:
        handoff.ready.wait()
        if handoff.action == "rollback":
            self._rollback_swap(
                handoff.prepared,
                handoff.error_type or "Error",
            )
        if handoff.action != "retire":
            raise RuntimeError("runtime activation handoff failed (RuntimeError)")
        self._retire_runtime(handoff.previous_runtime)

    def activate(
        self,
        prepared: _PreparedRuntimeReplacement,
        apply_controller,
    ):
        with self._lock:
            previous_runtime = self._runtime
            previous_settings = self._settings
        handoff = _ActivationHandoff(prepared, previous_runtime)
        try:
            completion = self._maintenance_executor.submit(
                self._complete_activation, handoff
            )
        except Exception as error:
            self._rollback_swap(prepared, type(error).__name__)
        try:
            apply_controller(
                prepared.candidate_runtime.controller,
                prepared.updated_settings.public_web_origin,
            )
        except Exception as error:
            error_type = type(error).__name__
            try:
                apply_controller(
                    previous_runtime.controller,
                    previous_settings.public_web_origin,
                )
            except Exception:
                pass
            handoff.action = "rollback"
            handoff.error_type = error_type
            handoff.ready.set()
            return completion

        with self._lock:
            self._runtime = prepared.candidate_runtime
            self._settings = prepared.updated_settings
            self._retired.append(previous_runtime)
        handoff.action = "retire"
        handoff.ready.set()
        return completion

    def _close_all(self) -> None:
        with self._lock:
            retired = tuple(self._retired)
            current = self._runtime
        for runtime in retired:
            self._retire_runtime(runtime)
        try:
            current.supervisor.close()
        except Exception as error:
            raise RuntimeError(
                f"local process cleanup failed ({type(error).__name__})"
            ) from None

    def submit_exit_cleanup(self):
        return self._maintenance_executor.submit(self._close_all)

    def shutdown_controllers(self) -> None:
        with self._lock:
            runtimes = (*self._retired, self._runtime)
        for runtime in runtimes:
            runtime.controller.shutdown()
        if self._owns_maintenance_executor:
            self._maintenance_executor.shutdown(
                wait=False,
                cancel_futures=True,
            )


def _default_settings(repo_root: Path) -> ControlSettings:
    program_files = os.environ.get(
        "PROGRAMFILES(X86)", r"C:\Program Files (x86)"
    )
    user_profile = os.environ.get("USERPROFILE", str(Path.home()))
    return ControlSettings(
        repo_root=repo_root,
        data_root=Path(r"C:\DEFEND_DATA"),
        public_web_origin="https://ai.defend-network.org",
        cloudflared_exe=Path(program_files) / "cloudflared" / "cloudflared.exe",
        cloudflared_config=Path(user_profile) / ".cloudflared" / "config.yml",
        cloudflared_tunnel="defend-ai",
        adapter_repo="Defend-network/defend-qwen-32b-lora",
        local_model="defend-ai:latest",
        vast_max_hourly=Decimal("3.00"),
    )


def _build_runtime(
    settings: ControlSettings,
    secret_source,
) -> _Runtime:
    supervisor = ProcessSupervisor()
    try:
        orchestrator = StackOrchestrator(
            settings=settings,
            secrets=secret_source,
            preflight=PreflightRunner(),
            supervisor=supervisor,
            local_backend=LocalOllamaBackend(),
        )
        controller = ControlController(orchestrator)
        repository = Path(__file__).resolve().parents[1]

        products_settings = ProductsSettings.from_env()
        scs_settings = ScsAiSettings.from_env()

        token_file = os.environ.get(
            "SCS_AI_TUNNEL_TOKEN_FILE"
        )

        if token_file:
            scs_token_source = FileTokenSource(
                Path(token_file)
            )
        else:
            scs_token_source = EnvTokenSource()

        scs_tunnel = TunnelController(
            scs_settings,
            executable=os.environ.get(
                "SCS_AI_CLOUDFLARED_EXE",
                str(settings.cloudflared_exe),
            ),
            token_source=scs_token_source,
            probe=lambda: probe_http(
                (
                    f"http://127.0.0.1:"
                    f"{products_settings.scs_ai_api_port}/health"
                ),
                2.0,
            ).ok,
        )

        confirmer = _CoderFingerprintConfirmer()
        coder_plane = _build_coder_plane(
            products_settings=products_settings,
            secret_source=secret_source,
            supervisor=supervisor,
            confirmer=confirmer,
        )

        products = build_products(
            controller=controller,
            supervisor=supervisor,
            repository=repository,
            python_executable=sys.executable,
            public_origin=settings.public_web_origin,
            settings=products_settings,
            scs_tunnel=scs_tunnel,
            coder_plane=coder_plane,
        )
        return _Runtime(
            controller,
            supervisor,
            products,
            coder_plane=coder_plane,
            coder_fingerprint_confirmer=confirmer,
        )
    except Exception:
        try:
            supervisor.close()
        except Exception:
            pass
        raise


def run_control_center() -> None:
    """Open the Control Center without starting or provisioning DEFEND."""

    repo_root = Path(__file__).resolve().parents[1]
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA is required for DEFEND Control Center")
    settings_root = Path(local_app_data) / "DEFEND"
    settings_store = JsonSettingsStore(settings_root / "control-center.json")
    secret_store = DpapiSecretStore(settings_root / "secrets.dpapi")

    root = tk.Tk()
    try:
        settings = settings_store.load()
    except FileNotFoundError:
        settings = _default_settings(repo_root)
    except Exception as error:
        settings = _default_settings(repo_root)
        root.after(
            0,
            lambda: messagebox.showerror(
                "DEFEND settings require attention",
                f"Stored settings could not be loaded ({type(error).__name__}). Open Setup.",
                parent=root,
            ),
        )

    runtime = _build_runtime(settings, secret_store)
    coordinator = _RuntimeCoordinator(
        runtime=runtime,
        settings=settings,
        settings_store=settings_store,
        secret_store=secret_store,
        build_runtime=_build_runtime,
    )
    app: ControlCenterUI

    def submit_exit_cleanup():
        return coordinator.submit_exit_cleanup()

    def destroy_window() -> None:
        coordinator.shutdown_controllers()
        root.destroy()

    def submit_save(
        raw_settings: dict[str, object],
        secret_updates: dict[str, str],
    ):
        return coordinator.runtime.controller.submit_work(
            coordinator.prepare, raw_settings, secret_updates
        )

    def settings_saved(result: object):
        return coordinator.activate(
            result,
            lambda controller, origin: (
                app.set_controller(controller, public_origin=origin),
                app.set_products(result.candidate_runtime.products),
                app.wire_coder_fingerprint_confirmer(
                    result.candidate_runtime.coder_fingerprint_confirmer
                ),
            ),
        )

    def open_setup() -> None:
        SetupDialog(
            root,
            coordinator.settings,
            submit_save,
            settings_saved,
        )

    app = ControlCenterUI(
        root,
        coordinator.runtime.controller,
        public_origin=settings.public_web_origin,
        products=coordinator.runtime.products,
        open_setup=open_setup,
        submit_exit_cleanup=submit_exit_cleanup,
        destroy_window=destroy_window,
    )
    app.wire_coder_fingerprint_confirmer(
        coordinator.runtime.coder_fingerprint_confirmer
    )
    root.mainloop()


def _check_paths() -> tuple[ControlSettings, DpapiSecretStore]:
    repo_root = Path(__file__).resolve().parents[1]
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA is required for DEFEND Control Center")
    settings_root = Path(local_app_data) / "DEFEND"
    settings_store = JsonSettingsStore(settings_root / "control-center.json")
    try:
        settings = settings_store.load()
    except FileNotFoundError:
        settings = _default_settings(repo_root)
    return settings, DpapiSecretStore(settings_root / "secrets.dpapi")


def _print_check_report(report: CheckModeReport) -> None:
    for check in report.checks:
        status = "READY" if check.ok else "BLOCKED"
        print(f"{status} {check.name}: {check.detail}")
        if not check.ok and check.remediation:
            print(f"REMEDIATION {check.name}: {check.remediation}")
    print("READY" if report.ready else "NOT READY")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DEFEND Windows Control Center")
    parser.add_argument(
        "--check",
        action="store_true",
        help="run non-billable readiness checks without starting DEFEND",
    )
    args = parser.parse_args(argv)
    if not args.check:
        run_control_center()
        return 0

    try:
        settings, secrets = _check_paths()
        report = run_check_mode(settings, secrets)
    except Exception as error:
        print(f"BLOCKED check-mode: setup could not be loaded ({type(error).__name__})")
        print("REMEDIATION check-mode: Open Start-DEFEND.cmd and complete Setup")
        print("NOT READY")
        return 2
    _print_check_report(report)
    return 0 if report.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
