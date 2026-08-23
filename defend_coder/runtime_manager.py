"""DEFENDcoder-owned model runtime authority (production).

CoderRuntimeManager is the routing/status FACADE over the product-owned
``defend_coder.runtime.control_plane.CoderControlPlane``. The control plane
performs the real lifecycle (plan/approve/provision/resume/stop/destroy/idle);
the manager maps that to the routing-facing state machine and enforces
health-backed READY.

READY is NEVER synthesized: it requires an exact instance identity, an endpoint,
a matching served model, AND a successful bounded health probe.

ProductRuntimeAdapterBoundary remains a TEST-ONLY fake and is never production
authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .providers import NEXT_MODEL
from .runtime.health import probe_endpoint_ready

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

#: control-plane state -> runtime-manager state (fail-closed default UNKNOWN).
_CONTROL_PLANE_STATE_MAP = {
    "stopped": ABSENT,
    "retained": STOPPED_RETAINED,
    "starting": STARTING,
    "provisioning": PROVISIONING,
    "ready": READY,
    "failed": FAILED,
}


@dataclass(frozen=True)
class RuntimeSnapshot:
    """Concrete runtime evidence (used when no control plane is attached)."""

    state: str
    instance_id: str | None
    model: str | None
    endpoint: str | None
    gpu: str | None
    hourly_cost: str | None
    detail: str | None


class CoderRuntimeManager:
    """Routing/status facade over the product runtime control plane."""

    def __init__(
        self,
        *,
        snapshot: RuntimeSnapshot | None = None,
        health_probe: HealthProbe | None = None,
        control_plane: object | None = None,
        alias: str = "defendcoder-default",
        expected_model: str = NEXT_MODEL,
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
        self._health_probe = health_probe or (
            lambda ep, mdl: probe_endpoint_ready(ep, mdl)
        )
        self._control_plane = control_plane
        self._alias = alias
        self._expected_model = expected_model

    # -- status derivation -------------------------------------------------

    def _plane_status(self) -> dict[str, Any] | None:
        if self._control_plane is None:
            return None
        return self._control_plane.status(self._alias)

    def _derived_state(self) -> str:
        plane = self._plane_status()
        if plane is None:
            return self._snapshot.state
        return _CONTROL_PLANE_STATE_MAP.get(
            str(plane.get("state") or "stopped"), UNKNOWN
        )

    def runtime_status(self, product_id: str = "defendcoder") -> dict[str, Any]:
        del product_id
        plane = self._plane_status()
        if plane is not None:
            state = _CONTROL_PLANE_STATE_MAP.get(
                str(plane.get("state") or "stopped"), UNKNOWN
            )
            return {
                "state": state,
                "provider_instance_state": state,
                "model": self._expected_model,
                "instance_id": plane.get("instance_id"),
                "gpu": plane.get("gpu_type"),
                "hourly_cost": plane.get("hourly_price"),
                "detail": None,
                "endpoint": plane.get("endpoint"),
            }
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

    def _evidence(self) -> tuple[str, str | None, str | None]:
        plane = self._plane_status()
        if plane is not None:
            state = _CONTROL_PLANE_STATE_MAP.get(
                str(plane.get("state") or "stopped"), UNKNOWN
            )
            return state, plane.get("endpoint"), plane.get("instance_id")
        return self._snapshot.state, self._snapshot.endpoint, self._snapshot.instance_id

    # -- routing separation -------------------------------------------------

    def model_selectable(self) -> bool:
        return self._derived_state() in SELECTABLE_STATES

    def runtime_resumable(self) -> bool:
        return self._derived_state() in RESUMABLE_STATES

    def runtime_ready(self) -> bool:
        state, endpoint, instance_id = self._evidence()
        if state != READY or not endpoint or not instance_id:
            return False
        return bool(self._health_probe(endpoint, self._expected_model))

    def is_next_ready(self) -> bool:
        return self.runtime_ready()

    def next_availability(self) -> bool:
        """Routing availability == health-backed runtime readiness.

        NEXT may receive a run NOW only when the runtime is READY (exact
        instance + endpoint + matching health). STARTING / STOPPED_RETAINED /
        PROVISIONING / PENDING_HOST_APPROVAL / FAILED / UNKNOWN / ABSENT are
        NOT routable.
        """
        return self.runtime_ready()

    def routing_available(self) -> bool:
        return self.runtime_ready()

    def get_runtime_endpoint(self, product_id: str = "defendcoder") -> str | None:
        del product_id
        if self.runtime_ready():
            _, endpoint, _ = self._evidence()
            return endpoint
        return None

    # -- lifecycle delegation ----------------------------------------------

    def plan_runtime(self, alias: str | None = None) -> object:
        """Produce an immutable plan (no provider mutation)."""
        if self._control_plane is None:
            raise RuntimeError("no runtime control plane attached")
        return self._control_plane.live_smoke_plan(alias or self._alias)

    def approve_plan(self, prepared: object) -> object:
        if self._control_plane is None:
            raise RuntimeError("no runtime control plane attached")
        return self._control_plane.approve(prepared)

    def provision(self, approval: object) -> dict[str, Any]:
        if self._control_plane is None:
            raise RuntimeError("no runtime control plane attached")
        return self._control_plane.provision(approval)

    def resume_retained(self, *, authorize_resume: bool = False) -> dict[str, Any]:
        if not authorize_resume:
            from .routing import RuntimeResumeDenied

            raise RuntimeResumeDenied(
                "resuming a retained paid runtime requires owner approval"
            )
        if self._control_plane is None:
            from .routing import RuntimeResumeDenied

            raise RuntimeResumeDenied("no retained runtime to resume")
        return self._control_plane.resume_existing(self._alias)

    def start_runtime(
        self,
        product_id: str = "defendcoder",
        *,
        authorize_resume: bool = False,
    ) -> dict[str, Any]:
        del product_id
        if not authorize_resume:
            from .routing import RuntimeResumeDenied

            raise RuntimeResumeDenied(
                "resuming a retained paid runtime requires owner approval"
            )
        if self._control_plane is not None:
            return self._control_plane.resume_existing(self._alias)
        if self._snapshot.state != STOPPED_RETAINED:
            from .routing import RuntimeResumeDenied

            raise RuntimeResumeDenied("no retained Next runtime is provisioned")
        return {"state": STARTING, "resumed": False}

    def stop_runtime(self, product_id: str = "defendcoder") -> dict[str, Any]:
        """STOP/RETAIN (never destroy). ABSENT remains ABSENT."""
        del product_id
        if self._control_plane is not None:
            return self._control_plane.release(self._alias, destroy=False)
        if self._snapshot.state in (ABSENT, UNKNOWN, FAILED):
            return {"state": self._snapshot.state, "retained": False}
        if self._snapshot.state == READY:
            return {"state": STOPPED_RETAINED, "retained": True}
        return {"state": self._snapshot.state, "retained": True}

    def destroy_exact(self, *, instance_id: int) -> dict[str, Any]:
        """Destroy only the exact retained instance identity."""
        if self._control_plane is None:
            raise RuntimeError("no runtime control plane attached")
        plane = self._plane_status()
        if plane is None or str(plane.get("instance_id")) != str(instance_id):
            raise ValueError("instance identity mismatch; destroy refused")
        return self._control_plane.release(self._alias, destroy=True)

    def maybe_reap_idle(self) -> None:
        """Product-owned idle policy: STOP/RETAIN (never destroy)."""
        if self._control_plane is None:
            return
        self._control_plane.maybe_reap_idle(self._alias)
