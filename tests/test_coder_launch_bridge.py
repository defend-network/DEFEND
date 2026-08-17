"""DEFENDcoder NEXT launch bridge behavioral tests (E1-E13).

Fake supervisor + recording backend + real CoderControlPlane and
CoderService: no network, no billing, no Tk.
"""

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import tempfile

import pytest

from defend_control.coder_control_plane import (
    ActiveCoderEndpoint,
    CoderControlPlane,
    CoderNoQualifyingOffer,
    CoderProvisionBlocked,
)
from defend_control.coder_provisioning import (
    CoderProvisionFailure,
    format_elapsed,
)
from defend_control.coder_vast_backend import (
    CoderVastBackendError,
    PROVIDER_ERROR_CATEGORIES,
)
from defend_control.products import (
    CoderService,
    ProductsSettings,
    coder_approval_ready,
    coder_plan_rows,
)
from defend_control.types import VastOffer

from test_coder_control_plane import (
    RecordingBackend,
    _QUALIFYING_OFFERS,
)

_OVER_BUDGET_OFFER = VastOffer(
    900,
    "H100 SXM 80GB",
    81920,
    Decimal("5.25"),
    Decimal("0.99"),
)


class NoOfferBackend(RecordingBackend):
    def __init__(self) -> None:
        super().__init__(offers=())

    def search_offers_for(self, model, profile, *, launch_runtype=None):
        del model, profile, launch_runtype
        return self.offers


class OverBudgetBackend(RecordingBackend):
    def __init__(self) -> None:
        super().__init__(offers=(_OVER_BUDGET_OFFER,))


class _FakeLogs:
    def __init__(self) -> None:
        self.known_secrets: list[str] = []

    def add_known_secrets(self, secrets: list[str]) -> None:
        self.known_secrets.extend(secrets)


class FakeSupervisor:
    def __init__(self, running: tuple[str, ...] = ()) -> None:
        self.processes = {
            name: {"running": True} for name in running
        }
        self.logs = _FakeLogs()

    def snapshot(self):
        return [
            SimpleNamespace(name=name, running=info["running"])
            for name, info in self.processes.items()
        ]

    def start(self, spec) -> bool:
        self.processes[spec.name] = {"running": True}
        return True

    def stop(self, name: str) -> bool:
        info = self.processes.get(name)
        if info is not None:
            info["running"] = False
        return True


class FailingBackend(RecordingBackend):
    def __init__(
        self,
        *,
        message: str = "provisioning exploded",
        destroys_owned_instance: bool = False,
        category: str = "provider",
        failure=None,
        stop_fails: bool = False,
    ) -> None:
        super().__init__()
        self._message = message
        self.destroyed_owned_instance = destroys_owned_instance
        self._category = category
        self.failure = failure
        self.last_provision_failure = failure
        self.stop_fails = stop_fails

    def start(self, model, *, local_port, session_budget_usd, offer=None, profile=None, launch_runtype=None):
        del launch_runtype
        if self.destroyed_owned_instance:
            self.destroyed_owned_instance = True
        raise CoderVastBackendError(
            self._message,
            category=self._category,
            phase=(
                self.failure.phase if self.failure is not None else None
            ),
            failure=self.failure,
        )

    def stop(self, *, instance_id, provider_run_id, destroy):
        self.stops.append((instance_id, provider_run_id, destroy))
        if self.stop_fails:
            raise CoderVastBackendError(
                "provider refused destroy",
                category="provider",
            )
        return {
            "state": "stopped",
            "message": "recording backend stopped",
            "instance_id": instance_id,
            "provider_run_id": provider_run_id,
        }


def _failure(
    phase: str = "model_load",
    *,
    message: str = "vllm process died during model load",
    instance_id: int = 555901,
    cleanup: str = "destroyed",
    rate: str = "1.10",
) -> "CoderProvisionFailure":
    from decimal import Decimal as _Decimal

    return CoderProvisionFailure(
        phase=phase,
        exception_type="CoderVastBackendError",
        sanitized_message=message,
        instance_id=instance_id,
        gpu_name="A100 SXM4",
        approved_hourly_rate=_Decimal(rate),
        elapsed_seconds=247.0,
        endpoint_state="ready",
        ssh_state="ready",
        bootstrap_state="model_load",
        vllm_state="model_load",
        readiness_state="not_ready",
        cleanup_state=cleanup,
    )


