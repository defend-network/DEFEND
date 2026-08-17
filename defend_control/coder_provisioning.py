"""DEFENDcoder provisioning observability — phase taxonomy, structured
failure record, and sanitized lifecycle reporting.

The failure record is built BEFORE provider teardown so it survives the
destroy of the instance. It never contains API keys, SSH private keys,
tokens, passwords, provider authorization headers, or raw command
environments.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from pathlib import Path
import re
import time


class CoderProvisionPhase(str, Enum):
    """Every provisioning phase that can fail, in execution order.

    Remote bootstrap stages (remote_preflight, bootstrap_upload,
    container_start, vllm_start, model_load, health_wait) are reported
    by the staged remote script through CODER_STAGE markers.
    """

    INSTANCE_CREATE = "instance_create"
    INSTANCE_RUNNING_WAIT = "instance_running_wait"
    DIRECT_ENDPOINT_WAIT = "direct_endpoint_wait"
    SSH_CONNECT = "ssh_connect"
    SSH_TUNNEL = "ssh_tunnel"
    REMOTE_PREFLIGHT = "remote_preflight"
    BOOTSTRAP_UPLOAD = "bootstrap_upload"
    CONTAINER_START = "container_start"
    VLLM_START = "vllm_start"
    MODEL_LOAD = "model_load"
    HEALTH_WAIT = "health_wait"
    OPENAI_SMOKE = "openai_smoke"
    LOCAL_API_START = "local_api_start"
    LOCAL_WEB_START = "local_web_start"
    CLEANUP = "cleanup"


CODER_PROVISION_PHASES = tuple(phase.value for phase in CoderProvisionPhase)

CLEANUP_STATES = (
    "destroyed",
    "destroy_pending",
    "destroy_verification_failed",
    "destroy_request_failed",
    "unknown",
    "not_attempted",
)

# Remote stages reported by the staged bootstrap script, in order.
REMOTE_STAGE_PHASES = (
    CoderProvisionPhase.REMOTE_PREFLIGHT,
    CoderProvisionPhase.BOOTSTRAP_UPLOAD,
    CoderProvisionPhase.CONTAINER_START,
    CoderProvisionPhase.VLLM_START,
    CoderProvisionPhase.MODEL_LOAD,
    CoderProvisionPhase.HEALTH_WAIT,
)

_CODER_STAGE_PATTERN = re.compile(r"^CODER_STAGE (\S+)$")
_AUTHORIZATION_LINE = re.compile(r"(?i)^.*(?:authorization|bearer)\s*:?\s+\S+.*$")
_BEARER_VALUE = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/-]+")

_SANITIZED_TAIL_CHARS = 24000


def parse_remote_stages(output: str) -> tuple[str, ...]:
    """Ordered remote stages reported by the staged bootstrap script.

    Only recognized CODER_STAGE markers are returned; anything else is
    ignored. Never returns secret-shaped content.
    """
    reached: list[str] = []
    seen: set[str] = set()
    for line in str(output).splitlines():
        match = _CODER_STAGE_PATTERN.match(line.strip())
        if match is None:
            continue
        stage = match.group(1)
        if stage not in REMOTE_STAGE_PHASES:
            continue
        if stage not in seen:
            seen.add(stage)
            reached.append(stage)
    return tuple(reached)


def sanitize_remote_tail(output: str, *, chars: int = _SANITIZED_TAIL_CHARS) -> str | None:
    """Bounded, secret-free tail of remote command output for diagnostics.

    Drops Authorization/Bearer-shaped lines and any Bearer token
    fragments, then keeps only the last ``chars`` characters.
    """
    if not output:
        return None
    lines = [
        line
        for line in str(output).splitlines()
        if not _AUTHORIZATION_LINE.match(line)
    ]
    cleaned = "\n".join(_BEARER_VALUE.sub("Bearer [redacted]", line) for line in lines)
    if not cleaned.strip():
        return None
    return cleaned[-chars:]


def format_elapsed(seconds: float) -> str:
    """Human runtime, e.g. '4m 12s' or '37s'."""
    total = max(0, int(seconds))
    minutes, remainder = divmod(total, 60)
    if minutes:
        return f"{minutes}m {remainder}s"
    return f"{remainder}s"


def _as_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


@dataclass(frozen=True)
class CoderProvisionFailure:
    """Sanitized structured record of ONE failed provisioning attempt.

    Built before teardown destroys the instance; ``cleanup_state`` is
    filled in as cleanup completes so the record survives the destroy.
    Every field is owner-visible and secret-free.
    """

    phase: str
    exception_type: str
    sanitized_message: str
    instance_id: int | None = None
    gpu_name: str | None = None
    approved_hourly_rate: Decimal | None = None
    elapsed_seconds: float = 0.0
    endpoint_state: str | None = None
    ssh_state: str | None = None
    bootstrap_state: str | None = None
    vllm_state: str | None = None
    readiness_state: str | None = None
    cleanup_state: str | None = None
    direct_port_count: int | None = None
    show_snapshot: dict | None = None

    def __post_init__(self) -> None:
        if self.phase not in CODER_PROVISION_PHASES:
            raise ValueError(f"unknown provisioning phase {self.phase!r}")
        if self.cleanup_state not in (None, *CLEANUP_STATES):
            raise ValueError(f"unknown cleanup state {self.cleanup_state!r}")
        rate = _as_decimal(self.approved_hourly_rate)
        object.__setattr__(self, "approved_hourly_rate", rate)

    def with_cleanup(self, cleanup_state: str) -> "CoderProvisionFailure":
        return CoderProvisionFailure(
            phase=self.phase,
            exception_type=self.exception_type,
            sanitized_message=self.sanitized_message,
            instance_id=self.instance_id,
            gpu_name=self.gpu_name,
            approved_hourly_rate=self.approved_hourly_rate,
            elapsed_seconds=self.elapsed_seconds,
            endpoint_state=self.endpoint_state,
            ssh_state=self.ssh_state,
            bootstrap_state=self.bootstrap_state,
            vllm_state=self.vllm_state,
            readiness_state=self.readiness_state,
            cleanup_state=cleanup_state,
            direct_port_count=self.direct_port_count,
            show_snapshot=self.show_snapshot,
        )

    def as_lines(self) -> tuple[str, ...]:
        """Owner-facing sanitized report lines for the failure panel."""
        lines = [
            "PROVISIONING FAILED",
            f"Phase: {self.phase}",
            f"Reason: {self.sanitized_message}",
        ]
        if self.instance_id is not None:
            lines.append(f"Instance: {self.instance_id}")
        if self.gpu_name:
            lines.append(f"GPU: {self.gpu_name}")
        if self.approved_hourly_rate is not None:
            lines.append(
                f"Approved rate: ${format(self.approved_hourly_rate, 'f')}/hr"
            )
        lines.append(f"Runtime before failure: {format_elapsed(self.elapsed_seconds)}")
        lines.append(f"Cleanup: {self.cleanup_state or 'unknown'}")
        return tuple(lines)

    def as_text(self) -> str:
        return "\n".join(self.as_lines())


def _json_safe(value: object) -> object:
    """Recursively convert a failure record into JSON-serializable values.

    Decimals become strings; nothing is truncated or redacted here because
    the record (including ``show_snapshot``) is already sanitized at
    capture time (whitelist-only provider fields, no credentials).
    """
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def failure_record_to_json(failure: CoderProvisionFailure) -> dict[str, object]:
    """Sanitized JSON-safe dictionary of a failure record for inspection."""
    return {
        "phase": failure.phase,
        "exception_type": failure.exception_type,
        "sanitized_message": failure.sanitized_message,
        "instance_id": failure.instance_id,
        "gpu_name": failure.gpu_name,
        "approved_hourly_rate": _json_safe(failure.approved_hourly_rate),
        "elapsed_seconds": failure.elapsed_seconds,
        "endpoint_state": failure.endpoint_state,
        "ssh_state": failure.ssh_state,
        "bootstrap_state": failure.bootstrap_state,
        "vllm_state": failure.vllm_state,
        "readiness_state": failure.readiness_state,
        "cleanup_state": failure.cleanup_state,
        "direct_port_count": failure.direct_port_count,
        "show_snapshot": _json_safe(failure.show_snapshot),
    }


def persist_failure_record(
    failure: CoderProvisionFailure,
    *,
    directory: str | None = None,
    clock: Callable[[], float] = time.time,
) -> Path:
    """Write the sanitized failure record (with the pre-cleanup show
    payload snapshot) to a JSON file so it survives process restart.

    Default directory: ``%LOCALAPPDATA%/DEFEND/provision-failures`` on
    Windows, else the system temp dir. The record is already sanitized —
    never credentials, never raw environments.
    """
    import json as _json
    import os

    from pathlib import Path as _Path

    if directory is None:
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = _Path(local_app_data) / "DEFEND" if local_app_data else _Path.home()
        directory = str(base / "provision-failures")
    target = _Path(directory)
    try:
        target.mkdir(parents=True, exist_ok=True)
    except Exception:
        target = _Path.home() / "provision-failures"
        try:
            target.mkdir(parents=True, exist_ok=True)
        except Exception:
            return _Path("provision-failure.json")
    stamp = int(clock() * 1000)
    instance = failure.instance_id
    if instance is not None:
        path = target / f"provision-failure-{instance}.json"
    else:
        path = target / f"provision-failure-{stamp}.json"
    payload = failure_record_to_json(failure)
    try:
        path.write_text(
            _json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except Exception:
        return _Path("provision-failure.json")
    return path


def wall_clock() -> str:
    """Local wall clock for lifecycle log lines, e.g. '16:01:03'."""
    return time.strftime("%H:%M:%S")