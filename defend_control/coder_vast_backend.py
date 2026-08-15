"""Vast-backed inference provider for DEFENDcoder M0.1.

Implements CoderInferenceBackend. Does not start API/UI/Cloudflare or touch
identity chat orchestration. Owner must still confirm pricing/fingerprint at
the Control Center layer when wiring UI (M0.1 core stays injectable).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
import time
import urllib.error
import urllib.request

from .coder_deployment import resolve_deployment
from .coder_m0 import CoderModelRef
from .coder_remote_vllm import CoderRemoteVllmBootstrap, CoderRemoteVllmError
from .types import LaunchSpec, ResourceProfile, VastInstance, VastOffer
from .vast import VastClient, VastError


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
    smoke_http: Callable[[str, str, CoderModelRef], dict[str, Any]] | None = None
    offer_chooser: Callable[[tuple[VastOffer, ...]], VastOffer] | None = None

    def __post_init__(self) -> None:
        if self.profile is None:
            object.__setattr__(self, "profile", ResourceProfile.coder_default())
        if self.launch is None:
            object.__setattr__(self, "launch", LaunchSpec.coder_default())
        if self.launch is None or self.launch.label != "defendcoder-vllm":
            raise ValueError("coder backend requires defendcoder-vllm launch label")

    def start(
        self,
        model: CoderModelRef,
        *,
        local_port: int,
        session_budget_usd: Decimal,
    ) -> dict[str, Any]:
        del session_budget_usd  # enforced by CoderM0Service / Control Center
        if type(local_port) is not int or not 1 <= local_port <= 65_535:
            raise CoderVastBackendError("local_port is invalid")

        try:
            offers = self.vast.search_offers(self.max_hourly, self.profile)
        except VastError as exc:
            raise CoderVastBackendError(str(exc)) from None
        if not offers:
            raise CoderVastBackendError("no eligible coder GPU offers under budget")

        offer = self.offer_chooser(offers) if self.offer_chooser else offers[0]
        artifact = resolve_deployment(model.alias)
        launch = LaunchSpec(
            image=f"vllm/vllm-openai:{artifact.image_tag}",
            disk_gb=160,
            runtype="ssh_direc ssh_proxy",
            label="defendcoder-vllm",
        )
        try:
            instance = self.vast.create_instance(offer, launch)
            instance = self.vast.wait_until_running(instance.instance_id)
        except VastError as exc:
            raise CoderVastBackendError(str(exc)) from None

        try:
            self.bootstrap.start(
                instance,
                model,
                self.secrets,
                remote_port=self.remote_port,
                artifact=artifact,
            )
        except CoderRemoteVllmError as exc:
            try:
                self.vast.destroy_instance(
                    instance.instance_id,
                    confirmed_instance_id=instance.instance_id,
                )
            except Exception:
                pass
            raise CoderVastBackendError(str(exc)) from None

        if self.tunnel_start is not None:
            endpoint = self.tunnel_start(instance, local_port)
        else:
            endpoint = f"http://127.0.0.1:{local_port}/v1"

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
