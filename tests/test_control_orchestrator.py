from decimal import Decimal
from pathlib import Path
import threading

import pytest

from defend_control.health import HealthResult
from defend_control.orchestrator import (
    AlreadyRunning,
    ExternalCloudflaredDetector,
    PriceConfirmationRequired,
    StackOrchestrator,
    StartCancellation,
    StartCancelled,
    StartFailed,
)
from defend_control.processes import ProcessSnapshot, ProcessSpec
from defend_control.settings import ControlSettings
from defend_control.ssh_tunnel import HostFingerprintConfirmation
from defend_control.types import AdapterSpec, ModelReady, VastInstance, VastOffer


class FakePreflight:
    def __init__(self, events, *, ok=True):
        self.events = events
        self.ok = ok

    def run(self, mode, _settings, _secrets):
        self.events.append(f"preflight:{mode}")
        return (
            type(
                "Check",
                (),
                {
                    "name": "synthetic-check",
                    "ok": self.ok,
                    "detail": "ready" if self.ok else "missing dependency",
                    "remediation": None if self.ok else "repair setup",
                },
            )(),
        )


class FakeOllama:
    def __init__(self, events, *, entered=None, release=None):
        self.events = events
        self.entered = entered
        self.release = release

    def verify(self, model):
        self.events.append("ollama:verify")
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            self.release.wait(2)
        return ModelReady(model, "ollama", "http://127.0.0.1:11434")


class FakeSupervisor:
    def __init__(self, events):
        self.events = events
        self.started = []
        self.stopped = []
        self.fail_stop_once = set()
        self.observed = []

    def start(self, spec):
        self.started.append(spec)
        if spec.name in {"api", "web"}:
            self.events.append(f"{spec.name}:start")
        return type("Process", (), {"pid": 100 + len(self.started)})()

    def stop(self, name):
        self.stopped.append(name)
        if name in self.fail_stop_once:
            self.fail_stop_once.remove(name)
            raise RuntimeError("synthetic private stop detail")
        self.started = [spec for spec in self.started if spec.name != name]
        return True

    def snapshot(self):
        return tuple(
            ProcessSnapshot(
                name=spec.name,
                pid=100 + index,
                owned=True,
                running=True,
                health_url=spec.health_url,
                returncode=None,
            )
            for index, spec in enumerate(self.started, 1)
        )

    def observe_external(self, name, *, pid, health_url=None):
        self.observed.append((name, pid, health_url))


def make_settings(tmp_path):
    return ControlSettings(
        repo_root=tmp_path,
        data_root=tmp_path / "data",
        public_web_origin="https://ai.example.test",
        cloudflared_exe=tmp_path / "cloudflared.exe",
        cloudflared_config=tmp_path / "config.yml",
        cloudflared_tunnel="defend-ai",
        adapter_repo="Defend-network/defend-qwen-32b-lora",
        local_model="defend-ai:latest",
        vast_max_hourly=Decimal("3.00"),
    )


def dependencies(tmp_path, *, health=None, external_tunnel_pid=None, ollama=None):
    events = []
    supervisor = FakeSupervisor(events)
    health_by_name = {"api": True, "web": True, "public": True}
    health_by_name.update(health or {})

    def health_probe(url, _timeout, **_kwargs):
        if url.endswith(":8000/health"):
            name = "api"
        elif url.endswith(":3000/health"):
            name = "web"
        else:
            name = "public"
        events.append(f"{name}:healthy")
        return HealthResult(health_by_name[name], 200 if health_by_name[name] else 503, 1, None)

    def tunnel_detector(_settings):
        events.append("tunnel:reuse-or-start")
        return external_tunnel_pid

    values = {
        "DEFEND_OWNER_PASS": "synthetic-owner",
        "DEFEND_VISITOR_HMAC_KEY": "synthetic-visitor-hmac-key-32-chars",
        "DEFEND_GMAIL_SMTP_USERNAME": "operator@example.test",
        "DEFEND_GMAIL_APP_PASSWORD": "synthetic-gmail",
    }
    return {
        "settings": make_settings(tmp_path),
        "secrets": values,
        "preflight": FakePreflight(events),
        "supervisor": supervisor,
        "local_backend": ollama or FakeOllama(events),
        "health_probe": health_probe,
        "external_tunnel_detector": tunnel_detector,
        "health_timeout_seconds": 0.05,
        "poll_interval_seconds": 0,
    }, events, supervisor


