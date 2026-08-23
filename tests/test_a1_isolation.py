"""PHASE A tests: DEFEND AI settings authority + supervision manifest."""

from __future__ import annotations

import os

from defend_ai.settings import PRODUCT_ID, load_settings
from defend_ai.supervision import supervision_manifest


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
    assert m["product_id"] == PRODUCT_ID
    assert m["api_port"] == int(os.getenv("DEFEND_API_PORT", "8000"))
    assert m["health_url"].endswith("/health")
    # no provider/training/promotion authority exposed
    for forbidden in ("training", "canary", "gpu", "rent", "promote", "provider_mutation"):
        assert forbidden not in m


def test_supervision_manifest_is_canonical_product():
    m = supervision_manifest()
    assert m["display_name"] == "DEFEND AI"
    assert m["api_command"]
    assert m["graceful_stop_contract"]
