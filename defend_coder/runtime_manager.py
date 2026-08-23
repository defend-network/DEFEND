"""DEFENDcoder-owned model runtime authority (production, fail-closed).

This is the CONCRETE product runtime manager. READY is NEVER synthesized: it
requires a concrete healthy endpoint plus the intended instance/model identity.
In this zero-cost milestone no live compute is provisioned, so the manager
reports STOPPED_RETAINED / UNKNOWN and NEXT availability is False.

ProductRuntimeAdapterBoundary remains a TEST-ONLY deterministic fake and is
never the production runtime authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .providers import NEXT_MODEL

NEXT_STATE_ABSENT = "ABSENT"
NEXT_STATE_STOPPED_RETAINED = "STOPPED_RETAINED"
NEXT_STATE_STARTING = "STARTING"
NEXT_STATE_READY = "READY"
NEXT_STATE_FAILED = "FAILED"
NEXT_STATE_UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class RuntimeSnapshot:
    """Concrete runtime evidence. READY only when all fields are consistent."""

    state: str
    instance_id: str | None
    model: str | None
    endpoint: str | None
    gpu: str | None
    hourly_cost: str | None
    detail: str | None


class CoderRuntimeManager:
    """Concrete product-owned model runtime manager.

    Derives NEXT availability/endpoint from its own runtime snapshot. It never
    fabricates READY: ``is_next_ready`` requires state==READY, a non-empty
    endpoint, and a non-empty instance identity. The full Vast/SSH/provisioning
    lifecycle is a later milestone; here it fails closed (STOPPED_RETAINED).
    """

    def __init__(self, *, snapshot: RuntimeSnapshot | None = None) -> None:
        self._snapshot = snapshot or RuntimeSnapshot(
            state=NEXT_STATE_ABSENT,
            instance_id=None,
            model=NEXT_MODEL,
            endpoint=None,
            gpu=None,
            hourly_cost=None,
            detail="ABSENT: no Next runtime has been provisioned",
        )

    def runtime_status(self, product_id: str = "defendcoder") -> dict[str, Any]:
        del product_id
        s = self._snapshot
        return {
            "state": s.state,
            "provider_instance_state": s.state,
            "model": s.model,
            "instance_id": s.instance_id,
            "gpu": s.gpu,
            "hourly_cost": s.hourly_cost,
            "detail": s.detail,
            "endpoint": s.endpoint,
        }

    def is_next_ready(self) -> bool:
        s = self._snapshot
        return bool(
            s.state == NEXT_STATE_READY
            and s.endpoint
            and s.instance_id
        )

    def next_availability(self) -> bool:
        """Next is routable when a runtime is known (READY / STOPPED_RETAINED /
        STARTING). ABSENT / UNKNOWN / FAILED are not routable and never READY."""
        return self._snapshot.state in (
            NEXT_STATE_READY,
            NEXT_STATE_STOPPED_RETAINED,
            NEXT_STATE_STARTING,
        )

    def get_runtime_endpoint(self, product_id: str = "defendcoder") -> str | None:
        del product_id
        if self.is_next_ready():
            return self._snapshot.endpoint
        return None

    def start_runtime(
        self,
        product_id: str = "defendcoder",
        *,
        authorize_resume: bool = False,
    ) -> dict[str, Any]:
        """Fail closed: this milestone performs no live provisioning, so there
        is never a runtime to start/resume. Never manufacture READY."""
        del product_id, authorize_resume
        from .routing import RuntimeResumeDenied

        raise RuntimeResumeDenied(
            "no retained Next runtime is provisioned; starting it is not "
            "available in this product milestone"
        )

    def stop_runtime(self, product_id: str = "defendcoder") -> dict[str, Any]:
        """Stop/RETAIN (never destroy) — no live runtime to act on here."""
        del product_id
        return {"state": "STOPPED_RETAINED", "retained": True}
