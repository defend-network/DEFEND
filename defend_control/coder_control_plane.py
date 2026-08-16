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

import hashlib
import json
import socket
import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Callable, Literal

from .coder_deployment import (
    is_exact_revision,
    meets_minimum_vllm_version,
    resolve_deployment,
)
from .coder_m0 import (
    CoderInferenceBackend,
    CoderSmokeResult,
    parse_session_budget,
    resolve_alias,
)
from .types import ResourceProfile, VastOffer

CoderMode = Literal["AUTO", "FAST", "DEFAULT", "HEAVY", "MAXIMUM"]

_HEAVY_ALIAS = "defendcoder-heavy"

# Owner-visible manual live-smoke sequence (LIVE HEAVY SMOKE PREP).
LIVE_SMOKE_SEQUENCE: tuple[str, ...] = (
    "search qualifying Vast offers",
    "select best qualifying offer",
    "print safe public launch plan + exact $/hr",
    "STOP for owner approval",
    "create instance (only after explicit approval)",
    "wait until running",
    "bootstrap pinned FP8 artifact",
    "wait for /v1/models",
    "exact-response smoke: return DEFENDCODER_HEAVY_READY",
    "tool-call smoke",
    "route smoke through CoderControlPlane",
    "capture real trace",
    "verify actual provider hourly rate",
    "stop/destroy instance",
    "report total measured cost",
)


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
    default_min_gpu_ram_mb: int = 81_920
    heavy_min_gpu_ram_mb: int = 81_920
    heavy_num_gpus: int = 2
    default_gpu_families: tuple[str, ...] = (
        "A100",
        "H100",
        "H200",
        "B200",
    )
    heavy_gpu_families: tuple[str, ...] = (
        "H100",
        "H200",
        "B200",
    )
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
        if self.heavy_num_gpus < 1:
            raise ValueError("heavy_num_gpus must be >= 1")
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
            num_gpus=policy.heavy_num_gpus,
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


@dataclass(frozen=True)
class CoderPreflightCheck:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class CoderPreflightReport:
    """Inspectable preflight result — public-safe, no secrets."""

    alias: str
    checks: tuple[CoderPreflightCheck, ...]

    @property
    def all_ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "alias": self.alias,
            "all_ok": self.all_ok,
            "checks": [
                {"name": check.name, "ok": check.ok, "detail": check.detail}
                for check in self.checks
            ],
        }


@dataclass(frozen=True)
class CoderLiveSmokePlan:
    """Exact expected live-smoke configuration/cost — owner approval basis.

    Produced after offer selection so the owner sees the exact selected
    GPU family, provider hourly rate, and estimated max hourly spend.
    """

    alias: str
    logical_repo_id: str
    logical_revision: str
    deployment_repo_id: str
    deployment_revision: str
    precision: str
    provider: str
    gpu_families: tuple[str, ...]
    gpu_family: str | None
    gpu_count: int
    vram_per_gpu_mb: int
    provider_hourly_rate: Decimal | None
    estimated_max_hourly_spend: Decimal
    max_hourly_price_usd: Decimal
    session_budget_usd: Decimal
    max_model_len: int
    tensor_parallel_size: int
    serving_runtime: str
    minimum_vllm_version: str
    tool_call_parser: str | None
    auto_tool_choice: bool
    launch_runtype: str
    local_port: int
    offer_id: int | None
    status: str
    plan_id: str
    plan_hash: str

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "alias": self.alias,
            "logical_repo_id": self.logical_repo_id,
            "logical_revision": self.logical_revision,
            "deployment_repo_id": self.deployment_repo_id,
            "deployment_revision": self.deployment_revision,
            "precision": self.precision,
            "provider": self.provider,
            "gpu_families": list(self.gpu_families),
            "gpu_family": self.gpu_family,
            "gpu_count": self.gpu_count,
            "vram_per_gpu_mb": self.vram_per_gpu_mb,
            "provider_hourly_rate": (
                format(self.provider_hourly_rate, "f")
                if self.provider_hourly_rate is not None
                else None
            ),
            "estimated_max_hourly_spend": format(
                self.estimated_max_hourly_spend, "f"
            ),
            "max_hourly_price_usd": format(self.max_hourly_price_usd, "f"),
            "session_budget_usd": format(self.session_budget_usd, "f"),
            "max_model_len": self.max_model_len,
            "tensor_parallel_size": self.tensor_parallel_size,
            "serving_runtime": self.serving_runtime,
            "minimum_vllm_version": self.minimum_vllm_version,
            "tool_call_parser": self.tool_call_parser,
            "auto_tool_choice": self.auto_tool_choice,
            "launch_runtype": self.launch_runtype,
            "local_port": self.local_port,
            "offer_id": self.offer_id,
            "status": self.status,
            "plan_id": self.plan_id,
            "plan_hash": self.plan_hash,
        }


