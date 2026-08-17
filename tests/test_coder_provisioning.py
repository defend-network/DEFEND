"""Provisioning observability unit tests — phase taxonomy, sanitization,
staged remote script markers, and the structured failure record."""

from decimal import Decimal

import pytest

from defend_control.coder_deployment import resolve_deployment
from defend_control.coder_m0 import CoderModelRef
from defend_control.coder_provisioning import (
    CLEANUP_STATES,
    CODER_PROVISION_PHASES,
    CoderProvisionFailure,
    CoderProvisionPhase,
    format_elapsed,
    parse_remote_stages,
    sanitize_remote_tail,
    wall_clock,
)
from defend_control.coder_remote_vllm import (
    CoderRemoteVllmBootstrap,
    _MODEL_READY_WAIT_SECONDS,
)


def test_phase_taxonomy_is_exactly_the_owner_spec():
    assert CODER_PROVISION_PHASES == (
        "instance_create",
        "instance_running_wait",
        "direct_endpoint_wait",
        "ssh_connect",
        "ssh_tunnel",
        "remote_preflight",
        "bootstrap_upload",
        "container_start",
        "vllm_start",
        "model_load",
        "health_wait",
        "openai_smoke",
        "local_api_start",
        "local_web_start",
        "cleanup",
    )


def test_cleanup_states_are_exactly_the_owner_spec():
    assert CLEANUP_STATES == (
        "destroyed",
        "destroy_pending",
        "destroy_verification_failed",
        "destroy_request_failed",
        "unknown",
        "not_attempted",
    )


def test_parse_remote_stages_ordered_and_ignores_unknown_markers():
    output = (
        "CODER_STAGE remote_preflight\n"
        "some output line\n"
        "CODER_STAGE bootstrap_upload\n"
        "CODER_STAGE container_start\n"
        "CODER_STAGE vllm_start\n"
        "CODER_STAGE model_load\n"
        "CODER_STAGE health_wait\n"
        "CODER_STAGE not_a_stage\n"
        "CODER_STAGE remote_preflight\n"
    )
    assert parse_remote_stages(output) == (
        "remote_preflight",
        "bootstrap_upload",
        "container_start",
        "vllm_start",
        "model_load",
        "health_wait",
    )


def test_parse_remote_stages_rejects_secret_shaped_content():
    output = "CODER_STAGE Bearer sk-abc123\nCODER_STAGE model_load\n"
    assert parse_remote_stages(output) == ("model_load",)


def test_sanitize_remote_tail_strips_authorization_lines_and_bearer_values():
    output = (
        "Authorization: Bearer sk-secret-value\n"
        "request: GET /v1/models with Bearer abc.def-ghi\n"
        "vllm log line\n"
    )
    cleaned = sanitize_remote_tail(output)
    assert cleaned is not None
    assert "sk-secret-value" not in cleaned
    assert "abc.def-ghi" not in cleaned
    assert "vllm log line" in cleaned


def test_sanitize_remote_tail_bounded_and_empty_safe():
    tail = sanitize_remote_tail("x" * 100_000)
    assert tail is not None
    assert len(tail) <= 24_000
    assert sanitize_remote_tail("") is None
    assert sanitize_remote_tail("Authorization: Bearer only") is None


def test_format_elapsed():
    assert format_elapsed(0) == "0s"
    assert format_elapsed(37) == "37s"
    assert format_elapsed(247) == "4m 7s"
    assert format_elapsed(-5) == "0s"


def test_wall_clock_shape():
    value = wall_clock()
    assert len(value) == 8
    assert value[2] == ":" and value[5] == ":"


def test_failure_record_validates_phase_and_cleanup():
    with pytest.raises(ValueError, match="unknown provisioning phase"):
        CoderProvisionFailure(
            phase="not_a_phase",
            exception_type="X",
            sanitized_message="m",
        )
    with pytest.raises(ValueError, match="unknown cleanup state"):
        CoderProvisionFailure(
            phase="model_load",
            exception_type="X",
            sanitized_message="m",
            cleanup_state="partially_destroyed",
        )


