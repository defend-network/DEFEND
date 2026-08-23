"""Product-owned runtime factory/bootstrap.

Builds the full product runtime stack (neutral Vast transport, neutral SSH
transport, product policy, control plane, runtime manager, bounded health
probe) with NO Control Center factory and NO hidden global singleton.

All transports are dependency-injectable so tests are fully deterministic.
No provider call is made at construction.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from ..runtime_manager import CoderRuntimeManager
from .control_plane import CoderControlPlane, CoderPolicy, resource_profile
from .deployment import resolve_deployment
from .health import probe_endpoint_ready
from .models import CoderModelRef, LocalFakeCoderBackend, resolve_alias
from .remote_vllm import CoderRemoteVllmBootstrap
from .vast_backend import VastCoderBackend


def _load_secrets(secret_source: object) -> Mapping[str, str]:
    if hasattr(secret_source, "load"):
        return secret_source.load() or {}
    if isinstance(secret_source, Mapping):
        return dict(secret_source)
    return {}


def build_runtime_manager(
    *,
    secret_source: object | None = None,
    state_directory: str | None = None,
    policy: CoderPolicy | None = None,
    alias: str = "defendcoder-default",
    health_probe: Callable[[str, str], bool] | None = None,
    vast_transport: object | None = None,
    ssh_transport: object | None = None,
) -> CoderRuntimeManager:
    """Build the product runtime manager over a concrete control plane.

    With a VAST_API_KEY present, the real VastCoderBackend is wired (using the
    injectable Vast/SSH transports); otherwise a deterministic local fake
    backend is used so the state machine remains exercisable without any
    provider call. The bounded health probe is the real endpoint-model probe
    unless a deterministic test probe is injected.
    """
    secrets = _load_secrets(secret_source) if secret_source is not None else {}
    api_key = secrets.get("VAST_API_KEY")

    expected_model = resolve_alias(alias).repo_id if _alias_resolvable(alias) else ""

    probe = health_probe or (lambda ep, mdl: probe_endpoint_ready(ep, mdl))
    effective_policy = policy or CoderPolicy()

    if api_key:
        from shared_platform.vast import VastClient

        vast = VastClient(api_key, transport=vast_transport) if vast_transport else VastClient(api_key)
        profile = resource_profile(alias, effective_policy)
        launch = _launch_for(alias)
        bootstrap = CoderRemoteVllmBootstrap(
            ssh_exe=Path("ssh"), known_hosts=Path("unused"), key_path=Path("unused")
        )
        backend = VastCoderBackend(
            vast=vast,
            secrets=dict(secrets),
            bootstrap=bootstrap,
            max_hourly=effective_policy.max_hourly_usd,
            profile=profile,
            launch=launch,
            tunnel_start=None,
            host_prepare=None,
        )
    else:
        backend = LocalFakeCoderBackend()

    plane = CoderControlPlane(
        backend=backend,
        policy=effective_policy,
        token_provider=lambda: secrets.get("HF_TOKEN"),
        state_directory=state_directory,
    )
    return CoderRuntimeManager(
        control_plane=plane,
        alias=alias,
        expected_model=expected_model or None,
        health_probe=probe,
    )


def _alias_resolvable(alias: str) -> bool:
    try:
        resolve_alias(alias)
        return True
    except Exception:  # noqa: BLE001
        return False


def _launch_for(alias: str):
    from shared_platform.compute_types import LaunchSpec

    from .launch import coder_default_launch, coder_heavy_direct_launch

    if "heavy" in alias or "direct" in alias:
        return coder_heavy_direct_launch()
    return coder_default_launch()