@dataclass(frozen=True)
class CoderPreparedProvision:
    """Offer-selected plan awaiting owner approval (or already approved)."""

    plan: CoderLiveSmokePlan
    offer: VastOffer | None
    plan_hash: str


@dataclass(frozen=True)
class CoderProvisionApproval:
    """Owner approval token bound to one exact plan hash — no substitutions."""

    approval_id: str
    plan_id: str
    plan_hash: str
    approved_at: datetime
    approver: str = "owner"


def _launch_runtype_for(alias: str) -> str:
    """The documented Vast runtype used at create time for an alias.

    Default and Heavy coder lanes request the documented direct-SSH runtype.
    Other DEFENDcoder lanes retain the documented proxy runtype.
    Binding this into the approval fingerprint means changing the launch
    transport invalidates prior owner approvals.
    """
    return (
        "ssh_direct"
        if alias in ("defendcoder-default", "defendcoder-heavy")
        else "ssh_proxy"
    )


def _plan_fingerprint(plan: CoderLiveSmokePlan, offer: VastOffer | None) -> str:
    """Deterministic hash of every cost/config-relevant plan + offer field."""
    payload: dict[str, object] = {
        "alias": plan.alias,
        "logical_repo_id": plan.logical_repo_id,
        "logical_revision": plan.logical_revision,
        "deployment_repo_id": plan.deployment_repo_id,
        "deployment_revision": plan.deployment_revision,
        "precision": plan.precision,
        "provider": plan.provider,
        "gpu_count": plan.gpu_count,
        "vram_per_gpu_mb": plan.vram_per_gpu_mb,
        "gpu_family": plan.gpu_family,
        "provider_hourly_rate": str(plan.provider_hourly_rate),
        "estimated_max_hourly_spend": str(plan.estimated_max_hourly_spend),
        "max_hourly_price_usd": str(plan.max_hourly_price_usd),
        "session_budget_usd": str(plan.session_budget_usd),
        "max_model_len": plan.max_model_len,
        "tensor_parallel_size": plan.tensor_parallel_size,
        "serving_runtime": plan.serving_runtime,
        "minimum_vllm_version": plan.minimum_vllm_version,
        "tool_call_parser": plan.tool_call_parser,
        "launch_runtype": plan.launch_runtype,
        "local_port": plan.local_port,
    }
    if offer is not None:
        payload.update(
            {
                "offer_id": offer.offer_id,
                "offer_gpu_name": offer.gpu_name,
                "offer_gpu_ram_mb": offer.gpu_ram_mb,
                "offer_dph_total": str(offer.dph_total),
                "offer_reliability": str(offer.reliability),
            }
        )
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _as_decimal(raw: object) -> Decimal | None:
    if raw is None or raw == "":
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


