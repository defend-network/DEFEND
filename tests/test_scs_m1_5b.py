"""SCS M1.5B — knowledge authority + field evidence integrity tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scs_copilot.concepts import (
    FIELD_CONCEPTS,
    normalize_concept,
    scope_of,
    validate_unit,
)
from scs_copilot.memory import JobConversationMemory
from scs_knowledge.discovery import (
    DiscoveryLedgerError,
    KnowledgeDiscoveryStore,
    KnowledgeRootNotConfigured,
)
from scs_knowledge.registry import SCSKnowledgeLibrary


def _store(tmp_path, root_configured=True, monkeypatch=None):
    root = tmp_path / "root"
    root.mkdir()
    if monkeypatch is not None:
        monkeypatch.setenv("SCS_KNOWLEDGE_ROOT", str(root) if root_configured else "")
    elif not root_configured:
        import os
        os.environ.pop("SCS_KNOWLEDGE_ROOT", None)
    return KnowledgeDiscoveryStore(root / "discovery.json", root=root)


def _discover(store, name="manual.txt", text="Carrier 50TC installation manual"):
    (store._root / name).write_text(text, encoding="utf-8")
    store.discover()
    return store.list()[0]


# ---------------------------------------------------------------------------
# Knowledge state machine
# ---------------------------------------------------------------------------


def test_full_transition_flow(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch=monkeypatch)
    record = _discover(store)
    assert record["state"] == "DISCOVERED"
    store.classify(record["discovery_id"], manufacturer="CARRIER", model="50TC-E08")
    assert store.get(record["discovery_id"])["state"] == "CLASSIFIED"
    store.approve(record["discovery_id"], manufacturer="CARRIER", model="50TC-E08")
    assert store.get(record["discovery_id"])["state"] == "OWNER_APPROVED"


def test_blocked_cannot_be_approved(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch=monkeypatch)
    record = _discover(store)
    store.block(record["discovery_id"], "customer invoice")
    assert store.get(record["discovery_id"])["state"] == "BLOCKED"
    store.classify(record["discovery_id"])  # should not reopen
    assert store.get(record["discovery_id"])["state"] == "BLOCKED"
    store.approve(record["discovery_id"], manufacturer="CARRIER")
    assert store.get(record["discovery_id"])["state"] == "BLOCKED"


def test_stale_cannot_be_approved(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch=monkeypatch)
    record = _discover(store, text="version one")
    store.approve(record["discovery_id"], manufacturer="CARRIER")
    # change bytes -> stale via rediscovery
    (store._root / "manual.txt").write_text("version two changed", encoding="utf-8")
    store.discover()
    assert store.get(record["discovery_id"])["state"] == "STALE_CHANGED"
    store.approve(record["discovery_id"], manufacturer="CARRIER")
    assert store.get(record["discovery_id"])["state"] == "STALE_CHANGED"


def test_identical_blocked_bytes_rediscovery_does_not_bypass(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch=monkeypatch)
    record = _discover(store, text="blocked content")
    store.block(record["discovery_id"])
    store.discover()  # same bytes
    assert store.get(record["discovery_id"])["state"] == "BLOCKED"
    assert sum(1 for r in store.list() if r["relative_location"] == "manual.txt") == 1


def test_changed_bytes_creates_new_version(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch=monkeypatch)
    record = _discover(store, text="version one")
    (store._root / "manual.txt").write_text("version two", encoding="utf-8")
    store.discover()
    records = store.list()
    assert any(r["state"] == "STALE_CHANGED" for r in records)
    assert any(r["state"] == "DISCOVERED" and r["discovery_id"] != record["discovery_id"]
               for r in records)


def test_parse_failed_requires_explicit_retry(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch=monkeypatch)
    record = _discover(store)
    store.classify(record["discovery_id"])
    store.approve(record["discovery_id"])
    store.mark_parse_failed(record["discovery_id"], "boom")
    assert store.get(record["discovery_id"])["state"] == "PARSE_FAILED"
    store.approve(record["discovery_id"])  # no generic re-approve
    assert store.get(record["discovery_id"])["state"] == "PARSE_FAILED"
    store.retry(record["discovery_id"])  # explicit retry -> CLASSIFIED
    assert store.get(record["discovery_id"])["state"] == "CLASSIFIED"


# ---------------------------------------------------------------------------
# Hash integrity
# ---------------------------------------------------------------------------


def test_changed_before_approve_stales(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch=monkeypatch)
    record = _discover(store)
    store.classify(record["discovery_id"])
    (store._root / "manual.txt").write_text("changed bytes", encoding="utf-8")
    store.approve(record["discovery_id"], manufacturer="CARRIER")
    assert store.get(record["discovery_id"])["state"] == "STALE_CHANGED"


def test_post_ingest_sha_mismatch_no_authority(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch=monkeypatch)
    record = _discover(store)
    store.classify(record["discovery_id"])
    library = SCSKnowledgeLibrary(tmp_path / "lib.db")

    class FakeResult:
        sha256 = "deadbeef"  # differs from the discovered sha
        source_id = "SRC-FAKE"
        source_state = "CANDIDATE"

    import scs_knowledge.discovery as disc
    original = disc.ingest_file
    disc.ingest_file = lambda *a, **k: FakeResult()
    try:
        result = store.approve_and_index(record["discovery_id"], library,
                                         private_root=tmp_path / "priv")
    finally:
        disc.ingest_file = original
        library.close()
    assert result["state"] == "STALE_CHANGED"


def test_approve_and_index_binds_sha(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch=monkeypatch)
    record = _discover(store, text="Carrier 50TC installation manual max ESP 2.5")
    store.classify(record["discovery_id"])
    library = SCSKnowledgeLibrary(tmp_path / "lib.db")
    result = store.approve_and_index(record["discovery_id"], library,
                                     manufacturer="CARRIER", model="50TC-E08",
                                     family_tags=["50TC"], private_root=tmp_path / "priv")
    assert result["state"] == "INDEXED"
    src = library.get_source(result["source_id"])
    assert src.document_hash == record["file_sha256"]
    library.close()


# ---------------------------------------------------------------------------
# Durable ledger
# ---------------------------------------------------------------------------


def test_missing_ledger_is_empty_not_corrupt(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    store = KnowledgeDiscoveryStore(root / "discovery.json", root=root)
    assert store.ledger_state == "EMPTY"


def test_corrupt_ledger_fails_closed(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "discovery.json").write_text("{not valid json", encoding="utf-8")
    store = KnowledgeDiscoveryStore(root / "discovery.json", root=root)
    assert store.ledger_state == "CORRUPT"
    with pytest.raises(DiscoveryLedgerError):
        store.classify("x")


def test_incompatible_version_fails_closed(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "discovery.json").write_text(
        json.dumps({"version": 999, "records": {}}), encoding="utf-8")
    store = KnowledgeDiscoveryStore(root / "discovery.json", root=root)
    assert store.ledger_state == "INCOMPATIBLE"


def test_restart_preserves_state(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch=monkeypatch)
    record = _discover(store)
    store.classify(record["discovery_id"], manufacturer="CARRIER")
    store2 = KnowledgeDiscoveryStore(store._path, root=store._root)
    assert store2.get(record["discovery_id"])["state"] == "CLASSIFIED"


# ---------------------------------------------------------------------------
# Root authority
# ---------------------------------------------------------------------------


def test_approve_blocked_without_root(tmp_path, monkeypatch):
    monkeypatch.delenv("SCS_KNOWLEDGE_ROOT", raising=False)
    store = _store(tmp_path, root_configured=False, monkeypatch=monkeypatch)
    record = _discover(store)
    store.classify(record["discovery_id"])
    with pytest.raises(KnowledgeRootNotConfigured):
        store.approve(record["discovery_id"], manufacturer="CARRIER")


# ---------------------------------------------------------------------------
# Field measurement contract
# ---------------------------------------------------------------------------


def test_normalize_concept():
    assert normalize_concept("SUPPLY_CFM") == "FIELD_SUPPLY_CFM"
    assert normalize_concept("FIELD_SUPPLY_CFM") == "FIELD_SUPPLY_CFM"
    assert normalize_concept("TOTALLY_UNKNOWN") is None
    assert normalize_concept("") is None


def test_validate_unit():
    assert validate_unit("FIELD_SUPPLY_CFM", "CFM") == "CFM"
    assert validate_unit("FIELD_TESP", "in.w.c.") == "IN.W.C."
    assert validate_unit("FIELD_TESP", "M") is None  # invalid unit
    assert validate_unit("FIELD_SUPPLY_CFM", None) == "CFM"  # canonical default


def test_scope():
    assert scope_of("FIELD_SUPPLY_CFM") == "EQUIPMENT"
    assert scope_of("BUILDING_PRESSURE") == "JOB"


def test_reading_persists_unit_and_actor():
    memory = JobConversationMemory(job_id="J1")
    entry = memory.record_reading("supply_cfm", 300, stage="FINAL",
                                  equipment_id="RTU-1", concept="FIELD_SUPPLY_CFM",
                                  unit="CFM", entered_by="emp-1")
    assert entry["unit"] == "CFM"
    assert entry["entered_by"] == "emp-1"


def test_reading_append_only_stages():
    memory = JobConversationMemory(job_id="J1")
    memory.record_reading("supply_cfm", 200, stage="AS_FOUND", equipment_id="RTU-1",
                          concept="FIELD_SUPPLY_CFM", unit="CFM")
    memory.record_reading("supply_cfm", 300, stage="FINAL", equipment_id="RTU-1",
                          concept="FIELD_SUPPLY_CFM", unit="CFM")
    assert [e["stage"] for e in memory.readings["supply_cfm"]] == ["AS_FOUND", "FINAL"]
    assert memory.readings["supply_cfm"][0]["value"] == 200