class SmokeFailureBackend(RecordingBackend):
    def __init__(self) -> None:
        super().__init__(smoke_ok=False)
        self.last_provision_failure: CoderProvisionFailure | None = None

    def smoke(self, endpoint: str, model: CoderModelRef) -> dict[str, object]:
        self.smokes.append((endpoint, model.alias))
        self.last_provision_failure = CoderProvisionFailure(
            phase="openai_smoke",
            exception_type="CoderSmokeFailure",
            sanitized_message="model did not answer /v1/models",
            instance_id=555002,
            gpu_name="A100 SXM4",
            approved_hourly_rate=Decimal("1.10"),
            elapsed_seconds=0.0,
            endpoint_state="ready",
            ssh_state="ready",
            bootstrap_state="ready",
            vllm_state="ready",
            readiness_state="model did not answer /v1/models",
            cleanup_state="unknown",
        )
        return {
            "ok": False,
            "latency_ms": 4,
            "detail": "model did not answer /v1/models",
        }


def _hermetic_repository() -> Path:
    """Standalone web build tree so CoderService can prepare/start coder:web
    without depending on a real `npm run build` output."""
    repository = Path(tempfile.mkdtemp(prefix="coder-bridge-repo-"))
    ui = repository / "defendcoder-ui"
    standalone = ui / ".next" / "standalone"
    standalone.mkdir(parents=True)
    (standalone / "server.js").write_text("")
    (ui / ".next" / "static").mkdir(parents=True)
    (ui / "public").mkdir(parents=True)
    (ui / "public" / "asset.txt").write_text("x")
    return repository


def _service(
    backend,
    *,
    supervisor: FakeSupervisor | None = None,
    settings: ProductsSettings | None = None,
) -> tuple[CoderService, CoderControlPlane, FakeSupervisor]:
    plane = CoderControlPlane(
        backend=backend,  # type: ignore[arg-type]
        token_provider=lambda: "hf_fake_token",
        port_available=lambda port: True,
    )
    supervisor = supervisor or FakeSupervisor()
    service = CoderService(
        settings or ProductsSettings(
            coder_database_url="postgresql://user:pass@localhost/coder_test"
        ),
        supervisor=supervisor,
        repository=_hermetic_repository(),
        python_executable="python",
        plane=plane,
    )
    plane.lifecycle_log = service.lifecycle_emit
    return service, plane, supervisor


def _ready_endpoint(alias: str, *, hourly: str = "1.10") -> ActiveCoderEndpoint:
    return ActiveCoderEndpoint(
        alias=alias,
        provider="recording",
        endpoint=f"http://127.0.0.1:8003/v1",
        state="ready",
        provisioned_at=__import__(
            "datetime"
        ).datetime(2026, 8, 14, tzinfo=__import__("datetime").timezone.utc),
        model_ready_at=None,
        last_used_at=__import__(
            "datetime"
        ).datetime(2026, 8, 14, tzinfo=__import__("datetime").timezone.utc),
        instance_id=555901,
        provider_run_id="vast-555901",
        gpu_type="A100 SXM4",
        hourly_price=Decimal(hourly),
    )


class TestLaunchRequiresExplicitApproval:
    def test_launch_no_runtime_returns_approval_required_zero_creates(self):
        backend = RecordingBackend()
        service, plane, supervisor = _service(backend)

        status = service.start()

        assert status.state == "approval_required"
        assert backend.starts == []
        assert service.pending_plan() is not None
        assert "coder:api" not in supervisor.processes
        assert "coder:web" not in supervisor.processes

    def test_cancel_after_launch_makes_zero_creates(self):
        backend = RecordingBackend()
        service, plane, supervisor = _service(backend)

        service.start()
        status = service.cancel()

        assert status.state == "stopped"
        assert backend.starts == []
        assert service.pending_plan() is None

    def test_approve_provisions_exactly_once_then_runs_local(self):
        backend = RecordingBackend()
        service, plane, supervisor = _service(backend)

        service.start()
        status = service.approve()

        assert status.state == "running"
        assert len(backend.starts) == 1
        assert len(backend.smokes) == 1
        assert supervisor.processes["coder:api"]["running"] is True
        assert supervisor.processes["coder:web"]["running"] is True