def test_local_start_orders_model_api_web_tunnel(tmp_path):
    kwargs, events, _supervisor = dependencies(tmp_path)
    orchestrator = StackOrchestrator(**kwargs)

    result = orchestrator.start("ollama")

    assert not isinstance(result, AlreadyRunning)
    assert events == [
        "preflight:ollama",
        "ollama:verify",
        "api:start",
        "api:healthy",
        "web:start",
        "web:healthy",
        "tunnel:reuse-or-start",
        "public:healthy",
    ]
    assert orchestrator.snapshot().state == "ready"


def test_failed_web_health_rolls_back_only_new_processes(tmp_path):
    kwargs, _events, supervisor = dependencies(tmp_path, health={"web": False})

    with pytest.raises(StartFailed, match="frontend"):
        StackOrchestrator(**kwargs).start("ollama")

    assert supervisor.stopped == ["web", "api"]
    assert "external-cloudflare" not in supervisor.stopped


def test_public_failure_rolls_back_owned_cloudflare_but_not_reused_tunnel(tmp_path):
    kwargs, _events, supervisor = dependencies(
        tmp_path, health={"public": False}, external_tunnel_pid=None
    )
    with pytest.raises(StartFailed, match="public"):
        StackOrchestrator(**kwargs).start("ollama")
    assert supervisor.stopped == ["cloudflare", "web", "api"]

    kwargs, _events, supervisor = dependencies(
        tmp_path, health={"public": False}, external_tunnel_pid=7341
    )
    with pytest.raises(StartFailed, match="public"):
        StackOrchestrator(**kwargs).start("ollama")
    assert supervisor.stopped == ["web", "api"]


def test_failed_rollback_stop_retains_owned_resource_for_later_cleanup(tmp_path):
    kwargs, _events, supervisor = dependencies(
        tmp_path, health={"public": False}, external_tunnel_pid=None
    )
    supervisor.fail_stop_once.add("cloudflare")
    orchestrator = StackOrchestrator(**kwargs)

    with pytest.raises(StartFailed, match="public"):
        orchestrator.start("ollama")

    assert [item.name for item in supervisor.snapshot()] == ["cloudflare"]
    orchestrator.stop_local()
    assert supervisor.stopped == ["cloudflare", "web", "api", "cloudflare"]
    assert supervisor.snapshot() == ()


def test_preflight_failure_starts_no_resources_and_reports_safe_component(tmp_path):
    kwargs, events, supervisor = dependencies(tmp_path)
    kwargs["preflight"] = FakePreflight(events, ok=False)

    with pytest.raises(StartFailed, match="preflight") as raised:
        StackOrchestrator(**kwargs).start("ollama")

    assert "synthetic-owner" not in str(raised.value)
    assert supervisor.started == []


def test_duplicate_start_returns_already_running_without_second_attempt(tmp_path):
    entered = threading.Event()
    release = threading.Event()
    kwargs, events, _supervisor = dependencies(tmp_path)
    kwargs["local_backend"] = FakeOllama(events, entered=entered, release=release)
    orchestrator = StackOrchestrator(**kwargs)
    errors = []

    worker = threading.Thread(
        target=lambda: _capture_error(errors, orchestrator.start, "ollama")
    )
    worker.start()
    assert entered.wait(1)
    try:
        duplicate = orchestrator.start("ollama")
    finally:
        release.set()
        worker.join(2)

    assert isinstance(duplicate, AlreadyRunning)
    assert events.count("preflight:ollama") == 1
    assert errors == []


