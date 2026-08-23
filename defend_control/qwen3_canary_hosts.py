"""Concrete (production) Vast gateway and remote host for the Qwen3 canary.

These compose the canonical Vast client and remote execution infrastructure
rather than reimplementing credentials, URLs, or launch payload logic. They are
the real paid-path adapters (M1.9.2D); the fakes in tests exercise the same
interfaces.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Callable

from .qwen3_canary_executor import ProductionInventory, candidate_canary_resource_profile, classify_production_inventory
from .qwen3_canary_runner import CanaryPolicy
from .training_hardening import INVENTORY_UNKNOWN
from .types import LaunchSpec, VastOffer


@dataclass(frozen=True)
class CanaryRemoteTarget:
    """Immutable connection identity bound exactly once for the run."""

    instance_id: int
    host: str
    port: int
    user: str
    offer_id: int
    hourly_rate: Decimal


BLOCKED_HOSTS = frozenset({"ssh3.vast.ai"})


def _classify_instance_response(instances) -> str:
    """Map a raw provider ``instances`` field to tri-state. ``None``/empty is
    authoritative ABSENT; non-empty mapping/list is PRESENT."""
    from .qwen3_canary_executor import INSTANCE_ABSENT, INSTANCE_PRESENT, INSTANCE_UNKNOWN

    if instances is None:
        return INSTANCE_ABSENT
    if isinstance(instances, dict) and instances:
        return INSTANCE_PRESENT
    if isinstance(instances, list) and instances:
        return INSTANCE_PRESENT
    if isinstance(instances, (dict, list)):
        return INSTANCE_ABSENT
    return INSTANCE_UNKNOWN


class ConcreteVastGateway:
    def __init__(self, client=None) -> None:
        self._client = client

    def _get_client(self):
        if self._client is None:
            from .secrets import DpapiSecretStore
            from .vast import VastClient

            store = DpapiSecretStore(Path(os.environ["LOCALAPPDATA"]) / "DEFEND" / "secrets.dpapi")
            self._client = VastClient(store.load()["VAST_API_KEY"])
        return self._client

    def inventory(self) -> ProductionInventory:
        import urllib.request
        from urllib.parse import urlencode

        client = self._get_client()
        key = getattr(client, "_api_key", None)
        if not key:
            return ProductionInventory(INVENTORY_UNKNOWN, False, ())
        all_instances: list[dict] = []
        next_token = None
        try:
            while True:
                query = {"limit": 100}
                if next_token:
                    query["next_token"] = next_token
                url = "https://console.vast.ai/api/v1/instances/?" + urlencode(query)
                req = urllib.request.Request(url, headers={"Accept": "application/json", "Authorization": f"Bearer {key}"})
                with urllib.request.urlopen(req, timeout=40) as resp:
                    document = json.loads(resp.read().decode("utf-8"))
                if not isinstance(document, dict) or document.get("success") is not True:
                    return ProductionInventory(INVENTORY_UNKNOWN, False, ())
                instances = document.get("instances")
                if not isinstance(instances, list):
                    return ProductionInventory(INVENTORY_UNKNOWN, False, ())
                all_instances.extend(instances)
                next_token = document.get("next_token")
                if next_token is None:
                    break
        except Exception:
            return ProductionInventory(INVENTORY_UNKNOWN, False, ())
        return classify_production_inventory(all_instances, complete=True)

    def select_offer(self, policy: CanaryPolicy) -> VastOffer | None:
        offers = self._get_client().search_offers(policy.max_hourly_usd, candidate_canary_resource_profile())
        return offers[0] if offers else None

    def create(self, offer: VastOffer):
        return self._get_client().create_instance(offer, LaunchSpec.candidate_canary())

    def destroy(self, instance_id: int) -> bool:
        return self._get_client().destroy_instance(instance_id, confirmed_instance_id=instance_id)

    def resolve_target(self, instance_id: int) -> dict | None:
        """Resolve the direct SSH endpoint belonging to the exact created
        instance from provider evidence (never caller-supplied host identity)."""
        instance = self._get_client().show_instance(instance_id)
        if instance.instance_id != instance_id:
            return None
        host = instance.direct_ssh_host or instance.ssh_host
        port = instance.direct_ssh_port or instance.ssh_port
        if not host or not port:
            return None
        return {"host": host, "port": int(port), "user": "root"}

    def instance_state(self, instance_id: int) -> str:
        """Tri-state read-only instance verification (never fail-open).

        ABSENT only from authoritative not-found/deleted provider evidence;
        transport/auth/5xx/malformed → UNKNOWN.
        """
        import urllib.error
        import urllib.request

        from .qwen3_canary_executor import INSTANCE_ABSENT, INSTANCE_PRESENT, INSTANCE_UNKNOWN

        key = getattr(self._get_client(), "_api_key", None)
        if not key:
            return INSTANCE_UNKNOWN
        url = f"https://console.vast.ai/api/v0/instances/{instance_id}/"
        req = urllib.request.Request(url, headers={"Accept": "application/json", "Authorization": f"Bearer {key}"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                document = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return INSTANCE_ABSENT if exc.code == 404 else INSTANCE_UNKNOWN
        except Exception:
            return INSTANCE_UNKNOWN
        instances = document.get("instances") if isinstance(document, dict) else None
        return _classify_instance_response(instances)


class ConcreteRemoteHost:
    """Runs canary stages on the rented Vast host over SSH.

    Every stage is bound to an immutable ``CanaryRemoteTarget``; local-only
    execution is impossible through the production path. The default runner is
    a real ``ssh`` subprocess; tests inject a fake runner.
    """

    def __init__(self, target: CanaryRemoteTarget | None = None, ssh_runner: Callable[[list[str], float], dict] | None = None,
                 git_head: str = "", train_remote_path: str = "/workspace/defend-canary/sft.jsonl") -> None:
        self._target = target
        self._ssh_runner = ssh_runner or self._default_ssh_runner
        self._git_head = git_head
        self._train_remote_path = train_remote_path

    @property
    def target(self) -> CanaryRemoteTarget | None:
        return self._target

    def bind_target(self, target: CanaryRemoteTarget) -> None:
        if self._target is not None:
            raise RuntimeError("remote target already bound")
        if not isinstance(target, CanaryRemoteTarget):
            raise ValueError("target must be a CanaryRemoteTarget")
        self._target = target

    @staticmethod
    def _default_ssh_runner(argv: list[str], timeout: float) -> dict:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return {"status": "PASS" if proc.returncode == 0 else "FAIL", "detail": proc.stdout.strip()[-300:]}

    @staticmethod
    def _build_ssh_command(target: CanaryRemoteTarget, remote_command: str) -> list[str]:
        return ["ssh", "-p", str(target.port), f"{target.user}@{target.host}", remote_command]

    def _stage_command(self, stage: str, adapter_dir: str, git_head: str) -> str:
        if stage == "HOST_PREFLIGHT":
            head = git_head or self._git_head
            return (
                f"python -m defend_control.qwen3_canary_preflight "
                f"--repo-head {head} --train-file {self._train_remote_path}"
            )
        if stage == "TRAIN_5_STEPS":
            return (
                f"python -m defend_control.qwen3_canary_train --data-file {self._train_remote_path} "
                f"--adapter-dir {adapter_dir} --steps 5"
            )
        if stage == "FRESH_RELOAD":
            return f"python -m defend_control.qwen3_canary_reload --adapter-dir {adapter_dir}"
        raise ValueError(f"unknown canary stage {stage!r}")

    def run_stage(self, stage: str, instance_id: int, adapter_dir: str, timeout_seconds: float) -> dict:
        if self._target is None:
            return {"status": "FAIL", "detail": "no remote target bound"}
        if instance_id != self._target.instance_id:
            return {"status": "FAIL", "detail": "instance ID mismatch vs bound target"}
        if self._target.host in BLOCKED_HOSTS:
            return {"status": "FAIL", "detail": "blocked host"}
        remote_command = self._stage_command(stage, adapter_dir, "")
        argv = self._build_ssh_command(self._target, remote_command)
        try:
            return self._ssh_runner(argv, timeout_seconds)
        except subprocess.TimeoutExpired:
            return {"status": "FAIL", "detail": "remote stage timeout"}
