"""DEFENDcoder deployment artifact tests (LIVE-HEAVY-READINESS).

No Vast, network, or Hugging Face calls in these tests. All provider
interaction is faked; preflight and plan inspection are pure logic.
"""

import inspect
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from defend_control.coder_billing import BillingPolicy
from defend_control.coder_control_plane import (
    CoderControlPlane,
    CoderLiveSmokePlan,
    CoderPolicy,
    CoderProvisionBlocked,
    resource_profile,
)
from defend_control.coder_deployment import (
    CODER_DEPLOYMENT_REGISTRY,
    is_exact_revision,
    meets_minimum_vllm_version,
    resolve_deployment,
)
from defend_control.coder_m0 import resolve_alias
from defend_control.coder_remote_vllm import (
    CoderRemoteVllmBootstrap,
    CoderRemoteVllmError,
)
from defend_control.ssh_tunnel import CommandResult
from defend_control.types import LaunchSpec, ResourceProfile, VastInstance

FP8_REVISION = "da6e2ed27304dd39abadd9c82ef50e8de67bdd4c"
LOGICAL_HEAVY_REVISION = "a7fbcb5c0e12d62a448eaa0e260346bf5dcc0feb"


class RecordingCoderRunner:
    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode
        self.calls: list[tuple[tuple[str, ...], bytes, float]] = []

    def __call__(self, argv, *, stdin, timeout, cancelled=None):
        self.calls.append((tuple(argv), stdin, timeout))
        return CommandResult(self.returncode, b"ok", b"")


class NoOpBackend:
    def __init__(self) -> None:
        self.starts: list[str] = []

    def start(self, model, *, local_port, session_budget_usd, offer=None, profile=None):
        del offer, profile
        self.starts.append(model.alias)
        return {
            "state": "ready",
            "provider": "recording",
            "endpoint": f"http://127.0.0.1:{local_port}/v1",
            "instance_id": 555100,
            "provider_run_id": "recording-555100",
            "hourly_price": "1.10",
            "gpu_type": "A100 SXM4",
            "message": "noop ready",
        }

    def smoke(self, endpoint, model):
        return {"ok": True, "latency_ms": 1, "detail": "noop ok"}

    def stop(self, *, instance_id, provider_run_id, destroy):
        return {"state": "stopped", "message": "noop stopped"}


def _bootstrap(runner: RecordingCoderRunner) -> CoderRemoteVllmBootstrap:
    return CoderRemoteVllmBootstrap(
        command_runner=runner,
        ssh_exe=Path("ssh"),
        known_hosts=Path("known_hosts"),
        key_path=Path("key"),
    )


def _instance() -> VastInstance:
    return VastInstance(1, "running", "host.example", 22, "A100", 81920, Decimal("1.10"))


def _plane(**overrides) -> CoderControlPlane:
    options = {
        "backend": NoOpBackend(),  # type: ignore[arg-type]
        "token_provider": lambda: "hf_fake_token",
        "port_available": lambda port: True,
    }
    options.update(overrides)
    return CoderControlPlane(**options)


def _rendered_heavy_script(runner: RecordingCoderRunner) -> str:
    boot = _bootstrap(runner)
    boot.start(
        _instance(),
        resolve_alias("defendcoder-heavy"),
        {"HF_TOKEN": "hf_synthetic", "CODER_VLLM_API_KEY": "vllm_synthetic"},
        artifact=resolve_deployment("defendcoder-heavy"),
    )
    return runner.calls[0][1].decode("ascii")


class TestHeavyIdentityAndArtifact:
    def test_heavy_logical_identity_is_qwen3_coder_next(self):
        ref = resolve_alias("defendcoder-heavy")
        assert ref.repo_id == "Qwen/Qwen3-Coder-Next"
        assert ref.revision == LOGICAL_HEAVY_REVISION
        assert ref.alias == "defendcoder-heavy"

    def test_heavy_deployment_artifact_is_official_fp8(self):
        artifact = resolve_deployment("defendcoder-heavy")
        assert artifact.repo_id == "Qwen/Qwen3-Coder-Next-FP8"
        assert artifact.precision == "FP8"
        assert artifact.artifact_id == "qwen3-coder-next-fp8"

    def test_deployment_revision_is_exact_never_main(self):
        artifact = resolve_deployment("defendcoder-heavy")
        assert artifact.revision == FP8_REVISION
        assert is_exact_revision(artifact.revision) is True
        assert is_exact_revision("main") is False
        assert artifact.revision != "main"
        for entry in CODER_DEPLOYMENT_REGISTRY.values():
            assert is_exact_revision(entry.revision) is True

    def test_heavy_requires_vllm_0150(self):
        artifact = resolve_deployment("defendcoder-heavy")
        assert artifact.minimum_vllm_version == "0.15.0"
        assert meets_minimum_vllm_version("0.15.0", "0.15.0") is True
        assert meets_minimum_vllm_version("0.14.5", "0.15.0") is False
        assert meets_minimum_vllm_version("0.15.1", "0.15.0") is True
        assert meets_minimum_vllm_version("1.0.0", "0.15.0") is True

    def test_heavy_initial_context_is_32768(self):
        assert resolve_deployment("defendcoder-heavy").max_model_len == 32_768

    def test_heavy_tool_parser_is_qwen3_coder(self):
        artifact = resolve_deployment("defendcoder-heavy")
        assert artifact.tool_call_parser == "qwen3_coder"
        assert artifact.enable_auto_tool_choice is True