def test_stop_during_start_cancels_and_rolls_back_created_services(tmp_path):
    api_started = threading.Event()
    release_api_health = threading.Event()
    kwargs, _events, supervisor = dependencies(tmp_path)
    original_probe = kwargs["health_probe"]

    def blocking_probe(url, timeout, **options):
        if url.endswith(":8000/health"):
            api_started.set()
            release_api_health.wait(2)
        return original_probe(url, timeout, **options)

    kwargs["health_probe"] = blocking_probe
    orchestrator = StackOrchestrator(**kwargs)
    errors = []
    start_worker = threading.Thread(
        target=lambda: _capture_error(errors, orchestrator.start, "ollama")
    )
    start_worker.start()
    assert api_started.wait(1)

    stop_worker = threading.Thread(target=orchestrator.stop_local)
    stop_worker.start()
    release_api_health.set()
    start_worker.join(2)
    stop_worker.join(2)

    assert len(errors) == 1 and isinstance(errors[0], StartCancelled)
    assert supervisor.stopped == ["api"]
    assert orchestrator.snapshot().state == "stopped"


def test_verified_external_cloudflare_pid_is_observed_and_not_started(tmp_path):
    kwargs, _events, supervisor = dependencies(
        tmp_path, external_tunnel_pid=7341
    )

    StackOrchestrator(**kwargs).start("ollama")

    assert supervisor.observed == [
        ("external-cloudflare", 7341, "https://ai.example.test")
    ]
    assert "cloudflare" not in [spec.name for spec in supervisor.started]


def test_healthy_public_route_without_verified_local_tunnel_starts_owned_one(tmp_path):
    kwargs, _events, supervisor = dependencies(
        tmp_path,
        health={"public": True},
        external_tunnel_pid=None,
    )

    StackOrchestrator(**kwargs).start("ollama")

    assert supervisor.observed == []
    assert "cloudflare" in [spec.name for spec in supervisor.started]


def test_external_cloudflared_detector_requires_exact_exe_config_and_tunnel(tmp_path):
    configured = make_settings(tmp_path)
    exact = {
        "pid": 7341,
        "executable": str(configured.cloudflared_exe),
        "argv": (
            str(configured.cloudflared_exe),
            "tunnel",
            "--config",
            str(configured.cloudflared_config),
            "run",
            configured.cloudflared_tunnel,
        ),
    }
    assert ExternalCloudflaredDetector(query=lambda: (exact,))(configured) == 7341

    for changed in (
        {**exact, "executable": str(tmp_path / "other.exe")},
        {
            **exact,
            "argv": (*exact["argv"][:3], str(tmp_path / "other.yml"), *exact["argv"][4:]),
        },
        {**exact, "argv": (*exact["argv"][:-1], "other-tunnel")},
        {**exact, "pid": 0},
    ):
        assert ExternalCloudflaredDetector(query=lambda changed=changed: (changed,))(
            configured
        ) is None


def test_per_attempt_cancellation_before_worker_entry_is_not_cleared(tmp_path):
    kwargs, events, supervisor = dependencies(tmp_path)
    cancellation = StartCancellation()
    cancellation.cancel()

    with pytest.raises(StartCancelled):
        StackOrchestrator(**kwargs).start("ollama", cancellation)

    assert events == []
    assert supervisor.started == []


def test_cancelled_start_with_failed_rollback_retains_failed_running_state(tmp_path):
    api_started = threading.Event()
    release_api_health = threading.Event()
    kwargs, _events, supervisor = dependencies(tmp_path)
    original_probe = kwargs["health_probe"]

    def blocking_probe(url, timeout, **options):
        if url.endswith(":8000/health"):
            api_started.set()
            release_api_health.wait(2)
        return original_probe(url, timeout, **options)

    kwargs["health_probe"] = blocking_probe
    supervisor.fail_stop_once.add("api")
    orchestrator = StackOrchestrator(**kwargs)
    errors = []
    worker = threading.Thread(
        target=lambda: _capture_error(errors, orchestrator.start, "ollama")
    )
    worker.start()
    assert api_started.wait(1)

    orchestrator.cancel_start()
    release_api_health.set()
    worker.join(2)

    snapshot = orchestrator.snapshot()
    assert len(errors) == 1 and isinstance(errors[0], StartCancelled)
    assert snapshot.state == "failed"
    assert snapshot.owned_services == ("api",)
    assert {item.name: item.state for item in snapshot.components}["api"] == (
        "cleanup pending"
    )

    orchestrator.stop_local()
    assert orchestrator.snapshot().state == "stopped"


def _capture_error(target, function, *args):
    try:
        function(*args)
    except BaseException as error:
        target.append(error)


