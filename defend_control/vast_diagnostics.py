"""Vast SSH transport readiness states and sanitized instance diagnostics.

The record never includes provider credentials, tokens, or key material.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from .types import LaunchSpec, VastInstance, VastOffer


class TransportReadiness(str, Enum):
    """Explicit transport-readiness states for a diagnostic instance."""

    PROVIDER_RUNNING = "provider_running"
    DIRECT_SSH_REACHABLE = "direct_ssh_reachable"
    FINGERPRINT_OBSERVED = "fingerprint_observed"
    OWNER_CONFIRMED = "owner_fingerprint_confirmed"
    BOOTSTRAP = "bootstrap"


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
        "runtype": launch.runtype if launch is not None else None,
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