"""DEFENDcoder-owned model runtime authority (production).

Concrete runtime state machine. READY is NEVER synthesized: it requires an
exact retained instance identity, an endpoint, a matching model, AND a
successful bounded health probe (dependency-injected, no real network here).

The full provisioning/resume/stop/destroy lifecycle is delegated to the
product-owned ``defend_coder.runtime.control_plane.CoderControlPlane`` (migrated
from Control Center); this manager is the routing/status-facing authority with
the selectable / resumable / ready separation.

ProductRuntimeAdapterBoundary remains a TEST-ONLY fake and is never production
authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .providers import NEXT_MODEL

ABSENT = "ABSENT"
PLANNING = "PLANNING"
APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
PROVISIONING = "PROVISIONING"
STARTING = "STARTING"
PENDING_HOST_APPROVAL = "PENDING_HOST_APPROVAL"
READY = "READY"
STOPPING = "STOPPING"
STOPPED_RETAINED = "STOPPED_RETAINED"
DESTROYING = "DESTROYING"
FAILED = "FAILED"
UNKNOWN = "UNKNOWN"

RESUMABLE_STATES = (STOPPED_RETAINED,)
SELECTABLE_STATES = (STARTING, STOPPED_RETAINED, READY)

HealthProbe = Callable[[str, str], bool]


@dataclass(frozen=True)
class RuntimeSnapshot:
    """Concrete runtime evidence."""

    state: str
    instance_id: str | None
    model: str | None
    endpoint: str | None
    gpu: str | None
    hourly_cost: str | None
    detail: str | None


def _default_health_probe(endpoint: str, expected_model: str) -> bool:
    """Default fail-closed health probe: no real network, returns False.

    Production must inject a real bounded probe; tests inject a deterministic
    one. An endpoint alone is never sufficient for READY.
    """
    del endpoint, expected_model
    return False


class CoderRuntimeManager:
    """Concrete product-owned model runtime manager.

    ``READY`` requires state==READY + non-empty instance identity + non-empty
    endpoint + a successful health probe confirming the intended model.
    """

    def __init__(
        self,
        *,
        snapshot: RuntimeSnapshot | None = None,
        health_probe: HealthProbe | None = None,
    ) -> None:
        self._snapshot = snapshot or RuntimeSnapshot(
            state=ABSENT,
            instance_id=None,
            model=NEXT_MODEL,
            endpoint=None,
            gpu=None,
            hourly_cost=None,
            detail="ABSENT: no Next runtime has been provisioned",
        )
        self._health_probe = health_probe or _default_health_probe

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

    def model_selectable(self) -> bool:
        return self._snapshot.state in SELECTABLE_STATES

    def runtime_resumable(self) -> bool:
        return self._snapshot.state in RESUMABLE_STATES

    def runtime_ready(self) -> bool:
        s = self._snapshot
        if s.state != READY or not s.endpoint or not s.instance_id or not s.model:
            return False
        return bool(self._health_probe(s.endpoint, s.model))

    def is_next_ready(self) -> bool:
        return self.runtime_ready()

    def next_availability(self) -> bool:
        """Routable tier: a known runtime exists (selectable)."""
        return self.model_selectable()

    def get_runtime_endpoint(self, product_id: str = "defendcoder") -> str | None:
        del product_id
        if self.runtime_ready():
            return self._snapshot.endpoint
        return None

    def start_runtime(
        self,
        product_id: str = "defendcoder",
        *,
        authorize_resume: bool = False,
    ) -> dict[str, Any]:
        """Resume a retained runtime only. Fails closed otherwise."""
        del product_id
        if not authorize_resume:
            from .routing import RuntimeResumeDenied

            raise RuntimeResumeDenied(
                "resuming a retained paid runtime requires owner approval"
            )
        if self._snapshot.state != STOPPED_RETAINED:
            from .routing import RuntimeResumeDenied

            raise RuntimeResumeDenied(
                "no retained Next runtime is provisioned to resume"
            )
        # Delegated to the product control plane in production; this
        # zero-cost milestone never performs a live resume.
        return {"state": STARTING, "resumed": False}

    def stop_runtime(self, product_id: str = "defendcoder") -> dict[str, Any]:
        """STOP/RETAIN (never destroy). ABSENT remains ABSENT."""
        del product_id
        if self._snapshot.state in (ABSENT, UNKNOWN, FAILED):
            return {"state": self._snapshot.state, "retained": False}
        if self._snapshot.state == READY:
            return {"state": STOPPED_RETAINED, "retained": True}
        return {"state": self._snapshot.state, "retained": True}