class FakeHuggingFace:
    def __init__(self, events):
        self.events = events
        self.calls = 0

    def resolve_adapter(self, repo, token):
        self.calls += 1
        self.events.append("hf:resolve")
        assert repo == "Defend-network/defend-qwen-32b-lora"
        assert token == "hf_synthetic"
        return AdapterSpec(repo, "a" * 40, "Qwen/example-32B", "b" * 40, "LORA")


class FakeVast:
    def __init__(self, events, offer, instance):
        self.events = events
        self.offer = offer
        self.instance = instance
        self.creates = 0
        self.destroyed = []

    def ensure_account_ssh_key(self, public_key):
        self.events.append("vast:ssh-key")
        assert public_key.startswith("ssh-ed25519 ")
        return 44

    def search_offers(self, max_hourly):
        self.events.append("vast:search")
        assert max_hourly == Decimal("3.00")
        return (self.offer,)

    def create_instance(self, offer, launch):
        self.events.append("vast:create")
        assert offer == self.offer
        self.creates += 1
        return VastInstance(
            self.instance.instance_id,
            None,
            None,
            None,
            self.instance.gpu_name,
            self.instance.gpu_ram_mb,
            self.instance.dph_total,
        )

    def wait_until_running(self, instance_id):
        self.events.append("vast:wait-running")
        assert instance_id == self.instance.instance_id
        return self.instance

    def destroy_instance(self, instance_id, *, confirmed_instance_id):
        self.events.append("vast:destroy")
        assert instance_id == confirmed_instance_id
        self.destroyed.append(instance_id)
        return True


class FakeSshTunnel:
    fingerprint = "SHA256:syntheticFingerprint"

    def __init__(self, events, supervisor, root):
        self.events = events
        self.supervisor = supervisor
        self.root = root

    def ensure_identity(self):
        self.events.append("ssh:identity")
        return "ssh-ed25519 AAAAC3NzaDedicated defend-control"

    def prepare_host(self, instance, confirm_fingerprint):
        self.events.append("ssh:prepare")
        if confirm_fingerprint != self.fingerprint:
            raise HostFingerprintConfirmation(instance.instance_id, self.fingerprint)
        return self.fingerprint

    def start(self, instance):
        self.events.append("ssh:start")
        return self.supervisor.start(
            ProcessSpec(
                "ssh tunnel",
                ("synthetic-ssh.exe", "-N"),
                self.root,
                {},
                None,
            )
        )


class FakeRemoteBootstrap:
    def __init__(self, events):
        self.events = events

    def start(self, instance, adapter, secrets, **options):
        self.events.append("vllm:bootstrap")
        assert adapter.adapter_revision == "a" * 40
        assert secrets["HF_TOKEN"] == "hf_synthetic"
        assert callable(options["cancelled"])

    def cleanup_token_file(self, instance):
        self.events.append("vllm:token-cleanup")


class FakeModelProbe:
    def __init__(self, events):
        self.events = events

    def wait_ready(self, base_url, api_key, model="defend-ai", **options):
        self.events.append("vllm:probe")
        assert base_url == "http://127.0.0.1:8001/v1"
        assert api_key == "vllm_synthetic"
        assert model == "defend-ai"
        assert callable(options["cancelled"])
        return ModelReady(model, "openai_compatible", base_url)


def remote_dependencies(tmp_path):
    kwargs, events, supervisor = dependencies(tmp_path)
    kwargs["secrets"].update(
        {
            "VAST_API_KEY": "vast_synthetic",
            "HF_TOKEN": "hf_synthetic",
            "VLLM_API_KEY": "vllm_synthetic",
        }
    )
    offer = VastOffer(
        101,
        "A100 SXM4",
        81920,
        Decimal("1.75"),
        Decimal("0.987"),
    )
    instance = VastInstance(
        4815,
        "running",
        "ssh.example.test",
        2222,
        offer.gpu_name,
        offer.gpu_ram_mb,
        offer.dph_total,
    )
    vast = FakeVast(events, offer, instance)
    kwargs.update(
        {
            "huggingface_client": FakeHuggingFace(events),
            "vast_client_factory": lambda token: vast,
            "ssh_tunnel": FakeSshTunnel(events, supervisor, tmp_path),
            "remote_bootstrap": FakeRemoteBootstrap(events),
            "model_probe": FakeModelProbe(events),
        }
    )
    return kwargs, events, supervisor, offer, instance, vast


