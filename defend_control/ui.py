from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
import os
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText

from .coder_m0 import CoderM0Service, LocalFakeCoderBackend
from .controller import ConfirmationRequired, ControlController, UIState
from .products import ProductStatus
from .settings import ControlSettings
from .integration_catalog import (
    SECRET_CATALOG,
    IntegrationOwner,
)


_POLL_MILLISECONDS = 250
_STATE_COLORS = {
    "running": "green",
    "ready": "green",
    "starting": "blue",
    "provisioning": "blue",
    "stopping": "orange",
    "stopped": "gray",
    "failed": "red",
    "not configured": "orange",
    "unavailable": "orange",
}
_PRODUCT_ACTIONS = (
    ("Launch", "launch"),
    ("Stop", "stop"),
    ("Open", "open"),
    ("Logs", "logs"),
)
_COMPONENT_LABELS = {
    "model": "Model",
    "ssh tunnel": "SSH tunnel",
    "api": "API",
    "frontend": "Frontend",
    "cloudflare": "Cloudflare",
}
_SETTING_FIELDS = (
    ("repo_root", "Repository root"),
    ("data_root", "Data root"),
    ("public_web_origin", "Public web origin"),
    ("cloudflared_exe", "cloudflared executable"),
    ("cloudflared_config", "cloudflared config"),
    ("cloudflared_tunnel", "Cloudflare tunnel name"),
    ("adapter_repo", "Vast adapter repository"),
    ("local_model", "Local Ollama model"),
    ("vast_max_hourly", "Maximum Vast hourly price"),
)

class SetupDialog(tk.Toplevel):
    _secret_groups = (
        (
            IntegrationOwner.PLATFORM,
            "Platform / Operations",
            "Compute, networking, observability, alerts, and shared infrastructure.",
        ),
        (
            IntegrationOwner.DEFEND,
            "DEFEND AI",
            "Identity, research, authentication, and communications.",
        ),
        (
            IntegrationOwner.CODER,
            "DEFENDcoder",
            "Repository access and isolated coding-model credentials.",
        ),
        (
            IntegrationOwner.SPORTS,
            "DEFEND Sports",
            "Odds, statistics, exchanges, and table-tennis data providers.",
        ),
        (
            IntegrationOwner.SCS,
            "SCS AI",
            "Payments, office integrations, address services, and business operations.",
        ),
    )

    def __init__(
        self,
        parent: tk.Misc,
        settings: ControlSettings,
        submit_save: Callable[[dict[str, object], dict[str, str]], object],
        on_saved: Callable[[object], object],
    ) -> None:
        super().__init__(parent)

        self.title("DEFEND Setup")
        self.transient(parent)
        self.resizable(True, True)
        self.geometry("900x760")
        self.minsize(760, 620)

        self._settings = settings
        self._submit_save = submit_save
        self._on_saved = on_saved
        self._setting_values: dict[str, tk.StringVar] = {}
        self._secret_values: dict[str, tk.StringVar] = {}

        outer = ttk.Frame(
            self,
            padding=12,
        )
        outer.grid(
            row=0,
            column=0,
            sticky="nsew",
        )

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        # ------------------------------------------------------
        # Header
        # ------------------------------------------------------

        header = ttk.Frame(outer)
        header.grid(
            row=0,
            column=0,
            sticky="ew",
            pady=(0, 10),
        )
        header.columnconfigure(0, weight=1)

        ttk.Label(
            header,
            text="DEFEND Setup",
            font=("Segoe UI", 16, "bold"),
        ).grid(
            row=0,
            column=0,
            sticky="w",
        )

        ttk.Label(
            header,
            text=(
                "Configure platform settings and integration credentials. "
                "Existing saved values are never displayed; leave a secret "
                "blank to retain its current encrypted value."
            ),
            wraplength=820,
            justify="left",
        ).grid(
            row=1,
            column=0,
            sticky="w",
            pady=(4, 0),
        )

        # ------------------------------------------------------
        # Non-secret settings
        # ------------------------------------------------------

        settings_frame = ttk.LabelFrame(
            outer,
            text="Core settings",
            padding=10,
        )
        settings_frame.grid(
            row=1,
            column=0,
            sticky="ew",
            pady=(0, 10),
        )
        settings_frame.columnconfigure(1, weight=1)

        raw_settings = asdict(settings)

        for row, (name, label) in enumerate(
            _SETTING_FIELDS
        ):
            value = str(raw_settings[name])

            variable = tk.StringVar(
                self,
                value=value,
            )
            self._setting_values[name] = variable

            ttk.Label(
                settings_frame,
                text=label,
            ).grid(
                row=row,
                column=0,
                sticky="w",
                padx=(0, 12),
                pady=2,
            )

            ttk.Entry(
                settings_frame,
                textvariable=variable,
            ).grid(
                row=row,
                column=1,
                sticky="ew",
                pady=2,
            )

        # ------------------------------------------------------
        # Scrollable integration credential area
        # ------------------------------------------------------

        credential_frame = ttk.LabelFrame(
            outer,
            text="Integrations & credentials",
            padding=6,
        )
        credential_frame.grid(
            row=2,
            column=0,
            sticky="nsew",
        )
        credential_frame.columnconfigure(0, weight=1)
        credential_frame.rowconfigure(0, weight=1)

        canvas = tk.Canvas(
            credential_frame,
            highlightthickness=0,
        )
        canvas.grid(
            row=0,
            column=0,
            sticky="nsew",
        )

        scrollbar = ttk.Scrollbar(
            credential_frame,
            orient="vertical",
            command=canvas.yview,
        )
        scrollbar.grid(
            row=0,
            column=1,
            sticky="ns",
        )

        canvas.configure(
            yscrollcommand=scrollbar.set,
        )

        secret_body = ttk.Frame(
            canvas,
            padding=(4, 4, 8, 4),
        )

        window_id = canvas.create_window(
            (0, 0),
            window=secret_body,
            anchor="nw",
        )

        def resize_scroll_region(_event=None) -> None:
            canvas.configure(
                scrollregion=canvas.bbox("all")
            )

        def resize_inner(event) -> None:
            canvas.itemconfigure(
                window_id,
                width=event.width,
            )

        secret_body.bind(
            "<Configure>",
            resize_scroll_region,
        )

        canvas.bind(
            "<Configure>",
            resize_inner,
        )

        secret_body.columnconfigure(0, weight=1)

        definitions_by_owner = {
            owner: tuple(
                definition
                for definition in SECRET_CATALOG
                if definition.owner == owner
            )
            for owner, _label, _description
            in self._secret_groups
        }

        body_row = 0

        for owner, group_label, description in self._secret_groups:
            group = ttk.LabelFrame(
                secret_body,
                text=group_label,
                padding=10,
            )
            group.grid(
                row=body_row,
                column=0,
                sticky="ew",
                pady=(0, 10),
            )
            group.columnconfigure(1, weight=1)
            body_row += 1

            ttk.Label(
                group,
                text=description,
                wraplength=760,
                justify="left",
            ).grid(
                row=0,
                column=0,
                columnspan=2,
                sticky="w",
                pady=(0, 8),
            )

            definitions = definitions_by_owner[
                owner
            ]

            for row, definition in enumerate(
                definitions,
                start=1,
            ):
                variable = tk.StringVar(
                    self,
                    value="",
                )

                self._secret_values[
                    definition.key
                ] = variable

                requirement = (
                    "required"
                    if definition.requirement.value
                    == "required"
                    else "optional"
                )

                label = (
                    f"{definition.display_name} "
                    f"({requirement})"
                )

                ttk.Label(
                    group,
                    text=label,
                ).grid(
                    row=row,
                    column=0,
                    sticky="w",
                    padx=(0, 12),
                    pady=2,
                )

                ttk.Entry(
                    group,
                    textvariable=variable,
                    show="*",
                ).grid(
                    row=row,
                    column=1,
                    sticky="ew",
                    pady=2,
                )

        # ------------------------------------------------------
        # Footer actions
        # ------------------------------------------------------

        buttons = ttk.Frame(outer)
        buttons.grid(
            row=3,
            column=0,
            sticky="e",
            pady=(10, 0),
        )

        self._cancel_button = ttk.Button(
            buttons,
            text="Cancel",
            command=self.destroy,
        )
        self._cancel_button.pack(
            side="right",
            padx=(6, 0),
        )

        self._save_button = ttk.Button(
            buttons,
            text="Save",
            command=self._save,
        )
        self._save_button.pack(
            side="right",
        )

        self.protocol(
            "WM_DELETE_WINDOW",
            self.destroy,
        )
        self.grab_set()

    def _save(self) -> None:
        raw = asdict(self._settings)
        raw.update(
            {name: variable.get() for name, variable in self._setting_values.items()}
        )
        try:
            future = self._submit_save(
                raw,
                {
                    name: value
                    for name, variable in self._secret_values.items()
                    if (value := variable.get())
                },
            )
        except Exception as error:
            messagebox.showerror(
                "Setup could not be saved",
                f"Check the entered values ({type(error).__name__}).",
                parent=self,
            )
            return
        self._save_button.configure(state="disabled")
        self._cancel_button.configure(state="disabled")
        self.protocol("WM_DELETE_WINDOW", lambda: None)
        self.after(50, lambda: self._finish_save(future))

    def _finish_save(self, future: object) -> None:
        done = getattr(future, "done", None)
        if not callable(done) or not done():
            self.after(50, lambda: self._finish_save(future))
            return
        try:
            result = future.result()
        except Exception as error:
            self._save_button.configure(state="normal")
            self._cancel_button.configure(state="normal")
            self.protocol("WM_DELETE_WINDOW", self.destroy)
            messagebox.showerror(
                "Setup could not be saved",
                f"Check the entered values ({type(error).__name__}).",
                parent=self,
            )
            return
        try:
            completion = self._on_saved(result)
        except Exception as error:
            self._save_button.configure(state="normal")
            self._cancel_button.configure(state="normal")
            self.protocol("WM_DELETE_WINDOW", self.destroy)
            messagebox.showerror(
                "Setup could not be activated",
                f"The previous runtime remains active ({type(error).__name__}).",
                parent=self,
            )
            return
        done = getattr(completion, "done", None)
        if callable(done):
            self.after(50, lambda: self._finish_activation(completion))
            return
        self.destroy()

    def _finish_activation(self, future: object) -> None:
        done = getattr(future, "done", None)
        if not callable(done) or not done():
            self.after(50, lambda: self._finish_activation(future))
            return
        try:
            future.result()
        except Exception as error:
            messagebox.showerror(
                "Setup cleanup requires attention",
                f"The runtime transition was incomplete ({type(error).__name__}).",
                parent=self,
            )
        self.destroy()


