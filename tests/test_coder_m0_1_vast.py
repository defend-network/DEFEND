"""DEFENDcoder M0.1 tests — Vast backend with fakes; no live billing."""

from decimal import Decimal
from pathlib import Path

import pytest

from defend_control.coder_m0 import CoderM0Service, CoderModelRef, resolve_alias
from defend_control.coder_remote_vllm import (
    CoderRemoteVllmBootstrap,
    CoderRemoteVllmError,
)
from defend_control.coder_vast_backend import (
    VastCoderBackend,
    CoderVastBackendError,
)
from defend_control.types import LaunchSpec, ResourceProfile, VastInstance, VastOffer
from defend_control.vast import VastError


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
        self._direct = True
        self._last_raw = {}
        self.search_kwargs = []
        self.labeled_ids = ()

    def set_direct(self, direct):
        self._direct = bool(direct)

    def list_labeled_instance_ids(self, label):
        assert label == "defendcoder-vllm"
        return tuple(self.labeled_ids)

    def search_offers(self, max_hourly, profile=None, *,
 require_direct_ports=False):
        self.search_kwargs.append(require_direct_ports)
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
        return self.show_instance(instance_id)

    def show_instance(self, instance_id):
        instance = VastInstance(
            instance_id,
            "running",
            "ssh.example",
            22,
            "A100 SXM4",
            81920,
            Decimal("1.10"),
        )
        if self._direct:
            instance = VastInstance(
                instance_id,
                "running",
                "ssh.example",
                22,
                "A100 SXM4",
                81920,
                Decimal("1.10"),
                direct_ssh_host="10.0.0.5",
                direct_ssh_port=22,
                image_runtype="ssh_direct",
            )
        return instance

    def last_raw_payload(self, kind):
        del kind
        return self._last_raw

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
        self.starts.append(
            (instance.instance_id, model.alias, remote_port, prefer_direct)
        )
        self.artifacts.append(artifact.artifact_id if artifact is not None else None)


def _backend(vast=None, bootstrap=None, **kwargs):
    vast = vast or FakeVast()
    bootstrap = bootstrap or FakeBootstrap()
    options = {
        "tunnel_start": lambda instance, local_port, *, prefer_direct: (
            f"http://127.0.0.1:{local_port}/v1"
        ),
        "local_verify": lambda endpoint: True,
        "direct_endpoint_wait_seconds": 5.0,
        "direct_endpoint_poll_seconds": 0.01,
        "smoke_http": lambda endpoint, key, model: {
            "ok": True,
            "latency_ms": 5,
            "detail": f"fake smoke {model.alias}",
        },
    }
    options.update(kwargs)
    backend = VastCoderBackend(
        vast=vast,  # type: ignore[arg-type]
        secrets={"HF_TOKEN": "hf_test", "CODER_VLLM_API_KEY": "coder-key"},
        bootstrap=bootstrap,  # type: ignore[arg-type]
        max_hourly=Decimal("2.00"),
        **options,
    )
    return vast, bootstrap, backend


def test_vast_coder_backend_start_smoke_destroy_with_fakes():
    vast, bootstrap, backend = _backend()
    service = CoderM0Service(backend=backend, local_port=8003)

    status = service.start("defendcoder-default")
    assert status.state == "ready"
    assert status.instance_id == 555001
    assert status.provider_run_id == "vast-555001"
    assert status.hourly_price == "1.10"
    assert bootstrap.starts == [(555001, "defendcoder-default", 8000, False)]
    assert bootstrap.artifacts == ["qwen3-coder-30b-a3b-bf16"]
    assert vast.created == [(101, "defendcoder-vllm")]

    smoke = service.smoke()
    assert smoke.ok is True

    stopped = service.stop(destroy=True, confirmed_instance_id=555001)
    assert stopped.state == "stopped"
    assert vast.destroyed == [555001]


def test_vast_coder_backend_stop_without_destroy_sets_stopped_state():
    vast, bootstrap, backend = _backend()
    service = CoderM0Service(backend=backend)
    service.start()
    status = service.stop(destroy=False)
    assert status.state == "stopped"
    assert vast.states == [(555001, "stopped")]
    assert vast.destroyed == []


