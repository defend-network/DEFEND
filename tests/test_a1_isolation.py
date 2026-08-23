"""PHASE A tests: DEFEND AI settings authority + supervision manifest."""

from __future__ import annotations

import os

from defend_ai.settings import load_settings
from defend_ai.supervision import APPLICATION_ID, supervision_dict, supervision_manifest


def test_product_settings_authority_env_driven(monkeypatch):
    monkeypatch.setenv("DEFEND_API_PORT", "8123")
    monkeypatch.setenv("DEFEND_UI_PORT", "3123")
    monkeypatch.setenv("DEFEND_DATA_ROOT", "C:/tmp/defend-data")
    s = load_settings()
    assert s.api_port == 8123
    assert s.web_port == 3123
    assert s.data_root == "C:/tmp/defend-data"


def test_supervision_manifest_owns_ports_and_health():
    m = supervision_manifest()
    assert m.application_id == "defend"
    assert m.display_name == "DEFEND AI"
    assert m.health_url.endswith("/health")
    assert m.api_launch == ("python", "-m", "defend_ai.api_server")


def test_supervision_manifest_is_canonical_product():
    m = supervision_dict()
    assert m["application_id"] == APPLICATION_ID
    assert m["api_launch"] == ["python", "-m", "defend_ai.api_server"]
    assert m["graceful_stop_contract"]
    # no provider/training/promotion authority exposed
    for forbidden in ("training", "canary", "gpu", "rent", "promote", "provider_mutation", "vast"):
        assert forbidden not in m


def test_supervision_launch_references_package_entrypoint():
    import importlib.util

    spec = importlib.util.find_spec("defend_ai.api_server")
    assert spec is not None
