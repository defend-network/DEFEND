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
from .coder_remote_vllm import CoderRemoteVllmBootstrap, CoderRemoteVllmError
from .types import LaunchSpec, ResourceProfile, VastInstance, VastOffer
from .vast import VastClient, VastError
from .vast_diagnostics import (
    DirectEndpointProbe,
    DirectEndpointState,
    wait_for_direct_endpoint,
)


class CoderVastBackendError(RuntimeError):
    """Safe coder Vast failure — no provider bodies or secrets."""


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
    tunnel_start: Callable[[VastInstance, int], str] | None = None
    # tunnel_start(instance, local_port) -> local endpoint e.g. http://127.0.0.1:8003/v1
    local_verify: Callable[[str], bool] | None = None
    # local_verify(endpoint) -> True only when the local forward actually listens
    direct_endpoint_wait_seconds: float = 300.0
    direct_endpoint_poll_seconds: float = 10.0
    smoke_http: Callable[[str, str, CoderModelRef], dict[str, Any]] | None = None
    offer_chooser: Callable[[tuple[VastOffer, ...]], VastOffer] | None = None
    last_direct_probe: DirectEndpointProbe | None = field(
        default=None, init=False
    )

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

    def search_offers_for(
        self, model: CoderModelRef, profile: ResourceProfile
    ) -> tuple[VastOffer, ...]:
        """Qualifying offers only: profile num_gpus/VRAM/families/reliability
        enforced by VastClient.search_offers under max_hourly. No creation.
        """
        del model
        try:
            return self.vast.search_offers(self.max_hourly, profile)
        except VastError as exc:
            raise CoderVastBackendError(str(exc)) from None

    def start(
        self,
        model: CoderModelRef,
        *,
        local_port: int,
        session_budget_usd: Decimal,
        offer: VastOffer | None = None,
        profile: ResourceProfile | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        del session_budget_usd  # enforced by CoderM0Service / Control Center
        if type(local_port) is not int or not 1 <= local_port <= 65_535:
            raise CoderVastBackendError("local_port is invalid")
        if offer is not None and not isinstance(offer, VastOffer):
            raise CoderVastBackendError("offer must be a VastOffer")

        # F1: fail closed BEFORE any billable spend when no local forward can
        # be established — never fabricate a localhost endpoint.
        if self.tunnel_start is None:
            raise CoderVastBackendError(
                "no local tunnel configured; cannot expose a coder endpoint"
            )

        if offer is not None:
            offers: tuple[VastOffer, ...] = (offer,)
        else:
            resolved_profile = profile if profile is not None else self.profile
            try:
                offers = self.vast.search_offers(self.max_hourly, resolved_profile)
            except VastError as exc:
                raise CoderVastBackendError(str(exc)) from None
        if not offers:
            raise CoderVastBackendError("no eligible coder GPU offers under budget")

        offer = self.offer_chooser(offers) if self.offer_chooser else offers[0]
        artifact = resolve_deployment(model.alias)
        prefer_direct = model.alias in (
            "defendcoder-default",
            "defendcoder-heavy",
        )
        launch = LaunchSpec(
            image=f"vllm/vllm-openai:{artifact.image_tag}",
            disk_gb=160,
            runtype="ssh_direct" if prefer_direct else "ssh_proxy",
            label="defendcoder-vllm",
        )
        try:
            instance = self.vast.create_instance(offer, launch)
            instance = self.vast.wait_until_running(instance.instance_id)
        except VastError as exc:
            raise CoderVastBackendError(str(exc)) from None

        # F3: post-creation rate verification against the owner-approved basis.
        # The actual provider rate comes from the show payload, not the offer.
        approved_ceiling = offer.dph_total if offer is not None else self.max_hourly
        if instance.dph_total > approved_ceiling:
            self._destroy_owned(instance.instance_id)
            raise CoderVastBackendError(
                f"actual provider rate {format(instance.dph_total, 'f')} "
                f"exceeds approved rate {format(approved_ceiling, 'f')}; "
                "instance destroyed"
            )

        # F2: for ssh_direct launches, wait for the provider to publish real
        # direct-endpoint metadata; never silently fall back to the proxy hop.
        if launch.runtype == "ssh_direct":
            probe = wait_for_direct_endpoint(
                self.vast,
                instance.instance_id,
                max_wait_seconds=self.direct_endpoint_wait_seconds,
                poll_interval_seconds=self.direct_endpoint_poll_seconds,
                cancelled=cancelled,
            )
            self.last_direct_probe = probe
            if probe.state is not DirectEndpointState.ENDPOINT_AVAILABLE:
                self._destroy_owned(instance.instance_id)
                raise CoderVastBackendError(
                    "direct SSH endpoint unavailable after "
                    f"{probe.elapsed_seconds:.0f}s "
                    f"(attempt {probe.attempt}, state={probe.state.value}); "
                    "instance destroyed"
                )
            try:
                instance = self.vast.show_instance(instance.instance_id)
            except VastError as exc:
                self._destroy_owned(instance.instance_id)
                raise CoderVastBackendError(str(exc)) from None

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
            self._destroy_owned(instance.instance_id)
            raise CoderVastBackendError(str(exc)) from None

        # F1: the local forward must be established AND actually listening
        # before "ready" is reported. Any tunnel failure destroys the owned
        # instance — fail closed, never report a fabricated endpoint.
        try:
            endpoint = self._establish_local_endpoint(instance, local_port)
            if not self._local_listening(endpoint):
                raise CoderVastBackendError(
                    f"local coder endpoint {endpoint} is not listening; "
                    "instance destroyed"
                )
        except CoderVastBackendError:
            self._destroy_owned(instance.instance_id)
            raise

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

    def _destroy_owned(self, instance_id: int) -> None:
        try:
            self.vast.destroy_instance(
                instance_id, confirmed_instance_id=instance_id
            )
        except Exception:
            pass

    def _establish_local_endpoint(
        self, instance: VastInstance, local_port: int
    ) -> str:
        if self.tunnel_start is None:
            raise CoderVastBackendError("no local tunnel configured for coder endpoint")
        try:
            endpoint = self.tunnel_start(instance, local_port)
        except Exception as exc:
            raise CoderVastBackendError(
                f"local tunnel failed to establish ({type(exc).__name__})"
            ) from None
        if not isinstance(endpoint, str) or not endpoint:
            raise CoderVastBackendError("local tunnel returned no endpoint")
        if not _is_loopback_endpoint(endpoint, local_port):
            raise CoderVastBackendError(
                "local tunnel endpoint is not a loopback URL on the expected port"
            )
        return endpoint

    def _local_listening(self, endpoint: str) -> bool:
        if self.local_verify is not None:
            return bool(self.local_verify(endpoint))
        return _default_local_listening(endpoint)

    def smoke(self, endpoint: str, model: CoderModelRef) -> dict[str, Any]:
        if self.smoke_http is not None:
            return self.smoke_http(endpoint, self._api_key(), model)
        return _default_smoke(endpoint, self._api_key(), model)

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
            try:
                self.vast.destroy_instance(
                    instance_id, confirmed_instance_id=instance_id
                )
            except VastError as exc:
                raise CoderVastBackendError(str(exc)) from None
            return {
                "state": "stopped",
                "message": f"coder instance {instance_id} destroyed",
                "instance_id": instance_id,
            }
        try:
            self.vast.set_state(instance_id, "stopped")
        except VastError as exc:
            raise CoderVastBackendError(str(exc)) from None
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
