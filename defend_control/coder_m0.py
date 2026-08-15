"""DEFENDcoder M0: start → smoke → stop/destroy only.

This module is intentionally isolated from the identity chat launch path.
It does not implement workspace management, Aider, agent loops, traces UI,
planner, or reviewer behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Protocol
import time
import uuid

from .types import ServiceState

CoderModelAlias = Literal[
    "defendcoder-fast",
    "defendcoder-default",
    "defendcoder-heavy",
    "defendcoder-eval",
]

_DEFAULT_BUDGET = Decimal("5.00")
_DEFAULT_ALIAS: CoderModelAlias = "defendcoder-default"

# Pinned 2026-08-14 from HfApi().model_info(...).sha
_CODER_DEFAULT_REPO = "Qwen/Qwen3-Coder-30B-A3B-Instruct"
_CODER_DEFAULT_REVISION = "b2cff646eb4bb1d68355c01b18ae02e7cf42d120"
_CODER_HEAVY_REPO = "Qwen/Qwen3-Coder-Next"
_CODER_HEAVY_REVISION = "a7fbcb5c0e12d62a448eaa0e260346bf5dcc0feb"


@dataclass(frozen=True)
class CoderModelRef:
    alias: CoderModelAlias
    repo_id: str
    revision: str
    max_model_len: int = 8192
    notes: str = ""


# Registry maps product aliases → concrete checkpoints.
# V0 pins practical single-GPU coder targets; fast/eval may share until filled.
CODER_MODEL_REGISTRY: dict[str, CoderModelRef] = {
    "defendcoder-fast": CoderModelRef(
        alias="defendcoder-fast",
        repo_id=_CODER_DEFAULT_REPO,
        revision=_CODER_DEFAULT_REVISION,
        max_model_len=8192,
        notes="Fast/cheap lane; may share weights with default until differentiated",
    ),
    "defendcoder-default": CoderModelRef(
        alias="defendcoder-default",
        repo_id=_CODER_DEFAULT_REPO,
        revision=_CODER_DEFAULT_REVISION,
        max_model_len=8192,
        notes="Standard quality/$ target for single A100-class GPU",
    ),
    "defendcoder-heavy": CoderModelRef(
        alias="defendcoder-heavy",
        repo_id=_CODER_HEAVY_REPO,
        revision=_CODER_HEAVY_REVISION,
        max_model_len=8192,
        notes="Heavy lane: Qwen3-Coder-Next on A100/H100 80GB-class",
    ),
    "defendcoder-eval": CoderModelRef(
        alias="defendcoder-eval",
        repo_id=_CODER_DEFAULT_REPO,
        revision=_CODER_DEFAULT_REVISION,
        max_model_len=8192,
        notes="Eval/reviewer lane placeholder",
    ),
}


def resolve_alias(alias: str) -> CoderModelRef:
    if alias not in CODER_MODEL_REGISTRY:
        raise ValueError(
            f"unknown coder alias {alias!r}; expected one of "
            f"{sorted(CODER_MODEL_REGISTRY)}"
        )
    return CODER_MODEL_REGISTRY[alias]


def parse_session_budget(raw: object) -> Decimal:
    if isinstance(raw, bool) or not isinstance(raw, (str, int, Decimal)):
        raise ValueError("CODER_SESSION_BUDGET_USD must be a decimal value")
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("CODER_SESSION_BUDGET_USD must be a decimal value") from exc
    if not value.is_finite() or value <= 0:
        raise ValueError("CODER_SESSION_BUDGET_USD must be a positive finite decimal")
    return value


@dataclass(frozen=True)
class CoderSessionStatus:
    state: ServiceState
    alias: CoderModelAlias
    model_repo: str
    model_revision: str
    endpoint: str | None
    instance_id: int | None
    provider_run_id: str | None
    hourly_price: str | None
    session_budget_usd: str
    message: str | None = None

    def as_public_dict(self) -> dict[str, Any]:
        """Observation payload — never includes API keys or tokens."""
        return {
            "service": "DEFENDcoder",
            "state": self.state,
            "alias": self.alias,
            "model_repo": self.model_repo,
            "model_revision": self.model_revision,
            "endpoint": self.endpoint,
            "instance_id": self.instance_id,
            "provider_run_id": self.provider_run_id,
            "hourly_price": self.hourly_price,
            "session_budget_usd": self.session_budget_usd,
            "message": self.message,
        }


@dataclass(frozen=True)
class CoderSmokeResult:
    ok: bool
    alias: str
    endpoint: str | None
    latency_ms: int
    detail: str
    instance_id: int | None = None
    provider_run_id: str | None = None


class CoderInferenceBackend(Protocol):
    """Provider boundary: ControlPlane/Vast/local implement this; M0 stays thin."""

    def start(
        self,
        model: CoderModelRef,
        *,
        local_port: int,
        session_budget_usd: Decimal,
    ) -> dict[str, Any]:
        """Return endpoint, instance_id, provider_run_id, hourly_price, state."""

    def smoke(self, endpoint: str, model: CoderModelRef) -> dict[str, Any]:
        """Return ok, latency_ms, detail."""

    def stop(
        self,
        *,
        instance_id: int | None,
        provider_run_id: str | None,
        destroy: bool,
    ) -> dict[str, Any]:
        """Return state and message."""


class LocalFakeCoderBackend:
    """Deterministic backend for tests and offline preflight — no billing."""

    def __init__(self) -> None:
        self.started = False
        self.destroyed = False
        self._endpoint = "http://127.0.0.1:8003/v1"
        self._instance_id = 900001
        self._provider_run_id = "fake-run-" + uuid.uuid4().hex[:12]

    def start(
        self,
        model: CoderModelRef,
        *,
        local_port: int,
        session_budget_usd: Decimal,
    ) -> dict[str, Any]:
        self.started = True
        self.destroyed = False
        self._endpoint = f"http://127.0.0.1:{local_port}/v1"
        self._provider_run_id = "fake-run-" + uuid.uuid4().hex[:12]
        return {
            "state": "ready",
            "endpoint": self._endpoint,
            "instance_id": self._instance_id,
            "provider_run_id": self._provider_run_id,
            "hourly_price": "0.0000",
            "message": f"fake backend ready for {model.alias}",
        }

    def smoke(self, endpoint: str, model: CoderModelRef) -> dict[str, Any]:
        if not self.started or self.destroyed:
            return {
                "ok": False,
                "latency_ms": 0,
                "detail": "coder backend is not running",
            }
        if endpoint != self._endpoint:
            return {
                "ok": False,
                "latency_ms": 0,
                "detail": "endpoint mismatch",
            }
        return {
            "ok": True,
            "latency_ms": 1,
            "detail": f"smoke ok alias={model.alias} model={model.repo_id}",
        }

    def stop(
        self,
        *,
        instance_id: int | None,
        provider_run_id: str | None,
        destroy: bool,
    ) -> dict[str, Any]:
        self.started = False
        self.destroyed = bool(destroy)
        return {
            "state": "stopped",
            "message": (
                "fake backend destroyed"
                if destroy
                else "fake backend stopped (instance retained)"
            ),
            "instance_id": instance_id,
            "provider_run_id": provider_run_id,
        }


@dataclass
class CoderM0Service:
    """Owner-facing M0 API: coder.start / coder.smoke / coder.stop.

    Does not touch StackOrchestrator identity chat flows.
    """

    backend: CoderInferenceBackend
    alias: CoderModelAlias = _DEFAULT_ALIAS
    local_port: int = 8003
    session_budget_usd: Decimal = field(default_factory=lambda: _DEFAULT_BUDGET)
    _state: ServiceState = "stopped"
    _endpoint: str | None = None
    _instance_id: int | None = None
    _provider_run_id: str | None = None
    _hourly_price: str | None = None
    _message: str | None = None

    def __post_init__(self) -> None:
        resolve_alias(self.alias)
        self.session_budget_usd = parse_session_budget(self.session_budget_usd)
        if not (1 <= int(self.local_port) <= 65_535):
            raise ValueError("local_port must be in 1..65535")

    def status(self) -> CoderSessionStatus:
        model = resolve_alias(self.alias)
        return CoderSessionStatus(
            state=self._state,
            alias=self.alias,
            model_repo=model.repo_id,
            model_revision=model.revision,
            endpoint=self._endpoint,
            instance_id=self._instance_id,
            provider_run_id=self._provider_run_id,
            hourly_price=self._hourly_price,
            session_budget_usd=format(self.session_budget_usd, "f"),
            message=self._message,
        )

    def start(self, alias: str | None = None) -> CoderSessionStatus:
        if alias is not None:
            model = resolve_alias(alias)
            self.alias = model.alias  # type: ignore[assignment]
        else:
            model = resolve_alias(self.alias)

        if self._state in ("starting", "provisioning", "ready"):
            raise RuntimeError(
                f"coder already in state {self._state!r}; stop first"
            )

        self._state = "starting"
        self._message = f"starting {model.alias}"
        try:
            result = self.backend.start(
                model,
                local_port=self.local_port,
                session_budget_usd=self.session_budget_usd,
            )
        except Exception as exc:
            self._state = "failed"
            self._message = f"start failed: {type(exc).__name__}"
            raise

        state = str(result.get("state", "ready"))
        if state not in (
            "stopped",
            "validating",
            "provisioning",
            "starting",
            "ready",
            "degraded",
            "stopping",
            "failed",
        ):
            state = "ready"
        self._state = state  # type: ignore[assignment]
        self._endpoint = result.get("endpoint")
        self._instance_id = result.get("instance_id")
        self._provider_run_id = result.get("provider_run_id")
        self._hourly_price = result.get("hourly_price")
        self._message = result.get("message")
        return self.status()

    def smoke(self) -> CoderSmokeResult:
        if self._state != "ready" or not self._endpoint:
            return CoderSmokeResult(
                ok=False,
                alias=self.alias,
                endpoint=self._endpoint,
                latency_ms=0,
                detail=f"cannot smoke in state {self._state!r}",
                instance_id=self._instance_id,
                provider_run_id=self._provider_run_id,
            )
        model = resolve_alias(self.alias)
        started = time.perf_counter()
        try:
            result = self.backend.smoke(self._endpoint, model)
        except Exception as exc:
            return CoderSmokeResult(
                ok=False,
                alias=self.alias,
                endpoint=self._endpoint,
                latency_ms=int((time.perf_counter() - started) * 1000),
                detail=f"smoke exception: {type(exc).__name__}",
                instance_id=self._instance_id,
                provider_run_id=self._provider_run_id,
            )
        latency = int(result.get("latency_ms") or (time.perf_counter() - started) * 1000)
        return CoderSmokeResult(
            ok=bool(result.get("ok")),
            alias=self.alias,
            endpoint=self._endpoint,
            latency_ms=latency,
            detail=str(result.get("detail", "")),
            instance_id=self._instance_id,
            provider_run_id=self._provider_run_id,
        )

    def stop(
        self,
        *,
        destroy: bool = False,
        confirmed_instance_id: int | None = None,
    ) -> CoderSessionStatus:
        if destroy:
            if (
                self._instance_id is not None
                and (
                    type(confirmed_instance_id) is not int
                    or confirmed_instance_id != self._instance_id
                )
            ):
                raise ValueError(
                    f"Enter exact coder instance ID {self._instance_id} to destroy"
                )

        self._state = "stopping"
        try:
            result = self.backend.stop(
                instance_id=self._instance_id,
                provider_run_id=self._provider_run_id,
                destroy=destroy,
            )
        except Exception as exc:
            self._state = "failed"
            self._message = f"stop failed: {type(exc).__name__}"
            raise

        self._state = str(result.get("state", "stopped"))  # type: ignore[assignment]
        if self._state not in (
            "stopped",
            "validating",
            "provisioning",
            "starting",
            "ready",
            "degraded",
            "stopping",
            "failed",
        ):
            self._state = "stopped"
        self._message = result.get("message")
        if destroy or self._state == "stopped":
            self._endpoint = None
            if destroy:
                self._instance_id = None
                self._provider_run_id = None
                self._hourly_price = None
        return self.status()
