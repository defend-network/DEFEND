"""DEFENDcoder owner-approved Heavy smoke prep tests (LIVE HEAVY SMOKE PREP).

Zero provider create calls anywhere in this file. All offers are fakes.
"""

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from defend_control.coder_control_plane import (
    CoderControlPlane,
    CoderLiveSmokePlan,
    CoderPolicy,
    CoderPreparedProvision,
    CoderProvisionApproval,
    CoderProvisionBlocked,
    LIVE_SMOKE_SEQUENCE,
    _plan_fingerprint,
    resource_profile,
)
from defend_control.coder_deployment import resolve_deployment
from defend_control.coder_m0 import resolve_alias
from defend_control.coder_remote_vllm import CoderRemoteVllmBootstrap
from defend_control.coder_vast_backend import (
    CoderVastBackendError,
    VastCoderBackend,
)
from defend_control.ssh_tunnel import CommandResult
from defend_control.types import (
    LaunchSpec,
    ResourceProfile,
    VastInstance,
    VastOffer,
)

FP8_REVISION = "da6e2ed27304dd39abadd9c82ef50e8de67bdd4c"

_OFFERS = (
    VastOffer(601, "H100 SXM 80GB", 81920, Decimal("1.65"), Decimal("0.99")),
    VastOffer(602, "H200 SXM 141GB", 144384, Decimal("2.00"), Decimal("0.99")),
)


class RecordingHeavyBackend:
    def __init__(self, offers: tuple[VastOffer, ...] = _OFFERS) -> None:
        self.offers = offers
        self.starts: list[tuple[str, int, int | None]] = []
        self.smokes = 0
        self.stops: list[tuple[int | None, bool]] = []

    def search_offers_for(self, model, profile, *, launch_runtype=None):
        return self.offers

    def start(self, model, *, local_port, session_budget_usd, offer=None, profile=None, launch_runtype=None):
        self.starts.append(
            (model.alias, local_port, offer.offer_id if offer is not None else None)
        )
        return {
            "state": "ready",
            "provider": "vast",
            "endpoint": f"http://127.0.0.1:{local_port}/v1",
            "instance_id": 555200,
            "provider_run_id": "vast-555200",
            "hourly_price": (
                str(offer.dph_total) if offer is not None else "1.65"
            ),
            "gpu_type": offer.gpu_name if offer is not None else None,
            "message": "heavy recording ready",
        }

    def smoke(self, endpoint, model):
        self.smokes += 1
        return {"ok": True, "latency_ms": 3, "detail": "recording ok"}

    def stop(self, *, instance_id, provider_run_id, destroy):
        self.stops.append((instance_id, destroy))
        return {"state": "stopped", "message": "recording stopped"}


class RecordingCoderRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], bytes, float]] = []

    def __call__(self, argv, *, stdin, timeout, cancelled=None):
        self.calls.append((tuple(argv), stdin, timeout))
        return CommandResult(0, b"ok", b"")


def _plane(
    backend: RecordingHeavyBackend | None = None,
    **overrides,
) -> CoderControlPlane:
    options = {
        "backend": backend if backend is not None else RecordingHeavyBackend(),
        "token_provider": lambda: "hf_fake_token",
        "port_available": lambda port: True,
    }
    options.update(overrides)
    return CoderControlPlane(**options)  # type: ignore[arg-type]


def _rendered_heavy_script() -> str:
    runner = RecordingCoderRunner()
    boot = CoderRemoteVllmBootstrap(
        command_runner=runner,
        ssh_exe=Path("ssh"),
        known_hosts=Path("known_hosts"),
        key_path=Path("key"),
    )
    boot.start(
        VastInstance(1, "running", "host.example", 22, "A100", 81920, Decimal("1.65")),
        resolve_alias("defendcoder-heavy"),
        {"HF_TOKEN": "hf_synthetic", "CODER_VLLM_API_KEY": "vllm_synthetic"},
        artifact=resolve_deployment("defendcoder-heavy"),
    )
    return runner.calls[0][1].decode("ascii")


class TestHeavyProfile:
    def test_heavy_smoke_profile_uses_two_gpus(self):
        profile = resource_profile("defendcoder-heavy", CoderPolicy())
        assert profile.num_gpus == 2
        assert profile.min_gpu_ram_mb == 81_920
        assert profile.allowed_gpu_families == (
            "H100",
            "H200",
            "B200",
        )

    def test_single_gpu_heavy_profile_remains_available(self):
        profile = resource_profile(
            "defendcoder-heavy", CoderPolicy(heavy_num_gpus=1)
        )
        assert profile.num_gpus == 1

    def test_policy_rejects_invalid_gpu_count(self):
        with pytest.raises(ValueError):
            CoderPolicy(heavy_num_gpus=0)  # type: ignore[arg-type]


