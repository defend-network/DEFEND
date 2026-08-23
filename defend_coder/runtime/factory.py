"""Product-owned runtime factory/bootstrap.

Builds the full product runtime stack (neutral Vast transport, neutral SSH
transport, product policy, control plane, runtime manager, bounded health
probe) with NO Control Center factory and NO hidden global singleton.

Production fail-closed behavior:
- NO VAST_API_KEY -> NoProviderBackend (ABSENT/UNCONFIGURED; can never become
  READY, never provision, never resume, never destroy).
- LocalFakeCoderBackend is TEST/OFFLINE-only and is injected explicitly via
  ``backend=`` — the factory never auto-selects it.

SSH transport/bootstrap uses product-owned runtime state (isolated known_hosts
+ key path derived from ``state_root``), never "unused", never global user
known_hosts, never StrictHostKeyChecking=no.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from ..runtime_manager import CoderRuntimeManager
from .control_plane import CoderControlPlane, CoderPolicy, resource_profile
from .health import probe_endpoint_ready
from .models import CoderModelRef, resolve_alias
from .no_provider import NoProviderBackend
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
    state_root: str | None = None,
    state_directory: str | None = None,
    policy: CoderPolicy | None = None,
    alias: str = "defendcoder-default",
    health_probe: Callable[[str, str], bool] | None = None,
    vast_transport: object | None = None,
    command_runner: Callable[..., Any] | None = None,
    backend: object | None = None,
) -> CoderRuntimeManager:
    """Build the product runtime manager over a concrete control plane.

    ``backend`` (TEST/OFFLINE only) is honored first; otherwise the production
    path is used: a real VastCoderBackend when a VAST_API_KEY is present, else
    a fail-closed NoProviderBackend. ``command_runner`` wires the SSH/bootstrap
    transport (used by CoderRemoteVllmBootstrap); the default is the product
    SSH runner. SSH state derives from ``state_root``.
    """
    secrets = _load_secrets(secret_source) if secret_source is not None else {}
    api_key = secrets.get("VAST_API_KEY")

    expected_model = _expected_model(alias)
    probe = health_probe or (lambda ep, mdl: probe_endpoint_ready(ep, mdl))
    effective_policy = policy or CoderPolicy()

    if backend is not None:
        plane_backend = backend
    elif api_key:
        from shared_platform.vast import VastClient

        vast = VastClient(api_key, transport=vast_transport) if vast_transport else VastClient(api_key)
        profile = resource_profile(alias, effective_policy)
        from .launch import coder_default_launch, coder_heavy_direct_launch

        launch = (
            coder_heavy_direct_launch()
            if ("heavy" in alias or "direct" in alias)
            else coder_default_launch()
        )
        bootstrap = CoderRemoteVllmBootstrap(
            ssh_exe=Path("ssh"),
            known_hosts=_ssh_known_hosts(state_root),
            key_path=_ssh_key_path(state_root),
            command_runner=command_runner,
        )
        plane_backend = VastCoderBackend(
            vast=vast,
            secrets=dict(secrets),
            bootstrap=bootstrap,
            max_hourly=effective_policy.max_hourly_usd,
            profile=profile,
            launch=launch,
        )
    else:
        plane_backend = NoProviderBackend()

    plane = CoderControlPlane(
        backend=plane_backend,
        policy=effective_policy,
        token_provider=lambda: secrets.get("HF_TOKEN"),
        state_directory=state_directory,
    )
    return CoderRuntimeManager(
        control_plane=plane,
        alias=alias,
        expected_model=expected_model,
        health_probe=probe,
    )


def _expected_model(alias: str) -> str | None:
    try:
        return resolve_alias(alias).repo_id
    except Exception:  # noqa: BLE001
        return None


def _ssh_known_hosts(state_root: str | None) -> Path:
    return _ssh_dir(state_root) / "known_hosts"


def _ssh_key_path(state_root: str | None) -> Path:
    return _ssh_dir(state_root) / "coder_ed25519"


def _ssh_dir(state_root: str | None) -> Path:
    if state_root:
        return Path(state_root) / "ssh"
    return Path("coder-state") / "ssh"