class TestDefaultDeployment:
    def test_default_artifact_is_agentic_bf16(self):
        artifact = resolve_deployment("defendcoder-default")
        assert artifact.repo_id == "Qwen/Qwen3-Coder-30B-A3B-Instruct"
        assert artifact.revision == "b2cff646eb4bb1d68355c01b18ae02e7cf42d120"
        assert artifact.precision == "BF16"
        assert artifact.minimum_vllm_version == "0.10.0"
        assert artifact.max_model_len == 8192
        assert artifact.tool_call_parser == "qwen3_coder"
        assert artifact.enable_auto_tool_choice is True
        assert artifact.image_tag == "v0.10.0"

    def test_default_bootstrap_script_enables_agentic_tools(self):
        runner = RecordingCoderRunner()
        boot = _bootstrap(runner)
        boot.start(
            _instance(),
            resolve_alias("defendcoder-default"),
            {"HF_TOKEN": "hf_synthetic", "CODER_VLLM_API_KEY": "vllm_synthetic"},
            artifact=resolve_deployment("defendcoder-default"),
        )
        rendered = runner.calls[0][1].decode("ascii")
        assert "Qwen/Qwen3-Coder-30B-A3B-Instruct" in rendered
        assert "--max-model-len 8192" in rendered
        assert "--tool-call-parser qwen3_coder" in rendered
        assert "--enable-auto-tool-choice" in rendered
        assert "hf_synthetic" not in rendered
        assert "vllm_synthetic" not in rendered

    def test_defend_ai_behavior_is_unchanged(self):
        assert LaunchSpec.default() == LaunchSpec(
            "vllm/vllm-openai:v0.10.0",
            160,
            "ssh_proxy",
            "defend-vllm",
        )
        assert ResourceProfile().min_gpu_ram_mb >= 140_000
        assert BillingPolicy().free_monthly_credit_allowance == Decimal("5.00")


class TestHeavyBootstrapArtifactAware:
    def test_heavy_script_uses_fp8_artifact_and_required_flags(self):
        runner = RecordingCoderRunner()
        rendered = _rendered_heavy_script(runner)
        assert len(runner.calls) == 1
        assert "Qwen/Qwen3-Coder-Next-FP8" in rendered
        assert FP8_REVISION in rendered
        assert "--max-model-len 32768" in rendered
        assert "--tool-call-parser qwen3_coder" in rendered
        assert "--enable-auto-tool-choice" in rendered
        assert "hf_synthetic" not in rendered
        assert "vllm_synthetic" not in rendered
        assert not any(
            secret in part
            for secret in ("hf_synthetic", "vllm_synthetic")
            for part in runner.calls[0][0]
        )

    def test_heavy_bootstrap_without_artifact_resolves_from_alias(self):
        runner = RecordingCoderRunner()
        boot = _bootstrap(runner)
        boot.start(
            _instance(),
            resolve_alias("defendcoder-heavy"),
            {"HF_TOKEN": "hf_synthetic", "CODER_VLLM_API_KEY": "vllm_synthetic"},
        )
        rendered = runner.calls[0][1].decode("ascii")
        assert "Qwen/Qwen3-Coder-Next-FP8" in rendered
        assert "--tool-call-parser qwen3_coder" in rendered

    def test_unknown_deployment_alias_is_rejected(self):
        with pytest.raises(ValueError, match="no deployment artifact"):
            resolve_deployment("not-a-real-alias")