def test_vast_coder_backend_fails_closed_without_tunnel():
    vast = FakeVast()
    backend = VastCoderBackend(
        vast=vast,  # type: ignore[arg-type]
        secrets={"HF_TOKEN": "hf_test", "CODER_VLLM_API_KEY": "coder-key"},
        bootstrap=FakeBootstrap(),  # type: ignore[arg-type]
        max_hourly=Decimal("2.00"),
        tunnel_start=None,
    )
    service = CoderM0Service(backend=backend)
    with pytest.raises(CoderVastBackendError, match="no local tunnel"):
        service.start("defendcoder-default")
    assert vast.created == []
    assert vast.destroyed == []


def test_vast_coder_backend_fails_closed_when_tunnel_not_listening():
    vast, bootstrap, backend = _backend(
        tunnel_start=lambda instance, local_port, *, prefer_direct: (
            f"http://127.0.0.1:{local_port}/v1"
        ),
        local_verify=lambda endpoint: False,
    )
    service = CoderM0Service(backend=backend)
    with pytest.raises(CoderVastBackendError, match="not listening"):
        service.start("defendcoder-default")
    assert vast.destroyed == [555001]
    assert bootstrap.starts == [(555001, "defendcoder-default", 8000, False)]


def test_vast_coder_backend_proxy_lane_skips_direct_probe_and_uses_proxy():
    vast = FakeVast()
    vast.set_direct(False)
    vast, bootstrap, backend = _backend(vast=vast)
    service = CoderM0Service(backend=backend)

    status = service.start("defendcoder-fast")

    assert status.state == "ready"
    assert bootstrap.starts == [(555001, "defendcoder-fast", 8000, False)]
    assert vast.destroyed == []


def test_vast_coder_backend_search_offers_for_is_runtype_aware():
    vast = FakeVast()
    vast, bootstrap, backend = _backend(vast=vast)
    profile = ResourceProfile(
        min_gpu_ram_mb=81_920,
        num_gpus=2,
        allowed_gpu_families=("H100", "H200", "B200"),
    )
    backend.search_offers_for(
        resolve_alias("defendcoder-heavy"),
        profile,
    )
    backend.search_offers_for(
        resolve_alias("defendcoder-heavy"),
        profile,
        launch_runtype="ssh_direct",
    )
    assert vast.search_kwargs == [False, True]


def test_vast_coder_backend_proxy_bootstrap_failure_destroys_exactly_once():
    class FailingBootstrap:
        def start(self, instance, model, secrets, *,
     remote_port=8000, prefer_direct=False, cancelled=None, artifact=None):
            raise CoderRemoteVllmError(
                "bootstrap upload failed",
                phase="bootstrap_upload",
                remote_tail="sanitized tail",
            )

    vast, bootstrap, backend = _backend(
        bootstrap=FailingBootstrap(),  # type: ignore[arg-type]
    )
    service = CoderM0Service(backend=backend)
    with pytest.raises(CoderVastBackendError) as captured:
        service.start("defendcoder-heavy")

    assert captured.value.failure is not None
    assert captured.value.failure.phase == "bootstrap_upload"
    assert vast.destroyed == [555001]


def test_vast_coder_backend_failure_captures_show_snapshot_and_direct_port_count():
    vast = FakeVast()
    vast._last_raw = {
        "actual_status": "running",
        "image_runtype": "ssh_direct",
        "ssh_host": "ssh.example",
        "ssh_port": 22,
        "direct_ssh_host": None,
        "direct_ssh_port": None,
        "public_ipaddr": None,
        "ports": {"22/tcp": [{"HostPort": 30220}]},
        "dph_total": 1.10,
        "num_gpus": 1,
        "gpu_name": "A100 SXM4",
        "gpu_ram": 81920,
        "verified": True,
        "rentable": True,
        "billing": {},
        "machine_id": 5908,
        "label": "test",
    }
    vast, bootstrap, backend = _backend(
        vast=vast,
        local_verify=lambda endpoint: False,
    )
    offer = VastOffer(
        101,
        "A100 SXM4",
        81920,
        Decimal("1.10"),
        Decimal("0.99"),
        direct_port_count=2,
    )
    with pytest.raises(CoderVastBackendError) as captured:
        backend.start(
            resolve_alias("defendcoder-default"),
            local_port=8003,
            session_budget_usd=Decimal("5.00"),
            offer=offer,
        )

    failure = captured.value.failure
    assert failure is not None
    assert failure.show_snapshot == vast._last_raw
    assert failure.direct_port_count == 2
    assert failure.cleanup_state == "destroyed"
    assert "hf_test" not in failure.as_text()


