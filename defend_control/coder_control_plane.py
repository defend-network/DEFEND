"""DEFENDcoder runtime-v1 compute control plane.

Owns: alias → pinned ModelRef → alias-specific ResourceProfile → endpoint
reuse / policy-gated provisioning → smoke → measured immutable run/cost trace.

This is NOT root control_plane.py (DEFEND AI agent runtime). Coder compute
orchestration is intentionally separate: the plane only talks to a
CoderInferenceBackend (e.g. VastCoderBackend). It never provisions Vast
directly and never sends provider credentials to the model box.

Financial semantics: None means unknown / not allocated / not charged;
Decimal("0.00") would mean positively known to be zero. Cost figures are
never fabricated — estimated_total_cost is derived only from known measured
inputs (provider hourly rate + measured active seconds).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Callable, Literal

from .coder_m0 import (
    CoderInferenceBackend,
    CoderSmokeResult,
    parse_session_budget,
    resolve_alias,
)
from .types import ResourceProfile

CoderMode = Literal["AUTO", "FAST", "DEFAULT", "HEAVY", "MAXIMUM"]

_HEAVY_ALIAS = "defendcoder-heavy"


@dataclass(frozen=True)
class CoderPolicy:
    """Centralized, configurable policy gates for coder compute (V1)."""

    mode: CoderMode = "DEFAULT"
    auto_provisioning_enabled: bool = True
    max_hourly_usd: Decimal = Decimal("2.00")
    max_session_spend_usd: Decimal = Decimal("5.00")
    max_concurrent_instances: int = 1
    idle_shutdown_minutes: int = 10
    heavy_escalation_after_failures: int = 2
    auto_escalation_eligible: bool = True
    default_min_gpu_ram_mb: int = 24_576
    heavy_min_gpu_ram_mb: int = 81_920
    default_gpu_families: tuple[str, ...] = (
        "A100",
        "H100",
        "H200",
        "B200",
        "RTX 4090",
        "L40S",
    )
    heavy_gpu_families: tuple[str, ...] = ("A100", "H100")
    min_reliability: Decimal = Decimal("0.98")
    min_disk_gb: int = 160
    max_model_len: int = 8192

    def __post_init__(self) -> None:
        if self.mode not in (
            "AUTO",
            "FAST",
            "DEFAULT",
            "HEAVY",
            "MAXIMUM",
        ):
            raise ValueError(
                f"unknown coder mode {self.mode!r}; expected one of "
                "AUTO, FAST, DEFAULT, HEAVY, MAXIMUM"
            )
        if self.max_hourly_usd <= 0 or self.max_session_spend_usd <= 0:
            raise ValueError("hourly/session budgets must be positive")
        if self.max_concurrent_instances < 1:
            raise ValueError("max_concurrent_instances must be >= 1")
        if self.idle_shutdown_minutes < 0:
            raise ValueError("idle_shutdown_minutes must be >= 0")
        if self.heavy_escalation_after_failures < 1:
            raise ValueError("heavy_escalation_after_failures must be >= 1")
        if self.default_min_gpu_ram_mb < 1 or self.heavy_min_gpu_ram_mb < 1:
            raise ValueError("min GPU RAM must be positive")


def resource_profile(alias: str, policy: CoderPolicy) -> ResourceProfile:
    """Resolve the alias-specific ResourceProfile (default vs heavy).

    DEFEND AI's identity chat ResourceProfile (>= 140 GB) is untouched.
    """
    resolve_alias(alias)
    if alias == _HEAVY_ALIAS:
        return ResourceProfile(
            min_gpu_ram_mb=policy.heavy_min_gpu_ram_mb,
            allowed_gpu_families=policy.heavy_gpu_families,
            num_gpus=1,
            min_reliability=policy.min_reliability,
            min_disk_gb=policy.min_disk_gb,
            max_model_len=policy.max_model_len,
        )
    return ResourceProfile(
        min_gpu_ram_mb=policy.default_min_gpu_ram_mb,
        allowed_gpu_families=policy.default_gpu_families,
        num_gpus=1,
        min_reliability=policy.min_reliability,
        min_disk_gb=policy.min_disk_gb,
        max_model_len=policy.max_model_len,
    )


def derive_estimated_cost(
    hourly_rate: Decimal | None, active_seconds: float
) -> Decimal | None:
    """Provider-infrastructure cost estimate from measured inputs only.

    None when the provider hourly rate is unknown. Never fabricates: the
    estimate is hourly_rate * active_seconds / 3600, rounded to cents.
    """
    if hourly_rate is None or active_seconds is None:
        return None
    estimate = (
        Decimal(hourly_rate) * Decimal(str(active_seconds)) / Decimal(3600)
    )
    return estimate.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class CoderProvisionBlocked(RuntimeError):
    """Policy denied provisioning (disabled, concurrency, budget, etc.)."""


@dataclass(frozen=True)
class EndpointLease:
    alias: str
    endpoint: str | None
    instance_id: int | None
    provider_run_id: str | None
    reused: bool


@dataclass
class ActiveCoderEndpoint:
    alias: str
    provider: str
    endpoint: str
    state: str
    provisioned_at: datetime
    last_used_at: datetime
    instance_id: int | None = None
    provider_run_id: str | None = None
    gpu_type: str | None = None
    hourly_price: Decimal | None = None
    model_ready_at: datetime | None = None

    def touch(self, now: datetime) -> None:
        self.last_used_at = now


@dataclass(frozen=True)
class CoderRunTrace:
    """Immutable, measured completed-run record. No secrets, ever."""

    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    user_id: str | None = None
    model_alias: str = ""
    provider: str = ""
    instance_id: int | None = None
    gpu_type: str | None = None
    provider_hourly_rate: Decimal | None = None
    provisioned_at: datetime | None = None
    model_ready_at: datetime | None = None
    run_started_at: datetime | None = None
    run_completed_at: datetime | None = None
    active_seconds: float | None = None
    allocated_compute_cost: Decimal | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    tool_runtime: float = 0
    retries: int = 0
    failures: int = 0
    final_status: str = ""
    estimated_total_cost: Decimal | None = None
    charged_credits: Decimal | None = None


class RunTraceStore:
    """Append-only store of immutable completed run traces (in-memory V1)."""

    def __init__(self) -> None:
        self._runs: list[CoderRunTrace] = []

    def record(self, run: CoderRunTrace) -> None:
        self._runs.append(run)

    def all_runs(self) -> list[CoderRunTrace]:
        return list(self._runs)


def _as_decimal(raw: object) -> Decimal | None:
    if raw is None or raw == "":
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class CoderControlPlane:
    """Coder-specific compute orchestration for a single owner/operator.

    Does not implement Maximum approval or AUTO/FAST routing (future).
    """

    backend: CoderInferenceBackend
    policy: CoderPolicy = field(default_factory=CoderPolicy)
    session_budget_usd: Decimal = field(default_factory=lambda: Decimal("5.00"))
    base_port: int = 8003
    clock: Callable[[], datetime] | None = None
    run_store: RunTraceStore = field(default_factory=RunTraceStore)
    _active: dict[str, ActiveCoderEndpoint] = field(
        default_factory=dict, init=False
    )

    def __post_init__(self) -> None:
        if self.policy is None:
            self.policy = CoderPolicy()
        self.session_budget_usd = parse_session_budget(self.session_budget_usd)
        if not (1 <= int(self.base_port) <= 65_535):
            raise ValueError("base_port must be in 1..65535")
        if self.clock is None:
            self.clock = _default_clock

    @property
    def mode(self) -> CoderMode:
        return self.policy.mode

    def _now(self) -> datetime:
        return self.clock()  # type: ignore[misc]

    def active_endpoints(self) -> tuple[ActiveCoderEndpoint, ...]:
        return tuple(self._active.values())

    def acquire(self, alias: str) -> EndpointLease:
        """Reuse a ready compatible endpoint or provision a new one."""
        model = resolve_alias(alias)
        now = self._now()

        existing = self._active.get(alias)
        if existing is not None and existing.state == "ready":
            existing.touch(now)
            return EndpointLease(
                alias=alias,
                endpoint=existing.endpoint,
                instance_id=existing.instance_id,
                provider_run_id=existing.provider_run_id,
                reused=True,
            )
        if existing is not None:
            self._active.pop(alias, None)

        self._authorize_provisioning()

        local_port = self.base_port + len(self._active)
        result = self.backend.start(
            model,
            local_port=local_port,
            session_budget_usd=self.session_budget_usd,
        )
        state = str(result.get("state") or "ready")
        endpoint = ActiveCoderEndpoint(
            alias=alias,
            provider=str(result.get("provider") or "backend"),
            endpoint=str(result.get("endpoint") or ""),
            state=state,
            provisioned_at=now,
            model_ready_at=now if state == "ready" else None,
            last_used_at=now,
            instance_id=result.get("instance_id"),
            provider_run_id=result.get("provider_run_id"),
            gpu_type=result.get("gpu_type"),
            hourly_price=_as_decimal(result.get("hourly_price")),
        )
        self._active[alias] = endpoint
        return EndpointLease(
            alias=alias,
            endpoint=endpoint.endpoint,
            instance_id=endpoint.instance_id,
            provider_run_id=endpoint.provider_run_id,
            reused=False,
        )

    def _authorize_provisioning(self) -> None:
        if not self.policy.auto_provisioning_enabled:
            raise CoderProvisionBlocked(
                "automatic provisioning disabled by policy"
            )
        active_count = sum(
            1
            for e in self._active.values()
            if e.state in ("starting", "provisioning", "ready")
        )
        if active_count >= self.policy.max_concurrent_instances:
            raise CoderProvisionBlocked(
                f"concurrent instance limit reached (max "
                f"{self.policy.max_concurrent_instances})"
            )

    def smoke(self, alias: str) -> CoderSmokeResult:
        """Smoke the model behind the ready endpoint and record a run trace."""
        resolve_alias(alias)
        endpoint = self._active.get(alias)
        if endpoint is None or endpoint.state != "ready":
            return CoderSmokeResult(
                ok=False,
                alias=alias,
                endpoint=endpoint.endpoint if endpoint else None,
                latency_ms=0,
                detail=f"no ready coder endpoint for {alias!r}",
                instance_id=endpoint.instance_id if endpoint else None,
                provider_run_id=endpoint.provider_run_id if endpoint else None,
            )

        model = resolve_alias(alias)
        started_clock = self._now()
        started = time.perf_counter()
        try:
            result = self.backend.smoke(endpoint.endpoint, model)
        except Exception as exc:
            completed_clock = self._now()
            elapsed = time.perf_counter() - started
            self._record_trace(
                endpoint,
                started_clock,
                completed_clock,
                round(elapsed, 3),
                ok=False,
                detail=f"smoke exception: {type(exc).__name__}",
            )
            return CoderSmokeResult(
                ok=False,
                alias=alias,
                endpoint=endpoint.endpoint,
                latency_ms=int(elapsed * 1000),
                detail=f"smoke exception: {type(exc).__name__}",
                instance_id=endpoint.instance_id,
                provider_run_id=endpoint.provider_run_id,
            )

        elapsed = time.perf_counter() - started
        completed_clock = self._now()
        ok = bool(result.get("ok"))
        latency = int(result.get("latency_ms") or elapsed * 1000)
        self._record_trace(
            endpoint,
            started_clock,
            completed_clock,
            round(elapsed, 3),
            ok=ok,
            detail=str(result.get("detail", "")),
        )
        endpoint.touch(completed_clock)
        return CoderSmokeResult(
            ok=ok,
            alias=alias,
            endpoint=endpoint.endpoint,
            latency_ms=latency,
            detail=str(result.get("detail", "")),
            instance_id=endpoint.instance_id,
            provider_run_id=endpoint.provider_run_id,
        )

    def _record_trace(
        self,
        endpoint: ActiveCoderEndpoint,
        started_clock: datetime,
        completed_clock: datetime,
        active_seconds: float,
        *,
        ok: bool,
        detail: str,
    ) -> None:
        trace = CoderRunTrace(
            model_alias=endpoint.alias,
            provider=endpoint.provider,
            instance_id=endpoint.instance_id,
            gpu_type=endpoint.gpu_type,
            provider_hourly_rate=endpoint.hourly_price,
            provisioned_at=endpoint.provisioned_at,
            model_ready_at=endpoint.model_ready_at,
            run_started_at=started_clock,
            run_completed_at=completed_clock,
            active_seconds=active_seconds,
            allocated_compute_cost=None,
            input_tokens=None,
            output_tokens=None,
            tool_runtime=0,
            retries=0,
            failures=0 if ok else 1,
            final_status="succeeded" if ok else "failed",
            estimated_total_cost=derive_estimated_cost(
                endpoint.hourly_price, active_seconds
            ),
            charged_credits=None,
        )
        self.run_store.record(trace)

    def maybe_reap_idle(self) -> tuple[str, ...]:
        """Stop endpoints idle past the configured timeout (never destroys).

        No background daemon: the owner/operator invokes this check.
        """
        now = self._now()
        reaped: list[str] = []
        for alias, endpoint in list(self._active.items()):
            if endpoint.state != "ready":
                continue
            idle_minutes = (
                now - endpoint.last_used_at
            ).total_seconds() / 60
            if idle_minutes >= self.policy.idle_shutdown_minutes:
                result = self.backend.stop(
                    instance_id=endpoint.instance_id,
                    provider_run_id=endpoint.provider_run_id,
                    destroy=False,
                )
                endpoint.state = str(result.get("state") or "stopped")
                reaped.append(alias)
        return tuple(reaped)

    def should_escalate(self, alias: str, consecutive_failures: int) -> bool:
        """AUTO-mode only: recommend Heavy after configured failures."""
        resolve_alias(alias)
        if alias == _HEAVY_ALIAS:
            return False
        if self.policy.mode != "AUTO":
            return False
        if not self.policy.auto_escalation_eligible:
            return False
        return consecutive_failures >= self.policy.heavy_escalation_after_failures

    def status(self, alias: str) -> dict[str, Any]:
        """Public observation — never includes credentials or secrets."""
        resolve_alias(alias)
        endpoint = self._active.get(alias)
        if endpoint is None:
            return {"alias": alias, "state": "stopped", "endpoint": None}
        return {
            "alias": endpoint.alias,
            "state": endpoint.state,
            "provider": endpoint.provider,
            "endpoint": endpoint.endpoint,
            "instance_id": endpoint.instance_id,
            "provider_run_id": endpoint.provider_run_id,
            "gpu_type": endpoint.gpu_type,
            "hourly_price": (
                format(endpoint.hourly_price, "f")
                if endpoint.hourly_price is not None
                else None
            ),
            "provisioned_at": endpoint.provisioned_at.isoformat(),
            "model_ready_at": (
                endpoint.model_ready_at.isoformat()
                if endpoint.model_ready_at is not None
                else None
            ),
            "last_used_at": endpoint.last_used_at.isoformat(),
        }