class ControlCenterUI:
    def __init__(
        self,
        root: tk.Tk,
        controller: ControlController,
        *,
        public_origin: str,
        open_setup: Callable[[], None],
        submit_exit_cleanup: Callable[[], object],
        destroy_window: Callable[[], None] | None = None,
        products: tuple[object, ...] = (),
        coder_service: CoderM0Service | None = None,
    ) -> None:
        self.root = root
        self._controller = controller
        self._public_origin = public_origin
        self._open_setup = open_setup
        self._submit_exit_cleanup = submit_exit_cleanup
        self._destroy_window = destroy_window or root.destroy
        self._products = tuple(products)
        self._product_states: dict[str, tk.StringVar] = {}
        self._product_text: dict[str, tk.StringVar] = {}
        self._product_state_labels: dict[str, ttk.Label] = {}
        self._product_buttons: dict[str, dict[str, ttk.Button]] = {}

        # Dedicated per-product presentation surfaces.
        self._product_tabs: dict[str, ttk.Frame] = {}
        self._product_detail: dict[
            str,
            dict[str, tk.StringVar],
        ] = {}
        self._product_logs: dict[str, ScrolledText] = {}
        self._product_tab_states: dict[str, tk.StringVar] = {}
        self._product_tab_text: dict[str, tk.StringVar] = {}

        self._home_cards: dict[str, ttk.LabelFrame] = {}
        self._home_card_states: dict[str, tk.StringVar] = {}
        self._home_card_text: dict[str, tk.StringVar] = {}
        self._home_buttons: dict[
            str,
            dict[str, ttk.Button],
        ] = {}
        self._tab_buttons: dict[
            str,
            dict[str, ttk.Button],
        ] = {}

        self._platform_posture = tk.StringVar(
            root,
            value="4 products registered",
        )
        # Observation-only until live VastCoderBackend is wired in Control Center.
        self._coder = coder_service or CoderM0Service(
            backend=LocalFakeCoderBackend()
        )
        self._closing_after_stop = False
        self._exit_future: object | None = None
        self._last_log_render: tuple[object, ...] | None = None
        self._last_confirmation_signature: tuple[object, ...] | None = None
        self._mode = tk.StringVar(root, value="")
        self._state = tk.StringVar(root, value="stopped")
        self._component_states = {
            name: tk.StringVar(root, value="stopped") for name in _COMPONENT_LABELS
        }
        self._vast_gpu = tk.StringVar(root, value="—")
        self._vast_instance = tk.StringVar(root, value="—")
        self._vast_price = tk.StringVar(root, value="—")
        self._vast_ram = tk.StringVar(root, value="—")
        self._vast_reliability = tk.StringVar(root, value="—")
        self._vast_status = tk.StringVar(root, value="—")
        self._vast_billing = tk.StringVar(root, value="No active Vast billing")
        self._coder_state = tk.StringVar(root, value="stopped")
        self._coder_alias = tk.StringVar(root, value="—")
        self._coder_model = tk.StringVar(root, value="—")
        self._coder_revision = tk.StringVar(root, value="—")
        self._coder_endpoint = tk.StringVar(root, value="—")
        self._coder_instance = tk.StringVar(root, value="—")
        self._coder_provider_run = tk.StringVar(root, value="—")
        self._coder_price = tk.StringVar(root, value="—")
        self._coder_budget = tk.StringVar(root, value="—")
        self._coder_message = tk.StringVar(root, value="—")
        self._coder_origin = tk.StringVar(
            root, value="https://defendcoder.defend-network.org (inactive)"
        )

        root.title("DEFEND Control Center")
        self._set_window_icon()
        root.minsize(860, 720)
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build()
        self._render(self._controller.poll_state())
        root.after(_POLL_MILLISECONDS, self._poll)

    def set_controller(
        self,
        controller: ControlController,
        *,
        public_origin: str,
    ) -> None:
        state = controller.poll_state()
        self._render(state)
        self._controller = controller
        self._public_origin = public_origin

    def set_products(self, products: tuple[object, ...]) -> None:
        self._products = tuple(products)
    def set_coder_service(self, coder_service: CoderM0Service) -> None:
        """Swap observation source (e.g. live Vast backend later)."""
        self._coder = coder_service
        self._render_coder()

    def _set_window_icon(self) -> None:
        """Apply the DEFEND logo when the local icon asset is available."""

        configured = os.environ.get("DEFEND_CONTROL_ICON")

        candidates = (
            Path(configured) if configured else None,
            Path.home() / "Downloads" / "DEFEND_LOGO.ico",
        )

        for candidate in candidates:
            if candidate is None or not candidate.is_file():
                continue

            try:
                self.root.iconbitmap(str(candidate))
            except tk.TclError:
                continue

            break

    @staticmethod
    def _product_tab_title(application_id: str, display_name: str) -> str:
        names = {
            "defend": "DEFEND AI",
            "sports": "DEFEND Sports",
            "scs": "SCS AI",
            "coder": "DEFENDcoder",
        }

        return names.get(application_id, display_name)

    def _build_product_detail_tab(
        self,
        notebook: ttk.Notebook,
        product: object,
    ) -> None:
        application_id = getattr(
            product,
            "application_id",
            "unknown",
        )
        display_name = getattr(
            product,
            "display_name",
            application_id,
        )

        tab = ttk.Frame(notebook, padding=12)
        notebook.add(
            tab,
            text=self._product_tab_title(
                application_id,
                display_name,
            ),
        )

        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(3, weight=1)

        self._product_tabs[application_id] = tab

        header = ttk.Frame(tab)
        header.grid(
            row=0,
            column=0,
            sticky="ew",
            pady=(0, 8),
        )
        header.columnconfigure(1, weight=1)

        ttk.Label(
            header,
            text=self._product_tab_title(
                application_id,
                display_name,
            ),
            font=("Segoe UI", 12, "bold"),
        ).grid(
            row=0,
            column=0,
            sticky="w",
        )

        state_var = tk.StringVar(
            self.root,
            value="\\u2014",
        )
        text_var = tk.StringVar(
            self.root,
            value="",
        )

        self._product_tab_states[application_id] = state_var
        self._product_tab_text[application_id] = text_var

        ttk.Label(
            header,
            textvariable=state_var,
        ).grid(
            row=0,
            column=1,
            sticky="w",
            padx=(16, 0),
        )

        ttk.Label(
            header,
            textvariable=text_var,
        ).grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(3, 0),
        )

        actions = ttk.Frame(tab)
        actions.grid(
            row=1,
            column=0,
            sticky="ew",
            pady=(0, 8),
        )

        tab_buttons: dict[str, ttk.Button] = {}

        for label, action in _PRODUCT_ACTIONS:
            button = ttk.Button(
                actions,
                text=label,
                command=lambda p=product, a=action: (
                    self._product_action(p, a)
                ),
            )
            button.pack(
                side="left",
                padx=(0, 6),
            )
            tab_buttons[action] = button

        self._tab_buttons[
            application_id
        ] = tab_buttons

        detail_frame = ttk.LabelFrame(
            tab,
            text="Identifiers / health",
            padding=8,
        )
        detail_frame.grid(
            row=2,
            column=0,
            sticky="ew",
            pady=(0, 8),
        )
        detail_frame.columnconfigure(1, weight=1)

        self._product_detail[application_id] = {}

        log_frame = ttk.LabelFrame(
            tab,
            text=f"{display_name} logs",
            padding=6,
        )
        log_frame.grid(
            row=3,
            column=0,
            sticky="nsew",
        )
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        log = ScrolledText(
            log_frame,
            height=16,
            wrap="word",
            state="disabled",
        )
        log.grid(
            row=0,
            column=0,
            sticky="nsew",
        )

        self._product_logs[application_id] = log

        # Store frame so detail fields can be built dynamically from
        # ProductStatus.details without hard-coding product-specific keys.
        setattr(
            detail_frame,
            "_defend_application_id",
            application_id,
        )

    def _render_product_details(
        self,
        application_id: str,
        status: ProductStatus,
    ) -> None:
        tab = self._product_tabs.get(application_id)

        if tab is None:
            return

        detail_frame = None

        for child in tab.winfo_children():
            if (
                isinstance(child, ttk.LabelFrame)
                and getattr(
                    child,
                    "_defend_application_id",
                    None,
                )
                == application_id
            ):
                detail_frame = child
                break

        if detail_frame is None:
            return

        variables = self._product_detail.setdefault(
            application_id,
            {},
        )

        incoming = tuple(status.details)

        # Product detail keys are stable enough to preserve rows between
        # polls; only rebuild if the backend changes the schema.
        incoming_keys = tuple(
            key
            for key, _value in incoming
        )

        if tuple(variables.keys()) != incoming_keys:
            for child in detail_frame.winfo_children():
                child.destroy()

            variables.clear()

            for row, (key, value) in enumerate(incoming):
                ttk.Label(
                    detail_frame,
                    text=key,
                ).grid(
                    row=row,
                    column=0,
                    sticky="w",
                    pady=1,
                )

                variable = tk.StringVar(
                    self.root,
                    value=str(value),
                )
                variables[key] = variable

                ttk.Label(
                    detail_frame,
                    textvariable=variable,
                ).grid(
                    row=row,
                    column=1,
                    sticky="w",
                    padx=(18, 0),
                    pady=1,
                )
        else:
            for key, value in incoming:
                variables[key].set(str(value))

    def _render_product_logs(
        self,
        product: object,
    ) -> None:
        application_id = getattr(
            product,
            "application_id",
            "",
        )

        widget = self._product_logs.get(
            application_id
        )

        if widget is None:
            return

        try:
            entries = tuple(
                getattr(product, "logs")()
            )
        except Exception as error:
            lines = (
                f"Logs unavailable ({type(error).__name__})",
            )
        else:
            lines_list: list[str] = []

            for entry in entries:
                service = getattr(
                    entry,
                    "service",
                    application_id,
                )
                text = getattr(
                    entry,
                    "text",
                    str(entry),
                )
                lines_list.append(
                    f"[{service}] {text}"
                )

            lines = tuple(lines_list)

        rendered = "\n".join(lines)

        current = widget.get(
            "1.0",
            "end-1c",
        )

        if current == rendered:
            return

        widget.configure(state="normal")
        widget.delete("1.0", "end")

        if rendered:
            widget.insert(
                "end",
                rendered,
            )

        widget.configure(state="disabled")
        widget.see("end")

    def _ordered_products(self) -> tuple[object, ...]:
        order = {
            "defend": 0,
            "sports": 1,
            "coder": 2,
            "scs": 3,
        }

        return tuple(
            sorted(
                self._products,
                key=lambda product: order.get(
                    getattr(
                        product,
                        "application_id",
                        "",
                    ),
                    99,
                ),
            )
        )

    def _resize_notebook_tabs(self, _event=None) -> None:
        if not hasattr(self, "_notebook"):
            return

        tabs = self._notebook.tabs()

        if not tabs:
            return

        width = max(
            self._notebook.winfo_width(),
            860,
        )

        # ttk tab width is character-based rather than pixel-based.
        # 8 pixels per character is a practical Segoe UI approximation.
        characters = max(
            12,
            int((width / len(tabs)) / 8),
        )

        style = ttk.Style(self.root)

        style.configure(
            "Defend.TNotebook.Tab",
            width=characters,
            anchor="center",
            padding=(6, 7),
        )

    def _build_home_card(
        self,
        parent: ttk.Frame,
        product: object,
        *,
        row: int,
        column: int,
    ) -> None:
        application_id = getattr(
            product,
            "application_id",
            "unknown",
        )

        display_name = self._product_tab_title(
            application_id,
            getattr(
                product,
                "display_name",
                application_id,
            ),
        )

        card = ttk.LabelFrame(
            parent,
            text=display_name,
            padding=12,
        )
        card.grid(
            row=row,
            column=column,
            sticky="nsew",
            padx=6,
            pady=6,
        )
        card.columnconfigure(0, weight=1)

        self._home_cards[application_id] = card

        state = tk.StringVar(
            self.root,
            value="\\u2014",
        )
        text = tk.StringVar(
            self.root,
            value="Waiting for status...",
        )

        self._home_card_states[
            application_id
        ] = state
        self._home_card_text[
            application_id
        ] = text

        ttk.Label(
            card,
            textvariable=state,
            font=("Segoe UI", 11, "bold"),
        ).grid(
            row=0,
            column=0,
            sticky="w",
        )

        ttk.Label(
            card,
            textvariable=text,
            wraplength=330,
            justify="left",
        ).grid(
            row=1,
            column=0,
            sticky="nw",
            pady=(6, 14),
        )

        actions = ttk.Frame(card)
        actions.grid(
            row=2,
            column=0,
            sticky="ew",
        )

        home_buttons: dict[str, ttk.Button] = {}

        for label, action in _PRODUCT_ACTIONS:
            button = ttk.Button(
                actions,
                text=label,
                command=lambda p=product, a=action: (
                    self._product_action(p, a)
                ),
                width=8,
            )
            button.pack(
                side="left",
                padx=(0, 5),
            )
            home_buttons[action] = button

        self._home_buttons[
            application_id
        ] = home_buttons

    def _render_platform_posture(
        self,
        statuses: tuple[ProductStatus, ...],
    ) -> None:
        total = len(statuses)

        healthy_states = {
            "running",
            "ready",
        }

        attention_states = {
            "failed",
            "degraded",
            "unavailable",
            "not configured",
        }

        active = sum(
            status.state in healthy_states
            for status in statuses
        )

        attention = sum(
            status.state in attention_states
            for status in statuses
        )

        stopped = sum(
            status.state == "stopped"
            for status in statuses
        )

        self._platform_posture.set(
            f"Products: {total}     "
            f"Active: {active}     "
            f"Stopped: {stopped}     "
            f"Attention: {attention}"
        )

    def _build(self) -> None:
        outer = ttk.Frame(
            self.root,
            padding=8,
        )
        outer.pack(
            fill="both",
            expand=True,
        )
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        style = ttk.Style(self.root)

        style.configure(
            "Defend.TNotebook",
            tabposition="n",
        )

        style.configure(
            "Defend.TNotebook.Tab",
            anchor="center",
            padding=(6, 7),
        )

        self._notebook = ttk.Notebook(
            outer,
            style="Defend.TNotebook",
        )
        self._notebook.grid(
            row=0,
            column=0,
            sticky="nsew",
        )

        self._notebook.bind(
            "<Configure>",
            self._resize_notebook_tabs,
        )

        # ==========================================================
        # HOME
        # ==========================================================

        home = ttk.Frame(
            self._notebook,
            padding=16,
        )

        self._notebook.add(
            home,
            text="Home",
        )

        home.columnconfigure(0, weight=1)
        home.rowconfigure(2, weight=1)

        header = ttk.Frame(home)
        header.grid(
            row=0,
            column=0,
            sticky="ew",
            pady=(0, 10),
        )
        header.columnconfigure(0, weight=1)

        ttk.Label(
            header,
            text="DEFEND CONTROL CENTER",
            font=("Segoe UI", 18, "bold"),
        ).grid(
            row=0,
            column=0,
            sticky="w",
        )

        ttk.Label(
            header,
            text=(
                "Unified operations console for DEFEND AI, "
                "DEFEND Sports, DEFENDcoder, and SCS AI."
            ),
            font=("Segoe UI", 9),
        ).grid(
            row=1,
            column=0,
            sticky="w",
            pady=(3, 0),
        )

        posture = ttk.LabelFrame(
            home,
            text="Platform posture",
            padding=(12, 8),
        )
        posture.grid(
            row=1,
            column=0,
            sticky="ew",
            pady=(0, 8),
        )

        ttk.Label(
            posture,
            textvariable=self._platform_posture,
            font=("Segoe UI", 10, "bold"),
        ).pack(
            anchor="w",
        )

        cards = ttk.Frame(home)
        cards.grid(
            row=2,
            column=0,
            sticky="nsew",
        )

        cards.columnconfigure(0, weight=1)
        cards.columnconfigure(1, weight=1)
        cards.rowconfigure(0, weight=1)
        cards.rowconfigure(1, weight=1)

        ordered_products = self._ordered_products()

        for index, product in enumerate(
            ordered_products
        ):
            self._build_home_card(
                cards,
                product,
                row=index // 2,
                column=index % 2,
            )

        footer = ttk.LabelFrame(
            home,
            text="Operations",
            padding=10,
        )
        footer.grid(
            row=3,
            column=0,
            sticky="ew",
            pady=(10, 0),
        )

        ttk.Label(
            footer,
            text=(
                "Each product is independently controlled. "
                "Open its tab for identifiers, runtime details, "
                "health information, and isolated logs."
            ),
            wraplength=780,
            justify="left",
        ).pack(
            side="left",
            anchor="w",
        )

        ttk.Button(
            footer,
            text="Setup",
            command=self._setup,
        ).pack(
            side="right",
            padx=(8, 0),
        )

        # ==========================================================
        # PRODUCT TABS
        #
        # Exact requested order:
        # DEFEND AI -> Sports -> DEFENDcoder -> SCS AI
        # ==========================================================

        for product in ordered_products:
            self._build_product_detail_tab(
                self._notebook,
                product,
            )

        # ==========================================================
        # DEFEND AI identity/runtime-specific controls
        # ==========================================================

        defend_tab = self._product_tabs.get(
            "defend"
        )

        if defend_tab is not None:
            identity = ttk.LabelFrame(
                defend_tab,
                text="DEFEND identity runtime",
                padding=8,
            )
            identity.grid(
                row=4,
                column=0,
                sticky="ew",
                pady=(8, 0),
            )

            mode_frame = ttk.Frame(identity)
            mode_frame.pack(
                fill="x",
                pady=(0, 8),
            )

            ttk.Label(
                mode_frame,
                text="Model backend:",
            ).pack(
                side="left",
                padx=(0, 10),
            )

            ttk.Radiobutton(
                mode_frame,
                text="Vast.ai",
                variable=self._mode,
                value="vast",
            ).pack(
                side="left",
                padx=(0, 16),
            )

            ttk.Radiobutton(
                mode_frame,
                text="Local Ollama",
                variable=self._mode,
                value="ollama",
            ).pack(
                side="left",
            )

            identity_actions = ttk.Frame(
                identity
            )
            identity_actions.pack(
                fill="x",
                pady=(0, 8),
            )

            for label, command in (
                ("Start", self._start),
                ("Stop Local", self._stop_local),
                ("Restart", self._restart),
                ("Open DEFEND", self._open_defend),
                (
                    "Stop + Destroy Vast",
                    self._destroy_vast,
                ),
            ):
                ttk.Button(
                    identity_actions,
                    text=label,
                    command=command,
                ).pack(
                    side="left",
                    padx=(0, 6),
                )

            component_frame = ttk.LabelFrame(
                identity,
                text="Components",
                padding=8,
            )
            component_frame.pack(
                fill="x",
                pady=(0, 8),
            )

            for row, (
                name,
                label,
            ) in enumerate(
                _COMPONENT_LABELS.items()
            ):
                ttk.Label(
                    component_frame,
                    text=label,
                ).grid(
                    row=row,
                    column=0,
                    sticky="w",
                )

                ttk.Label(
                    component_frame,
                    textvariable=(
                        self._component_states[name]
                    ),
                ).grid(
                    row=row,
                    column=1,
                    sticky="w",
                    padx=(18, 0),
                )

            vast = ttk.LabelFrame(
                identity,
                text="Current Vast.ai",
                padding=8,
            )
            vast.pack(
                fill="x",
            )

            for row, (
                label,
                variable,
            ) in enumerate(
                (
                    ("GPU", self._vast_gpu),
                    ("GPU RAM", self._vast_ram),
                    (
                        "Reliability",
                        self._vast_reliability,
                    ),
                    (
                        "Instance ID",
                        self._vast_instance,
                    ),
                    (
                        "Provider status",
                        self._vast_status,
                    ),
                    (
                        "Exact hourly price",
                        self._vast_price,
                    ),
                    (
                        "Billing warning",
                        self._vast_billing,
                    ),
                )
            ):
                ttk.Label(
                    vast,
                    text=label,
                ).grid(
                    row=row,
                    column=0,
                    sticky="w",
                )

                ttk.Label(
                    vast,
                    textvariable=variable,
                ).grid(
                    row=row,
                    column=1,
                    sticky="w",
                    padx=(18, 0),
                )

        # Legacy controller log sink. Product logs have their own visible
        # per-product widgets.
        self._log = ScrolledText(
            home,
            height=1,
            state="disabled",
        )
        self._log.grid_remove()

        self.root.after(
            50,
            self._resize_notebook_tabs,
        )

    def _build_products(self, outer: ttk.Frame) -> None:
        products = ttk.LabelFrame(outer, text="Products", padding=8)
        products.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        for row, product in enumerate(self._products):
            application_id = getattr(product, "application_id", "unknown")
            display_name = getattr(product, "display_name", application_id)
            state_var = tk.StringVar(self.root, value="—")
            text_var = tk.StringVar(self.root, value="")
            self._product_states[application_id] = state_var
            self._product_text[application_id] = text_var
            state_label = ttk.Label(products, textvariable=state_var, width=16)
            state_label.grid(row=row, column=0, sticky="w")
            self._product_state_labels[application_id] = state_label
            ttk.Label(products, text=display_name).grid(
                row=row, column=1, sticky="w", padx=(0, 12)
            )
            ttk.Label(products, textvariable=text_var).grid(
                row=row, column=2, sticky="w"
            )
            buttons: dict[str, ttk.Button] = {}
            for column, (label, action) in enumerate(_PRODUCT_ACTIONS):
                button = ttk.Button(
                    products,
                    text=label,
                    command=lambda p=product, a=action: self._product_action(
                        p, a
                    ),
                )
                button.grid(row=row, column=3 + column, padx=(4, 0))
                buttons[action] = button
            self._product_buttons[application_id] = buttons

    def _product_action(self, product: object, action: str) -> None:
        application_id = getattr(product, "application_id", "")
        if application_id == "defend":
            if action == "launch":
                self._start()
            elif action == "stop":
                self._stop_local()
            elif action == "open":
                self._open_defend()
            else:
                self._focus_product_log(
                    application_id
                )
            return
        try:
            if action == "launch":
                self._controller.submit_work(getattr(product, "start"))
            elif action == "stop":
                self._controller.submit_work(getattr(product, "stop"))
            elif action == "open":
                self._controller.submit_work(getattr(product, "open_url"))
            else:
                self._focus_product_log(
                    application_id
                )
        except Exception as error:
            self._show_error(error)

    def _focus_log(self) -> None:
        self._log.see("end")

    def _focus_product_log(
        self,
        application_id: str,
    ) -> None:
        tab = self._product_tabs.get(
            application_id
        )

        if tab is not None:
            self._notebook.select(tab)

        log = self._product_logs.get(
            application_id
        )

        if log is not None:
            log.see("end")
            log.focus_set()

    def _render_products(self) -> None:
        rendered_statuses: list[ProductStatus] = []

        for product in self._products:
            application_id = getattr(product, "application_id", "")
            state_var = self._product_states.get(
                application_id
            )

            try:
                status = product.status()
            except Exception as error:
                status = ProductStatus(
                    application_id,
                    getattr(product, "display_name", application_id),
                    "failed",
                    f"Status unavailable ({type(error).__name__})",
                )
            rendered_statuses.append(status)

            if state_var is not None:
                state_var.set(status.state)

            legacy_text = self._product_text.get(
                application_id
            )
            if legacy_text is not None:
                legacy_text.set(
                    status.status_text
                )

            home_state = self._home_card_states.get(
                application_id
            )
            if home_state is not None:
                home_state.set(status.state)

            home_text = self._home_card_text.get(
                application_id
            )
            if home_text is not None:
                home_text.set(status.status_text)

            tab_state = self._product_tab_states.get(
                application_id
            )
            if tab_state is not None:
                tab_state.set(status.state)

            tab_text = self._product_tab_text.get(
                application_id
            )
            if tab_text is not None:
                tab_text.set(status.status_text)

            self._render_product_details(
                application_id,
                status,
            )
            self._render_product_logs(
                product,
            )

            state_label = self._product_state_labels.get(application_id)
            if state_label is not None:
                state_label.configure(
                    foreground=_STATE_COLORS.get(status.state, "gray")
                )
            availability = (
                ("launch", status.launch_available),
                ("stop", status.stop_available),
                ("open", status.open_available),
                ("logs", status.logs_available),
            )

            button_groups = (
                self._product_buttons.get(
                    application_id,
                    {},
                ),
                self._home_buttons.get(
                    application_id,
                    {},
                ),
                self._tab_buttons.get(
                    application_id,
                    {},
                ),
            )

            for action, available in availability:
                for buttons in button_groups:
                    button = buttons.get(action)

                    if button is not None:
                        button.configure(
                            state=(
                                "normal"
                                if available
                                else "disabled"
                            )
                        )

        self._render_platform_posture(
            tuple(rendered_statuses)
        )

    def _show_error(self, error: BaseException) -> None:
        messagebox.showerror(
            "DEFEND Control Center",
            f"The action could not be queued ({type(error).__name__}).",
            parent=self.root,
        )

    def _start(self) -> None:
        mode = self._mode.get()
        if mode not in ("vast", "ollama"):
            messagebox.showwarning(
                "Choose a model backend",
                "Select Vast.ai or Local Ollama for this launch.",
                parent=self.root,
            )
            return
        try:
            self._last_confirmation_signature = None
            state = self._controller.start(mode)
            self._mode.set("")
            self._render(state)
        except Exception as error:
            self._show_error(error)

    def _stop_local(self) -> None:
        try:
            self._render(self._controller.stop_local())
        except Exception as error:
            self._show_error(error)

    def _restart(self) -> None:
        try:
            self._render(self._controller.restart())
        except Exception as error:
            self._show_error(error)

    def _open_defend(self) -> None:
        try:
            self._controller.open_defend(self._public_origin)
        except Exception as error:
            self._show_error(error)

    def _setup(self) -> None:
        state = self._controller.poll_state()
        if state.services_running:
            messagebox.showwarning(
                "Stop local services first",
                "Setup can be changed after local services are stopped.",
                parent=self.root,
            )
            return
        self._open_setup()

    def _destroy_vast(self) -> None:
        state = self._controller.poll_state()
        instance_id = state.vast_instance_id
        if instance_id is None:
            messagebox.showinfo(
                "No Vast.ai instance",
                "There is no active Vast.ai instance to destroy.",
                parent=self.root,
            )
            return
        entered = simpledialog.askstring(
            "Stop + Destroy Vast",
            (
                f"This stops local services and destroys billable instance {instance_id}.\n"
                f"{state.vast_billing_warning or 'Billing may remain active until destruction.'}\n"
                f"Enter the exact instance ID {instance_id} to continue."
            ),
            parent=self.root,
        )
        if entered != str(instance_id):
            return
        try:
            self._render(
                self._controller.stop_and_destroy_vast(
                    confirmed_instance_id=instance_id
                )
            )
        except (ConfirmationRequired, RuntimeError) as error:
            self._show_error(error)

    def _poll(self) -> None:
        try:
            state = self._controller.poll_state()
            self._render(state)
            self._handle_confirmation(state)
        except Exception as error:
            self._show_error(error)
            self.root.after(_POLL_MILLISECONDS, self._poll)
            return
        if self._closing_after_stop and state.state in ("stopped", "failed"):
            if state.vast_instance_id is not None:
                self._closing_after_stop = False
                self.root.iconify()
                self.root.after(_POLL_MILLISECONDS, self._poll)
                return
            self._begin_exit_cleanup()
            return
        self.root.after(_POLL_MILLISECONDS, self._poll)

    def _handle_confirmation(self, state: UIState) -> None:
        kind = state.pending_confirmation
        if kind == "price":
            signature = (
                kind,
                state.vast_offer_id,
                state.vast_hourly_price,
                state.vast_storage_cost_per_gb_month,
                state.vast_storage_total_hourly,
                state.vast_disk_gb,
            )
        elif kind == "fingerprint":
            signature = (
                kind,
                state.vast_instance_id,
                state.pending_fingerprint,
            )
        elif kind == "instance_selection":
            signature = (
                kind,
                tuple(
                    (
                        candidate.instance_id,
                        candidate.actual_status,
                        candidate.gpu_name,
                        candidate.gpu_ram_mb,
                        str(candidate.dph_total),
                    )
                    for candidate in state.vast_candidates
                ),
            )
        elif kind == "instance_restart":
            signature = (
                kind,
                state.vast_instance_id,
                state.vast_actual_status,
                state.vast_hourly_price,
            )
        elif kind == "instance_replace":
            offer = state.vast_replacement_offer
            signature = (
                kind,
                state.vast_instance_id,
                state.vast_actual_status,
                (
                    None
                    if offer is None
                    else (
                        offer.offer_id,
                        offer.gpu_name,
                        offer.gpu_ram_mb,
                        str(offer.reliability),
                        str(offer.dph_total),
                    )
                ),
            )
        else:
            self._last_confirmation_signature = None
            return
        if signature == self._last_confirmation_signature:
            return
        self._last_confirmation_signature = signature

        if kind == "instance_selection":
            if not state.vast_candidates:
                return
            choices = "\n".join(
                (
                    f"Instance {candidate.instance_id} | "
                    f"{candidate.actual_status or 'unknown'} | "
                    f"{candidate.gpu_name} | {candidate.gpu_ram_mb} MB | "
                    f"${candidate.dph_total}/hour"
                )
                for candidate in state.vast_candidates
            )
            selected = simpledialog.askinteger(
                "Choose an existing DEFEND Vast.ai pod",
                (
                    "DEFEND found existing pods and will not rent another.\n\n"
                    f"{choices}\n\n"
                    "Enter the exact instance ID to reconnect or restart:"
                ),
                parent=self.root,
                minvalue=1,
            )
            if selected is None:
                try:
                    self._render(
                        self._controller.decline_vast_instance_action()
                    )
                except Exception as error:
                    self._show_error(error)
                return
            if selected not in {
                candidate.instance_id for candidate in state.vast_candidates
            }:
                messagebox.showwarning(
                    "Choose a listed DEFEND pod",
                    "The instance ID must exactly match one of the listed pods.",
                    parent=self.root,
                )
                try:
                    self._render(
                        self._controller.decline_vast_instance_action()
                    )
                except Exception as error:
                    self._show_error(error)
                return
            try:
                self._render(self._controller.select_vast_instance(selected))
            except Exception as error:
                self._show_error(error)
            return

        if kind == "instance_restart":
            if (
                state.vast_instance_id is None
                or state.vast_gpu is None
                or state.vast_gpu_ram_mb is None
                or state.vast_actual_status is None
                or state.vast_hourly_price is None
            ):
                return
            storage = state.vast_billing_warning or (
                "Storage billing may remain active while this instance is stopped."
            )
            confirmed = messagebox.askyesno(
                "Restart BILLABLE DEFEND Vast.ai instance",
                (
                    "Restart this existing DEFEND pod and resume compute billing?\n\n"
                    f"Instance ID: {state.vast_instance_id}\n"
                    f"Provider status: {state.vast_actual_status}\n"
                    f"GPU: {state.vast_gpu}\n"
                    f"GPU RAM: {state.vast_gpu_ram_mb} MB\n"
                    f"Exact price: ${state.vast_hourly_price}/hour\n\n"
                    f"{storage}\n"
                    "Compute charges resume only after you confirm."
                ),
                parent=self.root,
            )
            if not confirmed:
                try:
                    self._render(
                        self._controller.decline_vast_instance_action()
                    )
                except Exception as error:
                    self._show_error(error)
                return
            try:
                self._render(
                    self._controller.confirm_vast_restart(
                        state.vast_instance_id, state.vast_hourly_price
                    )
                )
            except Exception as error:
                self._show_error(error)
            return

        if kind == "instance_replace":
            offer = state.vast_replacement_offer
            if (
                state.vast_instance_id is None
                or state.vast_actual_status is None
                or offer is None
                or state.vast_disk_gb is None
            ):
                return
            storage_warning = state.vast_billing_warning or (
                "Storage billing may remain active until the old instance is "
                "destroyed."
            )
            storage_details = ""
            if offer.storage_cost_per_gb_month is not None:
                storage_details += (
                    "\nStorage rate: "
                    f"${offer.storage_cost_per_gb_month}/GB/month"
                )
            if offer.storage_total_hourly is not None:
                storage_details += (
                    "\nStorage total: "
                    f"${offer.storage_total_hourly}/hour"
                )
            confirmed = messagebox.askyesno(
                "Replace unavailable BILLABLE Vast.ai instance",
                (
                    "The existing on-demand pod has remained scheduled for "
                    "30 seconds.\n\n"
                    f"Old instance ID: {state.vast_instance_id}\n"
                    f"Old provider status: {state.vast_actual_status}\n"
                    f"{storage_warning}\n\n"
                    "Confirmed on-demand replacement:\n"
                    f"Offer ID: {offer.offer_id}\n"
                    f"GPU: {offer.gpu_name}\n"
                    f"GPU RAM: {offer.gpu_ram_mb} MB\n"
                    f"Reliability: {offer.reliability}\n"
                    f"Exact price: ${offer.dph_total}/hour\n"
                    f"Disk: {state.vast_disk_gb} GB"
                    f"{storage_details}\n\n"
                    "The old instance will be destroyed before DEFEND attempts "
                    "this one replacement. If the offer becomes unavailable, "
                    "DEFEND will stop and will not rent a different offer."
                ),
                parent=self.root,
            )
            if not confirmed:
                try:
                    self._render(
                        self._controller.decline_vast_instance_action()
                    )
                except Exception as error:
                    self._show_error(error)
                return
            try:
                self._render(
                    self._controller.confirm_vast_replacement(
                        state.vast_instance_id,
                        offer.offer_id,
                        str(offer.dph_total),
                    )
                )
            except Exception as error:
                self._show_error(error)
            return

        if kind == "price":
            if (
                state.vast_offer_id is None
                or state.vast_hourly_price is None
                or state.vast_gpu is None
                or state.vast_gpu_ram_mb is None
                or state.vast_reliability is None
                or state.vast_disk_gb is None
            ):
                return
            storage_price = ""
            if state.vast_storage_cost_per_gb_month is not None:
                storage_price += (
                    "Storage rate: "
                    f"${state.vast_storage_cost_per_gb_month}/GB/month\n"
                )
            if state.vast_storage_total_hourly is not None:
                storage_price += (
                    "Storage total: "
                    f"${state.vast_storage_total_hourly}/hour\n"
                )
            confirmed = messagebox.askyesno(
                "BILLABLE Vast.ai instance",
                (
                    "Create this BILLABLE on-demand Vast.ai instance?\n\n"
                    f"Offer ID: {state.vast_offer_id}\n"
                    f"GPU: {state.vast_gpu}\n"
                    f"GPU RAM: {state.vast_gpu_ram_mb} MB\n"
                    f"Reliability: {state.vast_reliability}\n"
                    f"Exact price: ${state.vast_hourly_price}/hour\n\n"
                    f"Disk: {state.vast_disk_gb} GB\n"
                    f"{storage_price}"
                    "Launch body: image=vllm/vllm-openai:v0.10.0, "
                    "runtype=ssh_proxy, target_state=running\n\n"
                    "Charges begin only after you confirm."
                ),
                parent=self.root,
            )
            if not confirmed:
                return
            try:
                self._render(
                    self._controller.confirm_vast_offer(
                        state.vast_offer_id, state.vast_hourly_price
                    )
                )
            except Exception as error:
                self._show_error(error)
            return

        if state.vast_instance_id is None or state.pending_fingerprint is None:
            return
        billing = state.vast_billing_warning or (
            "Compute billing may remain active until this instance is destroyed."
        )
        confirmed = messagebox.askyesno(
            "Confirm Vast.ai SSH host",
            (
                f"Instance ID: {state.vast_instance_id}\n"
                f"SSH fingerprint: {state.pending_fingerprint}\n\n"
                f"{billing}\n\n"
                "Confirm only if this fingerprint matches the expected Vast host."
            ),
            parent=self.root,
        )
        if not confirmed:
            return
        try:
            self._render(
                self._controller.confirm_vast_fingerprint(
                    state.vast_instance_id, state.pending_fingerprint
                )
            )
        except Exception as error:
            self._show_error(error)

    def _begin_exit_cleanup(self) -> None:
        if self._exit_future is not None:
            return
        try:
            self._exit_future = self._submit_exit_cleanup()
        except Exception as error:
            self._show_error(error)
            self._closing_after_stop = False
            self.root.after(_POLL_MILLISECONDS, self._poll)
            return
        self.root.after(_POLL_MILLISECONDS, self._poll_exit_cleanup)

    def _poll_exit_cleanup(self) -> None:
        future = self._exit_future
        done = getattr(future, "done", None)
        if not callable(done) or not done():
            self.root.after(_POLL_MILLISECONDS, self._poll_exit_cleanup)
            return
        try:
            future.result()
        except Exception as error:
            self._exit_future = None
            self._closing_after_stop = False
            self._show_error(error)
            self.root.after(_POLL_MILLISECONDS, self._poll)
            return
        self._controller.shutdown()
        self._destroy_window()

    def _render_coder(self) -> None:
        status = self._coder.status()
        public = status.as_public_dict()
        self._coder_state.set(str(public.get("state") or "—"))
        self._coder_alias.set(str(public.get("alias") or "—"))
        self._coder_model.set(str(public.get("model_repo") or "—"))
        revision = str(public.get("model_revision") or "")
        self._coder_revision.set(revision[:12] + "…" if len(revision) > 12 else revision or "—")
        self._coder_endpoint.set(str(public.get("endpoint") or "—"))
        iid = public.get("instance_id")
        self._coder_instance.set(str(iid) if iid is not None else "—")
        self._coder_provider_run.set(str(public.get("provider_run_id") or "—"))
        price = public.get("hourly_price")
        self._coder_price.set(f"${price}/hour" if price else "—")
        budget = public.get("session_budget_usd")
        self._coder_budget.set(f"${budget}" if budget else "—")
        self._coder_message.set(str(public.get("message") or "—"))

    def _render(self, state: UIState) -> None:
        message = f"State: {state.state}"
        if state.message:
            message += f" — {state.message}"
        self._state.set(message)
        for component in state.components:
            variable = self._component_states.get(component.name)
            if variable is not None:
                variable.set(component.state)
        self._vast_gpu.set(state.vast_gpu or "—")
        self._vast_instance.set(
            str(state.vast_instance_id) if state.vast_instance_id is not None else "—"
        )
        self._vast_price.set(
            f"${state.vast_hourly_price}/hour"
            if state.vast_hourly_price is not None
            else "—"
        )
        self._vast_ram.set(
            f"{state.vast_gpu_ram_mb} MB"
            if state.vast_gpu_ram_mb is not None
            else "—"
        )
        self._vast_reliability.set(state.vast_reliability or "—")
        self._vast_status.set(state.vast_actual_status or "—")
        self._vast_billing.set(
            state.vast_billing_warning or "No active Vast billing"
        )
        self._render_coder()
        if state.logs != self._last_log_render:
            self._log.configure(state="normal")
            self._log.delete("1.0", "end")
            self._log.insert(
                "end",
                "\n".join(f"[{entry.service}] {entry.text}" for entry in state.logs),
            )
            self._log.configure(state="disabled")
            self._log.see("end")
            self._last_log_render = state.logs
        self._render_products()

    def _on_close(self) -> None:
        state = self._controller.poll_state()
        if not state.services_running:
            self._begin_exit_cleanup()
            return
        leave_running = messagebox.askyesnocancel(
            "Close DEFEND Control Center",
            (
                "Leave services running?\n\n"
                "Yes: keep the Control Center minimized so owned services remain running.\n"
                "No: stop local services and close. A Vast.ai instance is never destroyed here."
            ),
            parent=self.root,
        )
        if leave_running is None:
            return
        if leave_running:
            self.root.iconify()
            return
        if state.vast_instance_id is not None:
            messagebox.showwarning(
                "Vast.ai instance remains active",
                (
                    "Local services will stop, but the Control Center will stay "
                    "minimized so the billable Vast.ai instance remains visible "
                    "until you explicitly destroy it."
                ),
                parent=self.root,
            )
        self._closing_after_stop = True
        self._controller.stop_local()