def test_vast_coder_backend_persists_failure_record_to_disk(tmp_path: Path):
    vast = FakeVast()
    vast._last_raw = {
        "actual_status": "running",
        "ssh_host": "ssh.example",
        "ssh_port": 22,
        "ports": {"22/tcp": [{"HostPort": 30220}]},
        "gpu_name": "A100 SXM4",
        "gpu_ram": 81920,
        "dph_total": 1.10,
    }
    vast, bootstrap, backend = _backend(
        vast=vast,
        local_verify=lambda endpoint: False,
        failure_directory=str(tmp_path),
    )
    service = CoderM0Service(backend=backend)
    with pytest.raises(CoderVastBackendError):
        service.start("defendcoder-default")

    files = sorted(tmp_path.glob("provision-failure-*.json"))
    assert len(files) == 1
    import json

    document = json.loads(files[0].read_text(encoding="utf-8"))
    assert document["phase"] == "ssh_tunnel"
    assert document["cleanup_state"] == "destroyed"
    assert document["direct_port_count"] is None
    assert document["show_snapshot"]["ssh_host"] == "ssh.example"
    assert "hf_test" not in files[0].read_text(encoding="utf-8")


def test_vast_coder_backend_rejects_non_loopback_tunnel_endpoint():
    vast, bootstrap, backend = _backend(
        tunnel_start=lambda instance, local_port, *, prefer_direct: (
            f"http://203.0.113.7:{local_port}/v1"
        ),
        local_verify=lambda endpoint: True,
    )
    service = CoderM0Service(backend=backend)
    with pytest.raises(CoderVastBackendError, match="loopback"):
        service.start("defendcoder-default")
    assert vast.destroyed == [555001]


def test_vast_coder_backend_fails_closed_when_direct_endpoint_unavailable():
    vast = FakeVast()
    vast.set_direct(False)
    vast, bootstrap, backend = _backend(vast=vast)
    service = CoderM0Service(backend=backend)
    with pytest.raises(CoderVastBackendError, match="direct SSH endpoint"):
        service.start("defendcoder-default", launch_runtype="ssh_direct")
    assert vast.destroyed == [555001]


def test_vast_coder_backend_destroys_instance_when_actual_rate_exceeds_offer():
    class PriceSpikeVast(FakeVast):
        def show_instance(self, instance_id):
            return VastInstance(
                instance_id,
                "running",
                "ssh.example",
                22,
                "A100 SXM4",
                81920,
                Decimal("4.20"),
                direct_ssh_host="10.0.0.5",
                direct_ssh_port=22,
                image_runtype="ssh_direct",
            )

    vast, bootstrap, backend = _backend(vast=PriceSpikeVast())
    offer = VastOffer(
        101,
        "A100 SXM4",
        81920,
        Decimal("1.10"),
        Decimal("0.99"),
    )
    with pytest.raises(CoderVastBackendError, match="exceeds approved rate"):
        backend.start(
            resolve_alias("defendcoder-default"),
            local_port=8003,
            session_budget_usd=Decimal("5.00"),
            offer=offer,
        )
    assert vast.destroyed == [555001]
    assert bootstrap.starts == []


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


def test_vast_coder_backend_failure_record_tunnel_phase():
    vast, bootstrap, backend = _backend(
        local_verify=lambda endpoint: False,
    )
    service = CoderM0Service(backend=backend)
    with pytest.raises(CoderVastBackendError) as captured:
        service.start("defendcoder-default")

    error = captured.value
    assert error.phase == "ssh_tunnel"
    assert error.category == "tunnel"
    failure = error.failure
    assert failure is not None
    assert failure.phase == "ssh_tunnel"
    assert failure.instance_id == 555001
    assert failure.cleanup_state == "destroyed"
    assert failure.sanitized_message == (
        "local coder endpoint http://127.0.0.1:8003/v1 is not listening; "
        "instance destroyed"
    )
    assert vast.destroyed == [555001]
    assert backend.last_provision_failure is failure
    text = failure.as_text()
    assert "Phase: ssh_tunnel" in text
    assert "Instance: 555001" in text
    assert "Cleanup: destroyed" in text
    assert "coder-key" not in text
    assert "hf_test" not in text
    assert "hf_fake_token" not in text


def test_vast_coder_backend_failure_record_direct_endpoint_phase():
    vast = FakeVast()
    vast.set_direct(False)
    vast, bootstrap, backend = _backend(vast=vast)
    service = CoderM0Service(backend=backend)
    with pytest.raises(CoderVastBackendError) as captured:
        service.start(
            "defendcoder-default", launch_runtype="ssh_direct"
        )

    failure = captured.value.failure
    assert failure is not None
    assert failure.phase == "direct_endpoint_wait"
    assert failure.cleanup_state == "destroyed"
    assert failure.endpoint_state == (
        backend.last_direct_probe.state.value
        if backend.last_direct_probe is not None
        else None
    )
    assert vast.destroyed == [555001]