class TestApprovalBinding:
    def test_mutated_plan_rejected_and_never_provisioned(self):
        backend = RecordingBackend()
        service, plane, supervisor = _service(backend)

        service.start()
        prepared = service.pending_plan()
        plan = __import__("dataclasses").replace(
            prepared.plan,
            launch_runtype="ssh_direct",
        )
        prepared = __import__("dataclasses").replace(
            prepared,
            plan=plan,
        )
        service._prepared = prepared  # mutated before approve

        status = service.approve()

        assert status.state == "failed"
        assert backend.starts == []
        assert "no longer matches" in (status.status_text or "")

    def test_over_budget_offer_cannot_be_approved(self):
        backend = OverBudgetBackend()
        service, plane, supervisor = _service(backend)

        service.start()
        status = service.approve()

        assert status.state == "failed"
        assert backend.starts == []
        assert "spend-ready" in (status.status_text or "")

    def test_plane_rejects_offerless_approval_and_provision(self):
        backend = RecordingBackend()
        plane = CoderControlPlane(
            backend=backend,  # type: ignore[arg-type]
            token_provider=lambda: "hf_fake_token",
            port_available=lambda port: True,
        )
        prepared = plane.prepared_provision("defendcoder-heavy")
        offerless = __import__("dataclasses").replace(
            prepared,
            offer=None,
        )
        with pytest.raises(CoderProvisionBlocked, match="no qualifying offer"):
            plane.approve(offerless)
        approval = plane.approve(prepared)
        with pytest.raises(CoderProvisionBlocked, match="no qualifying offer"):
            plane.provision(offerless, approval)
        assert backend.starts == []


class TestFailureCleanup:
    def test_price_higher_than_approved_destroys_and_fails(self):
        backend = FailingBackend(
            message="actual provider rate 9.99 exceeds approved rate 2.00",
            destroys_owned_instance=True,
        )
        service, plane, supervisor = _service(backend)

        service.start()
        status = service.approve()

        assert status.state == "failed"
        assert backend.destroyed_owned_instance is True
        assert "coder:api" not in supervisor.processes
        assert "coder:web" not in supervisor.processes

    def test_direct_endpoint_timeout_tears_down(self):
        backend = FailingBackend(
            message="direct SSH endpoint unavailable after 300s; instance destroyed",
            destroys_owned_instance=True,
        )
        service, plane, supervisor = _service(backend)

        service.start()
        status = service.approve()

        assert status.state == "failed"
        assert backend.destroyed_owned_instance is True
        assert "coder:api" not in supervisor.processes
        assert "coder:web" not in supervisor.processes

    def test_remote_readiness_failure_never_starts_local(self):
        backend = RecordingBackend(smoke_ok=False)
        service, plane, supervisor = _service(backend)

        service.start()
        status = service.approve()

        assert status.state == "failed"
        assert len(backend.starts) == 1
        assert "coder:api" not in supervisor.processes
        assert "coder:web" not in supervisor.processes
        assert len(backend.stops) == 1
        assert backend.stops[0][2] is True


