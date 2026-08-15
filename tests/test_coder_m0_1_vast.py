"""DEFENDcoder M0.1 tests — Vast backend with fakes; no live billing."""

from decimal import Decimal
from pathlib import Path

import pytest

from defend_control.coder_m0 import CoderM0Service, CoderModelRef, resolve_alias
from defend_control.coder_remote_vllm import CoderRemoteVllmBootstrap
from defend_control.coder_vast_backend import VastCoderBackend, CoderVastBackendError
from defend_control.types import LaunchSpec, ResourceProfile, VastInstance, VastOffer


def test_coder_launch_spec_is_distinct_from_chat():
    chat = LaunchSpec.default()
    coder = LaunchSpec.coder_default()
    assert chat.label == "defend-vllm"
    assert coder.label == "defendcoder-vllm"
    assert chat.image == coder.image
    assert chat != coder


def test_coder_resource_profile_allows_80gb_class():
    profile = ResourceProfile.coder_default()
    assert profile.min_gpu_ram_mb == 80_000
    chat = ResourceProfile()
    assert chat.min_gpu_ram_mb >= 140_000
    assert profile.min_gpu_ram_mb < chat.min_gpu_ram_mb


class FakeVast:
    def __init__(self):
        self.created = []
        self.destroyed = []
        self.states = []

    def search_offers(self, max_hourly, profile=None):
        return (
            VastOffer(
                101,
                "A100 SXM4",
                81920,
                Decimal("1.10"),
                Decimal("0.99"),
            ),
        )

    def create_instance(self, offer, launch):
        assert launch.label == "defendcoder-vllm"
        self.created.append((offer.offer_id, launch.label))
        return VastInstance(
            555001,
            None,
            None,
            None,
            offer.gpu_name,
            offer.gpu_ram_mb,
            offer.dph_total,
        )

    def wait_until_running(self, instance_id):
        return VastInstance(
            instance_id,
            "running",
            "ssh.example",
            22,
            "A100 SXM4",
            81920,
            Decimal("1.10"),
        )

    def destroy_instance(self, instance_id, *,
 confirmed_instance_id=None):
        assert confirmed_instance_id == instance_id
        self.destroyed.append(instance_id)
        return True

    def set_state(self, instance_id, state):
        self.states.append((instance_id, state))
        return True


class FakeBootstrap:
    def __init__(self):
        self.starts = []
        self.artifacts = []

    def start(self, instance, model, secrets, *,
 remote_port=8000, prefer_direct=False, cancelled=None, artifact=None):
        self.starts.append((instance.instance_id, model.alias, remote_port))
        self.artifacts.append(artifact.artifact_id if artifact is not None else None)


def test_vast_coder_backend_start_smoke_destroy_with_fakes():
    vast = FakeVast()
    bootstrap = FakeBootstrap()
    backend = VastCoderBackend(
        vast=vast,  # type: ignore[arg-type]
        secrets={"HF_TOKEN": "hf_test", "CODER_VLLM_API_KEY": "coder-key"},
        bootstrap=bootstrap,  # type: ignore[arg-type]
        max_hourly=Decimal("2.00"),
        smoke_http=lambda endpoint, key, model: {
            "ok": True,
            "latency_ms": 5,
            "detail": f"fake smoke {model.alias}",
        },
    )
    service = CoderM0Service(backend=backend, local_port=8003)

    status = service.start("defendcoder-default")
    assert status.state == "ready"
    assert status.instance_id == 555001
    assert status.provider_run_id == "vast-555001"
    assert status.hourly_price == "1.10"
    assert bootstrap.starts == [(555001, "defendcoder-default", 8000)]
    assert bootstrap.artifacts == ["qwen3-coder-30b-a3b-bf16"]
    assert vast.created == [(101, "defendcoder-vllm")]

    smoke = service.smoke()
    assert smoke.ok is True

    stopped = service.stop(destroy=True, confirmed_instance_id=555001)
    assert stopped.state == "stopped"
    assert vast.destroyed == [555001]


def test_vast_coder_backend_stop_without_destroy_sets_stopped_state():
    vast = FakeVast()
    backend = VastCoderBackend(
        vast=vast,  # type: ignore[arg-type]
        secrets={"HF_TOKEN": "hf_test", "CODER_VLLM_API_KEY": "coder-key"},
        bootstrap=FakeBootstrap(),  # type: ignore[arg-type]
        max_hourly=Decimal("2.00"),
        smoke_http=lambda *args: {"ok": True, "latency_ms": 1, "detail": "ok"},
    )
    service = CoderM0Service(backend=backend)
    service.start()
    status = service.stop(destroy=False)
    assert status.state == "stopped"
    assert vast.states == [(555001, "stopped")]
    assert vast.destroyed == []


def test_coder_remote_bootstrap_rejects_bad_repo():
    boot = CoderRemoteVllmBootstrap(
        ssh_exe=Path("ssh"),
        known_hosts=Path("known_hosts"),
        key_path=Path("key"),
    )
    bad = CoderModelRef(
        alias="defendcoder-default",
        repo_id="not valid",
        revision="main",
    )
    with pytest.raises(Exception):
        boot.start(
            VastInstance(1, "running", "host", 22, "A100", 81920, Decimal("1")),
            bad,
            {"HF_TOKEN": "x", "CODER_VLLM_API_KEY": "y"},
        )
