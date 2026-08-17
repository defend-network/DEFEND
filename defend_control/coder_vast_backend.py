"""Vast-backed inference provider for DEFENDcoder M0.1.

Implements CoderInferenceBackend. Does not start API/UI/Cloudflare or touch
identity chat orchestration. Owner must still confirm pricing/fingerprint at
the Control Center layer when wiring UI (M0.1 core stays injectable).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .coder_deployment import resolve_deployment
from .coder_m0 import CoderModelRef
from .coder_provisioning import (
    CoderProvisionFailure,
    persist_failure_record,
)
from .coder_remote_vllm import CoderRemoteVllmBootstrap, CoderRemoteVllmError
from .types import LaunchSpec, ResourceProfile, VastInstance, VastOffer
from .vast import (
    VastClient,
    VastDestructionPendingError,
    VastDestructionRequestFailedError,
    VastDestructionUnverifiedError,
    VastError,
)
from .vast_diagnostics import (
    DirectEndpointProbe,
    DirectEndpointState,
    wait_for_direct_endpoint,
)


class CoderVastBackendError(RuntimeError):
    """Safe coder Vast failure — no provider bodies or secrets.

    category is a machine-readable error class so the UI can distinguish
    no-qualifying-offer / credit / auth / create-rejection / timeout /
    bootstrap / tunnel failures without parsing prose.

    phase names the provisioning phase that failed; failure carries the
    sanitized structured CoderProvisionFailure record built before
    teardown. The original exception is preserved through __cause__
    chaining for internal diagnosis while the message stays sanitized.
    """

    def __init__(
        self,
        message: str,
        *,
        category: str = "provider",
        phase: str | None = None,
        failure: CoderProvisionFailure | None = None,
    ) -> None:
        super().__init__(message)
        self.category = str(category)
        self.phase = phase
        self.failure = failure


PROVIDER_ERROR_CATEGORIES: tuple[str, ...] = (
    "no_qualifying_offer",
    "insufficient_credit",
    "auth",
    "api",
    "rate_limited",
    "create_rejected",
    "endpoint_timeout",
    "bootstrap",
    "tunnel",
    "rate_exceeded",
    "provider",
)


def classify_vast_error(
    error: BaseException,
    *,
    creating: bool = False,
) -> str:
    """Map a provider failure to a sanitized category.

    Uses only status codes and curated safe messages — never API keys,
    provider bodies, or secrets.
    """
    status = getattr(error, "status_code", None)
    if isinstance(status, int):
        if status == 401:
            return "auth"
        if status == 402:
            return "insufficient_credit"
        if status == 429:
            return "rate_limited"
        if 400 <= status < 500:
            return "create_rejected" if creating else "api"
        if status >= 500:
            return "api"
    text = str(error).casefold()
    if "credit" in text:
        return "insufficient_credit"
    if "no eligible coder gpu offers" in text:
        return "no_qualifying_offer"
    if "offer is no longer rentable" in text:
        return "create_rejected"
    if "not listening" in text or "tunnel" in text:
        return "tunnel"
    if "direct ssh endpoint unavailable" in text:
        return "endpoint_timeout"
    if "timed out" in text or "timeout" in text:
        return "endpoint_timeout"
    return "provider"


@dataclass
class VastCoderBackend:
    """Provision coder GPU, bootstrap plain vLLM, expose loopback endpoint."""

    vast: VastClient
    secrets: Mapping[str, str]
    bootstrap: CoderRemoteVllmBootstrap
    max_hourly: Decimal
    profile: ResourceProfile | None = None
    launch: LaunchSpec | None = None
    remote_port: int = 8000
    tunnel_start: Callable[[VastInstance, int, bool], str] | None = None
    host_prepare: Callable[[VastInstance, bool], None] | None = None
    # tunnel_start(instance, local_port, prefer_direct) -> local endpoint
    # e.g. http://127.0.0.1:8003/v1; prefer_direct=True only for ssh_direct
    # plans (direct endpoint), False for ssh_proxy plans (Vast proxy hop)
    local_verify: Callable[[str], bool] | None = None
    # local_verify(endpoint) -> True only when the local forward actually listens
    direct_endpoint_wait_seconds: float = 300.0
    direct_endpoint_poll_seconds: float = 10.0
    smoke_http: Callable[[str, str, CoderModelRef], dict[str, Any]] | None = None
    offer_chooser: Callable[[tuple[VastOffer, ...]], VastOffer] | None = None
    log: Callable[[str], None] | None = None
    failure_directory: str | None = None
    # lifecycle log sink; the owner UI renders timestamped transitions
    last_direct_probe: DirectEndpointProbe | None = field(
        default=None, init=False
    )
    last_provision_failure: CoderProvisionFailure | None = field(
        default=None, init=False
    )
    _last_instance_id: int | None = field(default=None, init=False)
    _last_gpu_name: str | None = field(default=None, init=False)
    _last_approved_rate: Decimal | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if self.profile is None:
            object.__setattr__(self, "profile", ResourceProfile.coder_default())
        if self.launch is None:
            object.__setattr__(self, "launch", LaunchSpec.coder_default())
        if self.launch is None or self.launch.label != "defendcoder-vllm":
            raise ValueError("coder backend requires defendcoder-vllm launch label")
        if (
            isinstance(self.direct_endpoint_wait_seconds, bool)
            or not isinstance(self.direct_endpoint_wait_seconds, (int, float))
            or not 0 < float(self.direct_endpoint_wait_seconds) <= 3600
        ):
            raise ValueError("direct endpoint wait must be in (0, 3600] seconds")
        if (
            isinstance(self.direct_endpoint_poll_seconds, bool)
            or not isinstance(self.direct_endpoint_poll_seconds, (int, float))
            or not 0 < float(self.direct_endpoint_poll_seconds) <= 60
        ):
            raise ValueError("direct endpoint poll must be in (0, 60] seconds")

    def resume_candidate(
        self,
        *,
        launch_runtype: str,
        approved_ceiling: Decimal,
    ) -> VastInstance | None:
        """A single running labeled instance compatible with this launch.

        Reuse/resume contract (fail closed, zero spend):
        - no labeled instances -> None (fresh provisioning may proceed)
        - exactly one running instance matching the runtype AND the
          owner-approved hourly ceiling -> that instance
        - anything else (multiple candidates, wrong runtype, over budget,
          stopped/ambiguous states, listing failure) -> raises, so a
          duplicate billable instance is NEVER created while the fleet
          label is in an uncertain state.
        """
        if launch_runtype not in ("ssh_direct", "ssh_proxy"):
            raise CoderVastBackendError("launch_runtype is invalid")
        try:
            labeled_ids = self.vast.list_labeled_instance_ids(
                LaunchSpec.coder_default().label
            )
        except VastError as exc:
            raise CoderVastBackendError(
                f"cannot verify existing coder instances: {exc}",
                category=classify_vast_error(exc),
            ) from exc

        running: list[VastInstance] = []
        for instance_id in labeled_ids:
            try:
                instance = self.vast.show_instance(instance_id)
            except VastError as exc:
                raise CoderVastBackendError(
                    f"cannot verify existing coder instance {instance_id}: {exc}",
                    category=classify_vast_error(exc),
                ) from exc
            if instance.actual_status != "running":
                raise CoderVastBackendError(
                    f"coder instance {instance_id} exists but is not running "
                    f"(state={instance.actual_status or 'unknown'}); "
                    "reconcile manually before launching",
                    category="duplicate_runtime",
                )
            if instance.image_runtype not in (None, launch_runtype):
                raise CoderVastBackendError(
                    f"coder instance {instance_id} runs "
                    f"{instance.image_runtype or 'unknown'}, not "
                    f"{launch_runtype}; reconcile manually before launching",
                    category="duplicate_runtime",
                )
            if instance.dph_total > approved_ceiling:
                raise CoderVastBackendError(
                    f"coder instance {instance_id} actual rate "
                    f"{format(instance.dph_total, 'f')} exceeds approved "
                    f"ceiling {format(approved_ceiling, 'f')}; reconcile "
                    "manually before launching",
                    category="rate_exceeded",
                )
            running.append(instance)

        if len(running) > 1:
            raise CoderVastBackendError(
                "multiple running coder instances; reconcile manually "
                "before launching",
                category="duplicate_runtime",
            )
        return running[0] if running else None

    def search_offers_for(
        self,
        model: CoderModelRef,
        profile: ResourceProfile,
        *,
        launch_runtype: str | None = None,
    ) -> tuple[VastOffer, ...]:
        """Qualifying offers only: profile num_gpus/VRAM/families/reliability
        enforced by VastClient.search_offers under max_hourly. No creation.

        Runtype-aware: ssh_direct searches additionally require
        direct_port_count >= 1 (provider capability filter, best-effort —
        never a guarantee); ssh_proxy searches omit it entirely.
        """
        del model
        prefer_direct = launch_runtype == "ssh_direct"
        try:
            return self.vast.search_offers(
                self.max_hourly,
                profile,
                require_direct_ports=prefer_direct,
            )
        except VastError as exc:
            raise CoderVastBackendError(
                str(exc),
                category=classify_vast_error(exc),
            ) from exc

    def offer_search_diagnostics(
        self,
    ) -> tuple[int, int, tuple[tuple[str, int], ...]]:
        """(provider returned, eligible, rejection counts) of the last
        search — sanitized counts only, never raw payloads or credentials.
        """
        provider = getattr(self.vast, "last_search_counts", None)
        if provider is None:
            return (0, 0, ())
        return provider()

    def start(
        self,
        model: CoderModelRef,
        *,
        local_port: int,
        session_budget_usd: Decimal,
        offer: VastOffer | None = None,
        profile: ResourceProfile | None = None,
        cancelled: Callable[[], bool] | None = None,
        launch_runtype: str | None = None,
        resume_instance: VastInstance | None = None,
    ) -> dict[str, Any]:
        del session_budget_usd  # enforced by CoderM0Service / Control Center
        if type(local_port) is not int or not 1 <= local_port <= 65_535:
            raise CoderVastBackendError("local_port is invalid")
        if offer is not None and not isinstance(offer, VastOffer):
            raise CoderVastBackendError("offer must be a VastOffer")
        if launch_runtype is not None and launch_runtype not in (
            "ssh_direct",
            "ssh_proxy",
        ):
            raise CoderVastBackendError("launch_runtype is invalid")

        # F1: fail closed BEFORE any billable spend when no local forward can
        # be established — never fabricate a localhost endpoint.
        if self.tunnel_start is None:
            raise CoderVastBackendError(
                "no local tunnel configured; cannot expose a coder endpoint"
            )
        if resume_instance is not None and not isinstance(
            resume_instance, VastInstance
        ):
            raise CoderVastBackendError("resume instance must be a VastInstance")

        # Duplicate-launch guard: while any labeled coder instance exists in
        # an uncertain state, refuse to create a second billable runtime.
        # The only clean path to a fresh instance is a prior destroy.
        candidate = self.resume_candidate(
            launch_runtype=launch_runtype or "ssh_proxy",
            approved_ceiling=(
                offer.dph_total if offer is not None else self.max_hourly
            ),
        )
        if resume_instance is None and candidate is not None:
            raise CoderVastBackendError(
                f"compatible coder instance {candidate.instance_id} is "
                "already running; resume it instead of creating a duplicate",
                category="duplicate_runtime",
            )

        if offer is not None:
            offers: tuple[VastOffer, ...] = (offer,)
        else:
            resolved_profile = profile if profile is not None else self.profile
            try:
                offers = self.vast.search_offers(
                    self.max_hourly,
                    resolved_profile,
                    require_direct_ports=(launch_runtype == "ssh_direct"),
                )
            except VastError as exc:
                raise CoderVastBackendError(
                    str(exc),
                    category=classify_vast_error(exc),
                ) from exc
        if not offers:
            raise CoderVastBackendError(
                "no eligible coder GPU offers under budget",
                category="no_qualifying_offer",
            )

        offer = self.offer_chooser(offers) if self.offer_chooser else offers[0]
        artifact = resolve_deployment(model.alias)
        prefer_direct = launch_runtype == "ssh_direct"
        launch = LaunchSpec(
            image=f"vllm/vllm-openai:{artifact.image_tag}",
            disk_gb=160,
            runtype=(
                launch_runtype
                if launch_runtype is not None
                else "ssh_proxy"
            ),
            label="defendcoder-vllm",
        )
        self.last_provision_failure = None
        started = time.perf_counter()
        instance_id: int | None = None
        gpu_name: str | None = None
        approved_rate = (
            offer.dph_total if offer is not None else self.max_hourly
        )

        def fail(
            phase: str,
            exc: BaseException | None = None,
            message: str | None = None,
            *,
            category: str = "provider",
            endpoint_state: str | None = None,
            ssh_state: str | None = None,
            bootstrap_state: str | None = None,
            vllm_state: str | None = None,
            readiness_state: str | None = None,
        ) -> CoderVastBackendError:
            """Build the sanitized failure record, tear down, then raise."""
            text = (
                message
                if message is not None
                else (str(exc) if exc is not None else "provisioning failed")
            )
            snapshot = getattr(self.vast, "last_raw_payload", None)
            show_snapshot = snapshot("show") if callable(snapshot) else None
            direct_port_count = (
                getattr(offer, "direct_port_count", None)
                if offer is not None
                else None
            )
            self.last_provision_failure = CoderProvisionFailure(
                phase=phase,
                exception_type=(
                    type(exc).__name__ if exc is not None else "CoderVastBackendError"
                ),
                sanitized_message=text,
                instance_id=instance_id,
                gpu_name=gpu_name,
                approved_hourly_rate=approved_rate,
                elapsed_seconds=time.perf_counter() - started,
                endpoint_state=endpoint_state,
                ssh_state=ssh_state,
                bootstrap_state=bootstrap_state,
                vllm_state=vllm_state,
                readiness_state=readiness_state,
                direct_port_count=direct_port_count,
                show_snapshot=show_snapshot,
            )
            self._persist_failure()
            if instance_id is not None:
                self._destroy_owned(instance_id)
            error = CoderVastBackendError(
                text,
                category=category,
                phase=phase,
                failure=self.last_provision_failure,
            )
            if exc is not None:
                raise error from exc
            raise error

        try:
            if resume_instance is not None:
                self._log(
                    f"resuming existing instance: "
                    f"{resume_instance.instance_id}"
                )
                instance = self.vast.show_instance(
                    resume_instance.instance_id
                )
                instance_id = instance.instance_id
                gpu_name = instance.gpu_name
            else:
                self._log("creating Vast instance")
                instance = self.vast.create_instance(offer, launch)
                instance_id = instance.instance_id
                gpu_name = instance.gpu_name
                self._log(f"instance created: {instance_id}")
                instance = self.vast.wait_until_running(
                    instance.instance_id
                )
            self._last_instance_id = instance_id
            self._last_gpu_name = gpu_name
            self._last_approved_rate = approved_rate
        except VastError as exc:
            raise fail(
                "instance_create" if instance_id is None else "instance_running_wait",
                exc,
                category=classify_vast_error(exc, creating=True),
            )

        self._log(f"provider state: {instance.actual_status or 'running'}")

        # F3: post-creation rate verification against the owner-approved basis.
        # The actual provider rate comes from the show payload, not the offer.
        approved_ceiling = offer.dph_total if offer is not None else self.max_hourly
        if instance.dph_total > approved_ceiling:
            raise fail(
                "instance_running_wait",
                message=(
                    f"actual provider rate {format(instance.dph_total, 'f')} "
                    f"exceeds approved rate {format(approved_ceiling, 'f')}; "
                    "instance destroyed"
                ),
                category="rate_exceeded",
            )

        # F2: for ssh_direct launches, wait for the provider to publish real
        # direct-endpoint metadata; never silently fall back to the proxy hop.
        if launch.runtype == "ssh_direct":
            self._log("waiting for direct SSH endpoint")
            probe = wait_for_direct_endpoint(
                self.vast,
                instance.instance_id,
                max_wait_seconds=self.direct_endpoint_wait_seconds,
                poll_interval_seconds=self.direct_endpoint_poll_seconds,
                cancelled=cancelled,
            )
            self.last_direct_probe = probe
            if probe.state is not DirectEndpointState.ENDPOINT_AVAILABLE:
                raise fail(
                    "direct_endpoint_wait",
                    message=(
                        "direct SSH endpoint unavailable after "
                        f"{probe.elapsed_seconds:.0f}s "
                        f"(attempt {probe.attempt}, state={probe.state.value}); "
                        "instance destroyed"
                    ),
                    category="endpoint_timeout",
                    endpoint_state=probe.state.value,
                )
            self._log("direct endpoint discovered")
            try:
                instance = self.vast.show_instance(instance.instance_id)
            except VastError as exc:
                raise fail(
                    "direct_endpoint_wait",
                    exc,
                    category=classify_vast_error(exc, creating=True),
                    endpoint_state=DirectEndpointState.ENDPOINT_AVAILABLE.value,
                )

        self._log("preparing SSH host identity")
        if self.host_prepare is not None:
            try:
                self.host_prepare(instance, prefer_direct)
            except Exception as exc:
                raise fail(
                    "ssh_connect",
                    f"SSH host preparation failed ({type(exc).__name__})",
                ) from None

        self._log("testing SSH")
        try:
            self.bootstrap.start(
                instance,
                model,
                self.secrets,
                remote_port=self.remote_port,
                artifact=artifact,
                prefer_direct=prefer_direct,
                cancelled=cancelled,
            )
        except CoderRemoteVllmError as exc:
            phase = getattr(exc, "phase", None) or "ssh_connect"
            reached = getattr(self.bootstrap, "last_stages", ())
            raise fail(
                phase,
                exc,
                category="bootstrap",
                ssh_state=(
                    "failed" if phase == "ssh_connect" else "ready"
                ),
                bootstrap_state=reached[-1] if reached else None,
                vllm_state=(
                    phase
                    if phase
                    in (
                        "container_start",
                        "vllm_start",
                        "model_load",
                        "health_wait",
                    )
                    else None
                ),
                readiness_state="not_ready",
            )
        self._log("SSH ready")
        for stage in getattr(self.bootstrap, "last_stages", ()):
            self._log(f"remote stage: {stage}")

        # F1: the local forward must be established AND actually listening
        # before "ready" is reported. Any tunnel failure destroys the owned
        # instance — fail closed, never report a fabricated endpoint.
        self._log("starting local SSH tunnel")
        try:
            endpoint = self._establish_local_endpoint(instance, local_port)
            if not self._local_listening(endpoint):
                raise CoderVastBackendError(
                    f"local coder endpoint {endpoint} is not listening; "
                    "instance destroyed",
                    category="tunnel",
                )
        except CoderVastBackendError as exc:
            raise fail(
                "ssh_tunnel",
                exc,
                category=exc.category,
                ssh_state="ready",
                vllm_state="ready",
                readiness_state="ready",
            )
        self._log("local tunnel listening")

        return {
            "state": "ready",
            "endpoint": endpoint,
            "instance_id": instance.instance_id,
            "provider_run_id": f"vast-{instance.instance_id}",
            "hourly_price": format(instance.dph_total, "f"),
            "message": (
                f"coder ready on {instance.gpu_name} "
                f"({instance.gpu_ram_mb} MB) alias={model.alias}"
            ),
        }

    def _log(self, line: str) -> None:
        if self.log is not None:
            try:
                self.log(line)
            except Exception:
                pass

    def _destroy_owned(self, instance_id: int) -> None:
        try:
            self.vast.destroy_instance(
                instance_id, confirmed_instance_id=instance_id
            )
        except Exception as exc:
            if self.last_provision_failure is not None:
                self.last_provision_failure = (
                    self.last_provision_failure.with_cleanup(
                        self._cleanup_state_for(exc)
                    )
                )
                self._persist_failure()
            return
        if self.last_provision_failure is not None:
            self.last_provision_failure = self.last_provision_failure.with_cleanup(
                "destroyed"
            )
            self._persist_failure()

    def _persist_failure(self) -> None:
        if self.last_provision_failure is None:
            return
        try:
            persist_failure_record(
                self.last_provision_failure,
                directory=self.failure_directory,
            )
        except Exception:
            pass

    @staticmethod
    def _cleanup_state_for(exc: BaseException) -> str:
        if isinstance(exc, VastDestructionPendingError):
            return "destroy_pending"
        if isinstance(exc, VastDestructionUnverifiedError):
            return "destroy_verification_failed"
        if isinstance(exc, VastDestructionRequestFailedError):
            return "destroy_request_failed"
        return "destroy_request_failed"

    def _establish_local_endpoint(
        self, instance: VastInstance, local_port: int
    ) -> str:
        if self.tunnel_start is None:
            raise CoderVastBackendError(
                "no local tunnel configured for coder endpoint",
                category="tunnel",
            )
        try:
            endpoint = self.tunnel_start(
                instance,
                local_port,
                prefer_direct=(self.launch.runtype == "ssh_direct"),
            )
        except Exception as exc:
            raise CoderVastBackendError(
                f"local tunnel failed to establish ({type(exc).__name__})",
                category="tunnel",
            ) from exc
        if not isinstance(endpoint, str) or not endpoint:
            raise CoderVastBackendError(
                "local tunnel returned no endpoint",
                category="tunnel",
            )
        if not _is_loopback_endpoint(endpoint, local_port):
            raise CoderVastBackendError(
                "local tunnel endpoint is not a loopback URL on the expected port",
                category="tunnel",
            )
        return endpoint

    def _local_listening(self, endpoint: str) -> bool:
        if self.local_verify is not None:
            return bool(self.local_verify(endpoint))
        return _default_local_listening(endpoint)

    def smoke(self, endpoint: str, model: CoderModelRef) -> dict[str, Any]:
        if self.smoke_http is not None:
            result = self.smoke_http(endpoint, self._api_key(), model)
        else:
            result = _default_smoke(endpoint, self._api_key(), model)
        if not isinstance(result, dict) or not bool(result.get("ok")):
            detail = (
                str(result.get("detail"))
                if isinstance(result, dict) and result.get("detail")
                else "smoke failed"
            )
            self.last_provision_failure = CoderProvisionFailure(
                phase="openai_smoke",
                exception_type="CoderSmokeFailure",
                sanitized_message=detail,
                instance_id=self._last_instance_id,
                gpu_name=self._last_gpu_name,
                approved_hourly_rate=self._last_approved_rate,
                elapsed_seconds=0.0,
                endpoint_state="ready",
                ssh_state="ready",
                bootstrap_state="ready",
                vllm_state="ready",
                readiness_state=detail,
            )
        return result

    def stop(
        self,
        *,
        instance_id: int | None,
        provider_run_id: str | None,
        destroy: bool,
    ) -> dict[str, Any]:
        del provider_run_id
        if instance_id is None:
            return {"state": "stopped", "message": "no coder instance to stop"}
        if destroy:
            self._log(f"destroying instance {instance_id}")
            try:
                self.vast.destroy_instance(
                    instance_id, confirmed_instance_id=instance_id
                )
            except VastError as exc:
                if self.last_provision_failure is not None:
                    self.last_provision_failure = (
                        self.last_provision_failure.with_cleanup(
                            self._cleanup_state_for(exc)
                        )
                    )
                    self._persist_failure()
                raise CoderVastBackendError(str(exc)) from exc
            self._log("cleanup confirmed")
            if self.last_provision_failure is not None:
                self.last_provision_failure = (
                    self.last_provision_failure.with_cleanup("destroyed")
                )
                self._persist_failure()
            return {
                "state": "stopped",
                "message": f"coder instance {instance_id} destroyed",
                "instance_id": instance_id,
            }
        try:
            self.vast.set_state(instance_id, "stopped")
        except VastError as exc:
            raise CoderVastBackendError(str(exc)) from exc
        return {
            "state": "stopped",
            "message": (
                f"coder instance {instance_id} stopped; "
                "storage billing may continue until destroy"
            ),
            "instance_id": instance_id,
        }

    def _api_key(self) -> str:
        key = self.secrets.get("CODER_VLLM_API_KEY") or self.secrets.get("VLLM_API_KEY")
        if not isinstance(key, str) or not key:
            raise CoderVastBackendError("CODER_VLLM_API_KEY is missing")
        return key


_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1", "0:0:0:0:0:0:0:1")


def _is_loopback_endpoint(endpoint: str, expected_port: int) -> bool:
    try:
        parsed = urllib.parse.urlsplit(endpoint)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return False
    if parsed.scheme != "http" or host is None or port is None:
        return False
    return host in _LOOPBACK_HOSTS and port == expected_port


def _default_local_listening(
    endpoint: str, *, attempts: int = 6, retry_seconds: float = 1.0
) -> bool:
    try:
        parsed = urllib.parse.urlsplit(endpoint)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return False
    if host is None or port is None:
        return False
    for _ in range(attempts):
        try:
            with socket.create_connection((host, port), timeout=2.0):
                return True
        except OSError:
            time.sleep(retry_seconds)
    return False


def _default_smoke(endpoint: str, api_key: str, model: CoderModelRef) -> dict[str, Any]:
    url = endpoint.rstrip("/") + "/models"
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        },
        method="GET",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read(4096)
            status = int(getattr(response, "status", 200))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return {
            "ok": False,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "detail": f"smoke transport failed ({type(exc).__name__})",
        }
    latency = int((time.perf_counter() - started) * 1000)
    if status < 200 or status >= 300:
        return {
            "ok": False,
            "latency_ms": latency,
            "detail": f"smoke HTTP {status}",
        }
    return {
        "ok": True,
        "latency_ms": latency,
        "detail": f"models endpoint ok for {model.alias} ({len(body)} bytes)",
    }