class TestProvisioningFailurePanel:
    def test_failed_provision_panel_renders_full_diagnostics(self):
        backend = FailingBackend(
            message="vllm process died during model load",
            failure=_failure(),
        )
        service, plane, supervisor = _service(backend)

        service.start()
        status = service.approve()

        assert status.state == "failed"
        assert status.status_text == "PROVISIONING FAILED"
        details = dict(status.details)
        assert details["Phase"] == "model_load"
        assert details["Reason"] == (
            "model_load failed \u2014 see DEFENDcoder logs / COPY DIAGNOSTICS"
        )
        assert status.diagnostics
        assert "model_load" in status.diagnostics
        assert details["Instance"] == "555901"
        assert details["GPU"] == "A100 SXM4"
        assert details["Approved rate"] == "$1.10/hr"
        assert details["Runtime before failure"] == format_elapsed(247.0)
        assert details["Cleanup"] == "instance destroyed"

        diagnostics = status.diagnostics
        assert diagnostics is not None
        assert "PROVISIONING FAILED" in diagnostics
        assert "Phase: model_load" in diagnostics
        assert "Reason: vllm process died during model load" in diagnostics
        assert "Instance: 555901" in diagnostics
        assert "GPU: A100 SXM4" in diagnostics
        assert "Approved rate: $1.10/hr" in diagnostics
        assert "Cleanup: destroyed" in diagnostics

    def test_failed_provision_destroyed_exactly_once_no_local_starts(self):
        backend = FailingBackend(
            message="direct SSH endpoint unavailable after 300s",
            failure=_failure(phase="direct_endpoint_wait"),
            destroys_owned_instance=True,
        )
        service, plane, supervisor = _service(backend)

        service.start()
        status = service.approve()

        assert status.state == "failed"
        assert backend.destroyed_owned_instance is True
        assert len(backend.stops) == 0
        assert "coder:api" not in supervisor.processes
        assert "coder:web" not in supervisor.processes
        assert service.pending_plan() is None
        assert plane.active_endpoints() == ()

    def test_failed_provision_diagnostics_contain_no_secrets(self):
        backend = FailingBackend(
            message="bootstrap failed",
            failure=_failure(),
        )
        service, plane, supervisor = _service(backend)

        service.start()
        status = service.approve()

        diagnostics = status.diagnostics or ""
        assert "hf_fake_token" not in diagnostics
        assert "postgresql://user:pass" not in diagnostics
        assert "sk-secret" not in diagnostics
        assert "hf_test" not in diagnostics

    def test_smoke_failure_panel_records_openai_smoke_phase(self):
        backend = SmokeFailureBackend()
        service, plane, supervisor = _service(backend)

        service.start()
        status = service.approve()

        assert status.state == "failed"
        assert status.status_text == "PROVISIONING FAILED"
        details = dict(status.details)
        assert details["Phase"] == "openai_smoke"
        assert details["Cleanup"] == "unknown"
        assert "coder:api" not in supervisor.processes

    def test_destroy_failure_warns_very_clearly(self):
        backend = FailingBackend(
            message="vllm process died during model load",
            failure=_failure(cleanup="destroy_request_failed"),
            stop_fails=True,
        )
        service, plane, supervisor = _service(backend)

        service.start()
        status = service.approve()

        assert status.state == "failed"
        assert "PROVIDER CLEANUP FAILED" in (status.status_text or "")
        assert "still be running and billing" in (status.status_text or "")
        details = dict(status.details)
        assert "DESTROY REQUEST FAILED" in details["Cleanup"]

    def test_destroy_pending_is_informational_not_a_billing_alarm(self):
        backend = FailingBackend(
            message="vllm process died during model load",
            failure=_failure(cleanup="destroy_pending"),
            stop_fails=True,
        )
        service, plane, supervisor = _service(backend)

        service.start()
        status = service.approve()

        assert status.state == "failed"
        assert status.status_text == "PROVISIONING FAILED"
        assert "PROVIDER CLEANUP FAILED" not in (status.status_text or "")
        details = dict(status.details)
        assert "destruction pending" in details["Cleanup"]

    def test_lifecycle_log_visible_after_cleanup(self):
        backend = FailingBackend(
            message="vllm process died during model load",
            failure=_failure(),
        )
        service, plane, supervisor = _service(backend)

        service.start()
        status = service.approve()
        assert status.state == "failed"

        entries = service.logs()
        texts = [entry.text for entry in entries]
        assert any("offer approved" in text for text in texts)
        assert any("FAILED phase=model_load" in text for text in texts)
        assert any("reason=vllm process died during model load" in text for text in texts)
        assert all(
            not text.startswith("coder:lifecycle ") or "[" in text
            for text in texts
        )

    def test_local_start_failure_keeps_instance_and_marks_not_attempted(self):
        backend = RecordingBackend()
        service, plane, supervisor = _service(backend)
        service.start()
        service.approve()
        assert service._coder_state == "running"

        class ExplodingSupervisor(FakeSupervisor):
            def start(self, spec):
                if spec.name == "coder:api":
                    raise RuntimeError("port in use")
                return super().start(spec)

        service._supervisor = ExplodingSupervisor()
        service._coder_state = "starting_local"
        service._start_local_and_finish()

        status = service.status()
        assert status.state == "failed"
        assert dict(status.details)["Phase"] == "local_api_start"
        assert dict(status.details)["Cleanup"] == (
            "not attempted \u2014 instance kept running (local start failed)"
        )
        assert dict(status.details)["Instance"] != "\u2014"
        assert len(backend.stops) == 0


