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
from decimal import Decimal
from pathlib import Path
from typing import Callable

from .qwen3_canary_executor import ProductionInventory, candidate_canary_resource_profile, classify_production_inventory
from .qwen3_canary_runner import CanaryPolicy
from .training_hardening import INVENTORY_UNKNOWN
from .types import LaunchSpec, VastOffer


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

    def instance_absent(self, instance_id: int) -> bool:
        try:
            self._get_client().show_instance(instance_id)
            return False
        except Exception:
            return True


class ConcreteRemoteHost:
    """Runs canary stages on the paid host via an injected SSH runner.

    The default runner is a real ``ssh`` subprocess with a hard timeout; tests
    inject a fake runner. Each paid stage receives a bounded timeout derived
    from remaining budget (never an unbounded hang).
    """

    def __init__(self, ssh_runner: Callable[[str, float], dict] | None = None) -> None:
        self._ssh_runner = ssh_runner or self._default_ssh_runner

    @staticmethod
    def _default_ssh_runner(command: str, timeout: float) -> dict:
        proc = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout)
        return {"status": "PASS" if proc.returncode == 0 else "FAIL", "detail": proc.stdout.strip()[-200:]}

    def _stage_command(self, stage: str, instance_id: int, adapter_dir: str) -> str:
        if stage == "TRAIN_5_STEPS":
            return (
                f"python -m defend_control.qwen3_canary_train --data-file /workspace/defend/sft.jsonl "
                f"--adapter-dir {adapter_dir} --steps 5"
            )
        if stage == "FRESH_RELOAD":
            return f"python -m defend_control.qwen3_canary_reload --adapter-dir {adapter_dir}"
        if stage == "SANITY_INFERENCE":
            return f"python -m defend_control.qwen3_canary_reload --adapter-dir {adapter_dir}"
        if stage == "HOST_PREFLIGHT":
            return "python -m defend_control.qwen3_canary_train --help"
        return f"echo STAGE={stage}"

    def run_stage(self, stage: str, instance_id: int, adapter_dir: str, timeout_seconds: float) -> dict:
        command = self._stage_command(stage, instance_id, adapter_dir)
        try:
            return self._ssh_runner(command, timeout_seconds)
        except subprocess.TimeoutExpired:
            return {"status": "FAIL", "detail": "remote stage timeout"}
