"""SCS M1.5C-S — product-owned Setup / Knowledge onboarding tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scs_copilot.memory import JobMemoryCorrupt, JobMemoryStore
from scs_data.settings import ScsSettingsStore, validate_knowledge_root
from scs_knowledge.discovery import KnowledgeDiscoveryStore


def test_recovery_archive_filename_sanitized(tmp_path):
    mem_dir = tmp_path / "mem"
    hostile = "../evil/../name"
    store = JobMemoryStore(mem_dir)
    store.update(hostile, lambda m: m.record_reading("x", 1, stage="FINAL"))
    safe_name = JobMemoryStore._safe_name(hostile)
    assert "/" not in safe_name and "\\" not in safe_name
    (mem_dir / f"{safe_name}.memory.json").write_text("{corrupt", encoding="utf-8")
    store2 = JobMemoryStore(mem_dir)
    result = store2.archive_corrupt_and_reset(hostile, actor="owner")
    assert result["archived"] is True
    recovery = mem_dir / "_recovery"
    assert recovery.exists()
    archives = list(recovery.iterdir())
    assert archives
    for p in archives:
        assert p.parent == recovery
        assert "/" not in p.name and "\\" not in p.name


def test_recovery_archive_contained(tmp_path):
    mem_dir = tmp_path / "mem"
    hostile = "..\\..\\evil"
    store = JobMemoryStore(mem_dir)
    store.update(hostile, lambda m: m.record_reading("x", 1, stage="FINAL"))
    safe_name = JobMemoryStore._safe_name(hostile)
    (mem_dir / f"{safe_name}.memory.json").write_text("{bad", encoding="utf-8")
    store2 = JobMemoryStore(mem_dir)
    store2.archive_corrupt_and_reset(hostile, actor="owner")
    recovery = mem_dir / "_recovery"
    archives = list(recovery.iterdir())
    assert archives and all(p.parent == recovery for p in archives)
    # nothing escaped outside the private memory root
    assert not list(mem_dir.parent.glob("evil*"))


def test_incompatible_parseable_no_authority_recovery(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("SCS_KNOWLEDGE_ROOT", str(root))
    (root / "discovery.json").write_text(json.dumps({"DSC-old": {"state": "DISCOVERED"}}), encoding="utf-8")
    store = KnowledgeDiscoveryStore(root / "discovery.json", root=root)
    assert store.ledger_state == "INCOMPATIBLE"
    result = store.archive_and_rediscover(actor="owner")
    assert result["archived"] is True
    assert result["auto_approved_count"] == 0


def test_incompatible_authoritative_recovery_refused(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("SCS_KNOWLEDGE_ROOT", str(root))
    (root / "discovery.json").write_text(json.dumps({"DSC-old": {"state": "INDEXED"}}), encoding="utf-8")
    store = KnowledgeDiscoveryStore(root / "discovery.json", root=root)
    result = store.archive_and_rediscover(actor="owner")
    assert result["state"] == "LEGACY_LEDGER_AUTHORITY_PRESENT"
    assert result["archived"] is False


def test_corrupt_ledger_unknown_authority_requires_confirmation(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "discovery.json").write_text("{not valid json", encoding="utf-8")
    store = KnowledgeDiscoveryStore(root / "discovery.json", root=root)
    assert store.ledger_state == "CORRUPT"
    result = store.archive_and_rediscover(actor="owner")
    assert result["state"] == "CORRUPT_UNKNOWN_AUTHORITY"
    assert result["requires_confirmation"] is True
    # second explicit confirmation proceeds
    result2 = store.archive_and_rediscover(actor="owner", confirm_unknown_authority=True)
    assert result2["state"] == "RECOVERED"


def test_settings_persistence_and_restart(tmp_path):
    store = ScsSettingsStore(tmp_path / "settings.json")
    assert store.knowledge_root() == (None, "not_configured")
    store.set("knowledge_root", str(tmp_path / "root"))
    store2 = ScsSettingsStore(tmp_path / "settings.json")  # restart
    assert store2.knowledge_root() == (str(tmp_path / "root"), "persisted")


def test_settings_env_fallback_and_precedence(tmp_path, monkeypatch):
    monkeypatch.setenv("SCS_KNOWLEDGE_ROOT", str(tmp_path / "envroot"))
    store = ScsSettingsStore(tmp_path / "settings.json")
    assert store.knowledge_root() == (str(tmp_path / "envroot"), "env")
    # persisted setting wins over env
    store.set("knowledge_root", str(tmp_path / "persisted"))
    assert store.knowledge_root() == (str(tmp_path / "persisted"), "persisted")


def test_invalid_root_rejected(tmp_path):
    with pytest.raises(ValueError):
        validate_knowledge_root(str(tmp_path / "does_not_exist"))
    (tmp_path / "afile.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        validate_knowledge_root(str(tmp_path / "afile.txt"))
