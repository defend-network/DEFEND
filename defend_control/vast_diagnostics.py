"""Vast SSH transport readiness states and sanitized instance diagnostics.

The record never includes provider credentials, tokens, or key material.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from enum import Enum
import time
from typing import Any

from .types import LaunchSpec, VastInstance, VastOffer
from .vast import direct_endpoint_sources


class TransportReadiness(str, Enum):
    """Explicit transport-readiness states for a diagnostic instance."""

    PROVIDER_RUNNING = "provider_running"
    DIRECT_SSH_REACHABLE = "direct_ssh_reachable"
    FINGERPRINT_OBSERVED = "fingerprint_observed"
    OWNER_CONFIRMED = "owner_fingerprint_confirmed"
    BOOTSTRAP = "bootstrap"


class DirectEndpointState(str, Enum):
    """Distinct publication states of the direct SSH endpoint on ssh_direct.

    The provider may keep the instance running while its direct-endpoint
    metadata (direct_ssh_host / direct_ssh_port, or public_ipaddr + port
    mapping) is not yet visible in the show payload. The wait separates
    "still running / metadata pending" from "published" and, at the bounded
    deadline, from "permanently unavailable".
    """

    PROVIDER_RUNNING = "provider_running"
    ENDPOINT_METADATA_PENDING = "endpoint_metadata_pending"
    ENDPOINT_AVAILABLE = "endpoint_available"
    ENDPOINT_PERMANENTLY_UNAVAILABLE = "endpoint_permanently_unavailable"


@dataclass(frozen=True)
class DirectEndpointProbe:
    """One classified snapshot of the direct-SSH publication wait."""

    state: DirectEndpointState
    host: str | None
    port: int | None
    actual_status: str | None
    attempt: int
    elapsed_seconds: float
    raw_sources: dict[str, Any]


def probe_direct_endpoint(
    instance: VastInstance,
    *,
    raw: Mapping[str, Any] | None = None,
    attempt: int = 0,
    elapsed_seconds: float = 0.0,
) -> DirectEndpointProbe:
    """Classify one show snapshot into the direct-endpoint publication state.

    The endpoint is AVAILABLE only when both host and port are present.
    A running instance without them is ENDPOINT_METADATA_PENDING; anything
    not yet running is PROVIDER_RUNNING.
    """
    sources = direct_endpoint_sources(raw) if raw is not None else {}
    host = instance.direct_ssh_host
    port = instance.direct_ssh_port
    if isinstance(host, str) and host and type(port) is int and port is not None:
        return DirectEndpointProbe(
            state=DirectEndpointState.ENDPOINT_AVAILABLE,
            host=host,
            port=port,
            actual_status=instance.actual_status,
            attempt=attempt,
            elapsed_seconds=elapsed_seconds,
            raw_sources=sources,
        )
    if instance.actual_status == "running":
        state = DirectEndpointState.ENDPOINT_METADATA_PENDING
    else:
        state = DirectEndpointState.PROVIDER_RUNNING
    return DirectEndpointProbe(
        state=state,
        host=None,
        port=None,
        actual_status=instance.actual_status,
        attempt=attempt,
        elapsed_seconds=elapsed_seconds,
        raw_sources=sources,
    )


def wait_for_direct_endpoint(
    client: Any,
    instance_id: int,
    *,
    max_wait_seconds: float,
    budget_seconds: float | None = None,
    poll_interval_seconds: float = 10.0,
    monotonic: Callable[[], float] = time.monotonic,
    cancelled: Callable[[], bool] | None = None,
) -> DirectEndpointProbe:
    """Bounded wait for the provider to publish the direct SSH endpoint.

    Terminal states: ENDPOINT_AVAILABLE (published within the window) or
    ENDPOINT_PERMANENTLY_UNAVAILABLE (instance running but never published
    before the min(max_wait_seconds, budget_seconds) deadline, or the caller
    cancelled the wait).

    This never mutates the instance and never destroys anything — the caller
    decides what to do with the terminal state. The client is duck-typed to
    ``show_instance(instance_id)`` plus ``last_raw_payload("show")``.
    """
    if not (0 < float(max_wait_seconds)):
        raise ValueError("max_wait_seconds must be positive")
    if budget_seconds is not None and not (0 < float(budget_seconds)):
        raise ValueError("budget_seconds must be positive")
    if not (0 < float(poll_interval_seconds)):
        raise ValueError("poll_interval_seconds must be positive")
    ceiling = float(max_wait_seconds)
    if budget_seconds is not None:
        ceiling = min(ceiling, float(budget_seconds))

    start = monotonic()
    attempt = 0
    while True:
        if cancelled is not None and cancelled():
            break
        attempt += 1
        elapsed = monotonic() - start
        instance = client.show_instance(instance_id)
        raw = client.last_raw_payload("show")
        probe = probe_direct_endpoint(
            instance,
            raw=raw,
            attempt=attempt,
            elapsed_seconds=elapsed,
        )
        if probe.state is DirectEndpointState.ENDPOINT_AVAILABLE:
            return probe
        remaining = ceiling - elapsed
        if remaining <= 0:
            break
        time.sleep(min(float(poll_interval_seconds), remaining))

    instance = client.show_instance(instance_id)
    raw = client.last_raw_payload("show")
    probe = probe_direct_endpoint(
        instance,
        raw=raw,
        attempt=attempt + 1,
        elapsed_seconds=monotonic() - start,
    )
    if probe.state is DirectEndpointState.ENDPOINT_AVAILABLE:
        return probe
    return replace(
        probe,
        state=DirectEndpointState.ENDPOINT_PERMANENTLY_UNAVAILABLE,
    )


def build_instance_diagnostic(
    *,
    instance: VastInstance,
    offer: VastOffer | None = None,
    launch: LaunchSpec | None = None,
    transport: str = "proxy",
    failure_category: str | None = None,
    timestamps: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Sanitized record of a diagnostic instance before cleanup.

    Contains no secrets: identity/label/runtype/endpoint presence only.
    """
    if not isinstance(instance, VastInstance):
        raise ValueError("instance must be a VastInstance")
    if transport not in ("direct", "proxy"):
        raise ValueError("transport must be 'direct' or 'proxy'")
    return {
        "instance_id": instance.instance_id,
        "offer_id": offer.offer_id if offer is not None else None,
        "machine_id": instance.machine_id,
        "actual_status": instance.actual_status,
        "image": launch.image if launch is not None else None,
        "requested_runtype": launch.runtype if launch is not None else None,
        "provider_image_runtype": instance.image_runtype,
        "ssh_direct_host_present": isinstance(
            instance.direct_ssh_host, str
        ) and bool(instance.direct_ssh_host),
        "ssh_direct_port_present": isinstance(
            instance.direct_ssh_port, int
        )
        and instance.direct_ssh_port is not None,
        "ssh_proxy_host_present": isinstance(instance.ssh_host, str) and bool(
            instance.ssh_host
        ),
        "ssh_proxy_port_present": isinstance(instance.ssh_port, int)
        and instance.ssh_port is not None,
        "transport_attempted": transport,
        "failure_category": failure_category,
        "timestamps": dict(timestamps or {}),
    }