def test_failure_record_as_lines_matches_panel_rows():
    failure = CoderProvisionFailure(
        phase="model_load",
        exception_type="CoderVastBackendError",
        sanitized_message="vllm process died during model load",
        instance_id=555901,
        gpu_name="A100 SXM4",
        approved_hourly_rate=Decimal("1.10"),
        elapsed_seconds=247.0,
        endpoint_state="ready",
        ssh_state="ready",
        bootstrap_state="model_load",
        vllm_state="model_load",
        readiness_state="not_ready",
        cleanup_state="destroyed",
    )
    lines = failure.as_lines()
    assert lines == (
        "PROVISIONING FAILED",
        "Phase: model_load",
        "Reason: vllm process died during model load",
        "Instance: 555901",
        "GPU: A100 SXM4",
        "Approved rate: $1.10/hr",
        "Runtime before failure: 4m 7s",
        "Cleanup: destroyed",
    )


def test_failure_record_optional_rows_omitted():
    failure = CoderProvisionFailure(
        phase="instance_create",
        exception_type="VastError",
        sanitized_message="provider rejected the offer",
    )
    lines = failure.as_lines()
    assert "Instance:" not in "".join(lines)
    assert "GPU:" not in "".join(lines)
    assert "Approved rate:" not in "".join(lines)
    assert "Cleanup: unknown" in lines


def test_failure_record_with_cleanup_preserves_everything_else():
    failure = CoderProvisionFailure(
        phase="ssh_tunnel",
        exception_type="CoderVastBackendError",
        sanitized_message="tunnel down",
        instance_id=555001,
        gpu_name="A100 SXM4",
        approved_hourly_rate=Decimal("2.00"),
        elapsed_seconds=12.0,
    )
    updated = failure.with_cleanup("destroyed")
    assert updated.cleanup_state == "destroyed"
    assert updated.phase == "ssh_tunnel"
    assert updated.instance_id == 555001
    assert updated.approved_hourly_rate == Decimal("2.00")
    assert updated.sanitized_message == "tunnel down"
    assert updated is not failure


def test_failure_record_accepts_string_rate():
    failure = CoderProvisionFailure(
        phase="local_api_start",
        exception_type="RuntimeError",
        sanitized_message="port in use",
        approved_hourly_rate="1.10",
    )
    assert failure.approved_hourly_rate == Decimal("1.10")


def _staged_script() -> bytes:
    boot = CoderRemoteVllmBootstrap(
        ssh_exe="ssh",
        known_hosts="known_hosts",
        key_path="key",
    )
    model = CoderModelRef(
        alias="defendcoder-default",
        repo_id="Qwen/Qwen3Coder-30B-A3B-Instruct",
        revision="main",
    )
    artifact = resolve_deployment("defendcoder-default")
    return boot._script(  # type: ignore[attr-defined]
        model,
        artifact,
        "hf_secret_token",
        "vllm_secret_key",
        8000,
    )


def test_staged_script_emits_all_stage_markers():
    script = _staged_script().decode("ascii")
    for stage in (
        "remote_preflight",
        "bootstrap_upload",
        "container_start",
        "vllm_start",
        "model_load",
    ):
        assert f"stage {stage}" in script
    assert 'echo "CODER_STAGE $1"' in script
    assert "CODER_STAGE health_wait" in script


def test_staged_script_polls_models_without_secret_in_headers_literal():
    script = _staged_script().decode("ascii")
    assert 'dict(Authorization="Bearer " + key)' in script
    assert f"time.monotonic() + {int(_MODEL_READY_WAIT_SECONDS)}" in script
    assert "os.kill(pid, 0)" in script
    assert "sys.exit(71)" in script
    assert "sys.exit(72)" in script
    assert "tail -n 200" in script
    assert "coder ready" in script


def test_staged_script_never_contains_plaintext_secrets():
    script = _staged_script().decode("ascii")
    assert "hf_secret_token" not in script
    assert "vllm_secret_key" not in script
    assert "unset VLLM_API_KEY" in script
    assert ".hf_token" in script