class TestTensorParallel:
    def test_heavy_tensor_parallel_size_is_two(self):
        assert resolve_deployment("defendcoder-heavy").tensor_parallel_size == 2
        assert resolve_deployment("defendcoder-default").tensor_parallel_size == 1

    def test_heavy_bootstrap_script_contains_tp_flag(self):
        rendered = _rendered_heavy_script()
        assert "--tensor-parallel-size 2" in rendered
        assert "--max-model-len 32768" in rendered
        assert "--tool-call-parser qwen3_coder" in rendered


class TestPlanAndApproval:
    def test_plan_shows_selected_offer_exact_rate_and_config(self):
        backend = RecordingHeavyBackend()
        plane = _plane(backend)
        plan = plane.live_smoke_plan("defendcoder-heavy")
        assert isinstance(plan, CoderLiveSmokePlan)
        assert plan.alias == "defendcoder-heavy"
        assert plan.provider == "vast"
        assert plan.logical_repo_id == "Qwen/Qwen3-Coder-Next"
        assert plan.deployment_repo_id == "Qwen/Qwen3-Coder-Next-FP8"
        assert plan.deployment_revision == FP8_REVISION
        assert plan.precision == "FP8"
        assert plan.gpu_count == 2
        assert plan.vram_per_gpu_mb == 81_920
        assert plan.gpu_family == "H100 SXM 80GB"
        assert plan.provider_hourly_rate == Decimal("1.65")
        assert plan.estimated_max_hourly_spend == Decimal("1.65")
        assert plan.offer_id == 601
        assert plan.max_hourly_price_usd == Decimal("4.50")
        assert plan.session_budget_usd == Decimal("5.00")
        assert plan.max_model_len == 32_768
        assert plan.tensor_parallel_size == 2
        assert plan.serving_runtime == "vllm/vllm-openai:v0.15.0"
        assert plan.tool_call_parser == "qwen3_coder"
        assert plan.launch_runtype == "ssh_proxy"
        assert plan.local_port == 8003
        assert plan.status == "requires_approval"
        assert plan.plan_id
        assert plan.plan_hash

    def test_default_coder_lane_plan_uses_qualification_proxy_runtype(self):
        backend = RecordingHeavyBackend()
        plane = _plane(backend)
        plan = plane.live_smoke_plan("defendcoder-default")
        assert plan.launch_runtype == "ssh_proxy"
        assert plan.as_public_dict()["launch_runtype"] == "ssh_proxy"

    def test_explicit_direct_lane_plan_is_fingerprinted_as_ssh_direct(self):
        backend = RecordingHeavyBackend()
        plane = _plane(backend)
        plan = plane.prepared_provision(
            "defendcoder-heavy", launch_runtype="ssh_direct"
        )
        assert plan.plan.launch_runtype == "ssh_direct"
        assert plan.plan.as_public_dict()["launch_runtype"] == "ssh_direct"

    def test_changed_launch_transport_invalidates_approval(self):
        plane = _plane()
        prepared = plane.prepared_provision("defendcoder-heavy")
        assert prepared.plan.launch_runtype == "ssh_proxy"
        approval = plane.approve(prepared)
        proxy_hash = _plan_fingerprint(prepared.plan, prepared.offer)
        direct_plan = replace(prepared.plan, launch_runtype="ssh_direct")
        direct_hash = _plan_fingerprint(direct_plan, prepared.offer)
        assert direct_hash != proxy_hash
        reoffered = CoderPreparedProvision(
            plan=direct_plan, offer=prepared.offer, plan_hash=direct_hash
        )
        with pytest.raises(CoderProvisionBlocked, match="no longer matches"):
            plane.provision(reoffered, approval)

    def test_plan_and_search_make_no_provider_calls(self):
        backend = RecordingHeavyBackend()
        plane = _plane(backend)
        prepared = plane.prepared_provision("defendcoder-heavy")
        plane.approve(prepared)
        assert backend.starts == []
        assert backend.smokes == 0

    def test_approval_binds_to_exact_plan(self):
        plane = _plane()
        prepared = plane.prepared_provision("defendcoder-heavy")
        approval = plane.approve(prepared)
        assert isinstance(approval, CoderProvisionApproval)
        assert approval.plan_id == prepared.plan.plan_id
        assert approval.plan_hash == prepared.plan.plan_hash
        assert approval.approver == "owner"
        assert approval.approved_at.tzinfo is not None

    def test_approval_is_mandatory_before_provisioning(self):
        backend = RecordingHeavyBackend()
        plane = _plane(backend)
        prepared = plane.prepared_provision("defendcoder-heavy")
        with pytest.raises(CoderProvisionBlocked, match="approval"):
            plane.provision(prepared, None)
        assert backend.starts == []

    def test_approval_from_another_plan_is_rejected(self):
        plane = _plane()
        first = plane.prepared_provision("defendcoder-heavy")
        approval = plane.approve(first)
        second = plane.prepared_provision("defendcoder-heavy")
        with pytest.raises(CoderProvisionBlocked, match="plan"):
            plane.provision(second, approval)

    def test_changed_offer_invalidates_approval(self):
        backend = RecordingHeavyBackend()
        plane = _plane(backend)
        prepared = plane.prepared_provision("defendcoder-heavy")
        approval = plane.approve(prepared)
        changed = RecordingHeavyBackend(
            offers=(
                VastOffer(777, "H100 SXM 80GB", 81920, Decimal("2.75"), Decimal("0.99")),
            )
        )
        plane_changed = _plane(changed)
        reoffered = plane_changed.prepared_provision("defendcoder-heavy")
        with pytest.raises(CoderProvisionBlocked, match="no longer matches"):
            plane_changed.provision(reoffered, approval)
        assert changed.starts == []

    def test_provision_after_approval_reaches_backend_with_offer(self):
        backend = RecordingHeavyBackend()
        plane = _plane(backend)
        prepared = plane.prepared_provision("defendcoder-heavy")
        approval = plane.approve(prepared)
        lease = plane.provision(prepared, approval)
        assert lease.reused is False
        assert backend.starts == [("defendcoder-heavy", 8003, 601)]
        assert plane.active_endpoints()[0].state == "ready"

    def test_cheapest_qualifying_proxy_capable_offer_wins(self):
        backend = RecordingHeavyBackend(
            offers=(
                VastOffer(602, "H200 SXM 141GB", 144384, Decimal("2.00"), Decimal("0.99")),
                VastOffer(601, "H100 SXM 80GB", 81920, Decimal("1.65"), Decimal("0.99")),
                VastOffer(600, "H100 SXM 80GB", 81920, Decimal("1.65"), Decimal("0.999")),
                VastOffer(599, "H100 SXM 80GB", 81920, Decimal("1.65"), Decimal("0.999")),
            )
        )
        plane = _plane(backend)
        prepared = plane.prepared_provision("defendcoder-heavy")
        assert prepared.plan.launch_runtype == "ssh_proxy"
        assert prepared.plan.offer_id == 599

    def test_over_budget_offer_cannot_be_approved(self):
        backend = RecordingHeavyBackend(
            offers=(
                VastOffer(900, "A100 SXM4 80GB", 81920, Decimal("5.25"), Decimal("0.99")),
            )
        )
        plane = _plane(backend)
        prepared = plane.prepared_provision("defendcoder-heavy")
        assert prepared.plan.estimated_max_hourly_spend == Decimal("5.25")
        with pytest.raises(ValueError, match="exceeds"):
            plane.approve(prepared)
        assert backend.starts == []

    def test_plan_public_dict_has_no_secrets_and_exact_rate(self):
        plane = _plane()
        public = plane.live_smoke_plan("defendcoder-heavy").as_public_dict()
        assert public["provider_hourly_rate"] == "1.65"
        assert public["estimated_max_hourly_spend"] == "1.65"
        assert public["gpu_count"] == 2
        assert public["tensor_parallel_size"] == 2
        blob = " ".join(f"{key}={value}" for key, value in public.items())
        for banned in ("api_key", "password", "secret", "bearer"):
            assert banned not in blob.casefold()