class TestLifecycleTelemetry:
    def test_approve_provision_and_ready_are_streamed(self):
        backend = RecordingBackend()
        service, plane, supervisor = _service(backend)

        service.start()
        service.approve()

        texts = [entry.text for entry in service.logs()]
        assert any("provisioning approved for defendcoder-heavy" in t for t in texts)
        assert any("runtime ready: defendcoder-heavy (smoke passed)" in t for t in texts)
        assert any("starting local coder services" in t for t in texts)

    def test_resume_ready_is_streamed_without_duplicate_local_start(self):
        from defend_control.types import VastInstance

        backend = ResumableBackend(
            candidate=VastInstance(
                555901,
                "running",
                "ssh.example",
                22,
                "A100 SXM4",
                81920,
                Decimal("1.10"),
                image_runtype="ssh_proxy",
            )
        )
        service, plane, supervisor = _service(backend)

        service.start()
        service.start()

        texts = [entry.text for entry in service.logs()]
        assert any("resumed runtime ready: defendcoder-heavy" in t for t in texts)
        starts = [t for t in texts if "starting local coder services" in t]
        assert len(starts) == 1

    def test_stop_streams_stopping_and_stopped(self):
        backend = RecordingBackend()
        service, plane, supervisor = _service(backend)
        service.start()
        service.approve()

        service.stop()

        texts = [entry.text for entry in service.logs()]
        assert any("stopping coder runtime" in t for t in texts)
        assert any("coder runtime stopped" in t for t in texts)

    def test_stop_with_errors_does_not_stream_stopped(self):
        backend = RecordingBackend()
        service, plane, supervisor = _service(backend)
        service.start()
        service.approve()

        class ExplodingSupervisor(FakeSupervisor):
            def stop(self, name):
                raise RuntimeError("cannot stop")

        exploding = ExplodingSupervisor()
        exploding.processes = supervisor.processes
        service._supervisor = exploding
        service.stop()

        texts = [entry.text for entry in service.logs()]
        assert any("stopping coder runtime" in t for t in texts)
        assert not any("coder runtime stopped" in t for t in texts)


class TestSuccessOrderAndReuse:
    def test_success_order_remote_then_api_then_web(self):
        backend = RecordingBackend()
        service, plane, supervisor = _service(backend)

        service.start()
        service.approve()

        endpoint = plane.active_endpoints()
        assert len(endpoint) == 1
        assert endpoint[0].state == "ready"
        assert supervisor.processes["coder:api"]["running"] is True
        assert supervisor.processes["coder:web"]["running"] is True

    def test_ready_runtime_reused_without_new_spend(self):
        backend = RecordingBackend()
        service, plane, supervisor = _service(backend)
        plane._active["defendcoder-heavy"] = _ready_endpoint(
            "defendcoder-heavy"
        )

        status = service.start()

        assert status.state == "running"
        assert backend.starts == []
        assert supervisor.processes["coder:api"]["running"] is True
        assert supervisor.processes["coder:web"]["running"] is True

    def test_status_exposes_real_model_gpu_instance_rate(self):
        backend = RecordingBackend()
        service, plane, supervisor = _service(backend)

        service.start()
        service.approve()
        status = service.status()

        details = dict(status.details)
        assert details["Alias"] == "defendcoder-heavy"
        assert details["GPU"] == "A100 SXM4"
        assert details["Instance"] == "555002"
        assert details["$/hr"] == "$1.10"


class TestStopIsolation:
    def test_stop_only_touches_coder_owned_resources(self):
        backend = RecordingBackend()
        supervisor = FakeSupervisor(
            running=(
                "coder:api",
                "coder:web",
                "coder ssh tunnel:8003",
                "scs:api",
                "scs:web",
            )
        )
        service, plane, _ = _service(backend, supervisor=supervisor)
        service._coder_state = "running"
        plane._active["defendcoder-heavy"] = _ready_endpoint(
            "defendcoder-heavy"
        )

        status = service.stop()

        assert status.state == "stopped"
        assert supervisor.processes["coder:api"]["running"] is False
        assert supervisor.processes["coder:web"]["running"] is False
        assert supervisor.processes["coder ssh tunnel:8003"]["running"] is False
        assert supervisor.processes["scs:api"]["running"] is True
        assert supervisor.processes["scs:web"]["running"] is True
        assert len(backend.stops) == 1
        assert backend.stops[0][2] is True