def confirm_and_start_vast(orchestrator, offer, instance):
    with pytest.raises(PriceConfirmationRequired):
        orchestrator.start("vast")
    orchestrator.confirm_offer(offer.offer_id, offer.dph_total)
    with pytest.raises(HostFingerprintConfirmation):
        orchestrator.start("vast")
    orchestrator.confirm_fingerprint(
        instance.instance_id, FakeSshTunnel.fingerprint
    )
    return orchestrator.start("vast")


def test_vast_start_requires_exact_price_then_exact_fingerprint(tmp_path):
    kwargs, events, supervisor, offer, instance, vast = remote_dependencies(
        tmp_path
    )
    orchestrator = StackOrchestrator(**kwargs)

    with pytest.raises(PriceConfirmationRequired) as price:
        orchestrator.start("vast")

    assert price.value.offer == offer
    assert vast.creates == 0
    pending = orchestrator.snapshot()
    assert pending.state == "provisioning"
    assert pending.pending_confirmation == "price"
    assert pending.vast_offer_id == offer.offer_id
    assert pending.vast_gpu == offer.gpu_name
    assert pending.vast_gpu_ram_mb == offer.gpu_ram_mb
    assert pending.vast_reliability == str(offer.reliability)
    assert pending.vast_hourly_price == str(offer.dph_total)

    with pytest.raises(ValueError, match="exact offer"):
        orchestrator.confirm_offer(offer.offer_id, Decimal("1.76"))
    orchestrator.confirm_offer(offer.offer_id, offer.dph_total)

    with pytest.raises(HostFingerprintConfirmation) as fingerprint:
        orchestrator.start("vast")

    assert fingerprint.value.instance_id == instance.instance_id
    assert vast.creates == 1
    billable = orchestrator.snapshot()
    assert billable.pending_confirmation == "fingerprint"
    assert billable.vast_instance_id == instance.instance_id
    assert billable.vast_actual_status == "running"
    assert billable.vast_billing_warning == (
        "Compute billing may remain active until this instance is destroyed."
    )

    with pytest.raises(ValueError, match="exact fingerprint"):
        orchestrator.confirm_fingerprint(instance.instance_id, "SHA256:wrong")
    orchestrator.confirm_fingerprint(instance.instance_id, fingerprint.value.fingerprint)
    result = orchestrator.start("vast")

    assert result.state == "ready"
    assert vast.creates == 1
    assert events.index("ssh:start") < events.index("vllm:bootstrap")
    assert events.index("vllm:bootstrap") < events.index("vllm:probe")
    assert events.index("vllm:probe") < events.index("vllm:token-cleanup")
    assert events.index("vllm:token-cleanup") < events.index("api:start")
    api_spec = next(spec for spec in supervisor.started if spec.name == "api")
    assert api_spec.env["DEFEND_MODEL_BACKEND"] == "openai_compatible"
    assert api_spec.env["DEFEND_MODEL"] == "defend-ai"
    assert api_spec.env["DEFEND_MODEL_BASE_URL"] == "http://127.0.0.1:8001/v1"
    assert api_spec.env["DEFEND_MODEL_API_KEY"] == "vllm_synthetic"
    assert not any("vllm_synthetic" in argument for argument in api_spec.argv)


def test_vast_destroy_requires_exact_id_and_clears_billing_state(tmp_path):
    kwargs, _events, supervisor, offer, instance, vast = remote_dependencies(
        tmp_path
    )
    orchestrator = StackOrchestrator(**kwargs)
    confirm_and_start_vast(orchestrator, offer, instance)

    with pytest.raises(ValueError, match="exact instance ID"):
        orchestrator.destroy_vast(instance.instance_id - 1)
    assert vast.destroyed == []

    orchestrator.destroy_vast(instance.instance_id)

    assert vast.destroyed == [instance.instance_id]
    assert supervisor.stopped == ["cloudflare", "web", "api", "ssh tunnel"]
    snapshot = orchestrator.snapshot()
    assert snapshot.state == "stopped"
    assert snapshot.vast_instance_id is None
    assert snapshot.vast_billing_warning is None