class TestUnchanged:
    def test_default_profile_remains_single_gpu(self):
        assert resource_profile("defendcoder-default", CoderPolicy()).num_gpus == 1
        assert ResourceProfile().num_gpus == 1
        assert LaunchSpec.default() == LaunchSpec(
            "vllm/vllm-openai:v0.10.0",
            160,
            "ssh_proxy",
            "defend-vllm",
        )

    def test_heavy_official_requirements_unchanged(self):
        artifact = resolve_deployment("defendcoder-heavy")
        assert artifact.minimum_vllm_version == "0.15.0"
        assert artifact.max_model_len == 32_768
        assert artifact.tool_call_parser == "qwen3_coder"
        assert artifact.enable_auto_tool_choice is True


class RecordingHeavyVast:
    def __init__(self) -> None:
        self.created: list[LaunchSpec] = []
        self._last_raw = {}

    def list_labeled_instance_ids(self, label):
        del label
        return ()

    def search_offers(self, max_hourly, profile):
        return _OFFERS

    def create_instance(self, offer, launch):
        self.created.append(launch)
        return VastInstance(
            555, None, "ssh.example", 2222, offer.gpu_name, offer.gpu_ram_mb, offer.dph_total
        )

    def wait_until_running(self, instance_id):
        return self.show_instance(instance_id)

    def show_instance(self, instance_id):
        return VastInstance(
            instance_id,
            "running",
            "ssh.example",
            2222,
            "A100 SXM4 80GB",
            81920,
            Decimal("1.65"),
            direct_ssh_host="10.0.0.9",
            direct_ssh_port=2222,
            image_runtype="ssh_direct",
        )

    def last_raw_payload(self, kind):
        del kind
        return self._last_raw

    def destroy_instance(self, instance_id, *, confirmed_instance_id=None):
        return True