class TestQualificationFailClosed:
    def test_no_offers_zero_create_calls_and_no_offer_state(self):
        backend = NoOfferBackend()
        service, plane, supervisor = _service(backend)

        status = service.start()

        assert status.state == "no_offer"
        assert backend.starts == []
        assert service.pending_plan() is None
        assert "coder:api" not in supervisor.processes
        assert "coder:web" not in supervisor.processes
        assert "NO QUALIFYING VAST OFFER" in status.status_text
        assert status.error_category == "no_qualifying_offer"

    def test_no_offers_cannot_approve(self):
        backend = NoOfferBackend()
        service, plane, supervisor = _service(backend)

        service.start()
        status = service.approve()

        assert status.state == "no_offer"
        assert backend.starts == []
        assert service._last_error == "no pending coder plan to approve"
        assert service.pending_plan() is None

    def test_approval_ui_never_presented_for_offerless_plan(self):
        backend = RecordingBackend()
        service, plane, _ = _service(backend)

        service.start()
        prepared = __import__("dataclasses").replace(
            service.pending_plan(),
            offer=None,
        )
        ready, problems = coder_approval_ready(prepared)
        assert ready is False
        assert "no concrete provider offer" in problems

    def test_no_offer_carries_sanitized_filter_summary_and_count(self):
        backend = NoOfferBackend()
        service, plane, _ = _service(backend)

        service.start()
        qualification = service.qualification()

        assert isinstance(qualification, CoderNoQualifyingOffer)
        assert qualification.searched_offer_count == 0
        assert qualification.required_gpu_count == 2
        assert qualification.required_vram_per_gpu_mb == 81_920
        assert qualification.required_min_reliability == Decimal("0.98")
        assert "H100" in qualification.required_gpu_families
        assert qualification.max_hourly_usd == Decimal("4.50")
        assert "VAST_API_KEY" not in str(qualification)

    def test_retry_after_no_offer_can_find_an_offer(self):
        backend = NoOfferBackend()
        service, plane, _ = _service(backend)
        service.start()
        assert service.state == "no_offer"

        backend.offers = _QUALIFYING_OFFERS
        status = service.start()

        assert status.state == "approval_required"
        assert backend.starts == []
        assert service.pending_plan() is not None

    def test_real_offer_plan_rows_show_exact_offer_id_and_rate(self):
        backend = RecordingBackend()
        service, plane, _ = _service(backend)

        service.start()
        rows = dict(coder_plan_rows(service.pending_plan()))

        assert rows["Offer ID"] == "601"
        assert rows["Exact $/hr"] == "$1.65"
        assert rows["GPU"] == "H100 SXM 80GB"
        assert rows["VRAM per GPU"] == "81,920 MB reported"
        assert rows["Reliability"] == "0.99"
        assert rows["Plan hash"] == service.pending_plan().plan_hash

    def test_spend_ready_gate_requires_every_provider_field(self):
        backend = RecordingBackend()
        service, plane, _ = _service(backend)
        service.start()
        prepared = service.pending_plan()

        ready, problems = coder_approval_ready(prepared)
        assert ready is True
        assert problems == ()

        without_rate = __import__("dataclasses").replace(
            prepared.plan,
            provider_hourly_rate=None,
        )
        ready, problems = coder_approval_ready(
            __import__("dataclasses").replace(prepared, plan=without_rate)
        )
        assert ready is False
        assert "missing exact provider hourly price" in problems

        over = __import__("dataclasses").replace(
            prepared.plan,
            provider_hourly_rate=Decimal("9.99"),
        )
        ready, problems = coder_approval_ready(
            __import__("dataclasses").replace(prepared, plan=over)
        )
        assert ready is False
        assert "exceeds configured max" in " ".join(problems)