class TestPreflight:
    def test_preflight_reports_all_checks_for_heavy(self):
        plane = _plane()
        report = plane.preflight("defendcoder-heavy")
        assert report.all_ok is True
        names = [check.name for check in report.checks]
        assert names == [
            "deployment artifact",
            "exact revision",
            "supported vLLM version",
            "resource profile",
            "model context",
            "HF token",
            "local port",
            "session budget",
        ]

    def test_preflight_surfaces_each_failure(self):
        plane = _plane(port_available=lambda port: False)
        report = plane.preflight("defendcoder-heavy")
        assert report.all_ok is False
        by_name = {check.name: check for check in report.checks}
        assert by_name["local port"].ok is False
        assert by_name["deployment artifact"].ok is True

    def test_preflight_failure_prevents_provisioning(self):
        backend = NoOpBackend()
        plane = _plane(backend=backend, port_available=lambda port: False)
        with pytest.raises(CoderProvisionBlocked, match="preflight"):
            plane.acquire("defendcoder-heavy")
        assert backend.starts == []

    def test_missing_required_hf_token_prevents_provisioning(self, monkeypatch):
        artifact = resolve_deployment("defendcoder-heavy")
        monkeypatch.setitem(
            CODER_DEPLOYMENT_REGISTRY,
            "defendcoder-heavy",
            replace(artifact, requires_hf_token=True),
        )
        backend = NoOpBackend()
        plane = _plane(backend=backend, token_provider=lambda: None)
        report = plane.preflight("defendcoder-heavy")
        by_name = {check.name: check for check in report.checks}
        assert by_name["HF token"].ok is False
        with pytest.raises(CoderProvisionBlocked, match="preflight"):
            plane.acquire("defendcoder-heavy")
        assert backend.starts == []

    def test_preflight_report_is_public_safe(self):
        plane = _plane()
        blob = plane.preflight("defendcoder-heavy").as_public_dict()
        assert blob["alias"] == "defendcoder-heavy"
        assert blob["all_ok"] is True
        for banned in ("api_key", "password", "secret", "bearer"):
            assert banned not in " ".join(
                str(check) for check in blob["checks"]
            ).casefold()


class TestLiveSmokePlan:
    def test_heavy_live_smoke_plan_is_exact_and_inspectable(self):
        plane = _plane()
        plan = plane.live_smoke_plan("defendcoder-heavy")
        assert plan.alias == "defendcoder-heavy"
        assert plan.logical_repo_id == "Qwen/Qwen3-Coder-Next"
        assert plan.logical_revision == LOGICAL_HEAVY_REVISION
        assert plan.deployment_repo_id == "Qwen/Qwen3-Coder-Next-FP8"
        assert plan.deployment_revision == FP8_REVISION
        assert plan.precision == "FP8"
        assert plan.gpu_families == ("A100", "H100")
        assert plan.gpu_count == 2
        assert plan.vram_per_gpu_mb == 81_920
        assert plan.tensor_parallel_size == 2
        assert plan.max_hourly_price_usd == Decimal("2.00")
        assert plan.session_budget_usd == Decimal("5.00")
        assert plan.max_model_len == 32_768
        assert plan.serving_runtime == "vllm/vllm-openai:v0.15.0"
        assert plan.minimum_vllm_version == "0.15.0"
        assert plan.tool_call_parser == "qwen3_coder"
        assert plan.auto_tool_choice is True
        assert plan.local_port == 8003
        assert plan.provider == "vast"
        assert plan.gpu_family is None
        assert plan.provider_hourly_rate is None
        assert plan.estimated_max_hourly_spend == Decimal("2.00")
        assert plan.offer_id is None
        assert plan.status == "requires_approval"
        assert plan.plan_id
        assert plan.plan_hash

    def test_live_smoke_plan_public_dict_has_no_secrets(self):
        plan = _plane().live_smoke_plan("defendcoder-heavy")
        public = plan.as_public_dict()
        assert public["alias"] == "defendcoder-heavy"
        assert public["deployment_revision"] == FP8_REVISION
        assert public["gpu_count"] == 2
        assert public["tensor_parallel_size"] == 2
        assert public["status"] == "requires_approval"
        blob = " ".join(f"{key}={value}" for key, value in public.items())
        for banned in ("api_key", "password", "secret", "token"):
            assert banned not in blob.casefold()

    def test_live_smoke_plan_requires_no_provisioning(self):
        backend = NoOpBackend()
        plane = _plane(backend=backend)
        plan = plane.live_smoke_plan("defendcoder-heavy")
        assert isinstance(plan, CoderLiveSmokePlan)
        assert backend.starts == []


class TestNoProviderCalls:
    def test_deployment_module_has_no_network_or_provider_imports(self):
        source = inspect.getsource(
            inspect.getmodule(resolve_deployment)
        ).casefold()
        for banned in ("urllib", "requests", "socket", "huggingface", "vast"):
            assert banned not in source

    def test_deployment_module_has_no_hf_token_literals(self):
        source = inspect.getsource(
            inspect.getmodule(resolve_deployment)
        ).casefold()
        assert source.count("hf_") == source.count("requires_hf_token")
        assert "bearer" not in source
        assert "sk-" not in source