def test_stop_local_keeps_vast_instance_and_prominent_billing_warning(tmp_path):
    kwargs, _events, _supervisor, offer, instance, _vast = remote_dependencies(
        tmp_path
    )
    orchestrator = StackOrchestrator(**kwargs)
    confirm_and_start_vast(orchestrator, offer, instance)

    stopped = orchestrator.stop_local()

    assert stopped.state == "stopped"
    assert stopped.vast_instance_id == instance.instance_id
    assert "billing may remain active" in (stopped.vast_billing_warning or "")


def test_destroy_still_stops_billing_when_local_cleanup_is_incomplete(tmp_path):
    kwargs, _events, supervisor, offer, instance, vast = remote_dependencies(
        tmp_path
    )
    orchestrator = StackOrchestrator(**kwargs)
    confirm_and_start_vast(orchestrator, offer, instance)
    supervisor.fail_stop_once.add("api")

    with pytest.raises(RuntimeError, match="local cleanup"):
        orchestrator.destroy_vast(instance.instance_id)

    assert vast.destroyed == [instance.instance_id]
    snapshot = orchestrator.snapshot()
    assert snapshot.vast_instance_id is None
    assert snapshot.vast_billing_warning is None
    assert snapshot.state == "failed"
    assert snapshot.owned_services == ("api",)


def test_operator_can_switch_to_local_mode_from_unconfirmed_vast_gate(tmp_path):
    kwargs, events, _supervisor, _offer, _instance, vast = remote_dependencies(
        tmp_path
    )
    orchestrator = StackOrchestrator(**kwargs)
    with pytest.raises(PriceConfirmationRequired):
        orchestrator.start("vast")

    result = orchestrator.start("ollama")

    assert result.state == "ready"
    assert result.mode == "ollama"
    assert result.pending_confirmation is None
    assert result.vast_offer_id is None
    assert vast.creates == 0
    assert "ollama:verify" in events


def test_stop_local_clears_fingerprint_prompt_but_keeps_billable_instance(tmp_path):
    kwargs, _events, _supervisor, offer, instance, _vast = remote_dependencies(
        tmp_path
    )
    orchestrator = StackOrchestrator(**kwargs)
    with pytest.raises(PriceConfirmationRequired):
        orchestrator.start("vast")
    orchestrator.confirm_offer(offer.offer_id, offer.dph_total)
    with pytest.raises(HostFingerprintConfirmation):
        orchestrator.start("vast")

    stopped = orchestrator.stop_local()

    assert stopped.pending_confirmation is None
    assert stopped.pending_fingerprint is None
    assert stopped.vast_instance_id == instance.instance_id
    assert "billing may remain active" in (stopped.vast_billing_warning or "")


def test_cancellation_during_remote_bootstrap_is_reported_as_cancelled(tmp_path):
    cancellation = StartCancellation()
    kwargs, _events, supervisor, offer, instance, _vast = remote_dependencies(
        tmp_path
    )

    class CancellingBootstrap:
        def start(self, _instance, _adapter, _secrets, **_options):
            cancellation.cancel()
            raise RuntimeError("synthetic command cancellation")

        def cleanup_token_file(self, _instance):
            raise AssertionError("cleanup cannot precede readiness")

    kwargs["remote_bootstrap"] = CancellingBootstrap()
    orchestrator = StackOrchestrator(**kwargs)
    with pytest.raises(PriceConfirmationRequired):
        orchestrator.start("vast")
    orchestrator.confirm_offer(offer.offer_id, offer.dph_total)
    with pytest.raises(HostFingerprintConfirmation):
        orchestrator.start("vast")
    orchestrator.confirm_fingerprint(instance.instance_id, FakeSshTunnel.fingerprint)

    with pytest.raises(StartCancelled):
        orchestrator.start("vast", cancellation)

    assert supervisor.stopped == ["ssh tunnel"]
    snapshot = orchestrator.snapshot()
    assert snapshot.state == "stopped"
    assert snapshot.vast_instance_id == instance.instance_id
    assert "billing may remain active" in (snapshot.vast_billing_warning or "")