def _default_port_available(port: int) -> bool:
    """Local-only probe: can 127.0.0.1:port be bound? No network egress."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False


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
    token_provider: Callable[[], str | None] | None = None
    port_available: Callable[[int], bool] | None = None
    offer_provider: Callable[[str], tuple[VastOffer, ...]] | None = None
    offer_chooser: Callable[[tuple[VastOffer, ...]], VastOffer] | None = None
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

        report = self.preflight(alias)
        if not report.all_ok:
            failed = ", ".join(
                check.name for check in report.checks if not check.ok
            )
            raise CoderProvisionBlocked(
                f"preflight failed for {alias!r}: {failed}"
            )

        self._authorize_provisioning()

        local_port = self.base_port + len(self._active)
        result = self.backend.start(
            model,
            local_port=local_port,
            session_budget_usd=self.session_budget_usd,
        )
        endpoint = self._endpoint_from_result(alias, now, result)
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

    def preflight(self, alias: str) -> CoderPreflightReport:
        """Validate the whole Heavy (or default) serving contract before any
        billable provisioning. Pure logic — no provider calls, no network.
        """
        checks: list[CoderPreflightCheck] = []

        try:
            resolve_alias(alias)
        except ValueError as exc:
            checks.append(
                CoderPreflightCheck("deployment artifact", False, str(exc))
            )
            return CoderPreflightReport(alias, tuple(checks))

        try:
            artifact = resolve_deployment(alias)
        except ValueError as exc:
            checks.append(
                CoderPreflightCheck("deployment artifact", False, str(exc))
            )
            return CoderPreflightReport(alias, tuple(checks))
        checks.append(
            CoderPreflightCheck(
                "deployment artifact",
                True,
                f"{artifact.repo_id} @ {artifact.revision}",
            )
        )

        checks.append(
            CoderPreflightCheck(
                "exact revision",
                is_exact_revision(artifact.revision),
                artifact.revision,
            )
        )

        runtime_version = (
            artifact.image_tag.removeprefix("v")
            if artifact.image_tag
            else artifact.minimum_vllm_version
        )
        version_ok = meets_minimum_vllm_version(
            runtime_version, artifact.minimum_vllm_version
        )
        checks.append(
            CoderPreflightCheck(
                "supported vLLM version",
                version_ok,
                f"runtime {runtime_version} >= required "
                f"{artifact.minimum_vllm_version}",
            )
        )

        profile = resource_profile(alias, self.policy)
        if artifact.required_min_gpu_ram_mb is None:
            checks.append(
                CoderPreflightCheck(
                    "resource profile",
                    True,
                    f"profile {profile.min_gpu_ram_mb} MB (no artifact minimum)",
                )
            )
        else:
            compatible = (
                profile.min_gpu_ram_mb >= artifact.required_min_gpu_ram_mb
            )
            checks.append(
                CoderPreflightCheck(
                    "resource profile",
                    compatible,
                    f"profile {profile.min_gpu_ram_mb} MB >= artifact "
                    f"minimum {artifact.required_min_gpu_ram_mb} MB",
                )
            )

        context_ok = (
            type(artifact.max_model_len) is int
            and 1 <= artifact.max_model_len <= 131_072
        )
        checks.append(
            CoderPreflightCheck(
                "model context", context_ok, str(artifact.max_model_len)
            )
        )

        token = self.token_provider() if self.token_provider is not None else None
        if artifact.requires_hf_token:
            token_ok = isinstance(token, str) and bool(token)
            checks.append(
                CoderPreflightCheck(
                    "HF token", token_ok, "available" if token_ok else "missing"
                )
            )
        else:
            checks.append(
                CoderPreflightCheck("HF token", True, "not required (public artifact)")
            )

        port = self.base_port + len(self._active)
        port_ok = (
            self.port_available(port)
            if self.port_available is not None
            else _default_port_available(port)
        )
        checks.append(CoderPreflightCheck("local port", port_ok, str(port)))

        budget_ok = self.session_budget_usd > 0
        checks.append(
            CoderPreflightCheck(
                "session budget",
                budget_ok,
                format(self.session_budget_usd, "f"),
            )
        )

        return CoderPreflightReport(alias, tuple(checks))

    def prepared_provision(self, alias: str) -> CoderPreparedProvision:
        """Search qualifying offers, select the best, produce the approval
        basis. Zero provider create calls — inspection/approval only.
        """
        model = resolve_alias(alias)
        artifact = resolve_deployment(alias)
        profile = resource_profile(alias, self.policy)

        offers = self._search_offers(alias, model, profile)
        offer = self._select_offer(offers) if offers else None
        plan = self._build_plan(alias, model, artifact, profile, offer)
        plan_hash = _plan_fingerprint(plan, offer)
        plan = replace(plan, plan_hash=plan_hash)
        return CoderPreparedProvision(
            plan=plan, offer=offer, plan_hash=plan_hash
        )

    def live_smoke_plan(self, alias: str) -> CoderLiveSmokePlan:
        """Convenience: the plan half of a prepared provision."""
        return self.prepared_provision(alias).plan

    def _search_offers(
        self,
        alias: str,
        model: Any,
        profile: ResourceProfile,
    ) -> tuple[VastOffer, ...]:
        if self.offer_provider is not None:
            return tuple(self.offer_provider(alias))
        provider = getattr(self.backend, "search_offers_for", None)
        if provider is None:
            return ()
        return tuple(provider(model, profile))

    def _select_offer(self, offers: tuple[VastOffer, ...]) -> VastOffer:
        if self.offer_chooser is not None:
            return self.offer_chooser(offers)
        return min(offers, key=lambda offer: (offer.dph_total, offer.offer_id))

    def _build_plan(
        self,
        alias: str,
        model: Any,
        artifact: Any,
        profile: ResourceProfile,
        offer: VastOffer | None,
    ) -> CoderLiveSmokePlan:
        rate = offer.dph_total if offer is not None else None
        max_spend = rate if rate is not None else self.policy.max_hourly_usd
        return CoderLiveSmokePlan(
            alias=alias,
            logical_repo_id=model.repo_id,
            logical_revision=model.revision,
            deployment_repo_id=artifact.repo_id,
            deployment_revision=artifact.revision,
            precision=artifact.precision,
            provider="vast",
            gpu_families=profile.allowed_gpu_families,
            gpu_family=offer.gpu_name if offer is not None else None,
            gpu_count=profile.num_gpus,
            vram_per_gpu_mb=profile.min_gpu_ram_mb,
            provider_hourly_rate=rate,
            estimated_max_hourly_spend=max_spend,
            max_hourly_price_usd=self.policy.max_hourly_usd,
            session_budget_usd=self.session_budget_usd,
            max_model_len=artifact.max_model_len,
            tensor_parallel_size=artifact.tensor_parallel_size,
            serving_runtime=f"vllm/vllm-openai:{artifact.image_tag}",
            minimum_vllm_version=artifact.minimum_vllm_version,
            tool_call_parser=artifact.tool_call_parser,
            auto_tool_choice=artifact.enable_auto_tool_choice,
            launch_runtype=_launch_runtype_for(alias),
            local_port=self.base_port + len(self._active),
            offer_id=offer.offer_id if offer is not None else None,
            status="requires_approval",
            plan_id=uuid.uuid4().hex,
            plan_hash="",
        )

    def approve(self, prepared: CoderPreparedProvision) -> CoderProvisionApproval:
        """Owner approval: binds to the exact plan hash; rejects over-budget."""
        if prepared.plan.status != "requires_approval":
            raise ValueError("plan is not awaiting approval")
        if prepared.plan.estimated_max_hourly_spend > self.policy.max_hourly_usd:
            raise ValueError(
                f"offer exceeds max hourly budget "
                f"{format(self.policy.max_hourly_usd, 'f')}"
            )
        if (
            prepared.offer is not None
            and prepared.offer.dph_total > self.policy.max_hourly_usd
        ):
            raise ValueError(
                f"offer {prepared.offer.offer_id} hourly rate exceeds budget "
                f"{format(self.policy.max_hourly_usd, 'f')}"
            )
        return CoderProvisionApproval(
            approval_id=uuid.uuid4().hex,
            plan_id=prepared.plan.plan_id,
            plan_hash=prepared.plan_hash,
            approved_at=self._now(),
        )

    def provision(
        self,
        prepared: CoderPreparedProvision,
        approval: CoderProvisionApproval | None,
    ) -> EndpointLease:
        """Provision ONLY with a valid approval bound to this exact plan."""
        if approval is None:
            raise CoderProvisionBlocked(
                "owner approval required before provisioning"
            )
        current_hash = _plan_fingerprint(prepared.plan, prepared.offer)
        if current_hash != approval.plan_hash:
            raise CoderProvisionBlocked(
                "approval no longer matches the current plan; re-approve"
            )
        if approval.plan_id != prepared.plan.plan_id:
            raise CoderProvisionBlocked("approval does not match the plan")

        alias = prepared.plan.alias
        report = self.preflight(alias)
        if not report.all_ok:
            failed = ", ".join(
                check.name for check in report.checks if not check.ok
            )
            raise CoderProvisionBlocked(
                f"preflight failed for {alias!r}: {failed}"
            )
        self._authorize_provisioning()

        model = resolve_alias(alias)
        profile = resource_profile(alias, self.policy)
        now = self._now()
        result = self.backend.start(
            model,
            local_port=prepared.plan.local_port,
            session_budget_usd=self.session_budget_usd,
            offer=prepared.offer,
            profile=profile,
        )
        endpoint = self._endpoint_from_result(alias, now, result)
        self._active[alias] = endpoint
        return EndpointLease(
            alias=alias,
            endpoint=endpoint.endpoint,
            instance_id=endpoint.instance_id,
            provider_run_id=endpoint.provider_run_id,
            reused=False,
        )

    def _endpoint_from_result(
        self, alias: str, now: datetime, result: dict[str, Any]
    ) -> ActiveCoderEndpoint:
        state = str(result.get("state") or "ready")
        return ActiveCoderEndpoint(
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