def _heavy_backend(vast: RecordingHeavyVast) -> VastCoderBackend:
    return VastCoderBackend(
        vast=vast,  # type: ignore[arg-type]
        secrets={
            "HF_TOKEN": "hf_synthetic",
            "CODER_VLLM_API_KEY": "vllm_synthetic",
        },
        bootstrap=CoderRemoteVllmBootstrap(
            command_runner=RecordingCoderRunner(),
            ssh_exe=Path("ssh"),
            known_hosts=Path("known_hosts"),
            key_path=Path("key"),
        ),
        max_hourly=Decimal("2.00"),
        tunnel_start=lambda instance, local_port, *, prefer_direct: (
            f"http://127.0.0.1:{local_port}/v1"
        ),
        local_verify=lambda endpoint: True,
        direct_endpoint_wait_seconds=5.0,
        direct_endpoint_poll_seconds=0.01,
    )


class TestHeavyProxySshLane:
    def test_heavy_lane_requests_proxy_ssh_runtype_at_creation(self):
        vast = RecordingHeavyVast()
        backend = _heavy_backend(vast)
        backend.start(
            resolve_alias("defendcoder-heavy"),
            local_port=8003,
            session_budget_usd=Decimal("5.00"),
            offer=_OFFERS[0],
        )
        assert len(vast.created) == 1
        assert vast.created[0].runtype == "ssh_proxy"
        assert vast.created[0].label == "defendcoder-vllm"
        assert vast.created[0].image == "vllm/vllm-openai:v0.15.0"

    def test_default_coder_lane_uses_proxy_ssh_runtype(self):
        vast = RecordingHeavyVast()
        backend = _heavy_backend(vast)
        backend.start(
            resolve_alias("defendcoder-default"),
            local_port=8003,
            session_budget_usd=Decimal("5.00"),
            offer=_OFFERS[0],
        )
        assert len(vast.created) == 1
        assert vast.created[0].runtype == "ssh_proxy"
        assert vast.created[0].label == "defendcoder-vllm"

    def test_direct_lane_remains_available_as_explicit_alternative(self):
        vast = RecordingHeavyVast()
        backend = _heavy_backend(vast)
        backend.start(
            resolve_alias("defendcoder-heavy"),
            local_port=8003,
            session_budget_usd=Decimal("5.00"),
            offer=_OFFERS[0],
            launch_runtype="ssh_direct",
        )
        assert len(vast.created) == 1
        assert vast.created[0].runtype == "ssh_direct"
        assert vast.created[0].label == "defendcoder-vllm"

    def test_invalid_explicit_runtype_is_rejected(self):
        vast = RecordingHeavyVast()
        backend = _heavy_backend(vast)
        with pytest.raises(CoderVastBackendError, match="launch_runtype"):
            backend.start(
                resolve_alias("defendcoder-heavy"),
                local_port=8003,
                session_budget_usd=Decimal("5.00"),
                offer=_OFFERS[0],
                launch_runtype="ssh_sidecar",
            )
        assert vast.created == []


class TestSmokeSequence:
    def test_live_smoke_sequence_is_documented_and_ordered(self):
        assert LIVE_SMOKE_SEQUENCE[3] == "STOP for owner approval"
        assert "create instance" in LIVE_SMOKE_SEQUENCE[4]
        assert "return DEFENDCODER_HEAVY_READY" in LIVE_SMOKE_SEQUENCE[8]
        assert len(LIVE_SMOKE_SEQUENCE) == 15
        assert LIVE_SMOKE_SEQUENCE[-1] == "report total measured cost"

