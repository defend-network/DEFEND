"""DEFENDcoder M0 tests — isolated from identity chat launch path."""

from decimal import Decimal

import pytest

from defend_control.coder_m0 import (
    CODER_MODEL_REGISTRY,
    CoderM0Service,
    LocalFakeCoderBackend,
    parse_session_budget,
    resolve_alias,
)


def test_registry_contains_required_aliases():
    for alias in (
        "defendcoder-fast",
        "defendcoder-default",
        "defendcoder-heavy",
        "defendcoder-eval",
    ):
        ref = resolve_alias(alias)
        assert ref.alias == alias
        assert ref.repo_id
        assert ref.revision


def test_unknown_alias_rejected():
    with pytest.raises(ValueError, match="unknown coder alias"):
        resolve_alias("not-a-real-alias")


def test_session_budget_configurable_default():
    assert parse_session_budget("5.00") == Decimal("5.00")
    assert parse_session_budget(Decimal("8.5")) == Decimal("8.5")
    with pytest.raises(ValueError):
        parse_session_budget("0")
    with pytest.raises(ValueError):
        parse_session_budget("-1")


def test_start_smoke_stop_happy_path():
    backend = LocalFakeCoderBackend()
    service = CoderM0Service(backend=backend, local_port=8003)

    status = service.start()
    assert status.state == "ready"
    assert status.alias == "defendcoder-default"
    assert status.endpoint == "http://127.0.0.1:8003/v1"
    assert status.instance_id == 900001
    assert status.provider_run_id
    assert status.session_budget_usd == "5.00"

    smoke = service.smoke()
    assert smoke.ok is True
    assert smoke.instance_id == 900001
    assert smoke.provider_run_id == status.provider_run_id

    stopped = service.stop(destroy=False)
    assert stopped.state == "stopped"
    assert stopped.endpoint is None
    # retain instance metadata when not destroying
    assert stopped.instance_id == 900001


def test_start_smoke_stop_destroy_requires_exact_instance_id():
    backend = LocalFakeCoderBackend()
    service = CoderM0Service(backend=backend)
    service.start()

    with pytest.raises(ValueError, match="exact coder instance ID"):
        service.stop(destroy=True, confirmed_instance_id=1)

    destroyed = service.stop(destroy=True, confirmed_instance_id=900001)
    assert destroyed.state == "stopped"
    assert destroyed.instance_id is None
    assert destroyed.provider_run_id is None


def test_smoke_fails_when_stopped():
    service = CoderM0Service(backend=LocalFakeCoderBackend())
    smoke = service.smoke()
    assert smoke.ok is False
    assert "cannot smoke" in smoke.detail


def test_cannot_double_start_without_stop():
    service = CoderM0Service(backend=LocalFakeCoderBackend())
    service.start()
    with pytest.raises(RuntimeError, match="already in state"):
        service.start()


def test_public_status_has_no_secret_shaped_fields():
    service = CoderM0Service(backend=LocalFakeCoderBackend())
    service.start()
    payload = service.status().as_public_dict()
    blob = str(payload).lower()
    for banned in ("api_key", "token", "password", "secret", "authorization"):
        assert banned not in blob
    assert payload["service"] == "DEFENDcoder"
    assert payload["instance_id"] == 900001
    assert payload["provider_run_id"]


def test_start_with_explicit_alias():
    service = CoderM0Service(backend=LocalFakeCoderBackend())
    status = service.start("defendcoder-fast")
    assert status.alias == "defendcoder-fast"
    assert status.model_repo == CODER_MODEL_REGISTRY["defendcoder-fast"].repo_id


def test_identity_chat_types_still_importable_unchanged():
    # Regression seam: M0 must not break existing control imports.
    from defend_control.types import LaunchSpec, ModelMode, ResourceProfile
    from defend_control.controller import ControlController

    assert LaunchSpec.default().label == "defend-vllm"
    assert "vast" in str(ModelMode)
    profile = ResourceProfile()
    assert profile.min_gpu_ram_mb >= 80_000
    assert ControlController is not None
