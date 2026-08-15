from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText

from .coder_m0 import CoderM0Service, LocalFakeCoderBackend
from .controller import ConfirmationRequired, ControlController, UIState
from .settings import ControlSettings


_POLL_MILLISECONDS = 250
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
_SECRET_FIELDS = (
    ("VAST_API_KEY", "Vast.ai API key"),
    ("HF_TOKEN", "Hugging Face token"),
    ("VLLM_API_KEY", "vLLM API key"),
    ("DEFEND_OWNER_USER", "Owner username"),
    ("DEFEND_OWNER_EMAIL", "Owner email"),
    ("DEFEND_OWNER_PASS", "Owner password"),
    ("DEFEND_VISITOR_HMAC_KEY", "Visitor HMAC key"),
    ("DEFEND_GMAIL_SMTP_USERNAME", "Gmail SMTP username"),
    ("DEFEND_GMAIL_APP_PASSWORD", "Gmail app password"),
    ("TAVILY_API_KEY", "Search API key (optional)"),
)


class SetupDialog(tk.Toplevel):
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
        self._settings = settings
        self._submit_save = submit_save
        self._on_saved = on_saved
        self._setting_values: dict[str, tk.StringVar] = {}
        self._secret_values: dict[str, tk.StringVar] = {}

        frame = ttk.Frame(self, padding=12)
        frame.grid(sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

        row = 0
        ttk.Label(frame, text="Non-secret settings").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(0, 6)
        )
        row += 1
        raw_settings = asdict(settings)
        for name, label in _SETTING_FIELDS:
            value = str(raw_settings[name])
            variable = tk.StringVar(self, value=value)
            self._setting_values[name] = variable
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w")
            ttk.Entry(frame, textvariable=variable, width=64).grid(
                row=row, column=1, sticky="ew", pady=2
            )
            row += 1

        ttk.Separator(frame).grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=8
        )
        row += 1
        ttk.Label(
            frame,
            text=(
                "Secrets (leave blank to retain the current value). DPAPI protects "
                "files at rest, not a compromised signed-in Windows account."
            ),
            wraplength=620,
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 6))
        row += 1
        for name, label in _SECRET_FIELDS:
            variable = tk.StringVar(self, value="")
            self._secret_values[name] = variable
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w")
            ttk.Entry(frame, textvariable=variable, show="*", width=64).grid(
                row=row, column=1, sticky="ew", pady=2
            )
            row += 1

        buttons = ttk.Frame(frame)
        buttons.grid(row=row, column=0, columnspan=2, sticky="e", pady=(10, 0))
        self._cancel_button = ttk.Button(
            buttons, text="Cancel", command=self.destroy
        )
        self._cancel_button.pack(side="right", padx=(6, 0))
        self._save_button = ttk.Button(buttons, text="Save", command=self._save)
        self._save_button.pack(side="right")
        self.protocol("WM_DELETE_WINDOW", self.destroy)
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
    """Four-product platform shell: DEFEND AI | Sports | SCS | DEFENDcoder."""

    def __init__(
        self,
        root: tk.Tk,
        controller: ControlController,
        *,
        public_origin: str,
        open_setup: Callable[[], None],
        submit_exit_cleanup: Callable[[], object],
        destroy_window: Callable[[], None] | None = None,
        coder_service: CoderM0Service | None = None,
    ) -> None:
        self.root = root
        self._controller = controller
        self._public_origin = public_origin
        self._open_setup = open_setup
        self._submit_exit_cleanup = submit_exit_cleanup
        self._destroy_window = destroy_window or root.destroy
        self._coder = coder_service or CoderM0Service(
            backend=LocalFakeCoderBackend()
        )
        self._closing_after_stop = False
        self._exit_future: object | None = None
        self._last_log_render: tuple[object, ...] | None = None
        self._last_confirmation_signature: tuple[object, ...] | None = None
        self._mode = tk.StringVar(root, value="vast")
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

        # Product row status lines
        self._prod_ai = tk.StringVar(root, value="○ OFFLINE")
        self._prod_sports = tk.StringVar(root, value="○ OFFLINE — not wired")
        self._prod_scs = tk.StringVar(root, value="○ OFFLINE — not wired")
        self._prod_coder = tk.StringVar(root, value="○ OFFLINE")
        self._coder_detail = tk.StringVar(root, value="")

        root.title("DEFEND Control Center")
        root.minsize(780, 780)
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

    def set_coder_service(self, coder_service: CoderM0Service) -> None:
        self._coder = coder_service
        self._render_coder_product()

    def _product_row(
        self,
        parent: ttk.Frame,
        *,
        title: str,
        status_var: tk.StringVar,
        launch: Callable[[], None] | None,
        stop: Callable[[], None] | None,
        open_cmd: Callable[[], None] | None,
        extra: str | None = None,
    ) -> None:
        frame = ttk.LabelFrame(parent, text=title, padding=8)
        frame.pack(fill="x", pady=4)
        top = ttk.Frame(frame)
        top.pack(fill="x")
        ttk.Label(top, textvariable=status_var, width=36).pack(side="left")
        btn = ttk.Frame(top)
        btn.pack(side="right")
        for label, command in (
            ("Launch", launch),
            ("Stop", stop),
            ("Open", open_cmd),
            ("Logs", None),
        ):
            state = "normal" if command is not None else "disabled"
            ttk.Button(
                btn,
                text=label,
                command=command if command is not None else (lambda: None),
                state=state,
            ).pack(side="left", padx=2)
        if extra:
            ttk.Label(frame, text=extra, foreground="#555").pack(anchor="w", pady=(4, 0))

    def _build(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(4, weight=1)

        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(
            header,
            text="DEFEND Platform — Control Center",
            font=("", 12, "bold"),
        ).pack(side="left")
        ttk.Button(header, text="Setup", command=self._setup).pack(side="right")

        products = ttk.Frame(outer)
        products.grid(row=1, column=0, sticky="ew", pady=8)

        self._product_row(
            products,
            title="DEFEND AI — identity / knowledge / RAG",
            status_var=self._prod_ai,
            launch=self._start_ai_prompt,
            stop=self._stop_local,
            open_cmd=self._open_defend,
            extra="Origin: ai.defend-network.org · Start uses Vast or Local backend below",
        )
        self._product_row(
            products,
            title="DEFEND Sports — markets / TT intelligence / arbitrage",
            status_var=self._prod_sports,
            launch=None,
            stop=None,
            open_cmd=None,
            extra="Origin: defendsports.defend-network.org (reserved) · owner-only V1",
        )
        self._product_row(
            products,
            title="Sunshine Climate Solutions — ops / CRM",
            status_var=self._prod_scs,
            launch=None,
            stop=None,
            open_cmd=None,
            extra="Origin: ai.sunshineclimatesolutions.com (reserved)",
        )
        self._product_row(
            products,
            title="DEFENDcoder — software engineering platform",
            status_var=self._prod_coder,
            launch=None,
            stop=None,
            open_cmd=None,
            extra="Origin: defendcoder.defend-network.org (reserved) · observation only",
        )
        ttk.Label(products, textvariable=self._coder_detail).pack(anchor="w")

        backend = ttk.LabelFrame(
            outer, text="DEFEND AI launch backend (identity stack)", padding=8
        )
        backend.grid(row=2, column=0, sticky="ew")
        ttk.Radiobutton(
            backend, text="Vast.ai", variable=self._mode, value="vast"
        ).pack(side="left", padx=(0, 16))
        ttk.Radiobutton(
            backend, text="Local Ollama", variable=self._mode, value="ollama"
        ).pack(side="left")
        ttk.Button(
            backend, text="Restart AI", command=self._restart
        ).pack(side="left", padx=12)
        ttk.Button(
            backend, text="Stop + Destroy Vast (AI)", command=self._destroy_vast
        ).pack(side="left")

        detail = ttk.Frame(outer)
        detail.grid(row=3, column=0, sticky="ew", pady=8)
        detail.columnconfigure(0, weight=1)
        detail.columnconfigure(1, weight=1)

        comps = ttk.LabelFrame(detail, text="AI stack components", padding=6)
        comps.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        for row, (name, label) in enumerate(_COMPONENT_LABELS.items()):
            ttk.Label(comps, text=label).grid(row=row, column=0, sticky="w")
            ttk.Label(comps, textvariable=self._component_states[name]).grid(
                row=row, column=1, sticky="w", padx=(12, 0)
            )

        vast = ttk.LabelFrame(detail, text="AI Vast instance", padding=6)
        vast.grid(row=0, column=1, sticky="nsew")
        for row, (label, variable) in enumerate(
            (
                ("GPU", self._vast_gpu),
                ("GPU RAM", self._vast_ram),
                ("Reliability", self._vast_reliability),
                ("Instance ID", self._vast_instance),
                ("Status", self._vast_status),
                ("$/hour", self._vast_price),
                ("Billing", self._vast_billing),
            )
        ):
            ttk.Label(vast, text=label).grid(row=row, column=0, sticky="w")
            ttk.Label(vast, textvariable=variable).grid(
                row=row, column=1, sticky="w", padx=(12, 0)
            )

        ttk.Label(outer, textvariable=self._state).grid(
            row=4, column=0, sticky="w"
        )

        log_frame = ttk.LabelFrame(outer, text="Bounded service log", padding=6)
        log_frame.grid(row=5, column=0, sticky="nsew", pady=(6, 0))
        outer.rowconfigure(5, weight=1)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self._log = ScrolledText(log_frame, height=10, wrap="word", state="disabled")
        self._log.grid(row=0, column=0, sticky="nsew")

    def _show_error(self, error: BaseException) -> None:
        messagebox.showerror(
            "DEFEND Control Center",
            f"The action could not be queued ({type(error).__name__}).",
            parent=self.root,
        )

    def _start_ai_prompt(self) -> None:
        mode = self._mode.get()
        if mode not in ("vast", "ollama"):
            messagebox.showwarning(
                "Choose a model backend",
                "Select Vast.ai or Local Ollama under DEFEND AI launch backend.",
                parent=self.root,
            )
            return
        try:
            self._last_confirmation_signature = None
            state = self._controller.start(mode)
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
                    "runtype=ssh_direc ssh_proxy, target_state=running\n\n"
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

    def _render_coder_product(self) -> None:
        status = self._coder.status()
        public = status.as_public_dict()
        state = str(public.get("state") or "stopped")
        if state == "ready":
            self._prod_coder.set("● ONLINE")
        elif state in ("starting", "provisioning", "validating"):
            self._prod_coder.set(f"◌ {state.upper()}")
        else:
            self._prod_coder.set("○ OFFLINE")
        rev = str(public.get("model_revision") or "")[:12]
        self._coder_detail.set(
            f"  alias={public.get('alias')}  model={public.get('model_repo')}  "
            f"rev={rev}…  budget=${public.get('session_budget_usd')}"
        )

    def _render(self, state: UIState) -> None:
        message = f"Platform state: {state.state}"
        if state.message:
            message += f" — {state.message}"
        self._state.set(message)

        if state.state == "ready":
            self._prod_ai.set("● ONLINE")
        elif state.state in ("starting", "provisioning", "validating"):
            self._prod_ai.set(f"◌ {state.state.upper()}")
        elif state.state == "degraded":
            self._prod_ai.set("● DEGRADED")
        else:
            self._prod_ai.set("○ OFFLINE")

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
        self._render_coder_product()

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