def test_vast_coder_backend_failure_record_rate_exceeded_phase():
    class PriceSpikeVast(FakeVast):
        def show_instance(self, instance_id):
            return VastInstance(
                instance_id,
                "running",
                "ssh.example",
                22,
                "A100 SXM4",
                81920,
                Decimal("4.20"),
                direct_ssh_host="10.0.0.5",
                direct_ssh_port=22,
                image_runtype="ssh_direct",
            )

    vast, bootstrap, backend = _backend(vast=PriceSpikeVast())
    offer = VastOffer(
        101,
        "A100 SXM4",
        81920,
        Decimal("1.10"),
        Decimal("0.99"),
    )
    with pytest.raises(CoderVastBackendError) as captured:
        backend.start(
            resolve_alias("defendcoder-default"),
            local_port=8003,
            session_budget_usd=Decimal("5.00"),
            offer=offer,
        )

    error = captured.value
    assert error.phase == "instance_running_wait"
    assert error.category == "rate_exceeded"
    failure = error.failure
    assert failure is not None
    assert failure.phase == "instance_running_wait"
    assert failure.instance_id == 555001
    assert failure.gpu_name == "A100 SXM4"
    assert failure.approved_hourly_rate == Decimal("1.10")
    assert failure.cleanup_state == "destroyed"
    assert "exceeds approved rate" in failure.sanitized_message
    assert vast.destroyed == [555001]


def test_vast_coder_backend_failure_record_smoke_phase():
    vast, bootstrap, backend = _backend(
        smoke_http=lambda endpoint, key, model: {
            "ok": False,
            "latency_ms": 5,
            "detail": "model did not answer /v1/models",
        },
    )
    service = CoderM0Service(backend=backend)
    service.start("defendcoder-default")

    smoke = service.smoke()
    assert smoke.ok is False

    failure = backend.last_provision_failure
    assert failure is not None
    assert failure.phase == "openai_smoke"
    assert failure.instance_id == 555001
    assert failure.readiness_state == "model did not answer /v1/models"

    stopped = service.stop(destroy=True, confirmed_instance_id=555001)
    assert stopped.state == "stopped"
    assert backend.last_provision_failure.cleanup_state == "destroyed"


def test_vast_coder_backend_failure_record_chained_cause():
    class RaisingVast(FakeVast):
        def create_instance(self, offer, launch):
            raise VastError("provider rejected the offer")

    vast, bootstrap, backend = _backend(vast=RaisingVast())
    service = CoderM0Service(backend=backend)
    with pytest.raises(CoderVastBackendError) as captured:
        service.start("defendcoder-default")

    error = captured.value
    assert error.phase == "instance_create"
    assert isinstance(error.__cause__, VastError)
    failure = error.failure
    assert failure is not None
    assert failure.phase == "instance_create"
    assert failure.instance_id is None
    assert failure.cleanup_state is None
    assert vast.destroyed == []


def test_vast_coder_backend_failure_record_bootstrap_phase_attribution():
    class StageFailingBootstrap(FakeBootstrap):
        def start(self, instance, model, secrets, **kwargs):
            self.last_stages = (
                "remote_preflight",
                "bootstrap_upload",
                "container_start",
                "vllm_start",
                "model_load",
            )
            raise CoderRemoteVllmError(
                "vllm process died during model load",
                phase="model_load",
            )

    vast, bootstrap, backend = _backend(bootstrap=StageFailingBootstrap())
    service = CoderM0Service(backend=backend)
    with pytest.raises(CoderVastBackendError) as captured:
        service.start("defendcoder-default")

    error = captured.value
    assert error.phase == "model_load"
    assert error.category == "bootstrap"
    assert isinstance(error.__cause__, CoderRemoteVllmError)
    failure = error.failure
    assert failure is not None
    assert failure.phase == "model_load"
    assert failure.ssh_state == "ready"
    assert failure.bootstrap_state == "model_load"
    assert failure.vllm_state == "model_load"
    assert failure.readiness_state == "not_ready"
    assert failure.cleanup_state == "destroyed"
    assert vast.destroyed == [555001]
    assert "hf_test" not in failure.as_text()


