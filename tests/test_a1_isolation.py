"""PHASE A tests: DEFEND AI settings authority + supervision manifest."""

from __future__ import annotations

from defend_ai.settings import (
    API_PORT_DEFAULT,
    MODEL_PORT_DEFAULT,
    WEB_PORT_DEFAULT,
    load_settings,
)
from defend_ai.supervision import APPLICATION_ID, supervision_dict, supervision_manifest


def test_product_settings_authority_env_driven(monkeypatch):
    monkeypatch.setenv("DEFEND_API_PORT", "8123")
    monkeypatch.setenv("DEFEND_UI_PORT", "3123")
    monkeypatch.setenv("DEFEND_DATA_ROOT", "C:/tmp/defend-data")
    s = load_settings()
    assert s.api_port == 8123
    assert s.web_port == 3123
    assert s.data_root == "C:/tmp/defend-data"


def test_ai_ports_have_one_authority():
    assert API_PORT_DEFAULT == 8401
    assert WEB_PORT_DEFAULT == 3000
    assert MODEL_PORT_DEFAULT == 8402
    s = load_settings()
    assert s.api_port == 8401
    assert s.web_port == 3000
    assert s.model_port == 8402


def test_product_api_does_not_take_over_admin_api_port():
    assert load_settings().api_port != 8000


def test_ai_provider_settings_are_product_owned():
    s = load_settings()
    assert s.adapter_repo == "Defend-network/defend-identity-lora-v002"
    rp = s.resource_profile()
    assert rp.min_gpu_ram_mb >= 140_000
    assert rp.allowed_gpu_families == ("A100", "H100", "H200", "B200")


def test_supervision_manifest_owns_ports_and_health():
    m = supervision_manifest()
    assert m.application_id == "defend"
    assert m.display_name == "DEFEND AI"
    assert m.health_url.endswith("/health")
    assert m.api_launch == ("python", "-m", "defend_ai.api_server")
    assert m.api_port == 8401
    assert m.web_port == 3000


def test_supervision_manifest_is_canonical_product():
    m = supervision_dict()
    assert m["application_id"] == APPLICATION_ID
    assert m["api_launch"] == ["python", "-m", "defend_ai.api_server"]
    assert m["graceful_stop_contract"]
    for forbidden in ("training", "canary", "gpu", "rent", "promote", "provider_mutation", "vast"):
        assert forbidden not in m


def test_supervision_launch_references_package_entrypoint():
    import importlib.util

    spec = importlib.util.find_spec("defend_ai.api_server")
    assert spec is not None
