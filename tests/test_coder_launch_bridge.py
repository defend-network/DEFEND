"""DEFENDcoder NEXT launch bridge behavioral tests (E1-E13).

Fake supervisor + recording backend + real CoderControlPlane and
CoderService: no network, no billing, no Tk.
"""

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from defend_control.coder_control_plane import (
    ActiveCoderEndpoint,
    CoderControlPlane,
)
from defend_control.coder_vast_backend import CoderVastBackendError
from defend_control.products import (
    CoderService,
    ProductsSettings,
    coder_plan_rows,
)

from test_coder_control_plane import RecordingBackend


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
    ) -> None:
        super().__init__()
        self._message = message
        self.destroyed_owned_instance = destroys_owned_instance

    def start(self, model, *, local_port, session_budget_usd, offer=None, profile=None):
        if self.destroyed_owned_instance:
            self.destroyed_owned_instance = True
        raise CoderVastBackendError(self._message)


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
        repository=Path("."),
        python_executable="python",
        plane=plane,
    )
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
            provider_hourly_rate=Decimal("9.99"),
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
            "Launch runtype",
            "Plan ID",
            "Plan hash",
        ):
            assert required in labels

        by_label = dict(rows)
        assert "Qwen/Qwen3-Coder-Next" in by_label["Logical model"]
        assert by_label["Plan hash"] == prepared.plan_hash
        assert by_label["Max model length"] == "32768"

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