class TestPlanAndSecrets:
    def test_plan_rows_render_exact_plan_fields(self):
        backend = RecordingBackend()
        service, plane, _ = _service(backend)

        service.start()
        prepared = service.pending_plan()
        rows = coder_plan_rows(prepared)
        labels = [label for label, _ in rows]

        for required in (
            "Logical model",
            "Deployment",
            "Pinned revision",
            "Precision",
            "GPU",
            "GPU count",
            "VRAM per GPU",
            "Reliability",
            "Offer ID",
            "Exact $/hr",
            "Configured max $/hr",
            "Session budget",
            "vLLM image",
            "Max model length",
            "Tensor parallel",
            "Tool parser",
            "Runtype",
            "Plan ID",
            "Plan hash",
        ):
            assert required in labels

        by_label = dict(rows)
        assert "Qwen/Qwen3-Coder-Next" in by_label["Logical model"]
        assert by_label["Plan hash"] == prepared.plan_hash
        assert by_label["Max model length"] == "32768"
        assert "ssh_proxy" in by_label["Runtype"]
        assert "default" in by_label["Runtype"]
        assert by_label["Transport"] == "Vast SSH Proxy"

    def test_no_secrets_in_status_errors_or_details(self):
        secret = "VAST_API_KEY_LEAK_CHECK_9f1a"
        backend = FailingBackend(message=f"boom {secret}")
        service, plane, _ = _service(backend)

        service.start()
        status = service.approve()

        joined = " ".join(
            [
                status.status_text or "",
                status.last_error or "",
                *[f"{label}={value}" for label, value in status.details],
            ]
        )
        assert secret not in joined


class ResumableBackend(RecordingBackend):
    """RecordingBackend that reports one resumable labeled instance."""

    def __init__(self, *, candidate: object | None = None) -> None:
        super().__init__()
        self.candidate = candidate
        self.resumed: list[tuple[str, int, int | None]] = []

    def resume_candidate(self, *, launch_runtype, approved_ceiling):
        del launch_runtype, approved_ceiling
        return self.candidate

    def start(
        self,
        model,
        *,
        local_port,
        session_budget_usd,
        offer=None,
        profile=None,
        launch_runtype=None,
        resume_instance=None,
    ):
        self.resumed.append(
            (
                model.alias,
                local_port,
                (
                    resume_instance.instance_id
                    if resume_instance is not None
                    else None
                ),
            )
        )
        result = super().start(
            model,
            local_port=local_port,
            session_budget_usd=session_budget_usd,
            offer=offer,
            profile=profile,
            launch_runtype=launch_runtype,
        )
        if resume_instance is not None:
            result = dict(result)
            result["instance_id"] = resume_instance.instance_id
        return result


class TestReuseResume:
    def test_plane_resume_existing_reuses_running_labeled_instance(self):
        from defend_control.types import VastInstance

        candidate = VastInstance(
            555901,
            "running",
            "ssh.example",
            22,
            "A100 SXM4",
            81920,
            Decimal("1.10"),
            image_runtype="ssh_proxy",
        )
        backend = ResumableBackend(candidate=candidate)
        service, plane, supervisor = _service(backend)

        lease = plane.resume_existing("defendcoder-default")

        assert lease is not None
        assert lease.reused is True
        assert lease.instance_id == 555901
        assert backend.resumed == [("defendcoder-default", 8003, 555901)]
        assert backend.starts == [("defendcoder-default", 8003, Decimal("5.00"))]
        assert list(supervisor.processes) == []

    def test_service_start_resumes_without_approval_dialog(self):
        from defend_control.types import VastInstance

        candidate = VastInstance(
            555902,
            "running",
            "ssh.example",
            22,
            "A100 SXM4",
            81920,
            Decimal("1.10"),
            image_runtype="ssh_proxy",
        )
        backend = ResumableBackend(candidate=candidate)
        service, plane, supervisor = _service(backend)

        status = service.start()

        assert status.state == "running"
        assert service.pending_plan() is None
        assert sorted(supervisor.processes) == [
            "coder:api",
            "coder:web",
        ]
        assert backend.resumed == [("defendcoder-heavy", 8003, 555902)]

    def test_service_start_falls_back_to_fresh_approval_when_nothing_to_resume(self):
        backend = ResumableBackend(candidate=None)
        service, plane, _ = _service(backend)

        status = service.start()

        assert status.state == "approval_required"
        assert service.pending_plan() is not None
        assert backend.resumed == []

    def test_duplicate_launch_prevention_while_provisioning(self):
        backend = RecordingBackend()
        service, plane, _ = _service(backend)

        service.start()
        service.approve()

        during = service.start()
        assert during.state in ("starting_local", "running")

        again = service.start()
        assert again.state == during.state