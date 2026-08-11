from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import os
from pathlib import Path
import threading
import tkinter as tk
from tkinter import messagebox

from defend_control.controller import ControlController
from defend_control.local_model import LocalOllamaBackend
from defend_control.orchestrator import StackOrchestrator
from defend_control.preflight import PreflightRunner
from defend_control.processes import ProcessSupervisor
from defend_control.secrets import DpapiSecretStore
from defend_control.settings import ControlSettings, JsonSettingsStore
from defend_control.ui import ControlCenterUI, SetupDialog


@dataclass
class _Runtime:
    controller: ControlController
    supervisor: ProcessSupervisor


@dataclass(frozen=True)
class _PreparedRuntimeReplacement:
    updated_settings: ControlSettings
    candidate_runtime: _Runtime
    previous_settings: ControlSettings
    previous_secrets: dict[str, str] = field(repr=False)


class _RuntimeCoordinator:
    def __init__(
        self,
        *,
        runtime: _Runtime,
        settings: ControlSettings,
        settings_store,
        secret_store,
        build_runtime,
    ) -> None:
        self._runtime = runtime
        self._settings = settings
        self._settings_store = settings_store
        self._secret_store = secret_store
        self._build_runtime = build_runtime
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

    def activate(
        self,
        prepared: _PreparedRuntimeReplacement,
        apply_controller,
    ):
        with self._lock:
            previous_runtime = self._runtime
            previous_settings = self._settings
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
            return prepared.candidate_runtime.controller.submit_work(
                self._rollback_swap, prepared, error_type
            )

        with self._lock:
            self._runtime = prepared.candidate_runtime
            self._settings = prepared.updated_settings
            self._retired.append(previous_runtime)
        return prepared.candidate_runtime.controller.submit_work(
            self._retire_runtime, previous_runtime
        )

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
        return self.runtime.controller.submit_work(self._close_all)

    def shutdown_controllers(self) -> None:
        with self._lock:
            runtimes = (*self._retired, self._runtime)
        for runtime in runtimes:
            runtime.controller.shutdown()


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
        return _Runtime(ControlController(orchestrator), supervisor)
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
            lambda controller, origin: app.set_controller(
                controller, public_origin=origin
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
        open_setup=open_setup,
        submit_exit_cleanup=submit_exit_cleanup,
        destroy_window=destroy_window,
    )
    root.mainloop()


if __name__ == "__main__":
    run_control_center()
