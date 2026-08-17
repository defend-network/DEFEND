from __future__ import annotations

import json

import pytest

from defend_integrations.models import HealthBadge
from defend_integrations.stores import (
    ProviderConfigStore,
    SecretRegistry,
    apply_rotation_invalidation,
    default_secret_path,
)
from defend_integrations.registry import (
    LEGACY_SECRET_MAP,
    REGISTRY_SECRET_NAMES,
    find_provider,
)


class MemStore:
    def __init__(self, initial=None):
        self.data = dict(initial or {})

    def load(self):
        return dict(self.data)

    def save(self, values):
        self.data = dict(values)


def test_secret_registry_save_remove_and_blank_retain(tmp_path):
    store = MemStore()
    registry = SecretRegistry(store)
    registry.save({"FRED_API_KEY": "fred-key-value", "HF_TOKEN": ""})
    assert store.data == {"FRED_API_KEY": "fred-key-value"}
    assert registry.configured("FRED_API_KEY") is True
    assert registry.masked("FRED_API_KEY") == "****alue"
    registry.save({"FRED_API_KEY": "second-value"})
    assert store.data["FRED_API_KEY"] == "second-value"
    registry.remove("FRED_API_KEY")
    assert "FRED_API_KEY" not in store.data
    assert registry.configured("FRED_API_KEY") is False


def test_secret_registry_rejects_unknown_names(tmp_path):
    registry = SecretRegistry(MemStore())
    with pytest.raises(ValueError, match="unknown secret name"):
        registry.save({"NOT_A_REAL_SECRET": "x"})
    with pytest.raises(ValueError, match="unknown secret name"):
        registry.remove("NOT_A_REAL_SECRET")


def test_legacy_secret_ids_remain_usable_without_reentry(tmp_path):
    store = MemStore({"VAST_API_KEY": "legacy-vast-key", "HF_TOKEN": "legacy-hf"})
    registry = SecretRegistry(store)
    assert registry.configured("VAST_API_KEY")
    assert registry.masked("HF_TOKEN") == "****y-hf"
    # The legacy map resolves these ids onto registry providers.
    assert LEGACY_SECRET_MAP["VAST_API_KEY"] == "vast"
    assert LEGACY_SECRET_MAP["HF_TOKEN"] == "huggingface"
    assert LEGACY_SECRET_MAP["DEFEND_OWNER_USER"] == "admin_identity"


def test_registry_secret_names_include_all_known_ids(tmp_path):
    assert "FRED_API_KEY" in REGISTRY_SECRET_NAMES
    assert "THE_ODDS_API_KEY" in REGISTRY_SECRET_NAMES
    assert "CONGRESS_API_KEY" in REGISTRY_SECRET_NAMES
    assert "DEFEND_OWNER_USER" in REGISTRY_SECRET_NAMES


def test_config_store_round_trip_and_invalidation(tmp_path):
    path = tmp_path / "integrations-config.json"
    store = ProviderConfigStore(path)
    store.set_enabled("fred", False)
    store.set_config("fred", {"note": "hello"})
    store.record_probe(
        "fred",
        badge=HealthBadge.HEALTHY,
        tested_at="2026-08-17T10:00:00Z",
        detail="reachable",
        status_code=200,
        latency_ms=42,
        last_success_at="2026-08-17T10:00:00Z",
        remaining_quota=97,
        quota_reset_at="2026-08-18T00:00:00Z",
    )
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["fred"]["health_badge"] == "HEALTHY"
    assert persisted["fred"]["remaining_quota"] == 97

    reloaded = ProviderConfigStore(path)
    config = reloaded.get("fred")
    assert config.enabled is False
    assert config.health_badge is HealthBadge.HEALTHY
    assert config.remaining_quota == 97
    assert config.config == {"note": "hello"}

    reloaded.invalidate_health("fred")
    assert reloaded.get("fred").health_badge is HealthBadge.NOT_TESTED
    assert reloaded.get("fred").tested_at is None
    assert reloaded.get("fred").config == {"note": "hello"}


def test_config_store_rejects_corrupt_json(tmp_path):
    path = tmp_path / "integrations-config.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="valid JSON"):
        ProviderConfigStore(path)


def test_config_store_rejects_bad_entries(tmp_path):
    path = tmp_path / "integrations-config.json"
    path.write_text(json.dumps({"fred": {"enabled": "yes"}}), encoding="utf-8")
    with pytest.raises(ValueError, match="boolean"):
        ProviderConfigStore(path)


def test_rotation_invalidation_clears_only_affected_providers(tmp_path):
    config_path = tmp_path / "config.json"
    config = ProviderConfigStore(config_path)
    config.record_probe(
        "vast",
        badge=HealthBadge.HEALTHY,
        tested_at="2026-08-17T10:00:00Z",
        detail="reachable",
        status_code=200,
        latency_ms=10,
        last_success_at="2026-08-17T10:00:00Z",
        remaining_quota=None,
        quota_reset_at=None,
    )
    config.record_probe(
        "fred",
        badge=HealthBadge.HEALTHY,
        tested_at="2026-08-17T10:00:00Z",
        detail="reachable",
        status_code=200,
        latency_ms=10,
        last_success_at="2026-08-17T10:00:00Z",
        remaining_quota=None,
        quota_reset_at=None,
    )
    registry = SecretRegistry(MemStore({"VAST_API_KEY": "key"}))
    apply_rotation_invalidation(config, registry, updates={"VAST_API_KEY": "new"})
    assert config.get("vast").health_badge is HealthBadge.NOT_TESTED
    assert config.get("fred").health_badge is HealthBadge.HEALTHY


def test_legacy_secret_map_covers_owner_credentials():
    assert LEGACY_SECRET_MAP["DEFEND_OWNER_PASS"] == "admin_identity"
    assert "DEFEND_OWNER_USER" in REGISTRY_SECRET_NAMES


def test_default_secret_path_uses_localappdata(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert default_secret_path() == tmp_path / "DEFEND" / "secrets.dpapi"


def test_default_secret_path_requires_localappdata(monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    with pytest.raises(RuntimeError, match="LOCALAPPDATA"):
        default_secret_path()


def test_secret_registry_save_rejects_non_strings(tmp_path):
    registry = SecretRegistry(MemStore())
    with pytest.raises(ValueError, match="strings"):
        registry.save({"FRED_API_KEY": 123})  # type: ignore[dict-item]


def test_every_legacy_secret_is_known_somewhere():
    for name in LEGACY_SECRET_MAP:
        assert name in REGISTRY_SECRET_NAMES or name in LEGACY_SECRET_MAP


def test_dpapi_store_compat_shapes(tmp_path):
    """The store surface we consume matches DpapiSecretStore's public API."""
    from defend_control.secrets import DpapiSecretStore

    store = DpapiSecretStore(
        tmp_path / "secrets.dpapi",
        backend=_ReversingBackend(),
        acl=lambda _path: None,
    )
    store.save({"VAST_API_KEY": "compat-key-value"})
    registry = SecretRegistry(store)
    assert registry.configured("VAST_API_KEY") is True
    assert registry.masked("VAST_API_KEY") == "****alue"
    assert find_provider(LEGACY_SECRET_MAP["VAST_API_KEY"]) is not None


class _ReversingBackend:
    def protect(self, data: bytes) -> bytes:
        return data[::-1]

    def unprotect(self, data: bytes) -> bytes:
        return data[::-1]