def test_vast_coder_backend_destroy_rejection_marks_cleanup_request_failed():
    class DestroyFailingVast(FakeVast):
        def destroy_instance(self, instance_id, *,
     confirmed_instance_id=None):
            raise VastError("provider refused destroy")

    vast, bootstrap, backend = _backend(
        vast=DestroyFailingVast(),
        local_verify=lambda endpoint: False,
    )
    service = CoderM0Service(backend=backend)
    with pytest.raises(CoderVastBackendError) as captured:
        service.start("defendcoder-default")

    failure = captured.value.failure
    assert failure is not None
    assert failure.cleanup_state == "destroy_request_failed"


def test_vast_coder_backend_success_clears_failure_record():
    vast, bootstrap, backend = _backend()
    service = CoderM0Service(backend=backend)
    status = service.start("defendcoder-default")
    assert status.state == "ready"
    assert backend.last_provision_failure is None


class ResumableVast(FakeVast):
    """FakeVast exposing one running labeled instance for resume tests."""

    def __init__(self, *, instance_id=555001, rate="1.10",
     status="running", image_runtype=None):
        super().__init__()
        self._instance_id = instance_id
        self._rate = Decimal(rate)
        self._status = status
        self._image_runtype = image_runtype
        self.labeled_ids = (instance_id,)

    def show_instance(self, instance_id):
        return VastInstance(
            instance_id,
            self._status,
            "ssh.example",
            22,
            "A100 SXM4",
            81920,
            self._rate,
            image_runtype=self._image_runtype,
        )


def test_vast_coder_backend_resume_skips_create_and_bootstraps():
    vast, bootstrap, backend = _backend(
        vast=ResumableVast(instance_id=555801),
    )
    service = CoderM0Service(backend=backend)

    status = service.start(
        "defendcoder-default",
        resume_instance=VastInstance(
            555801,
            "running",
            "ssh.example",
            22,
            "A100 SXM4",
            81920,
            Decimal("1.10"),
        ),
    )

    assert status.state == "ready"
    assert status.instance_id == 555801
    assert vast.created == []
    assert vast.destroyed == []
    assert bootstrap.starts == [(555801, "defendcoder-default", 8000, False)]


def test_vast_coder_backend_duplicate_guard_refuses_second_instance():
    vast, bootstrap, backend = _backend(
        vast=ResumableVast(instance_id=555802),
    )
    service = CoderM0Service(backend=backend)

    with pytest.raises(CoderVastBackendError) as captured:
        service.start("defendcoder-default")

    assert captured.value.category == "duplicate_runtime"
    assert "already running" in str(captured.value)
    assert vast.created == []
    assert vast.destroyed == []


def test_vast_coder_backend_resume_fails_closed_on_stopped_labeled_instance():
    vast, bootstrap, backend = _backend(
        vast=ResumableVast(instance_id=555803, status="off"),
    )
    service = CoderM0Service(backend=backend)

    with pytest.raises(CoderVastBackendError) as captured:
        service.start("defendcoder-default")

    assert captured.value.category == "duplicate_runtime"
    assert "not running" in str(captured.value)
    assert vast.created == []
    assert vast.destroyed == []


def test_vast_coder_backend_resume_fails_closed_on_multiple_running():
    vast = ResumableVast(instance_id=555804)
    vast.labeled_ids = (555804, 555805)
    vast, bootstrap, backend = _backend(vast=vast)
    service = CoderM0Service(backend=backend)

    with pytest.raises(CoderVastBackendError) as captured:
        service.start("defendcoder-default")

    assert captured.value.category == "duplicate_runtime"
    assert "multiple" in str(captured.value)
    assert vast.created == []


def test_vast_coder_backend_resume_fails_closed_when_labeled_rate_exceeds_ceiling():
    vast, bootstrap, backend = _backend(
        vast=ResumableVast(instance_id=555806, rate="4.20"),
    )
    service = CoderM0Service(backend=backend)

    with pytest.raises(CoderVastBackendError) as captured:
        service.start("defendcoder-default")

    assert captured.value.category == "rate_exceeded"
    assert vast.created == []


def test_vast_coder_backend_resume_fails_closed_on_runtype_mismatch():
    vast, bootstrap, backend = _backend(
        vast=ResumableVast(
            instance_id=555807,
            image_runtype="ssh_direct",
        ),
    )
    service = CoderM0Service(backend=backend)

    with pytest.raises(CoderVastBackendError) as captured:
        service.start("defendcoder-default")

    assert captured.value.category == "duplicate_runtime"
    assert "not ssh_proxy" in str(captured.value)
    assert vast.created == []
