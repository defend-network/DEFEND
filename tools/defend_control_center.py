from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import os
from pathlib import Path
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
    secret_store: DpapiSecretStore,
) -> _Runtime:
    supervisor = ProcessSupervisor()
    orchestrator = StackOrchestrator(
        settings=settings,
        secrets=secret_store,
        preflight=PreflightRunner(),
        supervisor=supervisor,
        local_backend=LocalOllamaBackend(),
    )
    return _Runtime(ControlController(orchestrator), supervisor)


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
    current_settings = settings
    app: ControlCenterUI

    def stop_runtime_and_destroy_window() -> None:
        nonlocal runtime
        runtime.controller.shutdown()
        try:
            runtime.supervisor.close()
        except RuntimeError as error:
            messagebox.showerror(
                "DEFEND cleanup",
                f"Local process cleanup is incomplete ({type(error).__name__}).",
                parent=root,
            )
            return
        root.destroy()

    def persist_and_replace(
        raw_settings: dict[str, object],
        secret_updates: dict[str, str],
    ) -> tuple[ControlSettings, _Runtime]:
        updated = ControlSettings.from_mapping(raw_settings)
        existing = secret_store.load()
        existing.update(secret_updates)
        secret_store.save(existing)
        settings_store.save(updated)
        runtime.supervisor.close()
        return updated, _build_runtime(updated, secret_store)

    def submit_save(
        raw_settings: dict[str, object],
        secret_updates: dict[str, str],
    ):
        return runtime.controller.submit_work(
            persist_and_replace, raw_settings, secret_updates
        )

    def settings_saved(result: object) -> None:
        nonlocal runtime, current_settings
        updated, replacement = result
        old_runtime = runtime
        old_runtime.controller.shutdown()
        runtime = replacement
        current_settings = updated
        app.set_controller(
            replacement.controller,
            public_origin=updated.public_web_origin,
        )

    def open_setup() -> None:
        SetupDialog(
            root,
            current_settings,
            submit_save,
            settings_saved,
        )

    app = ControlCenterUI(
        root,
        runtime.controller,
        public_origin=settings.public_web_origin,
        open_setup=open_setup,
        on_stopped_exit=stop_runtime_and_destroy_window,
    )
    root.mainloop()


if __name__ == "__main__":
    run_control_center()
