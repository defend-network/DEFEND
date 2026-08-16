"""DEFENDcoder runtime-v1 ControlPlane tests — mocked backend only, no network/billing."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from defend_control.coder_billing import BillingPolicy as BillingPolicySettings
from defend_control.coder_control_plane import (
    ActiveCoderEndpoint,
    CoderControlPlane,
    CoderPolicy,
    CoderProvisionBlocked,
    CoderRunTrace,
    EndpointLease,
    RunTraceStore,
    derive_estimated_cost,
    resource_profile,
)
from defend_control.coder_m0 import CoderModelRef, resolve_alias
from defend_control.types import ResourceProfile


def _utc(year: int = 2026, month: int = 8, day: int = 14) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


class RecordingBackend:
    """Deterministic CoderInferenceBackend recording every call."""

    def __init__(
        self,
        *,
        hourly_price: str | None = "1.10",
        gpu_type: str = "A100 SXM4",
        smoke_ok: bool = True,
    ) -> None:
        self.starts: list[tuple[str, int, Decimal]] = []
        self.smokes: list[tuple[str, str]] = []
        self.stops: list[tuple[int | None, str | None, bool]] = []
        self._hourly_price = hourly_price
        self._gpu_type = gpu_type
        self._smoke_ok = smoke_ok
        self._instance = 555001

    def start(
        self,
        model: CoderModelRef,
        *,
        local_port: int,
        session_budget_usd: Decimal,
        offer=None,
        profile=None,
    ) -> dict[str, object]:
        del offer, profile
        self.starts.append((model.alias, local_port, session_budget_usd))
        self._instance += 1
        return {
            "state": "ready",
            "provider": "recording",
            "endpoint": f"http://127.0.0.1:{local_port}/v1",
            "instance_id": self._instance,
            "provider_run_id": f"vast-{self._instance}",
            "hourly_price": self._hourly_price,
            "gpu_type": self._gpu_type,
            "message": f"recording backend ready for {model.alias}",
        }

    def smoke(self, endpoint: str, model: CoderModelRef) -> dict[str, object]:
        self.smokes.append((endpoint, model.alias))
        return {
            "ok": self._smoke_ok,
            "latency_ms": 4,
            "detail": f"recording smoke {model.alias}",
        }

    def stop(
        self,
        *,
        instance_id: int | None,
        provider_run_id: str | None,
        destroy: bool,
    ) -> dict[str, object]:
        self.stops.append((instance_id, provider_run_id, destroy))
        return {
            "state": "stopped",
            "message": "recording backend stopped",
            "instance_id": instance_id,
            "provider_run_id": provider_run_id,
        }


def _plane(
    backend: RecordingBackend,
    *,
    policy: CoderPolicy | None = None,
    clock: list[datetime] | None = None,
) -> CoderControlPlane:
    return CoderControlPlane(
        backend=backend,  # type: ignore[arg-type]
        policy=policy,
        clock=(lambda: clock[0]) if clock else None,
        token_provider=lambda: "hf_fake_token",
        port_available=lambda port: True,
    )


class TestLockedRegistry:
    def test_default_pin_is_locked(self):
        ref = resolve_alias("defendcoder-default")
        assert ref.repo_id == "Qwen/Qwen3-Coder-30B-A3B-Instruct"
        assert ref.revision == "b2cff646eb4bb1d68355c01b18ae02e7cf42d120"

    def test_heavy_pin_is_locked_to_qwen3_coder_next(self):
        ref = resolve_alias("defendcoder-heavy")
        assert ref.repo_id == "Qwen/Qwen3-Coder-Next"
        assert ref.revision == "a7fbcb5c0e12d62a448eaa0e260346bf5dcc0feb"

    def test_default_and_heavy_are_independent_aliases(self):
        default = resolve_alias("defendcoder-default")
        heavy = resolve_alias("defendcoder-heavy")
        assert default.alias != heavy.alias
        assert default.repo_id != heavy.repo_id
        assert default.revision != heavy.revision


class TestCoderPolicy:
    def test_defaults_match_v1_intent(self):
        policy = CoderPolicy()
        assert policy.mode == "DEFAULT"
        assert policy.auto_provisioning_enabled is True
        assert policy.max_hourly_usd == Decimal("2.00")
        assert policy.max_session_spend_usd == Decimal("5.00")
        assert policy.max_concurrent_instances == 1
        assert policy.idle_shutdown_minutes == 10
        assert policy.heavy_escalation_after_failures == 2
        assert policy.auto_escalation_eligible is True

    def test_thresholds_are_configurable(self):
        policy = CoderPolicy(
            mode="HEAVY",
            max_hourly_usd=Decimal("3.50"),
            max_concurrent_instances=2,
            idle_shutdown_minutes=25,
            heavy_escalation_after_failures=4,
            default_min_gpu_ram_mb=16_384,
        )
        assert policy.mode == "HEAVY"
        assert policy.max_hourly_usd == Decimal("3.50")
        assert policy.max_concurrent_instances == 2
        assert policy.idle_shutdown_minutes == 25
        assert policy.heavy_escalation_after_failures == 4
        assert policy.default_min_gpu_ram_mb == 16_384

    def test_all_modes_are_accepted_and_unknown_rejected(self):
        for mode in ("AUTO", "FAST", "DEFAULT", "HEAVY", "MAXIMUM"):
            assert CoderPolicy(mode=mode).mode == mode  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            CoderPolicy(mode="NONSENSE")  # type: ignore[arg-type]


class TestResourceProfiles:
    def test_default_profile_targets_single_80gb_class(self):
        profile = resource_profile("defendcoder-default", CoderPolicy())
        assert profile.min_gpu_ram_mb == 81_920
        assert profile.num_gpus == 1
        assert "RTX 4090" not in profile.allowed_gpu_families
        assert "L40S" not in profile.allowed_gpu_families

    def test_heavy_profile_targets_fp8_capable_gpu_families(self):
        profile = resource_profile("defendcoder-heavy", CoderPolicy())
        assert profile.min_gpu_ram_mb == 81_920
        assert profile.allowed_gpu_families == (
            "H100",
            "H200",
            "B200",
        )
        assert profile.num_gpus == 2

    def test_identity_chat_profile_is_unchanged(self):
        assert ResourceProfile().min_gpu_ram_mb >= 140_000

    def test_default_and_heavy_profiles_differ(self):
        policy = CoderPolicy()
        assert resource_profile("defendcoder-default", policy) != resource_profile(
            "defendcoder-heavy", policy
        )


class TestAcquireAndReuse:
    def test_acquire_provisions_once_then_reuses_warm_endpoint(self):
        backend = RecordingBackend()
        plane = _plane(backend)
        first = plane.acquire("defendcoder-default")
        second = plane.acquire("defendcoder-default")
        assert first.reused is False
        assert second.reused is True
        assert first.endpoint == second.endpoint
        assert first.instance_id == second.instance_id
        assert len(backend.starts) == 1

    def test_heavy_and_default_are_independent_instances(self):
        backend = RecordingBackend()
        plane = _plane(backend, policy=CoderPolicy(max_concurrent_instances=2))
        default = plane.acquire("defendcoder-default")
        heavy = plane.acquire("defendcoder-heavy")
        assert default.reused is False
        assert heavy.reused is False
        assert default.alias != heavy.alias
        assert default.instance_id != heavy.instance_id
        assert len(backend.starts) == 2

    def test_concurrency_limit_blocks_second_alias(self):
        backend = RecordingBackend()
        plane = _plane(backend, policy=CoderPolicy(max_concurrent_instances=1))
        plane.acquire("defendcoder-default")
        with pytest.raises(CoderProvisionBlocked, match="concurrent"):
            plane.acquire("defendcoder-heavy")

    def test_auto_provisioning_disabled_blocks_provisioning(self):
        backend = RecordingBackend()
        plane = _plane(backend, policy=CoderPolicy(auto_provisioning_enabled=False))
        with pytest.raises(CoderProvisionBlocked, match="automatic provisioning"):
            plane.acquire("defendcoder-default")

    def test_unknown_alias_is_rejected(self):
        plane = _plane(RecordingBackend())
        with pytest.raises(ValueError, match="unknown coder alias"):
            plane.acquire("not-a-real-alias")


class TestIdleShutdown:
    def test_reuse_within_idle_window_does_not_reprovision(self):
        backend = RecordingBackend()
        now = [_utc()]
        plane = _plane(backend, clock=now)
        plane.acquire("defendcoder-default")
        now[0] = now[0] + timedelta(minutes=5)
        lease = plane.acquire("defendcoder-default")
        assert lease.reused is True
        assert len(backend.starts) == 1

    def test_idle_reap_stops_without_destroying(self):
        backend = RecordingBackend()
        now = [_utc()]
        plane = _plane(backend, clock=now)
        plane.acquire("defendcoder-default")
        now[0] = now[0] + timedelta(minutes=11)
        reaped = plane.maybe_reap_idle()
        assert reaped == ("defendcoder-default",)
        assert backend.stops[-1] == (555002, "vast-555002", False)
        assert backend.stops[-1][2] is False
        endpoint = plane.active_endpoints()[0]
        assert endpoint.state == "stopped"

    def test_reacquire_after_idle_reap_provisions_fresh_instance(self):
        backend = RecordingBackend()
        now = [_utc()]
        plane = _plane(backend, clock=now)
        plane.acquire("defendcoder-default")
        now[0] = now[0] + timedelta(minutes=11)
        plane.maybe_reap_idle()
        lease = plane.acquire("defendcoder-default")
        assert lease.reused is False
        assert len(backend.starts) == 2


class TestMeasuredRunTrace:
    def test_successful_smoke_records_measured_run_trace(self):
        backend = RecordingBackend(hourly_price="1.10", gpu_type="A100 SXM4")
        plane = _plane(backend)
        plane.acquire("defendcoder-default")
        result = plane.smoke("defendcoder-default")
        assert result.ok is True

        runs = plane.run_store.all_runs()
        assert len(runs) == 1
        run = runs[0]
        assert run.run_id
        assert run.user_id is None
        assert run.model_alias == "defendcoder-default"
        assert run.provider == "recording"
        assert run.instance_id is not None
        assert run.gpu_type == "A100 SXM4"
        assert run.provider_hourly_rate == Decimal("1.10")
        assert run.provisioned_at is not None
        assert run.model_ready_at is not None
        assert run.run_started_at.tzinfo is not None
        assert run.run_completed_at.tzinfo is not None
        assert run.run_started_at <= run.run_completed_at
        assert run.active_seconds >= 0
        assert run.input_tokens is None
        assert run.output_tokens is None
        assert run.tool_runtime == 0
        assert run.retries == 0
        assert run.failures == 0
        assert run.final_status == "succeeded"
        assert run.estimated_total_cost is not None
        assert run.charged_credits is None
        assert run.allocated_compute_cost is None

    def test_trace_without_provider_rate_leaves_costs_unknown(self):
        backend = RecordingBackend(hourly_price=None)
        plane = _plane(backend)
        plane.acquire("defendcoder-default")
        plane.smoke("defendcoder-default")
        run = plane.run_store.all_runs()[0]
        assert run.provider_hourly_rate is None
        assert run.estimated_total_cost is None
        assert run.charged_credits is None
        assert run.allocated_compute_cost is None

    def test_failed_smoke_records_failed_run_trace(self):
        backend = RecordingBackend(smoke_ok=False)
        plane = _plane(backend)
        plane.acquire("defendcoder-default")
        result = plane.smoke("defendcoder-default")
        assert result.ok is False
        run = plane.run_store.all_runs()[0]
        assert run.final_status == "failed"
        assert run.failures == 1

    def test_run_trace_has_exact_accounting_fields_and_no_secrets(self):
        from dataclasses import fields

        names = {field.name for field in fields(CoderRunTrace)}
        assert names == {
            "run_id",
            "user_id",
            "model_alias",
            "provider",
            "instance_id",
            "gpu_type",
            "provider_hourly_rate",
            "provisioned_at",
            "model_ready_at",
            "run_started_at",
            "run_completed_at",
            "active_seconds",
            "allocated_compute_cost",
            "input_tokens",
            "output_tokens",
            "tool_runtime",
            "retries",
            "failures",
            "final_status",
            "estimated_total_cost",
            "charged_credits",
        }
        blob = " ".join(names).casefold()
        for banned in ("api_key", "password", "secret", "token_value"):
            assert banned not in blob

    def test_cost_derivation_is_formula_based_not_fabricated(self):
        assert derive_estimated_cost(Decimal("1.10"), 3600) == Decimal("1.10")
        assert derive_estimated_cost(Decimal("1.10"), 0) == Decimal("0.00")
        assert derive_estimated_cost(None, 60) is None

    def test_run_trace_store_is_append_only(self):
        store = RunTraceStore()
        assert store.all_runs() == []
        store.record(CoderRunTrace(run_id="r1"))
        store.record(CoderRunTrace(run_id="r2"))
        assert [r.run_id for r in store.all_runs()] == ["r1", "r2"]


class TestEscalation:
    def test_auto_mode_escalates_heavy_after_configured_failures(self):
        plane = _plane(RecordingBackend(), policy=CoderPolicy(mode="AUTO"))
        assert plane.should_escalate("defendcoder-default", 1) is False
        assert plane.should_escalate("defendcoder-default", 2) is True

    def test_default_mode_never_escalates(self):
        plane = _plane(RecordingBackend(), policy=CoderPolicy(mode="DEFAULT"))
        assert plane.should_escalate("defendcoder-default", 99) is False

    def test_heavy_alias_never_escalates_further(self):
        plane = _plane(RecordingBackend(), policy=CoderPolicy(mode="AUTO"))
        assert plane.should_escalate("defendcoder-heavy", 99) is False

    def test_escalation_respects_owner_eligibility_setting(self):
        plane = _plane(
            RecordingBackend(),
            policy=CoderPolicy(mode="AUTO", auto_escalation_eligible=False),
        )
        assert plane.should_escalate("defendcoder-default", 99) is False


def test_billing_policy_settings_are_separate_and_present():
    settings = BillingPolicySettings()
    assert settings.free_monthly_credit_allowance > 0
    assert settings.cost_multiplier >= 1
    assert settings.heavy_availability is True
    assert settings.auto_escalation_eligible is True


def test_active_endpoint_touch_updates_last_used():
    endpoint = ActiveCoderEndpoint(
        alias="defendcoder-default",
        provider="recording",
        endpoint="http://127.0.0.1:8003/v1",
        instance_id=1,
        provider_run_id="vast-1",
        gpu_type="A100",
        hourly_price=Decimal("1.10"),
        state="ready",
        provisioned_at=_utc(),
        model_ready_at=_utc(),
        last_used_at=_utc(),
    )
    later = _utc(month=8, day=15)
    endpoint.touch(later)
    assert endpoint.last_used_at == later
    assert endpoint.instance_id == 1